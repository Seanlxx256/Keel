"""Repository-held-out offline gate selection from paired, completed SWE sweeps."""
from dataclasses import asdict
import hashlib
import itertools
import json
import math
from pathlib import Path
import statistics

from .benchmarks import canonical_repository_id
from .retrieval import Routing, routing_from_dict, upgrade_reasons


THRESHOLDS = ("min_relevance", "min_overlap", "max_entropy", "max_files")
DEFAULT_GRID = {"min_relevance": [0.2, 0.35, 0.5], "min_overlap": [0.0, 0.2, 0.4],
                "max_entropy": [0.9, 0.98, 1.0], "max_files": [4, 8, 16]}
COSTS = ("seconds", "tokens", "model_calls", "tool_calls", "vector_queries")


def _number(value, name, maximum=None):
    if type(value) not in {int, float} or not math.isfinite(value) or value < 0 or (maximum is not None and value > maximum):
        raise ValueError(f"Invalid {name}")
    return value


def _outcome(result):
    return {"recall": _number(result["metrics"]["line_recall"], "line recall", 1),
            "seconds": _number(result["elapsed_seconds"], "seconds"),
            **{key: _number(result["usage"][key], key) for key in COSTS if key != "seconds"}}


def _average(results):
    return {key: statistics.mean(row[key] for row in results) for key in ("recall", *COSTS)}


def load_sweeps(paths, line_budget):
    if type(line_budget) is not int or line_budget < 1:
        raise ValueError("Choose a positive line budget")
    samples, references, seen, expected_protocol = [], [], set(), None
    for path in paths:
        path = Path(path).resolve(strict=True)
        report_raw = path.read_bytes()
        report = json.loads(report_raw)
        if report.get("benchmark_format") != "SWE-Explore reference sweep":
            raise ValueError("Calibration inputs must be SWE sweep.json reports")
        if not report.get("repository_id"):
            raise ValueError("Every sweep needs an explicit canonical repository_id; rerun with --repository-id owner/repo")
        repo = canonical_repository_id(report["repository_id"])
        identity = (repo, report["instance_id"])
        if identity in seen:
            raise ValueError("Duplicate repository/instance would bias calibration")
        seen.add(identity)
        routing = routing_from_dict(report["routing"])
        protocol = {"routing_fixed": {key: value for key, value in asdict(routing).items() if key not in THRESHOLDS},
                    "embedding": report["index_metadata"]["embedding"],
                    "dimensions": report["index_metadata"].get("dimensions"),
                    "parser": report["index_metadata"]["parser"], "model": report["model"],
                    "symbol_line_cap": report.get("symbol_line_cap", 32),
                    "limits_per_run": report["limits_per_run"]}
        if protocol["embedding"] is not None and not isinstance(protocol["embedding"], dict):
            raise ValueError("Invalid embedding metadata")
        if expected_protocol is not None and protocol != expected_protocol:
            raise ValueError("Sweeps use different model, embedding, parser, limits or exploration settings")
        expected_protocol = protocol
        raw_path = path.parent / "runs.jsonl"
        raw = raw_path.read_bytes()
        runs = [json.loads(line) for line in raw.splitlines() if line.strip()]
        repeats = report["repeats"]
        if type(repeats) is not int or repeats < 1:
            raise ValueError("Invalid sweep repetition count")
        paired = {}
        for mode in ("t0", "t1", "t2"):
            selected = [row for row in runs if row["mode"] == mode and row["line_budget"] == line_budget]
            if len(selected) != repeats or sorted(row["repeat"] for row in selected) != list(range(repeats)):
                raise ValueError("Each instance needs exactly paired T0/T1/T2 runs at the selected line budget")
            if any(row["status"] != "passed" or not row["result"]["complete"] for row in selected):
                raise ValueError("Failed, deferred or incomplete paired runs cannot calibrate a gate")
            expected_status = "completed" if mode == "t2" else "not_needed"
            if any(row["result"]["tier"] != mode.upper() or row["result"]["routing"]["mode_status"] != expected_status for row in selected):
                raise ValueError("Paired mode did not finish its requested retrieval tier")
            if any(row["result"]["instance_id"] != report["instance_id"] or
                   row["result"]["base_commit"] != report["base_commit"] or
                   row["result"]["line_budget"] != line_budget for row in selected):
                raise ValueError("Paired instance, snapshot or line budget differs from its sweep")
            if any(row["result"]["index_ref"] != report["index_metadata"]["index_ref"] for row in selected):
                raise ValueError("Paired run/index identities differ")
            paired[mode] = selected
        signals = paired["t1"][0]["result"]["signals"]
        if any(row["result"]["signals"] != signals for row in paired["t1"]):
            raise ValueError("T1 gate signals changed across repetitions")
        for key in ("top_relevance", "score_entropy"):
            _number(signals[key], key, 1)
        if signals["channel_overlap"] is not None:
            _number(signals["channel_overlap"], "channel_overlap", 1)
        for key in ("file_span", "lexical_hits", "vector_hits"):
            if type(signals[key]) is not int or signals[key] < 0:
                raise ValueError(f"Invalid {key}")
        bypass = bool(paired["t0"][0]["result"]["predictions"])
        if any(bool(row["result"]["predictions"]) != bypass for row in paired["t0"]):
            raise ValueError("T0 bypass changed across repetitions")
        samples.append({"repository": repo, "id": report["instance_id"], "base_commit": report["base_commit"],
                        "signals": signals, "t0_bypass": bypass,
                        **{mode: _average([_outcome(row["result"]) for row in paired[mode]]) for mode in paired}})
        references.append({"sweep": str(path), "sweep_sha256": hashlib.sha256(report_raw).hexdigest(),
                           "runs_sha256": hashlib.sha256(raw).hexdigest(), "line_budget": line_budget})
    if not samples:
        raise ValueError("No paired samples")
    return samples, references, expected_protocol


def split_repositories(samples, seed=42, holdout_fraction=0.25):
    if type(seed) is not int or not 0 < holdout_fraction < 1:
        raise ValueError("Choose an integer seed and holdout fraction between 0 and 1")
    repositories = sorted({row["repository"] for row in samples},
                          key=lambda repo: hashlib.sha256(json.dumps([seed, repo]).encode()).digest())
    if len(repositories) < 3:
        raise ValueError("Calibration requires at least three independent repository groups")
    count = max(1, min(len(repositories) - 1, math.ceil(len(repositories) * holdout_fraction)))
    holdout = set(repositories[:count])
    return ([row for row in samples if row["repository"] not in holdout],
            [row for row in samples if row["repository"] in holdout])


def simulate(samples, routing, upgrade_penalty):
    rows = []
    for sample in samples:
        upgrade = not sample["t0_bypass"] and bool(upgrade_reasons(sample["signals"], True, routing))
        chosen = sample["t0"] if sample["t0_bypass"] else sample["t2"] if upgrade else sample["t1"]
        rows.append({"repository": sample["repository"], "id": sample["id"], "upgraded": upgrade, **chosen})
    groups = {}
    for row in rows:
        groups.setdefault(row["repository"], []).append(row)
    recall = statistics.mean(statistics.mean(row["recall"] for row in group) for group in groups.values())
    rate = statistics.mean(statistics.mean(row["upgraded"] for row in group) for group in groups.values())
    return {"instances": len(rows), "repositories": sorted(groups), "repository_mean_recall": recall,
            "repository_mean_upgrade_rate": rate, "utility": recall - upgrade_penalty * rate,
            "query_mean_cost": {key: statistics.mean(row[key] for row in rows) for key in COSTS}, "decisions": rows}


def calibrate(paths, output_dir, *, line_budget, seed=42, holdout_fraction=0.25,
              upgrade_penalty=0.02, max_upgrade_rate=1.0, grid=None):
    _number(upgrade_penalty, "upgrade_penalty")
    _number(max_upgrade_rate, "max_upgrade_rate", 1)
    samples, references, protocol = load_sweeps(paths, line_budget)
    development, holdout = split_repositories(samples, seed, holdout_fraction)
    grid = DEFAULT_GRID if grid is None else grid
    if not isinstance(grid, dict) or set(grid) != set(THRESHOLDS) or any(not isinstance(grid[key], list) or not grid[key] for key in THRESHOLDS):
        raise ValueError("Grid must contain nonempty lists for the four routing thresholds")
    combinations = math.prod(len(grid[key]) for key in THRESHOLDS)
    if combinations > 4096:
        raise ValueError("Grid exceeds 4096 combinations")
    candidates = []
    fixed = protocol["routing_fixed"]
    for values in itertools.product(*(grid[key] for key in THRESHOLDS)):
        routing = Routing(**fixed, **dict(zip(THRESHOLDS, values)))
        outcome = simulate(development, routing, upgrade_penalty)
        candidates.append({"routing": asdict(routing), "utility": outcome["utility"],
                           "development_recall": outcome["repository_mean_recall"],
                           "development_upgrade_rate": outcome["repository_mean_upgrade_rate"]})
    eligible = [row for row in candidates if row["development_upgrade_rate"] <= max_upgrade_rate]
    if not eligible:
        raise ValueError("No candidate satisfies the development upgrade-rate cap")
    # No holdout labels or outcomes participate in candidate selection or tie breaking.
    selected = sorted(eligible, key=lambda row: (-row["utility"], row["development_upgrade_rate"],
                                                json.dumps(row["routing"], sort_keys=True)))[0]
    routing = Routing(**selected["routing"])
    result = {"kind": "repository-held-out offline routing calibration", "protocol": protocol,
              "implementation_sha256": {name: hashlib.sha256((Path(__file__).parent / name).read_bytes()).hexdigest()
                                        for name in ("calibration.py", "retrieval.py")},
              "inputs": references, "seed": seed, "holdout_fraction": holdout_fraction,
              "upgrade_penalty": upgrade_penalty, "max_development_upgrade_rate": max_upgrade_rate,
              "grid": grid, "candidates": candidates, "selected_routing": asdict(routing),
              "semantic_embedding_configured": bool(protocol["embedding"] and protocol["embedding"].get("provider") == "ollama"),
              "online_adaptive_verified": False,
              "development": simulate(development, routing, upgrade_penalty),
              "holdout": simulate(holdout, routing, upgrade_penalty), "public_benchmark_verified": False,
              "limitations": "Offline replay chooses measured T0/T1/T2 outcomes, not a new online adaptive run. Repetitions are averaged within instances. Selection maximizes repository-mean line recall minus a declared upgrade-rate penalty on development repositories only. The rate cap applies to development only. User-declared repository identities and prior holdout access cannot be independently verified. No official evaluator parity or statistical significance."}
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=False)
    (output_dir / "calibration.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    (output_dir / "routing.json").write_text(json.dumps(asdict(routing), indent=2), encoding="utf-8")
    return result
