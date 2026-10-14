"""Replay saved rankings under context budgets; never rerun retrieval or models."""
import argparse
import hashlib
import json
from pathlib import Path
import statistics

from .benchmarks import file_digest, load_swe_instance, pack_regions, region_metrics


def replay(result_path, output, *, budgets=(100, 300, 500), caps=(32, 64)):
    result_path, output = Path(result_path), Path(output)
    for values in (budgets, caps):
        if not values or len(set(values)) != len(values) or any(type(n) is not int or not 1 <= n <= 100000 for n in values):
            raise ValueError("Choose unique positive budgets/caps up to 100000")
    inputs = {}
    def read(path):
        path = Path(path)
        raw = path.read_bytes()
        inputs[str(path)] = hashlib.sha256(raw).hexdigest()
        return raw
    source = json.loads(read(result_path))
    if source.get("prepared_only") or source.get("planned_only"):
        raise ValueError("Expected a measured batch result")
    records, excluded = [], []
    for item in source["instances"]:
        if not item.get("measurements"):
            excluded.append({"instance": item["instance_id"], "reason": item["status"]})
            continue
        first = Path(item["measurements"][0]["sweep"])
        dataset = first.parent.parent / "instance.jsonl"
        read(dataset)
        instance = load_swe_instance(dataset, item["instance_id"], Path(item["snapshot"]))
        for measured in item["measurements"]:
            sweep_path = Path(measured["sweep"])
            sweep = json.loads(read(sweep_path))
            if sweep["instance_id"] != instance["id"] or sweep["base_commit"] != instance["base_commit"]:
                raise ValueError("Saved sweep identity does not match the instance")
            runs = [json.loads(line) for line in read(sweep_path.parent / "runs.jsonl").decode().splitlines() if line.strip()]
            if len({run["line_budget"] for run in runs}) > 1:
                raise ValueError("Replay requires a single source line budget per sweep")
            eligible = {(row["mode"], row["line_budget"]) for row in measured["summary"] if row["eligible"]}
            for run in runs:
                identity = {"instance": instance["id"], "repository": item["repository_id"],
                            "ranking": measured["ranking"], "mode": run["mode"], "repeat": run["repeat"]}
                if run["status"] != "passed" or (run["mode"], run["line_budget"]) not in eligible:
                    excluded.append({**identity, "reason": run["status"] if run["status"] != "passed" else "ineligible_source_configuration"})
                    continue
                saved = run["result"]
                if "candidates" not in saved:
                    raise ValueError("Saved results need candidate ranges for budget replay")
                candidates = saved["candidates"]
                if [row["rank"] for row in candidates] != list(range(1, len(candidates) + 1)):
                    raise ValueError("Candidate order must preserve consecutive ranks")
                rows = [{"path": row["path"], "start_line": row["start"], "end_line": row["end"]} for row in candidates]
                for budget in budgets:
                    for cap in caps:
                        regions = pack_regions(rows, budget, cap)
                        metrics = region_metrics(regions, instance["core_regions"], instance["optional_regions"], instance["core_files"])
                        ceiling = min(budget, metrics["core_lines"]) / metrics["core_lines"] if metrics["core_lines"] else 0
                        records.append({**identity, "line_budget": budget, "symbol_line_cap": cap,
                                        "metrics": metrics, "predictions": regions,
                                        "budget_utilization": metrics["predicted_unique_lines"] / budget,
                                        "budget_recall_ceiling": ceiling,
                                        "recall_fraction_of_ceiling": metrics["line_recall"] / ceiling if ceiling else 0})
    # Average repetitions within each task first; tasks then receive equal weight.
    summaries = []
    for ranking in sorted({row["ranking"] for row in records}):
        for mode in sorted({row["mode"] for row in records}):
            for budget in budgets:
                for cap in caps:
                    grouped = {}
                    for row in records:
                        if (row["ranking"], row["mode"], row["line_budget"], row["symbol_line_cap"]) == (ranking, mode, budget, cap):
                            grouped.setdefault((row["repository"], row["instance"]), []).append(row)
                    if not grouped:
                        continue
                    mean = lambda key: statistics.mean(statistics.mean(key(row) for row in group) for group in grouped.values())
                    summaries.append({"ranking": ranking, "mode": mode, "line_budget": budget, "symbol_line_cap": cap,
                                      "instances": len(grouped), "line_recall": mean(lambda r: r["metrics"]["line_recall"]),
                                      "line_precision": mean(lambda r: r["metrics"]["line_precision"]),
                                      "emitted_lines": mean(lambda r: r["metrics"]["predicted_unique_lines"]),
                                      "budget_utilization": mean(lambda r: r["budget_utilization"]),
                                      "recall_fraction_of_ceiling": mean(lambda r: r["recall_fraction_of_ceiling"])})
    if any(file_digest(Path(path)) != digest for path, digest in inputs.items()):
        raise ValueError("Source artifacts changed during replay")
    report = {"kind": "fixed-ranking context budget replay", "source_all_passed": source["all_passed"],
              "implementation_sha256": {name: file_digest(Path(__file__).parent / name)
                                        for name in ("budget_ablation.py", "benchmarks.py")},
              "inputs_sha256": inputs, "excluded": excluded, "summary": summaries, "records": records,
              "new_model_calls": 0, "public_benchmark_verified": False,
              "limitations": "Post-retrieval replay only. Rankings, model selections and source run costs are fixed; no live latency or downstream coding quality was measured. Recall ceiling uses line count only and may be unattainable with symbol prefixes. Partial runs are excluded; repetitions are not independent tasks."}
    output.mkdir(parents=True, exist_ok=False)
    (output / "budget-replay.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    lines = ["# Fixed-ranking context budget replay", "", report["limitations"], "",
             "| Ranking | Mode | Tasks | Budget | Symbol cap | Recall | Precision | Emitted lines |",
             "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    lines.extend(f"| {r['ranking']} | {r['mode']} | {r['instances']} | {r['line_budget']} | {r['symbol_line_cap']} | {r['line_recall']:.5f} | {r['line_precision']:.5f} | {r['emitted_lines']:.1f} |" for r in summaries)
    (output / "budget-replay.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--line-budgets", nargs="+", type=int, default=[100, 300, 500])
    parser.add_argument("--symbol-line-caps", nargs="+", type=int, default=[32, 64])
    args = parser.parse_args(argv)
    try:
        replay(args.result, args.output_dir, budgets=args.line_budgets, caps=args.symbol_line_caps)
        print(args.output_dir / "budget-replay.md")
    except (ValueError, OSError, KeyError, TypeError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
