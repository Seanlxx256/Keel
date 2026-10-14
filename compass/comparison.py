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
        output[mode] = row
    return {"modes": output, "planned_instances": len(instances), "public_benchmark_verified": False,
            "limitations": "Paired completed configurations only; means weight instances equally, not repositories. Repetitions are not independent tasks. No significance or official evaluator claims."}
