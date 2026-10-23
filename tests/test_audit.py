import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from keel.audit import audit_text, protected_path, read_junit
from keel.core import PolicyDenied
from keel.execution import CommandRunner, normalize_acceptance, validate_execution
from keel.runtime import run


class StaticAuditTests(unittest.TestCase):
    def rules(self, before, after, name="app.py"):
        return {f["rule"] for f in audit_text(name, before.encode(), after.encode())}

    def test_assertion_deletion_and_rewrite_are_rejected(self):
        for updated in ("pass\n", "assert True\n", "assert 1 == 1\n"):
            with self.subTest(updated=updated):
                self.assertIn("assertion_removed_or_rewritten", self.rules("assert value > 0\n", updated))

    def test_skip_aliases_and_unittest_skips_are_detected(self):
        attempts = ["import pytest as p\np.skip('reason')\n",
                    "from pytest import mark as m\n@m.xfail\ndef f(): pass\n",
                    "from unittest import skip as s\n@s('reason')\ndef f(): pass\n",
                    "self.skipTest('reason')\n"]
        for attempt in attempts:
            with self.subTest(attempt=attempt):
                self.assertIn("skip_or_xfail_added", self.rules("pass\n", attempt))

    def test_comments_strings_and_existing_skips_do_not_trigger(self):
        before = "import pytest\npytest.skip('already exists')\nVALUE = 1\n"
        after = before.replace("VALUE = 1", "VALUE = 2\n# assert True\nTEXT = 'pytest.skip()'")
        self.assertEqual(self.rules(before, after), set())

    def test_protected_path_variants(self):
        for name in ("src/widget.spec.tsx", "src/widget.test.jsx", "Conftest.py", ".gitlab-ci.yml",
                     "foo/TESTS/check.py", "testing/python/integration.py", "pkg/Testing/check.py",
                     r"testing\python\integration.py", ".circleci/config.yml", "pytest.ini"):
            with self.subTest(name=name):
                self.assertTrue(protected_path(name))

    def test_added_test_under_testing_is_protected_even_without_assertion_removal(self):
        before='VALUE = 1\n'
        after=before+'def test_feature():\n    assert True\n'
        self.assertIn('protected_file_changed',self.rules(before,after,'testing/python/integration.py'))
        self.assertFalse(protected_path('src/_pytest/skipping.py'))
        self.assertFalse(protected_path('pkg/testing_helpers.py'))

    def test_dependency_upgrade_keeps_test_configuration(self):
        before = '[project]\nversion="1"\n[tool.pytest.ini_options]\naddopts="-v"\n'
        self.assertEqual(self.rules(before, before.replace('version="1"', 'version="2"'), "pyproject.toml"), set())
        self.assertIn("test_configuration_changed", self.rules(before, before.replace('addopts="-v"', 'addopts="--ignore=tests"'), "pyproject.toml"))

    def test_package_scripts_cannot_be_replaced_with_noop(self):
        before = json.dumps({"scripts": {"test": "jest"}, "dependencies": {"foo": "1"}})
        after = json.dumps({"scripts": {"test": "echo done"}, "dependencies": {"foo": "2"}})
        self.assertIn("test_configuration_changed", self.rules(before, after, "package.json"))

    def test_missing_or_invalid_python_fails_closed(self):
        self.assertIn("python_audit_parse_failed", self.rules("assert ok\n", "broken ("))


class MetadataIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "app.py").write_text("VERSION = 1\n")

    def xml(self, names=("a", "b"), skipped=(), failed=()):
        return '<testsuites><testsuite tests="999">' + ''.join(
            f'<testcase classname="suite" name="{name}">' +
            ('<skipped/>' if name in skipped else '') +
            ('<failure/>' if name in failed else '') + '</testcase>' for name in names
        ) + '</testsuite></testsuites>'

    def execute(self, final, baseline=None, produce_final=True):
        baseline = self.xml() if baseline is None else baseline
        script = ("import app,sys; from pathlib import Path; "
                  f"xml={baseline!r} if app.VERSION==1 else {final!r}; "
                  f"emit=app.VERSION==1 or {produce_final!r}; "
                  "Path(sys.argv[1]).write_text(xml) if emit else None; "
                  "raise SystemExit(1 if app.VERSION==1 else 0)")
        config = {"goal": "Upgrade", "acceptance": [{"command": [sys.executable, "-c", script, "{junit}"], "junit": True}],
                  "work_items": [{"id": "upgrade", "edits": [{"path": "app.py", "old": "VERSION = 1", "new": "VERSION = 2"}]}]}
        return run(config, self.root, self.root / ".keel" / "run")

    def rules(self, result):
        return {f["rule"] for f in result["audit"]["findings"]}

    def test_baseline_may_fail_but_final_must_pass(self):
        result = self.execute(self.xml())
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["baseline_verification"][0]["returncode"], 1)
        self.assertEqual(result["verification"][0]["metadata"]["collected"], 2)
        self.assertTrue(result["audit"]["metadata_checked"])

    def test_zero_tests_despite_exit_zero_is_rejected(self):
        result = self.execute(self.xml(names=()))
        self.assertEqual(result["failure"]["category"], "audit_failed")
        self.assertIn("no_tests_executed", self.rules(result))

    def test_removing_test_is_rejected(self):
        result = self.execute(self.xml(names=("a",)))
        self.assertIn("test_cases_removed", self.rules(result))

    def test_replacing_test_with_different_name_is_rejected(self):
        result = self.execute(self.xml(names=("a", "c")))
        self.assertIn("test_cases_removed", self.rules(result))

    def test_more_skips_is_rejected(self):
        result = self.execute(self.xml(skipped=("b",)))
        self.assertIn("skipped_tests_increased", self.rules(result))

    def test_nonzero_report_failures_override_exit_zero(self):
        result = self.execute(self.xml(failed=("a",)))
        self.assertIn("test_failures_in_report", self.rules(result))

    def test_stale_baseline_report_cannot_substitute_missing_final_report(self):
        result = self.execute(self.xml(), produce_final=False)
        self.assertIn("missing_test_metadata", self.rules(result))

    def test_invalid_baseline_blocks_edits(self):
        result = self.execute(self.xml(), baseline="<broken")
        self.assertEqual(result["failure"]["stage"], "baseline_verifier")
        self.assertEqual((self.root / "app.py").read_text(), "VERSION = 1\n")

    def test_xml_entities_are_rejected(self):
        report = self.root / "report.xml"
        report.write_text('<!DOCTYPE testsuite [<!ENTITY x "hello">]><testsuite/>')
        with self.assertRaises(ValueError):
            read_junit(report)

    def test_ast_attack_stops_before_write(self):
        (self.root / "app.py").write_text("assert value > 0\n")
        config = {"goal": "Bypass validation", "acceptance": [[sys.executable, "-c", "pass"]],
                  "work_items": [{"id": "hack", "edits": [{"path": "app.py", "old": "assert value > 0", "new": "assert True"}]}]}
        result = run(config, self.root, self.root / ".keel" / "hack")
        self.assertEqual(result["failure"]["category"], "audit_failed")
        self.assertEqual((self.root / "app.py").read_text(), "assert value > 0\n")


class ExecutionTests(unittest.TestCase):
    def test_relative_workspace_and_reports_resolve_before_docker_launch(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            base = Path(directory)
            repo, reports = base/'repo', base/'reports'
            repo.mkdir()
            reports.mkdir()
            relative_repo = repo.relative_to(Path.cwd())
            relative_reports = reports.relative_to(Path.cwd())
            with patch('keel.execution.shutil.which', return_value='docker'), patch(
                    'keel.execution.subprocess.run', return_value=subprocess.CompletedProcess([], 0, b'ok', b'')) as launch:
                CommandRunner({'backend': 'docker', 'image': 'test'}).run(
                    ['python', '-c', 'pass'], relative_repo, 1, relative_reports)
            args = launch.call_args.args[0]
            self.assertIn(f'type=bind,source={repo.resolve()},target=/workspace,readonly', args)
            self.assertIn(f'type=bind,source={reports.resolve()},target=/keel-reports', args)
            self.assertEqual(launch.call_args.kwargs['cwd'], repo.resolve())

    def test_docker_command_enforces_isolation_flags_and_mounts(self):
        runner = CommandRunner({"backend": "docker", "image": "keel-tests:local"})
        command = runner.docker_command(["python", "-m", "pytest"], Path("/repo"), Path("/reports"), "keel-test")
        for flag in ("--network=none", "--read-only", "--cap-drop=ALL", "--security-opt=no-new-privileges",
                     "--pull=never", "--user=65534:65534"):
            self.assertIn(flag, command)
        self.assertIn(f"type=bind,source={Path('/repo')},target=/workspace,readonly", command)
        self.assertIn(f"type=bind,source={Path('/reports')},target=/keel-reports", command)
        self.assertEqual(command[-4:], ["keel-tests:local", "python", "-m", "pytest"])

    def test_missing_docker_does_not_fall_back(self):
        with patch("keel.execution.shutil.which", return_value=None), patch("keel.execution.subprocess.run") as launch:
            with self.assertRaises(PolicyDenied):
                CommandRunner({"backend": "docker", "image": "test"}).run(["echo"], Path.cwd(), 1)
        launch.assert_not_called()

    def test_timeout_removes_only_named_container(self):
        with patch("keel.execution.shutil.which", return_value="docker"), patch("keel.execution.subprocess.run") as launch:
            launch.side_effect = [subprocess.TimeoutExpired("docker", 1), subprocess.CompletedProcess([], 0, b"", b"")]
            result = CommandRunner({"backend": "docker", "image": "test"}).run(["sleep", "10"], Path.cwd(), 1)
        self.assertTrue(result["timeout"])
        docker_args = launch.call_args_list[0].args[0]
        name = docker_args[docker_args.index("--name") + 1]
        self.assertEqual(launch.call_args_list[1].args[0], ["docker", "rm", "--force", name])

    def test_invalid_resource_settings_rejected(self):
        for setting in ({"cpus": float("nan")}, {"memory_mb": 0}, {"pids_limit": -1}):
            with self.subTest(setting=setting), self.assertRaises(ValueError):
                validate_execution({"backend": "docker", "image": "test", **setting})

    def test_junit_requires_explicit_output_placeholder(self):
        with self.assertRaises(ValueError):
            normalize_acceptance([{"command": ["python"], "junit": True}])


if __name__ == "__main__":
    unittest.main()
