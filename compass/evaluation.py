"""Normalized offline retrieval evaluation. Does not download or relabel public benchmarks."""
from __future__ import annotations

import json
import math
import hashlib
from dataclasses import asdict
from pathlib import Path, PurePosixPath
import time

from .retrieval import Retriever, Routing
from keel.core import Budget, BudgetExceeded, Limits, ModelError


def load_queries(path: Path):
    queries, identifiers = [], set()
    with path.open(encoding="utf-8") as stream:
        for number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            entry = json.loads(line)
            if not isinstance(entry, dict) or not isinstance(entry.get("id"), str) or not entry["id"] or entry["id"] in identifiers:
                raise ValueError(f"Dataset line {number} needs a unique nonempty id")
            if not isinstance(entry.get("query"), str) or not entry["query"].strip():
                raise ValueError(f"Dataset line {number} needs a query")
            files = entry.get("relevant_files")
            if not isinstance(files, list) or not files or any(not isinstance(name, str) or not name or
                    PurePosixPath(name.replace('\\', '/')).is_absolute() or '..' in PurePosixPath(name.replace('\\', '/')).parts
                    for name in files):
                raise ValueError(f"Dataset line {number} needs repository-relative relevant_files")
            entry["relevant_files"] = list(dict.fromkeys(name.replace("\\", "/") for name in files))
            if "source" in entry and not isinstance(entry["source"], str):
                raise ValueError("Dataset source must be a string")
            queries.append(entry)
            identifiers.add(entry["id"])
    if not queries:
        raise ValueError("Evaluation dataset is empty")
    return queries


def file_metrics(results, relevant, k):
    # Evaluate unique files; repeated function hits in one file never inflate relevance.
    ranked = list(dict.fromkeys(row["path"] for row in results))[:k]
    relevant = set(relevant)
    hits = [1 if name in relevant else 0 for name in ranked]
    ideal = sum(1 / math.log2(rank + 2) for rank in range(min(k, len(relevant))))
    return {"hit_file": int(any(hits)), "recall": sum(hits) / len(relevant),
            "ndcg": sum(hit / math.log2(rank + 2) for rank, hit in enumerate(hits)) / ideal,
            "returned_files": ranked}


def evaluate(index, queries, *, modes=("t0", "t1", "adaptive"), k=10, model=None, routing=None, limits=None):
    index.require_fresh()
    index._limit(k)
    if not queries:
        raise ValueError("Evaluation dataset is empty")
    modes = list(modes)
    if not modes or len(set(modes)) != len(modes) or any(mode not in {"t0", "t1", "t2", "adaptive"} for mode in modes):
        raise ValueError("Evaluation modes must be unique t0/t1/t2/adaptive values")
    records = []
    for query in queries:
        for mode in modes:
            budget = Budget(limits or Limits(max_wallclock=120, max_model_calls=8))
            started = time.perf_counter()
            record = {"id": query["id"], "query": query["query"], "relevant_files": query["relevant_files"],
                      "mode": mode, "source": query.get("source", "unspecified")}
            try:
                result = Retriever(index, routing=routing, model=model, budget=budget).retrieve(query["query"], limit=k, mode=mode)
                record.update(file_metrics(result["results"], query["relevant_files"], k), tier=result["tier"],
                              routing_status=result["routing"]["mode_status"], usage=result["usage"], status="ok")
            except (BudgetExceeded, ModelError, ValueError) as error:
                record.update(file_metrics([], query["relevant_files"], k), tier=None, routing_status="failed",
                              usage={key: budget.report()[key] for key in ("tokens", "model_calls", "tool_calls")},
                              status="failed", error=str(error))
            record["seconds"] = time.perf_counter() - started
            records.append(record)
    summary = {}
    for mode in modes:
        group = [record for record in records if record["mode"] == mode]
        summary[mode] = {"queries": len(group), "failures": sum(row["status"] != "ok" for row in group),
                         "deferred_escalations": sum(row["routing_status"] == "model_unconfigured" for row in group),
                         "incomplete_explorations": sum(row["routing_status"] == "step_limit" for row in group),
                         **{f"mean_{metric}": sum(row[metric] for row in group) / len(group)
                            for metric in ("hit_file", "recall", "ndcg", "seconds")},
                         **{f"mean_{metric}": sum(row["usage"][metric] for row in group) / len(group)
                            for metric in ("tokens", "model_calls", "tool_calls")},
                         "mean_vector_queries": sum(row["usage"].get("vector_queries", 0) for row in group) / len(group)}
    oracle = []
    if "adaptive" in modes and len(modes) > 1:
        for query in queries:
            group = [row for row in records if row["id"] == query["id"]]
            adaptive = next(row for row in group if row["mode"] == "adaptive")
            best = max(row["recall"] for row in group)
            oracle.append(best - adaptive["recall"])
    return {"dataset_sources": sorted({query.get("source", "unspecified") for query in queries}),
            "dataset_ref": hashlib.sha256(json.dumps(queries, ensure_ascii=False, sort_keys=True).encode()).hexdigest(),
            "routing": asdict(routing or Routing()), "limits": asdict(limits or Limits(max_wallclock=120, max_model_calls=8)),
            "modes": modes, "chat_model": {"configured": model is not None, "name": getattr(model, "model", type(model).__name__) if model else None},
            "metric_scope": f"binary file relevance at k={k}; unique files within the top-k symbol results",
            "k": k, "index_ref": index.metadata["index_ref"], "embedding": index.metadata["embedding"],
            "summary": summary, "mean_recall_regret_to_evaluated_modes": sum(oracle) / len(oracle) if oracle else None,
            "records": records, "public_benchmark_verified": False}
