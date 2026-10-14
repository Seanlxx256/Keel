import json
import contextlib
import importlib.util
import io
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from compass.preparation import PublicData, SWE_DATASET, prepare_snapshot, select_data_files, select_instances


class PreparationTests(unittest.TestCase):
    def test_split_discovery_never_combines_train_and_test(self):
        paths = ["data/train-00000.parquet", "data/train-00001.parquet", "data/test-00000.parquet", "README.md"]
        self.assertEqual(select_data_files(paths, "train"), paths[:2])
        self.assertEqual(select_data_files(["bench.final.mixcap.jsonl"], "train"), ["bench.final.mixcap.jsonl"])
        with self.assertRaisesRegex(ValueError, "unambiguously"):
            select_data_files(["a.jsonl", "b.jsonl"], "train")
        with self.assertRaises(ValueError):
            select_data_files(paths, "train", ["../outside.jsonl"])

    def records(self):
        swe, verified = [], []
        for repo, identifier in [("pallets/flask", "flask-1"), ("psf/requests", "requests-1"), ("org/third", "third-1")]:
            verified.append({"repo": repo, "instance_id": identifier, "problem_statement": "Find the invoice calculation", "base_commit": "a" * 40})
            swe.append({"instance_id": identifier, "repo_dir": "../../untrusted", "ground_truth": {
                "read_core_files": ["api.py", "config.toml"], "read_core_regions": [{"path": "api.py", "start": 1, "end": 3}]}})
        return swe, verified

    def test_selection_is_order_independent_enriches_metadata_and_retains_gold(self):
        swe, verified = self.records()
        selected, audit = select_instances(swe, verified, count=2)
        again, _ = select_instances(list(reversed(swe)), verified, count=2)
        self.assertEqual(selected, again)
        self.assertEqual([row["repository_id"] for row in selected], ["pallets/flask", "psf/requests"])
        self.assertEqual(selected[0]["record"]["base_commit"], "a" * 40)
        self.assertEqual(selected[0]["record"]["ground_truth"], swe[0]["ground_truth"])
        self.assertNotIn("base_commit", swe[0])
        self.assertEqual(audit["eligible_instances"], 3)

    def test_conflicting_commits_and_insufficient_groups_fail(self):
        swe, verified = self.records()
        swe[0]["base_commit"] = "b" * 40
        with self.assertRaisesRegex(ValueError, "commit conflict"):
            select_instances(swe, verified)
        with self.assertRaisesRegex(ValueError, "only 1"):
            select_instances(swe[1:], verified, count=2, repositories=["psf/requests"])

    def test_invalid_instance_ids_and_duplicate_metadata_are_rejected(self):
        swe, verified = self.records()
        with self.assertRaisesRegex(ValueError, "unique"):
            select_instances(swe + [swe[0]], verified)
        with self.assertRaisesRegex(ValueError, "unique"):
            select_instances(swe, verified + [verified[0]])

    def test_verified_only_and_query_length_exclusions_are_visible(self):
        swe, verified = self.records()
        swe.append({"instance_id": "unmatched"})
        verified[1]["problem_statement"] = "x" * 8001
        selected, audit = select_instances(swe, verified)
        self.assertEqual(selected[0]["repository_id"], "pallets/flask")
        self.assertEqual(audit["exclusions"], {"issue_outside_query_limit": 1, "not_in_verified": 1})

    def test_curl_cache_checks_hash_before_offline_reuse(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "download.jsonl"
            def download(args, **kwargs):
                Path(args[args.index("--output") + 1]).write_bytes(b'{"id":1}\n')
                return subprocess.CompletedProcess(args, 0)
            with patch("compass.preparation.subprocess.run", side_effect=download) as process:
                PublicData(root).download("https://example.invalid/data", target)
                self.assertEqual(process.call_count, 1)
            PublicData(root, offline=True).download("https://example.invalid/data", target)
            target.write_bytes(b'{"id":2}\n')
            with self.assertRaisesRegex(ValueError, "Offline cache"):
                PublicData(root, offline=True).download("https://example.invalid/data", target)

    def test_hub_downloads_are_revision_pinned(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            urls = []
            def download(url, path):
                urls.append(url)
                path.parent.mkdir(parents=True, exist_ok=True)
                text = json.dumps({"sha": "a" * 40, "siblings": [{"rfilename": "train.jsonl"}]}) if "/api/" in url else '{"instance_id":"fixture"}\n'
                path.write_text(text, encoding="utf-8")
                return path
            hub = PublicData(root)
            with patch.object(hub, "download", side_effect=download):
                rows, provenance = hub.dataset(SWE_DATASET, "train")
            self.assertEqual(rows[0]["instance_id"], "fixture")
            self.assertIn("/resolve/" + "a" * 40 + "/train.jsonl", urls[1])
            self.assertEqual(provenance["revision"], "a" * 40)


@unittest.skipUnless(shutil.which("git"), "Git required")
class SnapshotPreparationTests(unittest.TestCase):
    def test_prepare_only_runner_writes_plan_and_verified_instance_without_model_calls(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = root / "snapshot"
            repo.mkdir()
            (repo / "api.py").write_bytes(b"def fetch(value):\n    return value\n# end\n")
            for args in (("init", "-q"), ("add", "."), ("commit", "-qm", "fixture")):
                subprocess.run(["git", "-C", str(repo), "-c", "user.name=Preparation Test", "-c", "user.email=test@example.invalid",
                                "-c", "commit.gpgsign=false", *args], check=True, capture_output=True)
            commit = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()
            swe = [{"instance_id": "fixture", "ground_truth": {"read_core_files": ["api.py"],
                    "read_core_regions": [{"path": "api.py", "start": 1, "end": 3}]}}]
            verified = [{"instance_id": "fixture", "repo": "pallets/flask", "base_commit": commit, "problem_statement": "fetch"}]
            script = Path(__file__).resolve().parents[1] / "examples/run_swe_public.py"
            spec = importlib.util.spec_from_file_location("swe_preparation_runner", script)
            runner = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(runner)
            with patch.object(runner, "__file__", str(root / "examples/run_swe_public.py")), \
                 patch.object(runner.PublicData, "dataset", side_effect=[(swe, {"revision": "a" * 40}), (verified, {"revision": "b" * 40})]), \
                 patch.object(runner, "prepare_snapshot", return_value=repo), \
                 patch.object(runner, "OllamaModel", side_effect=AssertionError("No model calls allowed")), \
                 contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(runner.main(["--prepare-only"]), 0)
            plans = list((root / ".keel/swe-public").glob("*/plan.json"))
            self.assertEqual(len(plans), 1)
            plan = json.loads(plans[0].read_text())
            self.assertEqual(plan["instances"][0]["base_commit"], commit)
            result = json.loads((plans[0].parent / "result.json").read_text())
            self.assertEqual(result["instances"][0]["status"], "prepared")
            self.assertFalse(result["public_benchmark_verified"])

    def test_exact_commit_checkout_and_dirty_snapshot_refusal(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            (source / "api.py").write_bytes(b"def fetch():\n    return 1\n")
            def git(*args):
                return subprocess.run(["git", "-C", str(source), "-c", "user.name=Preparation Test", "-c", "user.email=test@example.invalid",
                                       "-c", "commit.gpgsign=false", *args], check=True, capture_output=True, text=True)
            git("init", "-q")
            git("add", ".")
            git("commit", "-qm", "fixture")
            commit = git("rev-parse", "HEAD").stdout.strip()
            destination = root / "snapshots" / commit
            # Transfer is mocked: restricted Windows agents cannot start Git's MSYS pipe helper.
            # The actual Git init, detached checkout, HEAD and cleanliness checks still run.
            real_run = subprocess.run
            def interrupted(args, **kwargs):
                if "fetch" in args:
                    raise subprocess.CalledProcessError(128, args, b"", b"network unavailable")
                return real_run(args, **kwargs)
            with patch("compass.preparation.subprocess.run", side_effect=interrupted):
                with self.assertRaisesRegex(ValueError, "network unavailable"):
                    prepare_snapshot("org/repo", commit, destination, source=str(source))
            self.assertTrue(destination.with_name(commit + ".partial").joinpath(".git/compass-preparation.json").is_file())
            def transfer(args, **kwargs):
                if "fetch" in args:
                    staging = Path(args[args.index("-C") + 1])
                    shutil.copytree(source / ".git/objects", staging / ".git/objects", dirs_exist_ok=True)
                    return subprocess.CompletedProcess(args, 0, b"", b"")
                return real_run(args, **kwargs)
            with patch("compass.preparation.subprocess.run", side_effect=transfer):
                prepare_snapshot("org/repo", commit, destination, source=str(source))
            self.assertEqual((destination / "api.py").read_bytes(), (source / "api.py").read_bytes())
            self.assertEqual(prepare_snapshot("org/repo", commit, destination, offline=True), destination)
            (destination / "extra.py").write_text("future code", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "untracked"):
                prepare_snapshot("org/repo", commit, destination, offline=True)
