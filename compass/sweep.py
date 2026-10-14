"""Paired Compass mode/context-budget sweeps on one verified SWE snapshot."""
import csv
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import random
import statistics

from keel.core import Budget, BudgetExceeded, Limits, ModelError
from .benchmarks import canonical_repository_id, evaluate_swe, file_digest
from .retrieval import Routing


QUALITIES = ("line_recall", "line_precision", "line_f1", "hit_file_rate", "context_efficiency")
COSTS = ("seconds", "tokens", "model_calls", "tool_calls", "vector_queries", "emitted_lines")


def summarize(records, configurations, repeats):
    rows = []
    for mode, line_budget in configurations:
        selected = [row for row in records if row["mode"] == mode and row["line_budget"] == line_budget]
        successful = [row for row in selected if row["status"] == "passed"]
        exclusions = sorted({row["status"] for row in selected if row["status"] != "passed"})
        if len(selected) != repeats:
            exclusions.append("missing_repetitions")
        row = {"mode": mode, "line_budget": line_budget, "runs": len(selected),
               "successful_runs": len(successful), "eligible": not exclusions, "exclusions": exclusions}
        if successful:
            row["quality"] = {key: statistics.mean(run["result"]["metrics"][key] for run in successful) for key in QUALITIES}
            costs = [{"seconds": run["result"]["elapsed_seconds"],
                      "emitted_lines": run["result"]["emitted_lines"], **run["result"]["usage"]} for run in successful]
            row["cost"] = {key: statistics.mean(run[key] for run in costs) for key in COSTS}
            row["seconds_stdev"] = statistics.stdev(run["seconds"] for run in costs) if len(costs) > 1 else 0.0
        rows.append(row)
    eligible = [row for row in rows if row["eligible"]]
    frontiers = {}
    for quality in QUALITIES:
        frontiers[quality] = {}
        for cost in COSTS:
            frontiers[quality][cost] = [{"mode": row["mode"], "line_budget": row["line_budget"]} for row in eligible if not any(
                other["cost"][cost] <= row["cost"][cost] and other["quality"][quality] >= row["quality"][quality] and
                (other["cost"][cost] < row["cost"][cost] or other["quality"][quality] > row["quality"][quality]) for other in eligible)]
    return rows, frontiers


def run_swe_sweep(index, instance, output_dir, *, modes=("t0", "t1", "adaptive"), line_budgets=(100, 300),
                  repeats=3, seed=0, model=None, routing=None, limits=None, repository_id=None):
    modes, line_budgets = list(modes), list(line_budgets)
    if not modes or len(set(modes)) != len(modes) or any(mode not in {"t0", "t1", "t2", "adaptive"} for mode in modes):
        raise ValueError("Choose unique t0/t1/t2/adaptive modes")
    if not line_budgets or any(type(value) is not int or not 1 <= value <= 100000 for value in line_budgets) or len(set(line_budgets)) != len(line_budgets):
        raise ValueError("Choose unique line budgets between 1 and 100000")
    if type(repeats) is not int or not 1 <= repeats <= 100 or type(seed) is not int:
        raise ValueError("repeats must be 1..100 and seed must be an integer")
    if repository_id is not None:
        repository_id = canonical_repository_id(repository_id)
    routing, limits = routing or Routing(), limits or Limits()
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=False)
    configurations = [(mode, count) for mode in modes for count in line_budgets]
    records, randomizer = [], random.Random(seed)
    for repeat in range(repeats):
        order = configurations.copy()
        randomizer.shuffle(order)
        for mode, count in order:
            budget = Budget(limits)
            row = {"mode": mode, "line_budget": count, "repeat": repeat, "status": "failed"}
            def record(event, data):
                with (output_dir / "events.jsonl").open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps({"mode": mode, "line_budget": count, "repeat": repeat,
                                             "event": event, "data": data}, ensure_ascii=False) + "\n")
            try:
                result = evaluate_swe(index, instance, line_budget=count, mode=mode, model=model, routing=routing,
                                      budget=budget, record=record)
                status = result["routing"]["mode_status"]
                row["result"] = result
                row["status"] = "passed"
                if not result["complete"]:
                    row["status"] = "incomplete_index"
                elif status == "model_unconfigured":
                    row["status"] = "deferred_escalation"
                elif status == "step_limit":
                    row["status"] = "incomplete_exploration"
            except (ValueError, OSError, BudgetExceeded, ModelError) as error:
                row["error"] = f"{type(error).__name__}: {error}"
                row["usage_at_failure"] = budget.report()
            records.append(row)
            # Retain progress and failure evidence even if a later run is interrupted.
            with (output_dir / "runs.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(row, ensure_ascii=False) + "\n")
    rows, frontiers = summarize(records, configurations, repeats)
    result = {"benchmark_format": "SWE-Explore reference sweep", "instance_id": instance["id"],
              "repository_id": repository_id,
              "base_commit": instance["base_commit"], "provenance": instance["provenance"],
              "query_sha256": hashlib.sha256(instance["query"].encode()).hexdigest(),
              "index_metadata": index.metadata, "routing": asdict(routing), "limits_per_run": asdict(limits),
              "implementation_sha256": {name: file_digest(Path(__file__).parent / name) for name in ("sweep.py", "benchmarks.py", "retrieval.py", "lexical.py")},
              "model_adapter_sha256": file_digest(Path(__file__).resolve().parent.parent / "keel/models.py"),
              "model": {"class": type(model).__name__ if model else None, "name": getattr(model, "model", None)},
              "seed": seed, "repeats": repeats, "all_passed": all(row["eligible"] for row in rows),
              "summary": rows, "frontiers": frontiers, "public_benchmark_verified": False,
              "limitations": "One instance, reference region metrics, no official evaluator parity. Configuration order is shuffled per round. Each run has an independent budget; no global sweep budget. Repetitions share an index and uncontrolled OS/model caches. Timing excludes snapshot checks and index opening. Chat tokens exclude embeddings. Frontiers use observed means without statistical significance; deferred, failed and incomplete configurations are excluded."}
    (output_dir / "sweep.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    with (output_dir / "comparison.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["mode", "line_budget", "runs", "eligible", *QUALITIES, *COSTS, "exclusions"])
        for row in rows:
            writer.writerow([row["mode"], row["line_budget"], row["runs"], row["eligible"],
                             *(row.get("quality", {}).get(key, "") for key in QUALITIES),
                             *(row.get("cost", {}).get(key, "") for key in COSTS), ",".join(row["exclusions"])])
    markdown = ["# SWE-Explore reference sweep", "", "Single-instance measurements; not a verified public-benchmark score.", "",
                "| Mode | Line budget | Recall | Seconds | Eligible |", "| --- | ---: | ---: | ---: | --- |"]
    for row in rows:
        markdown.append(f"| {row['mode']} | {row['line_budget']} | {row.get('quality', {}).get('line_recall', 'n/a')} | {row.get('cost', {}).get('seconds', 'n/a')} | {row['eligible']} |")
    markdown.extend(["", result["limitations"], ""])
    (output_dir / "report.md").write_text("\n".join(markdown), encoding="utf-8")
    return result
