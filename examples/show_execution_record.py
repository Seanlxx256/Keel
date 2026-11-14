"""Read-only interview walkthrough of a saved trial; never rerun the agent.

Use --trial for a local trial directory containing trial.json, run/, prediction/
and final-grade/. Saved evidence is historical, not a fresh acceptance result.
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path


def read_json(path):
    if path.stat().st_size > 4_000_000:
        raise ValueError(f"JSON exceeds viewer limit: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def check_hash(path, expected):
    if not isinstance(expected, str) or len(expected) != 64:
        raise ValueError(f"Missing SHA256 receipt: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(65536), b""):
            digest.update(block)
    if digest.hexdigest() != expected:
        raise ValueError(f"Saved artifact hash mismatch: {path}")


def show(trial):
    trial = trial.resolve(strict=True)
    summary = read_json(trial / "trial.json")
    result = read_json(trial / "run/result.json")
    receipt = read_json(trial / "prediction/export-receipt.json")
    grading = read_json(trial / "final-grade/grading.json")
    for name, key in (("run/result.json", "result_sha256"),
                      ("run/changes.patch", "patch_sha256"),
                      ("prediction/predictions.jsonl", "predictions_sha256")):
        check_hash(trial / name, receipt[key])
    # The bridge hashes the per-instance report, not the top-level aggregate.
    official = [path for family in ("evaluation", "run_evaluation")
                for path in (trial / "final-grade/logs" / family / grading["run_id"]).glob(
                    "*/" + summary["instance_id"] + "/report.json")]
    if len(official) != 1:
        raise ValueError("Expected exactly one saved official harness report")
    check_hash(official[0], grading["report_sha256"])
    if read_json(official[0])[summary["instance_id"]]["resolved"] != grading.get("official_resolved"):
        raise ValueError("Official instance report and grading disagree")
    if summary["instance_id"] != receipt["instance_id"]:
        raise ValueError("Trial and patch receipt identify different instances")
    if summary.get("official_resolved") != grading.get("official_resolved"):
        raise ValueError("Trial and grading disagree; inspect raw reports")

    print("HISTORICAL RUN WALKTHROUGH | model calls now: 0 | Docker runs now: 0")
    print("Saved artifact hashes matched; this is not fresh verification.\n")
    print("1. TASK:", summary["instance_id"])
    print(result.get("goal", "").splitlines()[0])
    print("Scope:", summary.get("scope"))
    print("Environment:", summary.get("environment_scope", "see saved report"))

    print("\n2. ROLE / EXECUTION EVENTS (selected events, original order)")
    selected = {"role_entered", "role_exited", "item_started", "item_completed",
                "command_started", "command_finished", "run_finished"}
    shown = 0
    with (trial / "run/trace.jsonl").open(encoding="utf-8") as stream:
        for line in stream:
            if len(line) > 4_000_000:
                raise ValueError("Oversized trace line; inspect externally")
            event = json.loads(line)
            if event.get("event") in selected:
                view = {key: event[key] for key in ("sequence", "role", "event", "phase",
                        "item_id", "status", "returncode") if key in event}
                print(json.dumps(view, ensure_ascii=False))
                shown += 1
                if shown == 60:
                    print("Preview limit reached; full trace remains on disk.")
                    break

    print("\n3. PATCH (first 100 lines; original file unchanged)")
    with (trial / "run/changes.patch").open(encoding="utf-8") as stream:
        for index, line in enumerate(stream):
            if index == 100:
                print("... see changes.patch for the remainder")
                break
            print(line.rstrip())
    print("\n4. SAVED ACCEPTANCE")
    print(json.dumps({"runtime_status": result.get("status"),
        "official_resolved": grading.get("official_resolved"),
        "patch_successfully_applied": grading.get("patch_successfully_applied"),
        "infra_failure": grading.get("infra_failure"),
        "verification_rounds": summary.get("verification_rounds"),
        "benchmark_ready": summary.get("benchmark_ready")}, indent=2))
    print("\n5. HISTORICAL AGENT COST (not the cost of this viewer)")
    print(json.dumps(summary.get("budget", {}), indent=2))
    print("\n6. EVIDENCE FILES")
    for name in ("run/trace.jsonl", "run/ledger.sqlite", "run/changes.patch",
                 "run/result.json", "model-transcript.jsonl", "final-grade/grading.json"):
        print(trial / name)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trial", type=Path, required=True)
    args = parser.parse_args()
    try:
        show(args.trial)
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(1, f"Saved evidence unavailable or inconsistent: {error}\n")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    main()
