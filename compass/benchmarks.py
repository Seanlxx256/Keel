"""Local public-format adapters. No download, dataset authenticity, or official-score claims."""
from __future__ import annotations

import csv
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import subprocess
import time

from .index import IGNORED, RepositoryIndex, git_ref
from .lexical import BM25
from .retrieval import Retriever


CORE_SOURCE = "https://github.com/zhangfw123/CORE-Bench-Eval"
SWE_SOURCE = "https://github.com/Qiushao-E/SWE-Explore-Bench"


def _jsonl(path):
    with path.open(encoding="utf-8") as stream:
        for number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            entry = json.loads(line)
            if not isinstance(entry, dict):
                raise ValueError(f"{path.name}:{number}: expected an object")
            yield entry


def _identifier(value):
    if type(value) not in {str, int} or not str(value):
        raise ValueError("Benchmark IDs must be nonempty strings or integers")
    return str(value)


def file_digest(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(65536), b""):
            digest.update(block)
    return digest.hexdigest()


@dataclass
class CoreDataset:
    corpus: dict
    queries: dict
    qrels: dict
    allowed: dict
    provenance: dict


def load_core(directory: Path, *, revision: str, level: int, max_documents=200000):
    if type(max_documents) is not int or max_documents < 1:
        raise ValueError("max_documents must be a positive integer")
    if not isinstance(revision, str) or not revision.strip() or level not in {2, 3}:
        raise ValueError("CORE input requires a data revision and level 2 or 3")
    directory = directory.resolve(strict=True)
    corpus, queries, qrels, allowed = {}, {}, {}, {}
    inputs = [directory / "corpus.jsonl", directory / "queries.jsonl"]
    for entry in _jsonl(inputs[0]):
        identifier = _identifier(entry.get("_id"))
        if identifier in corpus or not isinstance(entry.get("text"), str):
            raise ValueError("CORE corpus needs unique _id values and text strings")
        corpus[identifier] = entry["text"]
        if len(corpus) > max_documents:
            raise ValueError("CORE corpus exceeds max_documents; choose a smaller repository export or explicitly raise the limit")
    if not corpus:
        raise ValueError("CORE corpus is empty")
    for entry in _jsonl(inputs[1]):
        identifier = _identifier(entry.get("_id"))
        if identifier in queries or not isinstance(entry.get("text"), str) or not entry["text"].strip():
            raise ValueError("CORE queries need unique _id values and nonempty text")
        queries[identifier] = entry["text"]
        if "filtered_corpus_id" in entry:
            if not isinstance(entry["filtered_corpus_id"], list):
                raise ValueError("filtered_corpus_id must be an explicit list")
            ids = {_identifier(value) for value in entry["filtered_corpus_id"]}
            if ids - corpus.keys():
                raise ValueError("CORE temporal filter references missing corpus IDs")
            allowed[identifier] = ids
    labels = directory / "qrels.jsonl"
    if labels.is_file():
        entries = _jsonl(labels)
    else:
        labels = directory / "qrels" / "test.tsv"
        def tsv_rows():
            with labels.open(encoding="utf-8", newline="") as stream:
                reader = csv.DictReader(stream, delimiter="\t")
                if reader.fieldnames != ["query-id", "corpus-id", "score"]:
                    raise ValueError("Expected BEIR qrels TSV header: query-id, corpus-id, score")
                for row in reader:
                    yield {"query_id": row["query-id"], "corpus_id": row["corpus-id"], "score": row["score"]}
        entries = tsv_rows()
    for entry in entries:
        query, document = _identifier(entry.get("query_id")), _identifier(entry.get("corpus_id"))
        score = entry.get("score")
        if isinstance(score, str) and score.isdigit():
            score = int(score)
        if type(score) is not int or not 0 <= score <= 1000000:
            raise ValueError("CORE relevance grades must be nonnegative integers")
        if query not in queries or document not in corpus:
            raise ValueError("CORE qrels reference unknown queries/documents")
        if document in qrels.setdefault(query, {}):
            raise ValueError("Duplicate CORE query/document relevance label")
        if score > 0 and query in allowed and document not in allowed[query]:
            raise ValueError("Positive qrel lies outside the query's allowed snapshot corpus")
        qrels[query][document] = score
    excluded = sorted(query for query in queries if not any(value > 0 for value in qrels.get(query, {}).values()))
    queries = {query: text for query, text in queries.items() if query not in excluded}
    if not queries:
        raise ValueError("CORE export contains no queries with positive judgments")
    inputs.append(labels)
    return CoreDataset(corpus, queries, qrels, allowed, {
        "source": CORE_SOURCE, "data_revision": revision, "level": level, "origin": "user-supplied local export",
        "files": {str(path): file_digest(path) for path in inputs}, "excluded_unjudged_queries": excluded,
        "authenticity_verified": False})


def document_metrics(ranked, qrels):
    if len(set(ranked)) != len(ranked):
        raise ValueError("Ranked document IDs must be unique")
    ideal = sum(grade / math.log2(rank + 2) for rank, grade in enumerate(sorted(qrels.values(), reverse=True)[:10]))
    dcg = sum(qrels.get(identifier, 0) / math.log2(rank + 2) for rank, identifier in enumerate(ranked[:10]))
    positive = {identifier for identifier, grade in qrels.items() if grade > 0}
    return {"ndcg_at_10": dcg / ideal if ideal else 0.0,
            "recall_at_100": len(set(ranked[:100]) & positive) / len(positive) if positive else 0.0}


def evaluate_core(dataset: CoreDataset, *, max_queries=None):
    if max_queries is not None and (type(max_queries) is not int or max_queries <= 0):
        raise ValueError("max_queries must be positive")
    scorer = BM25(dataset.corpus.items())
    records = []
    for identifier in list(dataset.queries)[:max_queries]:
        started = time.perf_counter()
        # Score against full-corpus statistics, but apply snapshot eligibility before top-K.
        rows = scorer.search(dataset.queries[identifier], 100, allowed=dataset.allowed.get(identifier))
        ranked = [row["id"] for row in rows]
        records.append({"query_id": identifier, "ranked_doc_ids": ranked,
                        **document_metrics(ranked, dataset.qrels[identifier]),
                        "allowed_documents": len(dataset.allowed.get(identifier, dataset.corpus)),
                        "seconds": time.perf_counter() - started})
    return {"benchmark_format": "CORE-Bench", "policy": "compass_bm25_reference", "full_cascade": False,
            "metric_scope": "canonical document IDs; linear graded NDCG@10 and positive-label Recall@100",
            "provenance": dataset.provenance, "available_queries": len(dataset.queries), "evaluated_queries": len(records),
            "corpus_documents": len(dataset.corpus), "summary": {key: sum(row[key] for row in records) / len(records)
                                                                for key in ("ndcg_at_10", "recall_at_100", "seconds")},
            "records": records, "public_benchmark_verified": False,
            "limitations": "Per-export reference baseline; not an official evaluator or full-cascade/public leaderboard result"}


def relative_path(value):
    if not isinstance(value, str) or not value or "\x00" in value or PureWindowsPath(value).drive:
        raise ValueError("Expected a repository-relative path")
    path = PurePosixPath(value.replace("\\", "/"))
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise ValueError("Expected a repository-relative path")
    return path.as_posix()


def check_snapshot(repo: Path, expected):
    if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-fA-F]{40,64}", expected) or git_ref(repo) != expected:
        raise ValueError("SWE evaluation requires the exact labeled Git base commit")
    prefix = ["git", "-c", f"safe.directory={repo.as_posix()}", "-C", str(repo)]
    changes = subprocess.run(prefix + ["diff", "--quiet", "--no-ext-diff", "--no-textconv", expected, "--"],
                             stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=10)
    if changes.returncode != 0:
        raise ValueError("SWE repository has tracked changes or could not be checked")
    untracked = subprocess.run(prefix + ["ls-files", "--others", "-z"],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10, check=True)
    for raw in untracked.stdout.split(b"\x00"):
        if not raw:
            continue
        parts = PurePosixPath(raw.decode("utf-8")).parts
        if not set(parts) & IGNORED:
            raise ValueError("SWE repository has untracked input files; use a clean snapshot")


def load_swe_instance(path: Path, instance_id: str, repo: Path, *, issue_map=None, commit_map=None):
    if any(value is not None and not isinstance(value, dict) for value in (issue_map, commit_map)):
        raise ValueError("Issue and commit maps must be JSON objects keyed by instance ID")
    records = [entry for entry in _jsonl(path) if entry.get("instance_id") == instance_id]
    if len(records) != 1:
        raise ValueError("Select exactly one unique SWE-Explore instance")
    record, repo = records[0], repo.resolve(strict=True)
    if not isinstance(record.get("meta", {}), dict):
        raise ValueError("SWE meta must be an object")
    issue = record.get("problem_statement") or (issue_map or {}).get(instance_id)
    if not isinstance(issue, str) or not issue.strip():
        raise ValueError("SWE instance needs problem_statement or an external issue-map entry")
    expected = record.get("base_commit") or record.get("meta", {}).get("base_commit") or (commit_map or {}).get(instance_id)
    check_snapshot(repo, expected)
    gold = record.get("ground_truth")
    if not isinstance(gold, dict) or not isinstance(gold.get("read_core_regions"), list) or not gold["read_core_regions"]:
        raise ValueError("SWE ground truth requires nonempty read_core_regions")
    core_files = gold.get("read_core_files")
    if not isinstance(core_files, list) or not core_files:
        raise ValueError("SWE ground truth requires read_core_files")
    counts = {}
    def regions(entries):
        if not isinstance(entries, list):
            raise ValueError("SWE regions must be lists")
        normalized = []
        for region in entries:
            if not isinstance(region, dict):
                raise ValueError("SWE regions must contain path/start/end objects")
            name = relative_path(region.get("path"))
            target = (repo / name).resolve(strict=True)
            if not target.is_relative_to(repo) or not target.is_file():
                raise ValueError("Region points outside the repository")
            if name not in counts:
                counts[name] = len(target.read_bytes().splitlines())
            length = counts[name]
            start, end = region.get("start"), region.get("end")
            if type(start) is not int or type(end) is not int or start == 0 or not length:
                raise ValueError("Invalid SWE line interval")
            if start < 0 or end == -1:
                start = max(1, min(length + start + 1 if start < 0 else start, length))
                end = length if end == -1 else max(1, min(end, length))
            if not 1 <= start <= end <= length:
                raise ValueError("SWE region exceeds its snapshot's line bounds")
            normalized.append({"path": name, "start": start, "end": end})
        return normalized
    core = regions(gold["read_core_regions"])
    normalized_files = list(dict.fromkeys(relative_path(name) for name in core_files))
    for name in normalized_files:
        target = (repo / name).resolve(strict=True)
        if not target.is_relative_to(repo) or not target.is_file():
            raise ValueError("Core file points outside the repository")
    if {region["path"] for region in core} - set(normalized_files):
        raise ValueError("Core regions and core files disagree")
    optional_map = gold.get("read_optional_regions_map") or {}
    if not isinstance(optional_map, dict):
        raise ValueError("Optional regions must be a model-to-regions map")
    optional = [region for values in optional_map.values() for region in regions(values)]
    return {"id": instance_id, "query": issue, "repo": str(repo), "base_commit": expected,
            "core_files": normalized_files,
            "core_regions": core, "optional_regions": optional, "line_counts": counts,
            "provenance": {"source": SWE_SOURCE, "input_sha256": file_digest(path), "authenticity_verified": False}}


def _merged(regions):
    groups = {}
    for region in regions:
        groups.setdefault(region["path"], []).append((region["start"], region["end"]))
    result = {}
    for name, intervals in groups.items():
        merged = []
        for start, end in sorted(intervals):
            if merged and start <= merged[-1][1] + 1:
                merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
            else:
                merged.append((start, end))
        result[name] = merged
    return result


def _size(groups):
    return sum(end - start + 1 for intervals in groups.values() for start, end in intervals)


def _intersection(left, right):
    total = 0
    for name in left.keys() & right.keys():
        first, second = left[name], right[name]
        a = b = 0
        while a < len(first) and b < len(second):
            total += max(0, min(first[a][1], second[b][1]) - max(first[a][0], second[b][0]) + 1)
            if first[a][1] < second[b][1]:
                a += 1
            else:
                b += 1
    return total


def region_metrics(predictions, core, optional, core_files):
    pred, gold = _merged(predictions), _merged(core)
    predicted, relevant = _size(pred), _size(gold)
    hits = _intersection(pred, gold)
    precision, recall = hits / predicted if predicted else 0.0, hits / relevant if relevant else 0.0
    first = next((1 - index / len(predictions) for index, region in enumerate(predictions)
                  if _intersection(_merged([region]), gold)), 0.0)
    return {"line_precision": precision, "line_recall": recall,
            "line_f1": 2 * precision * recall / (precision + recall) if precision + recall else 0.0,
            "hit_file_rate": len(pred.keys() & set(core_files)) / len(set(core_files)) if core_files else 0.0,
            "context_efficiency": _intersection(pred, _merged(core + optional)) / predicted if predicted else 0.0,
            "first_useful_hit": first, "predicted_unique_lines": predicted, "core_lines": relevant}


def evaluate_swe(index, instance, *, line_budget=300, mode="adaptive", model=None, routing=None, budget=None):
    if type(line_budget) is not int or not 1 <= line_budget <= 100000:
        raise ValueError("line_budget must be between 1 and 100000")
    if Path(instance["repo"]).resolve() != index.root or index.metadata["git_ref"] != instance["base_commit"]:
        raise ValueError("SWE snapshot and index identities do not match")
    check_snapshot(index.root, instance["base_commit"])
    result = Retriever(index, model=model, routing=routing, budget=budget).retrieve(instance["query"], 100, mode)
    predictions, remaining = [], line_budget
    for row in result["results"]:
        if remaining == 0:
            break
        count = min(remaining, row["end_line"] - row["start_line"] + 1)
        predictions.append({"path": row["path"], "start": row["start_line"], "end": row["start_line"] + count - 1})
        remaining -= count
    check_snapshot(index.root, instance["base_commit"])
    indexed = {row[0] for row in index.db.execute("SELECT path FROM files WHERE status='indexed'")}
    return {"benchmark_format": "SWE-Explore", "instance_id": instance["id"], "base_commit": instance["base_commit"],
            "index_ref": result["index_ref"], "provenance": instance["provenance"], "line_budget": line_budget,
            "emitted_lines": line_budget - remaining, "predictions": predictions,
            "metrics": region_metrics(predictions, instance["core_regions"], instance["optional_regions"], instance["core_files"]),
            "unindexed_gold_files": sorted(set(instance["core_files"]) - indexed),
            "tier": result["tier"], "routing": result["routing"], "usage": result["usage"],
            "complete": result["complete"], "elapsed_seconds": result["elapsed_seconds"],
            "public_benchmark_verified": False, "limitations": "Reference metric subset; official evaluator parity is not verified; Python-only index"}
