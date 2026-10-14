"""Cost/quality comparisons from measured normalized evaluation reports."""
from __future__ import annotations

import csv
import io
import json
import math
from pathlib import Path


COSTS = ("mean_seconds", "mean_tokens", "mean_model_calls", "mean_tool_calls", "mean_vector_queries")
QUALITIES = ("mean_recall", "mean_ndcg", "mean_hit_file")


def comparisons(evaluation):
    summary = evaluation.get("summary") if isinstance(evaluation, dict) else None
    if not isinstance(summary, dict) or not summary:
        raise ValueError("Expected an evaluation report with a nonempty summary")
    rows = []
    for mode, metrics in summary.items():
        if not isinstance(metrics, dict):
            raise ValueError("Invalid evaluation summary")
        for key in COSTS + QUALITIES:
            value = metrics.get(key)
            if type(value) not in {int, float} or not math.isfinite(value) or value < 0 or (key in QUALITIES and value > 1):
                raise ValueError(f"Invalid or missing {key} for {mode}")
        exclusions = []
        for field in ("failures", "deferred_escalations", "incomplete_explorations"):
            value = metrics.get(field, 0)
            if type(value) is not int or value < 0:
                raise ValueError(f"Invalid {field}")
            if value:
                exclusions.append(field)
        if type(metrics.get("queries")) is not int or metrics["queries"] <= 0:
            exclusions.append("no_queries")
        rows.append({"mode": mode, **metrics, "eligible": not exclusions, "exclusions": exclusions})
    frontiers = {}
    eligible = [row for row in rows if row["eligible"]]
    for quality in QUALITIES:
        frontiers[quality] = {}
        for cost in COSTS:
            selected = [row for row in eligible if not any(
                other[cost] <= row[cost] and other[quality] >= row[quality] and
                (other[cost] < row[cost] or other[quality] > row[quality]) for other in eligible)]
            selected.sort(key=lambda row: (row[cost], -row[quality], row["mode"]))
            frontiers[quality][cost] = [row["mode"] for row in selected]
    return {"rows": rows, "frontiers": frontiers,
            "dataset_sources": evaluation.get("dataset_sources", []),
            "index_ref": evaluation.get("index_ref"), "embedding": evaluation.get("embedding"),
            "metric_scope": evaluation.get("metric_scope"),
            "public_benchmark_verified": evaluation.get("public_benchmark_verified", False)}


def write_report(evaluation, directory: Path):
    data = comparisons(evaluation)
    output = io.StringIO(newline="")
    columns = ["mode", "queries", *QUALITIES, *COSTS, "eligible", "exclusions"]
    writer = csv.DictWriter(output, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    for row in data["rows"]:
        writer.writerow({**row, "exclusions": ",".join(row["exclusions"])})

    def safe(value):
        return str(value).replace("|", "\\|").replace("\n", " ")

    markdown = ["# Compass cost-quality comparison", "",
                "This report summarizes the supplied measurements, not a verified public-benchmark result.", "",
                f"Dataset sources: {safe(', '.join(data['dataset_sources']))}",
                f"Index ref: `{safe(data['index_ref'])}`", "",
                f"Metric scope: {safe(data['metric_scope'])}", "",
                "| Mode | Recall | NDCG | Seconds | Chat tokens | Model calls | Eligible |",
                "| --- | ---: | ---: | ---: | ---: | ---: | --- |"]
    for row in data["rows"]:
        markdown.append(f"| {safe(row['mode'])} | {row['mean_recall']:.4f} | {row['mean_ndcg']:.4f} | "
                        f"{row['mean_seconds']:.6f} | {row['mean_tokens']:.1f} | {row['mean_model_calls']:.2f} | {row['eligible']} |")
    markdown.extend(["", "## Nondominated modes by recall", ""])
    for cost, modes in data["frontiers"]["mean_recall"].items():
        markdown.append(f"- {cost}: {safe(', '.join(modes) or 'none')}")
    markdown.extend(["", "## Limitations", "",
                     "Modes with failures, deferred escalations, or incomplete exploration are excluded from frontiers.",
                     "Chat token counts exclude embedding tokens. Seconds include retrieval setup but not index opening.",
                     "Dominance is computed from observed averages without confidence intervals; small timing differences may be noise.",
                     "Hash embeddings and synthetic fixtures do not establish semantic retrieval quality or production savings.", ""])
    directory = directory.resolve()
    directory.mkdir(parents=True, exist_ok=False)
    (directory / "comparison.csv").write_text(output.getvalue(), encoding="utf-8", newline="")
    (directory / "report.md").write_text("\n".join(markdown), encoding="utf-8")
    (directory / "frontiers.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"directory": str(directory), "files": [str(directory / name) for name in
                                                    ("report.md", "comparison.csv", "frontiers.json")]}
