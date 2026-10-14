"""Instance-paired ranking summaries; repetitions never multiply task coverage."""
import statistics


def compare_rankings(instances):
    output = {}
    for mode in ("t0", "t1", "t2", "adaptive"):
        pairs, excluded = [], []
        for item in instances:
            found = {}
            for measured in item.get("measurements", []):
                for row in measured["summary"]:
                    if row["mode"] == mode and row["eligible"]:
                        found[measured["ranking"]] = row
            if set(found) == {"rrf", "code-aware"}:
                pairs.append(found)
            else:
                excluded.append(item["instance_id"])
        row = {"paired_instances": len(pairs), "excluded_instances": excluded}
        if pairs:
            row["instance_mean"] = {policy: {
                metric: statistics.mean(pair[policy]["quality"][metric] for pair in pairs)
                for metric in pairs[0][policy]["quality"]} for policy in ("rrf", "code-aware")}
            row["code_aware_minus_rrf"] = {
                metric: row["instance_mean"]["code-aware"][metric] - row["instance_mean"]["rrf"][metric]
                for metric in row["instance_mean"]["rrf"]}
            row["instance_mean_cost"] = {policy: {
                metric: statistics.mean(pair[policy]["cost"][metric] for pair in pairs)
                for metric in pairs[0][policy].get("cost", {})} for policy in ("rrf", "code-aware")}
        output[mode] = row
    escalation = {}
    for policy in ("rrf", "code-aware"):
        escalation[policy] = {}
        for advanced in ("t2", "adaptive"):
            pairs, excluded = [], []
            for item in instances:
                found = {row["mode"]: row for measured in item.get("measurements", [])
                         if measured["ranking"] == policy for row in measured["summary"]
                         if row["eligible"] and row["mode"] in {"t1", advanced}}
                if set(found) == {"t1", advanced}:
                    pairs.append(found)
                else:
                    excluded.append(item["instance_id"])
            row = {"paired_instances": len(pairs), "excluded_instances": excluded}
            for field in ("quality", "cost"):
                if pairs:
                    row[field + "_delta"] = {
                        metric: statistics.mean(pair[advanced][field][metric] - pair["t1"][field][metric] for pair in pairs)
                        for metric in pairs[0]["t1"].get(field, {})}
            if pairs:
                row["quality_outcomes"] = {metric: {
                    "improved": sum(pair[advanced]["quality"][metric] > pair["t1"]["quality"][metric] for pair in pairs),
                    "tied": sum(pair[advanced]["quality"][metric] == pair["t1"]["quality"][metric] for pair in pairs),
                    "regressed": sum(pair[advanced]["quality"][metric] < pair["t1"]["quality"][metric] for pair in pairs)}
                    for metric in pairs[0]["t1"]["quality"]}
            escalation[policy][advanced + "_minus_t1"] = row
    return {"modes": output, "escalation": escalation,
            "planned_instances": len(instances), "public_benchmark_verified": False,
            "limitations": "Paired completed configurations only; means weight instances equally, not repositories. Repetitions are not independent tasks. No significance or official evaluator claims."}


def comparison_markdown(report):
    lines = ["# Paired retrieval comparison", "",
             f"Planned independent instances: {report['planned_instances']}.", "",
             "| Mode | Paired tasks | Policy | Line recall | Line precision | File hit rate | Seconds | Model calls | Chat tokens |",
             "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    def value(mapping, key):
        return f"{mapping[key]:.5f}" if key in mapping else "n/a"
    for mode, row in report["modes"].items():
        for policy, quality in row.get("instance_mean", {}).items():
            cost = row["instance_mean_cost"][policy]
            lines.append(f"| {mode} | {row['paired_instances']} | {policy} | " +
                         " | ".join([value(quality, "line_recall"), value(quality, "line_precision"), value(quality, "hit_file_rate"),
                                     value(cost, "seconds"), value(cost, "model_calls"), value(cost, "tokens")]) + " |")
        if row["excluded_instances"]:
            lines.extend(["", f"Excluded from {mode}: " + ", ".join(row["excluded_instances"]) + ".", ""])
    lines.extend(["", "## Escalation relative to T1", "",
                  "| Policy | Comparison | Paired tasks | Recall delta | Precision delta | Recall improved/tied/regressed | Seconds delta | Model-call delta |",
                  "| --- | --- | --- | --- | --- | --- | --- | --- |"])
    for policy, comparisons in report["escalation"].items():
        for name, row in comparisons.items():
            outcomes = row.get("quality_outcomes", {}).get("line_recall")
            counts = "/".join(str(outcomes[key]) for key in ("improved", "tied", "regressed")) if outcomes else "n/a"
            lines.append(f"| {policy} | {name} | {row['paired_instances']} | " +
                         " | ".join([value(row.get("quality_delta", {}), "line_recall"),
                                     value(row.get("quality_delta", {}), "line_precision"), counts,
                                     value(row.get("cost_delta", {}), "seconds"),
                                     value(row.get("cost_delta", {}), "model_calls")]) + " |")
            if row["excluded_instances"]:
                lines.extend(["", f"Excluded from {policy}/{name}: " + ", ".join(row["excluded_instances"]) + ".", ""])
    lines.extend(["", report["limitations"], "",
                  "Timing depends on model residency and caches; it is not controlled.",
                  "A positive reference metric does not establish precise localization or official evaluator parity.", ""])
    return "\n".join(lines)


def main(argv=None):
    import argparse
    import hashlib
    import json
    from pathlib import Path
    parser = argparse.ArgumentParser(description="Summarize saved public sweeps without rerunning retrieval")
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        raw = args.result.read_bytes()
        saved = json.loads(raw)
        if saved.get("prepared_only") or saved.get("planned_only") or not isinstance(saved.get("instances"), list):
            raise ValueError("Expected an evaluation result with instances")
        report = compare_rankings(saved["instances"])
        report["source_result_sha256"] = hashlib.sha256(raw).hexdigest()
        report["source_all_passed"] = saved.get("all_passed", False)
        args.output_dir.mkdir(parents=True, exist_ok=False)
        (args.output_dir / "comparison.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        (args.output_dir / "comparison.md").write_text(comparison_markdown(report), encoding="utf-8")
        print(args.output_dir / "comparison.md")
        return 0
    except (ValueError, OSError, KeyError, TypeError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    raise SystemExit(main())
