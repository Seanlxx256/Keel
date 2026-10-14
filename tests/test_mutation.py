import sys
import tempfile
import unittest
from pathlib import Path

from keel.runtime import run


class MutationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "app.py").write_bytes(b"def version():\n    return 1\n")

    def config(self, code):
        return {"goal": "Upgrade return value", "mutation_samples": 1,
                "acceptance": [[sys.executable, "-c", code]],
                "work_items": [{"id": "upgrade", "edits": [
                    {"path": "app.py", "old": "return 1", "new": "return 2"}]}]}

    def test_covered_mutant_is_killed_and_exact_file_restored(self):
        result = run(self.config("import app; assert app.version() == 2"), self.root, self.root / ".keel" / "run")
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["mutation"]["probes"][0]["outcome"], "killed")
        self.assertEqual((self.root / "app.py").read_bytes(), b"def version():\n    return 2\n")
        self.assertNotIn("return 3", (self.root / ".keel" / "run" / "changes.patch").read_text())

    def test_uncovered_mutant_rejects_success_and_restores(self):
        result = run(self.config("import app; assert callable(app.version)"), self.root, self.root / ".keel" / "run")
        self.assertEqual(result["failure"]["category"], "audit_failed")
        self.assertEqual(result["mutation"]["status"], "survived")
        self.assertEqual((self.root / "app.py").read_bytes(), b"def version():\n    return 2\n")

    def test_restore_after_probe_cannot_start_due_to_budget(self):
        config = self.config("import app; assert app.version() == 2")
        config["budget"] = {"max_tool_calls": 4}
        result = run(config, self.root, self.root / ".keel" / "run")
        self.assertEqual(result["failure"]["category"], "budget_exhausted")
        self.assertEqual((self.root / "app.py").read_bytes(), b"def version():\n    return 2\n")

    def test_unsupported_function_reports_no_candidates(self):
        (self.root / "app.py").write_text("def version():\n    return 'one'\n")
        config = self.config("import app; assert app.version() == 'two'")
        config["work_items"][0]["edits"][0].update(old="'one'", new="'two'")
        result = run(config, self.root, self.root / ".keel" / "run")
        self.assertEqual(result["mutation"]["status"], "no_candidates")

    def test_unchanged_function_is_not_sampled(self):
        (self.root / "app.py").write_text("def version():\n    return 1\n\nVALUE = 1\n")
        config = self.config("import app; assert app.VALUE == 2")
        config["work_items"][0]["edits"][0].update(old="VALUE = 1", new="VALUE = 2")
        result = run(config, self.root, self.root / ".keel" / "run")
        self.assertEqual(result["mutation"]["sampled"], 0)

    def test_crlf_file_is_restored_without_normalizing_newlines(self):
        (self.root / "app.py").write_bytes(b"def version():\r\n    return 1\r\n")
        result = run(self.config("import app; assert app.version() == 2"), self.root, self.root / ".keel" / "run")
        self.assertEqual(result["status"], "passed")
        self.assertEqual((self.root / "app.py").read_bytes(), b"def version():\r\n    return 2\r\n")

    def test_junit_mutation_requires_real_test_failure_and_keeps_case_identity(self):
        config = self.config("pass")
        script = ("import app,sys; from pathlib import Path; ok=app.version()==2; "
                  "xml='<testsuite><testcase classname=\"suite\" name=\"version\">' + "
                  "('' if ok else '<failure/>') + '</testcase></testsuite>'; "
                  "Path(sys.argv[1]).write_text(xml); raise SystemExit(0 if ok else 1)")
        config["acceptance"] = [{"command": [sys.executable, "-c", script, "{junit}"], "junit": True}]
        result = run(config, self.root, self.root / ".keel" / "run")
        self.assertEqual(result["status"], "passed")
        probe = result["mutation"]["probes"][0]
        self.assertEqual(probe["outcome"], "killed")
        self.assertEqual(probe["verification"][0]["metadata"]["failures"], 1)


if __name__ == "__main__":
    unittest.main()
