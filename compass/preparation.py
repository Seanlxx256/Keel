"""Pinned public SWE data preparation. Downloads data; never executes repository code."""
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import urllib.parse

from .benchmarks import canonical_repository_id, check_snapshot, file_digest, relative_path


SWE_DATASET = "SWE-Explore-Bench/SWE-Explore-Bench"
VERIFIED_DATASET = "princeton-nlp/SWE-bench_Verified"


class PublicData:
    def __init__(self, root, *, offline=False, timeout=300, progress=lambda event, **fields: None):
        self.root, self.offline, self.timeout, self.progress = Path(root), offline, timeout, progress

    def download(self, url, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        receipt = Path(str(path) + ".receipt.json")
        if path.is_file() and receipt.is_file():
            try:
                saved = json.loads(receipt.read_text(encoding="utf-8"))
                if saved["url"] == url and saved["sha256"] == file_digest(path):
                    self.progress("cached", file=str(path))
                    return path
            except (ValueError, KeyError, OSError):
                pass
        if self.offline:
            raise ValueError(f"Offline cache missing or invalid: {path}")
        self.progress("download_started", url=url, file=str(path))
        partial = Path(str(path) + ".partial")
        subprocess.run(["curl.exe" if os.name == "nt" else "curl", "--fail", "--location", "--show-error",
                        "--connect-timeout", "10", "--max-time", str(self.timeout), "--retry", "2", "--retry-delay", "2",
                        "--output", str(partial), url], check=True, timeout=self.timeout * 3 + 30)
        if not partial.is_file() or not partial.stat().st_size:
            raise ValueError(f"Empty download: {url}")
        partial.replace(path)
        receipt.write_text(json.dumps({"url": url, "sha256": file_digest(path)}, indent=2), encoding="utf-8")
        self.progress("download_finished", file=str(path), bytes=path.stat().st_size)
        return path

    def dataset(self, identifier, split, *, filenames=None):
        if identifier not in {SWE_DATASET, VERIFIED_DATASET}:
            raise ValueError("Unsupported public dataset")
        directory = self.root / identifier.replace("/", "--")
        info = self.download(f"https://huggingface.co/api/datasets/{identifier}", directory / "info.json")
        metadata = json.loads(info.read_text(encoding="utf-8"))
        if not isinstance(metadata, dict) or not isinstance(metadata.get("siblings"), list):
            raise ValueError("Invalid Hub dataset metadata")
        revision = metadata.get("sha")
        if not isinstance(revision, str) or not re.fullmatch(r"[0-9a-f]{40}", revision):
            raise ValueError("Hub metadata must supply a full pinned commit SHA")
        available = [relative_path(entry["rfilename"]) for entry in metadata["siblings"]]
        selected = select_data_files(available, split, filenames)
        paths = []
        for name in selected:
            url = f"https://huggingface.co/datasets/{identifier}/resolve/{revision}/{urllib.parse.quote(name, safe='/')}"
            paths.append(self.download(url, directory / revision / name))
        return [row for path in paths for row in read_rows(path)], {
            "dataset": identifier, "revision": revision, "split": split,
            "info_sha256": file_digest(info), "files": {str(path): file_digest(path) for path in paths},
            "authenticity_verified": False}


def select_data_files(available, split, explicit=None):
    if explicit:
        selected = [relative_path(name) for name in explicit]
        if len(set(selected)) != len(selected) or set(selected) - set(available):
            raise ValueError("Explicit dataset files must exist in the pinned metadata and be unique")
        return selected
    # Prefer standard split shards. Do not mix alternate representations or unrelated JSON metadata.
    data = [name for name in available if name.endswith((".parquet", ".jsonl"))]
    matching = [name for name in data if PurePosixPath(name).name.startswith((split + "-", split + ".")) or
                split in PurePosixPath(name).parts[:-1]]
    if matching:
        formats = {PurePosixPath(name).suffix for name in matching}
        if len(formats) != 1:
            raise ValueError("Ambiguous dataset formats; specify exact --swe-files or --verified-files")
        return sorted(matching)
    if len(data) == 1:
        return data
    raise ValueError(f"Cannot choose {split} data unambiguously; pass explicit file paths from the Hub listing: {data}")


def read_rows(path):
    if path.suffix == ".parquet":
        try:
            import pyarrow.parquet as parquet
        except ImportError:
            raise ValueError("Parquet data needs pyarrow; install .[compass-vectors] or pyarrow") from None
        # Released dataset files contain data only; no remote Python loader is executed.
        for batch in parquet.ParquetFile(path).iter_batches(batch_size=64):
            yield from batch.to_pylist()
    elif path.suffix == ".jsonl":
        with path.open(encoding="utf-8") as stream:
            for line in stream:
                if line.strip():
                    row = json.loads(line)
                    if not isinstance(row, dict):
                        raise ValueError("Dataset rows must be JSON objects")
                    yield row
    else:
        raise ValueError("Only JSONL and Parquet public exports are supported")


def select_instances(swe_rows, verified_rows, *, count=1, seed=42, repositories=None):
    import hashlib
    if type(count) is not int or not 1 <= count <= 12 or type(seed) is not int:
        raise ValueError("Choose 1..12 repositories and an integer seed")
    requested = {canonical_repository_id(repo) for repo in repositories} if repositories else None
    verified = {}
    for row in verified_rows:
        identifier = row.get("instance_id")
        if not isinstance(identifier, str) or identifier in verified:
            raise ValueError("Verified metadata needs unique instance IDs")
        verified[identifier] = row
    seen, eligible, exclusions = set(), [], {}
    for row in swe_rows:
        identifier = row.get("instance_id")
        if not isinstance(identifier, str) or identifier in seen:
            raise ValueError("SWE-Explore data needs unique instance IDs")
        seen.add(identifier)
        reason = None
        if identifier not in verified:
            reason = "not_in_verified"
        else:
            source = verified[identifier]
            repo = canonical_repository_id(source["repo"])
            issue, commit = source.get("problem_statement"), source.get("base_commit")
            gold = row.get("ground_truth")
            if requested is not None and repo not in requested:
                reason = "repository_not_requested"
            elif not isinstance(issue, str) or not 0 < len(issue.strip()) <= 8000:
                reason = "issue_outside_query_limit"
            elif not isinstance(commit, str) or not re.fullmatch(r"[0-9a-f]{40}", commit):
                reason = "invalid_base_commit"
            elif not isinstance(gold, dict) or not gold.get("read_core_regions") or not gold.get("read_core_files"):
                reason = "missing_core_labels"
            elif not any(isinstance(name, str) and name.endswith(".py") for name in gold["read_core_files"]):
                reason = "no_python_core_file"
            else:
                if not isinstance(row.get("meta", {}), dict):
                    raise ValueError(f"Invalid SWE metadata for {identifier}")
                supplied_commit = row.get("base_commit") or row.get("meta", {}).get("base_commit")
                if supplied_commit and supplied_commit != commit:
                    raise ValueError(f"SWE/Verified base commit conflict for {identifier}")
                # Preserve supplied issue text when present; metadata enrichment is explicit in the plan.
                supplied_issue = row.get("problem_statement")
                if supplied_issue and supplied_issue != issue:
                    raise ValueError(f"SWE/Verified issue text conflict for {identifier}")
                enriched = {**row, "problem_statement": issue, "base_commit": commit}
                eligible.append({"repository_id": repo, "record": enriched})
        if reason:
            exclusions[reason] = exclusions.get(reason, 0) + 1
    # Prefer the predeclared small Python repositories for the first hardware smoke experiment.
    priority = {name: index for index, name in enumerate(("pallets/flask", "psf/requests", "mwaskom/seaborn", "pytest-dev/pytest", "pydata/xarray"))}
    def key(item):
        digest = hashlib.sha256(json.dumps([seed, item["repository_id"], item["record"]["instance_id"]]).encode()).digest()
        return priority.get(item["repository_id"], 99), item["repository_id"], digest
    selected, groups = [], set()
    for item in sorted(eligible, key=key):
        if item["repository_id"] not in groups:
            selected.append(item)
            groups.add(item["repository_id"])
        if len(selected) == count:
            break
    if len(selected) != count:
        raise ValueError(f"Requested {count} repositories, but only {len(selected)} eligible groups matched. Exclusions: {exclusions}")
    return selected, {"input_instances": len(seen), "eligible_instances": len(eligible), "exclusions": exclusions,
                      "selection": "One seeded instance per repository; predeclared small-repository preference; Verified-only intersection with at least one Python core file. No retrieval scores used."}


def prepare_snapshot(repository_id, commit, directory, *, offline=False, timeout=300, source=None):
    repository_id = canonical_repository_id(repository_id)
    if not isinstance(commit, str) or not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("A full base commit is required")
    directory = Path(directory).resolve()
    if directory.exists():
        check_snapshot(directory, commit)
        return directory
    if offline:
        raise ValueError(f"Offline snapshot is missing: {directory}")
    directory.parent.mkdir(parents=True, exist_ok=True)
    staging = directory.with_name(directory.name + ".partial")
    if staging.resolve().parent != directory.parent:
        raise ValueError("Snapshot staging path escaped its intended parent")
    if staging.is_symlink():
        raise ValueError("Snapshot staging directory cannot be a symlink")
    new_staging = not staging.exists()
    marker = staging / ".git/compass-preparation.json"
    descriptor = {"repository_id": repository_id, "base_commit": commit}
    if new_staging:
        staging.mkdir()
    elif not marker.is_file() or json.loads(marker.read_text(encoding="utf-8")) != descriptor:
        raise ValueError(f"Unrecognized staging directory: {staging}; refusing to overwrite it")
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0", GIT_LFS_SKIP_SMUDGE="1")
    def git(*args):
        command = ["git", "-c", "core.autocrlf=false", "-c", "core.hooksPath=" + str(staging / ".disabled-hooks"),
                   "-c", "core.fsmonitor=false", "-C", str(staging), *args]
        try:
            return subprocess.run(command, check=True, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
        except subprocess.CalledProcessError as error:
            raise ValueError(f"Git {args[0]} failed: {error.stderr.decode('utf-8', errors='replace')}") from None
    if new_staging:
        git("init", "-q")
        marker.write_text(json.dumps(descriptor), encoding="utf-8")
    git("fetch", "--depth", "1", "--no-tags", source or f"https://github.com/{repository_id}.git", commit)
    git("checkout", "--detach", commit)
    check_snapshot(staging, commit)
    staging.rename(directory)
    return directory
