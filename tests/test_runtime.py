import json
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from keel.core import Budget, Ledger, Limits, PolicyDenied, Trace
from keel.runtime import run, validate
from keel.workspace import Workspace


class RuntimeTests(unittest.TestCase):
    def test_crlf_patch_artifact_preserves_exact_diff_bytes(self):
        import difflib
        original=b'VERSION = 1\r\n'
        (self.root/'app.py').write_bytes(original)
        output=self.root/'.keel'/'crlf'
        run(self.config(),self.root,output)
        current=(self.root/'app.py').read_bytes()
        expected=''.join(difflib.unified_diff(original.decode().splitlines(True),current.decode().splitlines(True),
            fromfile='a/app.py',tofile='b/app.py')).encode()
        self.assertEqual((output/'changes.patch').read_bytes(),expected)
        self.assertNotIn(b'\r\r\n',expected)
        import subprocess
        subprocess.run(['git','init','-q',str(self.root)],check=True,capture_output=True)
        subprocess.run(['git','-c','safe.directory='+self.root.as_posix(),'-c','core.autocrlf=false',
            '-C',str(self.root),'apply','--check','--reverse',str((output/'changes.patch').resolve())],
            check=True,capture_output=True)
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "app.py").write_text("VERSION = 1\n", encoding="utf-8")

    def config(self):
        return {"goal": "Upgrade version", "queries": ["VERSION"],
                "acceptance": [[sys.executable, "-c", "import app; assert app.VERSION == 2"]],
                "work_items": [{"id": "upgrade", "edits": [
                    {"path": "app.py", "old": "VERSION = 1", "new": "VERSION = 2"}]}]}

    def test_successful_run_has_patch_trace_and_recall(self):
        output = self.root / ".keel" / "runs" / "success"
        result = run(self.config(), self.root, output)
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["state_machine"]["state"], "finished")
        self.assertEqual([row["role"] for row in result["state_machine"]["history"]],
                         ["scout", "planner", "implementer", "verifier", "auditor"])
        self.assertIn("+VERSION = 2", (output / "changes.patch").read_text())
        events = [json.loads(line) for line in (output / "trace.jsonl").read_text().splitlines()]
        self.assertEqual(events[-1]["event"], "run_finished")
        ledger = Ledger(output / "ledger.sqlite")
        self.addCleanup(ledger.close)
        self.assertEqual(ledger.recall(1)["matches"][0]["file"], "app.py")

    def test_verification_failure_is_recorded(self):
        config = self.config()
        config["acceptance"] = [[sys.executable, "-c", "raise SystemExit(3)"]]
        result = run(config, self.root, self.root / ".keel" / "failed")
        self.assertEqual(result["failure"]["category"], "verification_failed")
        history = result["state_machine"]["history"]
        self.assertEqual(next(row["status"] for row in history if row["role"] == "verifier"), "failed")
        self.assertEqual(history[-1]["role"], "critic")
        self.assertEqual(result["facts"][-1]["kind"], "failed_attempt")

    def test_budget_exhaustion_returns_report(self):
        config = self.config()
        config["budget"] = {"max_tool_calls": 1}
        result = run(config, self.root, self.root / ".keel" / "budget")
        self.assertEqual(result["failure"]["category"], "budget_exhausted")
        self.assertEqual((self.root / "app.py").read_text(), "VERSION = 1\n")

    def test_protected_targets_rejected_before_any_edit(self):
        (self.root / "tests").mkdir()
        (self.root / "tests" / "check.py").write_text("assert False\n")
        config = self.config()
        config["work_items"][0]["edits"].append(
            {"path": "tests/check.py", "old": "False", "new": "True"})
        result = run(config, self.root, self.root / ".keel" / "denied")
        self.assertEqual(result["failure"]["category"], "policy_denied")
        self.assertEqual((self.root / "app.py").read_text(), "VERSION = 1\n")

    def test_verifier_unexpected_write_fails_audit(self):
        config = self.config()
        config["acceptance"] = [[sys.executable, "-c",
                                "from pathlib import Path; Path('extra.txt').write_text('oops')"]]
        result = run(config, self.root, self.root / ".keel" / "audit")
        self.assertEqual(result["failure"]["category"], "policy_denied")

    def test_unexpected_error_keeps_original_exception_and_failed_state_artifact(self):
        output = self.root / ".keel" / "unexpected"
        with patch("keel.workspace.Workspace.verify", side_effect=RuntimeError("verifier interrupted")):
            with self.assertRaisesRegex(RuntimeError, "verifier interrupted"):
                run(self.config(), self.root, output)
        saved = json.loads((output / "result.json").read_text())
        self.assertEqual(saved["status"], "failed")
        self.assertEqual(saved["failure"]["category"], "unexpected_termination")
        self.assertEqual(saved["state_machine"]["history"][-1]["role"], "critic")

    def test_dependency_cycles_and_unknown_dependencies_rejected(self):
        for dependency in ("a", "missing"):
            with self.subTest(dependency=dependency), self.assertRaises(ValueError):
                validate({"goal": "test", "acceptance": [["python"]],
                          "work_items": [{"id": "a", "depends_on": [dependency]}]})

    def test_cache_invalidates_after_content_changes_and_paths_cannot_escape(self):
        ledger = Ledger(self.root / "ledger.sqlite")
        self.addCleanup(ledger.close)
        workspace = Workspace(self.root, Budget(Limits()), ledger, Trace(self.root / "trace.jsonl"))
        self.assertFalse(workspace.read("app.py")["cache_hit"])
        self.assertEqual(workspace.read("app.py")["repeat_count"], 1)
        (self.root / "app.py").write_text("VERSION = 3\n")
        self.assertFalse(workspace.read("app.py")["cache_hit"])
        with self.assertRaises(PolicyDenied):
            workspace.path("../escape.py", write=True)

    def test_command_timeout_produces_failure(self):
        config = self.config()
        config["budget"] = {"max_wallclock": 0.3}
        config["acceptance"] = [[sys.executable, "-c", "import time; time.sleep(5)"]]
        result = run(config, self.root, self.root / ".keel" / "timeout")
        self.assertEqual(result["status"], "failed")
        self.assertTrue(result["verification"][0]["timeout"])


if __name__ == "__main__":
    unittest.main()
