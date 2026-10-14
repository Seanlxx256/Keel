"""Offline end-to-end coverage of the PowerShell preparation/evaluation workflow."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
REVISION = "23da5d97a8a4495d4bd6d5616aa86d5a12a60699"
REMOTE = "data/LEVEL-2/SWE-bench_Verified"


@unittest.skipUnless(os.name == "nt" and shutil.which("powershell"), "Windows PowerShell required")
class PublicBatchScriptTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "examples").mkdir()
        self.script = self.root / "examples" / "run_core_verified_batch.ps1"
        shutil.copyfile(ROOT / "examples" / self.script.name, self.script)
        self.cache = self.root / ".keel" / "datasets" / "core" / REVISION
        self.listing = []
        for number in range(12):
            name = f"repo-{number:02d}"
            directory = self.cache / name
            directory.mkdir(parents=True)
            for filename, rows in {
                "corpus.jsonl": [{"_id": "doc", "text": "invoice"}],
                "queries.jsonl": [{"_id": "q", "text": "invoice"}],
                "qrels.jsonl": [{"query_id": "q", "corpus_id": "doc", "score": 1}],
            }.items():
                raw = "\n".join(json.dumps(row) for row in rows).encode()
                path = directory / filename
                path.write_bytes(raw)
                remote = f"{REMOTE}/{name}/{filename}"
                self.listing.append({"type": "file", "path": remote, "size": len(raw)})
                Path(str(path) + ".receipt.json").write_text(json.dumps({"revision": REVISION, "path": remote,
                    "sha256": hashlib.sha256(raw).hexdigest()}), encoding="utf-8")
        self.write_listing()

    def write_listing(self):
        (self.cache / "verified-directory.json").write_text(json.dumps(self.listing), encoding="utf-8")

    def execute(self, unavailable_hash_cmdlet=False):
        env = dict(os.environ, PYTHONPATH=str(ROOT))
        if unavailable_hash_cmdlet:
            wrapper = self.root / "unavailable-hash.ps1"
            wrapper.write_text('param([string]$TargetScript, [string]$PythonCommand)\n'
                               'Import-Module Microsoft.PowerShell.Utility\n'
                               'function global:Get-FileHash { throw "Simulated unavailable hashing cmdlet" }\n'
                               '& $TargetScript -Offline -PythonCommand $PythonCommand -MaxQueries 1 -Repeats 1\n'
                               'exit $LASTEXITCODE\n', encoding="utf-8")
            args = [str(wrapper), "-TargetScript", str(self.script), "-PythonCommand", sys.executable]
        else:
            args = [str(self.script), "-Offline", "-PythonCommand", sys.executable, "-MaxQueries", "1", "-Repeats", "1"]
        return subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", *args],
                              cwd=self.root, env=env, capture_output=True, text=True, timeout=60)

    def test_twelve_cached_repositories_reach_real_batch_evaluator(self):
        completed = self.execute()
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertIn("query_finished", completed.stdout + completed.stderr)
        reports = list((self.root / ".keel/core-verified-batch").glob("*/results/batch.json"))
        self.assertEqual(len(reports), 1)
        report = json.loads(reports[0].read_text(encoding="utf-8"))
        self.assertTrue(report["all_passed"])
        self.assertEqual(report["summary"]["successful_datasets"], 12)
        self.assertEqual(report["summary"]["queries"], 12)
        self.assertTrue(all(row["hashes_pinned"] for row in report["datasets"]))
        self.assertFalse(report["public_benchmark_verified"])

    def test_modified_cache_cannot_pass_on_file_size_alone(self):
        path = self.cache / "repo-00" / "corpus.jsonl"
        path.write_bytes(path.read_bytes().replace(b"invoice", b"changed"))
        completed = self.execute(unavailable_hash_cmdlet=True)
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("Offline cache is missing or invalid", completed.stdout)
        self.assertFalse(list((self.root / ".keel/core-verified-batch").glob("*/manifest.json")))

    def test_incomplete_repository_listing_fails_before_evaluation(self):
        self.listing = [row for row in self.listing if "/repo-11/" not in row["path"]]
        self.write_listing()
        completed = self.execute()
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("Expected exactly 12", completed.stdout)

    def test_cache_validation_does_not_depend_on_get_file_hash_cmdlet(self):
        completed = self.execute(unavailable_hash_cmdlet=True)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        reports = list((self.root / ".keel/core-verified-batch").glob("*/results/batch.json"))
        self.assertTrue(json.loads(reports[0].read_text(encoding="utf-8"))["all_passed"])

    def test_cache_receipt_parse_error_is_visible(self):
        (self.cache / "repo-00/corpus.jsonl.receipt.json").write_text("{invalid", encoding="utf-8")
        completed = self.execute()
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("Cache verification error for corpus.jsonl", completed.stdout)
