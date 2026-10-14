import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from compass.benchmarks import load_swe_instance
from compass.index import RepositoryIndex, build_index
from compass.retrieval import Routing
from compass.sweep import run_swe_sweep, summarize
from keel.core import BudgetExceeded


@unittest.skipUnless(shutil.which("git"), "Git required")
class SweepTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        (self.repo / "api.py").write_text('def fetch(value):\n    """Read invoice values."""\n    return value\n', encoding="utf-8")
        for args in (("init", "-q"), ("add", "."), ("commit", "-qm", "fixture")):
            self.git(*args)
        commit = self.git("rev-parse", "HEAD").stdout.strip()
        self.dataset = self.root / "dataset.jsonl"
        self.dataset.write_text(json.dumps({"instance_id": "fixture", "problem_statement": "fetch", "base_commit": commit,
            "ground_truth": {"read_core_files": ["api.py"], "read_core_regions": [{"path": "api.py", "start": 1, "end": 3}]}}), encoding="utf-8")
        self.instance = load_swe_instance(self.dataset, "fixture", self.repo)
        build_index(self.repo, parser="python-ast")

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.repo), "-c", "user.name=Sweep Tests", "-c", "user.email=test@example.invalid",
                               "-c", "commit.gpgsign=false", *args], check=True, capture_output=True, text=True)

    def run_sweep(self, **kwargs):
        with RepositoryIndex(self.repo) as index:
            return run_swe_sweep(index, self.instance, self.root / "results", **kwargs)

    def test_real_mode_and_line_budget_sweep_preserves_denominators(self):
        result = self.run_sweep(modes=["t0", "t1"], line_budgets=[1, 3], repeats=2)
        self.assertTrue(result["all_passed"])
        self.assertEqual(len(result["summary"]), 4)
        for row in result["summary"]:
            self.assertAlmostEqual(row["quality"]["line_recall"], row["line_budget"] / 3)
            self.assertEqual(row["successful_runs"], 2)
        self.assertEqual(len((self.root / "results" / "runs.jsonl").read_text().splitlines()), 8)
        self.assertTrue((self.root / "results" / "report.md").is_file())
        self.assertFalse(result["public_benchmark_verified"])

    def test_deferred_t2_cannot_enter_frontier(self):
        result = self.run_sweep(modes=["t0", "t2"], line_budgets=[3], repeats=1)
        self.assertFalse(result["all_passed"])
        t2 = next(row for row in result["summary"] if row["mode"] == "t2")
        self.assertEqual(t2["exclusions"], ["deferred_escalation"])
        self.assertNotIn({"mode": "t2", "line_budget": 3}, result["frontiers"]["line_recall"]["tokens"])

    def test_budget_failure_is_retained_and_other_configs_continue(self):
        from compass.sweep import evaluate_swe
        def fail_one(index, instance, **kwargs):
            if kwargs["mode"] == "t0":
                raise BudgetExceeded("fixture limit")
            return evaluate_swe(index, instance, **kwargs)
        with patch("compass.sweep.evaluate_swe", side_effect=fail_one):
            result = self.run_sweep(modes=["t0", "t1"], line_budgets=[3], repeats=1)
        self.assertFalse(result["all_passed"])
        self.assertTrue(next(row for row in result["summary"] if row["mode"] == "t1")["eligible"])
        records = [json.loads(line) for line in (self.root / "results" / "runs.jsonl").read_text().splitlines()]
        self.assertIn("usage_at_failure", next(row for row in records if row["mode"] == "t0"))

    def test_seed_reproduces_execution_order_and_refuses_overwrite(self):
        self.run_sweep(modes=["t0", "t1"], line_budgets=[1, 3], repeats=2, seed=7)
        first = [json.loads(line) for line in (self.root / "results" / "runs.jsonl").read_text().splitlines()]
        with RepositoryIndex(self.repo) as index:
            with self.assertRaises(FileExistsError):
                run_swe_sweep(index, self.instance, self.root / "results", repeats=1)
            run_swe_sweep(index, self.instance, self.root / "second", modes=["t0", "t1"], line_budgets=[1, 3], repeats=2, seed=7)
        second = [json.loads(line) for line in (self.root / "second" / "runs.jsonl").read_text().splitlines()]
        self.assertEqual([(row["mode"], row["line_budget"]) for row in first], [(row["mode"], row["line_budget"]) for row in second])

    def test_step_limited_model_is_ineligible(self):
        from keel.models import Reply
        class Model:
            def complete(self, *args, **kwargs):
                return Reply('{"query":"invoice"}', 1)
        result = self.run_sweep(modes=["t2"], line_budgets=[3], repeats=1, model=Model(), routing=Routing(max_steps=1))
        self.assertEqual(result["summary"][0]["exclusions"], ["incomplete_exploration"])

    def test_completed_t2_records_real_budget_accounting(self):
        from keel.models import Reply
        with RepositoryIndex(self.repo) as index:
            identifier = index.find_symbol("fetch")["results"][0]["id"]
        class Model:
            model = "scripted-test-only"
            def complete(self, *args, **kwargs):
                return Reply(json.dumps({"final": [identifier]}), 7)
        result = self.run_sweep(modes=["t2"], line_budgets=[3], repeats=2, model=Model())
        self.assertTrue(result["all_passed"])
        self.assertEqual(result["summary"][0]["cost"]["model_calls"], 1)
        self.assertEqual(result["summary"][0]["cost"]["tokens"], 7)
        self.assertEqual(result["summary"][0]["quality"]["line_recall"], 1)


class FrontierTests(unittest.TestCase):
    def test_missing_repetitions_are_not_eligible(self):
        rows, frontiers = summarize([], [("t0", 3)], 2)
        self.assertEqual(rows[0]["exclusions"], ["missing_repetitions"])
        self.assertEqual(frontiers["line_recall"]["seconds"], [])

    def test_dominated_modes_are_removed_and_equal_ties_remain(self):
        from compass.sweep import COSTS, QUALITIES
        records = []
        for mode, cost, quality in [("t0", 1, 0.5), ("t1", 2, 0.25), ("adaptive", 1, 0.5)]:
            records.append({"mode": mode, "line_budget": 3, "status": "passed", "result": {
                "metrics": {key: quality for key in QUALITIES}, "elapsed_seconds": cost,
                "emitted_lines": cost, "usage": {key: cost for key in COSTS if key not in {"seconds", "emitted_lines"}}}})
        _, frontiers = summarize(records, [(mode, 3) for mode in ("t0", "t1", "adaptive")], 1)
        self.assertEqual(frontiers["line_recall"]["seconds"], [{"mode": "t0", "line_budget": 3}, {"mode": "adaptive", "line_budget": 3}])
