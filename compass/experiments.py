"""Reproducible local CORE reference batches; never an official benchmark claim."""
from dataclasses import replace
import csv
import hashlib
import json
from pathlib import Path
import platform
import statistics
import time

from .benchmarks import evaluate_core, file_digest, load_core
from .progress import ProgressLog


METRICS = ("ndcg_at_10", "recall_at_100")


def load_manifest(path):
    path = Path(path).resolve(strict=True)
    raw = path.read_bytes()
    config = json.loads(raw)
    if not isinstance(config, dict) or type(config.get("version")) is not int or config["version"] != 1 or config.get("benchmark") != "core":
        raise ValueError("Manifest requires version 1 and benchmark core")
    entries = config.get("datasets")
    if not isinstance(entries, list) or not entries:
        raise ValueError("Manifest needs a nonempty datasets list")
    names, locations, result = set(), set(), []
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("Dataset entries must be objects")
        name, directory = entry.get("name"), entry.get("data_dir")
        if not isinstance(name, str) or not name.strip() or name in names:
            raise ValueError("Dataset names must be unique nonempty strings")
        if not isinstance(directory, str) or not directory:
            raise ValueError("Each dataset needs data_dir")
        directory = (path.parent / directory).resolve(strict=True)
        if directory in locations:
            raise ValueError("Duplicate dataset directories would bias aggregates")
        if not isinstance(entry.get("revision"), str) or not entry["revision"].strip() or type(entry.get("level")) is not int or entry["level"] not in {2, 3}:
            raise ValueError("Each dataset needs revision and level 2 or 3")
        pins = entry.get("sha256", {})
        if not isinstance(pins, dict) or any(not isinstance(k, str) or not isinstance(v, str) or
                len(v) != 64 or any(c not in "0123456789abcdef" for c in v) for k, v in pins.items()):
            raise ValueError("sha256 must map relative input names to lowercase SHA-256 values")
        result.append({**entry, "data_dir": directory})
        names.add(name)
        locations.add(directory)
    return result, hashlib.sha256(raw).hexdigest()


def select_queries(queries, count, seed, namespace):
    # Stable under JSONL reordering; labels never influence selection.
    def key(identifier):
        return hashlib.sha256(json.dumps([seed, namespace, identifier], ensure_ascii=False).encode()).digest(), identifier
    identifiers = sorted(queries, key=key)
    return {identifier: queries[identifier] for identifier in identifiers[:count]}


def run_core_batch(manifest, output_dir, *, repeats=3, max_queries=None, seed=0, max_documents=200000, progress=False):
    if type(repeats) is not int or not 1 <= repeats <= 100:
        raise ValueError("repeats must be between 1 and 100")
    if max_queries is not None and (type(max_queries) is not int or max_queries < 1):
        raise ValueError("max_queries must be positive")
    if type(seed) is not int:
        raise ValueError("seed must be an integer")
    entries, digest = load_manifest(manifest)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=False)
    with ProgressLog(output_dir / "progress.jsonl", console=progress) as reporter:
        reporter.emit("batch_started", datasets=len(entries), repeats=repeats)
        records = _run_datasets(entries, output_dir, repeats, max_queries, seed, max_documents, reporter)
        reporter.emit("batch_finished", successful_datasets=sum(row["status"] == "passed" for row in records),
                      failed_datasets=sum(row["status"] == "failed" for row in records))
    return _write_batch(entries, digest, output_dir, records, repeats, max_queries, seed, max_documents)


def _run_datasets(entries, output_dir, repeats, max_queries, seed, max_documents, reporter):
    records = []
    for number, entry in enumerate(entries):
        record = {"name": entry["name"], "status": "failed"}
        context = {"dataset": entry["name"], "dataset_number": number + 1, "total_datasets": len(entries)}
        def notify(event, **fields):
            reporter.emit(event, **context, **fields)
        try:
            notify("input_hashing_started")
            directory = entry["data_dir"]
            labels = directory / "qrels.jsonl" if (directory / "qrels.jsonl").is_file() else directory / "qrels" / "test.tsv"
            before = {str(path): file_digest(path) for path in (directory / "corpus.jsonl", directory / "queries.jsonl", labels)}
            notify("dataset_loading_started")
            dataset = load_core(entry["data_dir"], revision=entry["revision"], level=entry["level"], max_documents=max_documents)
            notify("dataset_loading_finished", documents=len(dataset.corpus), available_queries=len(dataset.queries))
            files = dataset.provenance["files"]
            if files != before:
                raise ValueError("Dataset inputs changed during loading")
            actual = {Path(name).relative_to(entry["data_dir"]).as_posix(): value for name, value in files.items()}
            pins = entry.get("sha256", {})
            if pins and pins != actual:
                raise ValueError("Pinned SHA-256 inputs differ; pins must cover every consumed input")
            queries = select_queries(dataset.queries, max_queries, seed, entry["name"])
            selected = replace(dataset, queries=queries)
            runs, durations = [], []
            for repeat in range(repeats):
                context["repeat"] = repeat + 1
                context["total_repeats"] = repeats
                notify("repeat_started", selected_queries=len(queries))
                started = time.perf_counter()
                evaluated = evaluate_core(selected, progress=notify)
                durations.append(time.perf_counter() - started)
                notify("integrity_check_started")
                if any(file_digest(Path(name)) != value for name, value in files.items()):
                    raise ValueError("Dataset inputs changed during evaluation")
                ranking = [(row["query_id"], row["ranked_doc_ids"]) for row in evaluated["records"]]
                if runs and ranking != [(row["query_id"], row["ranked_doc_ids"]) for row in runs[0]["records"]]:
                    raise ValueError("Deterministic BM25 rankings changed between repetitions")
                artifact = f"dataset-{number:04d}-repeat-{repeat:03d}.json"
                (output_dir / artifact).write_text(json.dumps(evaluated, indent=2), encoding="utf-8")
                runs.append(evaluated)
                notify("repeat_finished", seconds=durations[-1], artifact=artifact)
            record.update(status="passed", level=entry["level"], revision=entry["revision"],
                          identical_duplicate_qrels=dataset.provenance["identical_duplicate_qrels"],
                          available_queries=len(dataset.queries), evaluated_queries=len(queries),
                          selected_query_ids=list(queries), sha256=actual, hashes_pinned=bool(pins),
                          metrics={metric: runs[0]["summary"][metric] for metric in METRICS},
                          repeat_seconds=durations, mean_seconds=statistics.mean(durations),
                          stdev_seconds=statistics.stdev(durations) if repeats > 1 else 0.0)
        except (ValueError, OSError, KeyError) as error:
            record["error"] = f"{type(error).__name__}: {error}"
            notify("dataset_failed", error=record["error"])
        records.append(record)
        with (output_dir / "datasets.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")
        notify("dataset_finished", status=record["status"])
    return records


def _write_batch(entries, digest, output_dir, records, repeats, max_queries, seed, max_documents):
    passed = [record for record in records if record["status"] == "passed"]
    count = sum(record["evaluated_queries"] for record in passed)
    summary = {"successful_datasets": len(passed), "failed_datasets": len(records) - len(passed), "queries": count}
    if passed:
        summary["query_weighted_mean"] = {metric: sum(record["metrics"][metric] * record["evaluated_queries"] for record in passed) / count for metric in METRICS}
        summary["repository_mean"] = {metric: statistics.mean(record["metrics"][metric] for record in passed) for metric in METRICS}
    summary["by_level"] = {}
    for level in (2, 3):
        subset = [record for record in passed if record["level"] == level]
        if subset:
            queries = sum(record["evaluated_queries"] for record in subset)
            summary["by_level"][str(level)] = {
                "datasets": len(subset), "queries": queries,
                "query_weighted_mean": {metric: sum(record["metrics"][metric] * record["evaluated_queries"] for record in subset) / queries for metric in METRICS},
                "repository_mean": {metric: statistics.mean(record["metrics"][metric] for record in subset) for metric in METRICS}}
    result = {"benchmark": "CORE-Bench local reference batch", "policy": "compass_bm25_reference",
              "manifest_sha256": digest, "python": platform.python_version(), "platform": platform.platform(),
              "implementation_sha256": {name: file_digest(Path(__file__).parent / name) for name in ("experiments.py", "benchmarks.py", "lexical.py")},
              "repeats": repeats, "seed": seed, "max_queries_per_dataset": max_queries,
              "max_documents": max_documents, "all_passed": len(passed) == len(records),
              "public_benchmark_verified": False, "summary": summary, "datasets": records,
              "limitations": "Declared revisions; optional hash pins are integrity checks, not authenticity. Repetitions measure timing, not independent quality samples. Each repetition rebuilds BM25; OS caches are uncontrolled. Failed datasets excluded from means; partial batches are not complete results. No official evaluator parity or full cascade."}
    (output_dir / "batch.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    with (output_dir / "datasets.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["name", "status", "queries", *METRICS, "mean_seconds", "stdev_seconds", "error"])
        for row in records:
            writer.writerow([row["name"], row["status"], row.get("evaluated_queries", ""),
                             *(row.get("metrics", {}).get(metric, "") for metric in METRICS),
                             row.get("mean_seconds", ""), row.get("stdev_seconds", ""), row.get("error", "")])
    return result
