import json
import math
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from compass.benchmarks import (check_snapshot, document_metrics, evaluate_core, evaluate_swe,
                                load_core, load_swe_instance, region_metrics, relative_path)
from compass.index import RepositoryIndex, build_index


class CoreFormatTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.write("corpus.jsonl", [{"_id": "current", "text": "invoice"},
                                   {"_id": "future", "text": "invoice invoice invoice"}])
        self.write("queries.jsonl", [{"_id": "q", "text": "invoice", "filtered_corpus_id": ["current"]}])
        self.write("qrels.jsonl", [{"query_id": "q", "corpus_id": "current", "score": 2}])

    def write(self, name, rows):
        (self.root / name).write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")

    def load(self):
        return load_core(self.root, revision="synthetic-fixture-v1", level=2)

    def test_temporal_filter_blocks_high_scoring_future_snapshot(self):
        result = evaluate_core(self.load())
        self.assertEqual(result["records"][0]["ranked_doc_ids"], ["current"])
        self.assertEqual(result["summary"]["recall_at_100"], 1)
        self.assertFalse(result["public_benchmark_verified"])
        self.assertFalse(result["full_cascade"])

    def test_positive_label_outside_filter_is_rejected_instead_of_ignored(self):
        self.write("qrels.jsonl", [{"query_id": "q", "corpus_id": "future", "score": 1}])
        with self.assertRaisesRegex(ValueError, "outside"):
            self.load()

    def test_unknown_corpus_id_and_duplicate_labels_are_rejected(self):
        for rows in ([{"query_id": "q", "corpus_id": "unknown", "score": 1}],
                     [{"query_id": "q", "corpus_id": "current", "score": 1}] * 2):
            with self.subTest(rows=rows):
                self.write("qrels.jsonl", rows)
                with self.assertRaises(ValueError):
                    self.load()

    def test_beir_tsv_and_canonical_ids_are_preserved(self):
        (self.root / "qrels.jsonl").unlink()
        (self.root / "qrels").mkdir()
        (self.root / "qrels" / "test.tsv").write_text("query-id\tcorpus-id\tscore\nq\tcurrent\t2\n")
        self.assertEqual(self.load().qrels, {"q": {"current": 2}})

    def test_unjudged_queries_are_reported_not_given_fake_zero_scores(self):
        self.write("queries.jsonl", [{"_id": "q", "text": "invoice"}, {"_id": "unjudged", "text": "missing"}])
        data = self.load()
        self.assertEqual(data.provenance["excluded_unjudged_queries"], ["unjudged"])
        self.assertEqual(len(evaluate_core(data)["records"]), 1)

    def test_document_ndcg_uses_graded_document_labels(self):
        result = document_metrics(["low", "high"], {"high": 3, "low": 1})
        expected = (1 + 3 / math.log2(3)) / (3 + 1 / math.log2(3))
        self.assertAlmostEqual(result["ndcg_at_10"], expected)
        self.assertEqual(result["recall_at_100"], 1)

    def test_corpus_limit_fails_without_scoring_a_truncated_dataset(self):
        with self.assertRaisesRegex(ValueError, "exceeds"):
            load_core(self.root, revision="fixture", level=2, max_documents=1)


class RegionMetricsTests(unittest.TestCase):
    def test_overlapping_predictions_do_not_inflate_line_precision_or_recall(self):
        pred = [{"path": "a.py", "start": 1, "end": 3}, {"path": "a.py", "start": 2, "end": 4}]
        core = [{"path": "a.py", "start": 2, "end": 3}]
        optional = [{"path": "a.py", "start": 4, "end": 4}]
        result = region_metrics(pred, core, optional, ["a.py", "config.toml"])
        self.assertEqual(result["line_precision"], 0.5)
        self.assertEqual(result["line_recall"], 1)
        self.assertEqual(result["context_efficiency"], 0.75)
        self.assertEqual(result["hit_file_rate"], 0.5)
        self.assertEqual(result["predicted_unique_lines"], 4)

    def test_first_useful_hit_preserves_rank(self):
        predictions = [{"path": "noise.py", "start": 1, "end": 3}, {"path": "a.py", "start": 1, "end": 1}]
        result = region_metrics(predictions, [{"path": "a.py", "start": 1, "end": 1}], [], ["a.py"])
        self.assertEqual(result["first_useful_hit"], 0.5)

    def test_paths_cannot_escape_repository_on_either_platform(self):
        for name in ("../outside.py", "C:/outside.py", "/outside.py", "\\\\server\\share\\a.py"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                relative_path(name)


@unittest.skipUnless(shutil.which("git"), "Git is required for snapshot validation")
class SweFormatTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.repo = self.base / "repo"
        self.repo.mkdir()
        (self.repo / "api.py").write_bytes(b'def fetch(value):\n    """Read values."""\n    return value\n')
        (self.repo / "settings.toml").write_bytes(b"enabled = true\n")
        (self.repo / ".gitignore").write_bytes(b"hidden.py\n")
        self.git("init", "-q")
        self.git("add", ".")
        self.git("commit", "-qm", "fixture")
        self.commit = self.git("rev-parse", "HEAD").stdout.strip()
        self.path = self.base / "swe.jsonl"
        self.record = {"instance_id": "org__repo-1", "repo_dir": "../../untrusted-metadata", "problem_statement": "fetch",
                       "base_commit": self.commit, "ground_truth": {
                           "read_core_files": ["api.py", "settings.toml"],
                           "read_core_regions": [{"path": "api.py", "start": 1, "end": 3},
                                                 {"path": "settings.toml", "start": 1, "end": 1}]}}
        self.write()

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.repo), "-c", "user.name=Compass Tests",
                               "-c", "user.email=compass@example.invalid", "-c", "commit.gpgsign=false", *args],
                              check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=10)

    def write(self):
        self.path.write_text(json.dumps(self.record) + "\n", encoding="utf-8")

    def test_real_clean_git_snapshot_and_line_budget_export(self):
        instance = load_swe_instance(self.path, "org__repo-1", self.repo)
        build_index(self.repo, parser="python-ast")
        with RepositoryIndex(self.repo) as index:
            result = evaluate_swe(index, instance, line_budget=2, mode="t0")
        self.assertEqual(result["emitted_lines"], 2)
        self.assertEqual(result["predictions"], [{"path": "api.py", "start": 1, "end": 2}])
        self.assertEqual(result["metrics"]["line_recall"], 0.5)
        self.assertEqual(result["unindexed_gold_files"], ["settings.toml"])
        self.assertFalse(result["public_benchmark_verified"])

    def test_wrong_commit_and_tracked_edits_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "base commit"):
            check_snapshot(self.repo, "f" * 40)
        (self.repo / "api.py").write_bytes(b"def changed(): pass\n")
        with self.assertRaisesRegex(ValueError, "tracked changes"):
            load_swe_instance(self.path, "org__repo-1", self.repo)

    def test_ignored_untracked_python_cannot_leak_future_code(self):
        (self.repo / "hidden.py").write_bytes(b"def answer(): return 42\n")
        with self.assertRaisesRegex(ValueError, "untracked input"):
            check_snapshot(self.repo, self.commit)

    def test_external_issue_commit_maps_and_eof_regions(self):
        self.record.pop("problem_statement")
        self.record.pop("base_commit")
        self.record["ground_truth"]["read_core_regions"][0].update(start=-2, end=-1)
        self.write()
        result = load_swe_instance(self.path, "org__repo-1", self.repo,
                                   issue_map={"org__repo-1": "fetch"}, commit_map={"org__repo-1": self.commit})
        self.assertEqual(result["core_regions"][0], {"path": "api.py", "start": 2, "end": 3})

    def test_labels_cannot_reach_outside_checkout(self):
        self.record["ground_truth"]["read_core_regions"][0]["path"] = "../swe.jsonl"
        self.write()
        with self.assertRaises(ValueError):
            load_swe_instance(self.path, "org__repo-1", self.repo)


if __name__ == "__main__":
    unittest.main()
