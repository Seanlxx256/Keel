"""Validate 300/64 on new Requests/Seaborn issues, then replay packing baselines."""
import argparse
from pathlib import Path
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from compass.budget_ablation import replay
from run_swe_public import main as run_public


def main(argv=None):
    project = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--previous-result", type=Path, default=project / "docs/evaluations/compass-final-policy-three-repo.json")
    parser.add_argument("--plan-only", action="store_true")
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--repeats", type=int, default=1)
    args = parser.parse_args(argv)
    output = project / ".keel/swe-independent" / uuid.uuid4().hex
    command = ["--repositories", "2", "--repository-id", "psf/requests", "mwaskom/seaborn",
               "--exclude-result", str(args.previous_result), "--line-budget", "300", "--symbol-line-cap", "64",
               "--ranking", "code-aware", "--repeats", str(args.repeats), "--output-dir", str(output)]
    for option in ("plan_only", "prepare_only", "offline"):
        if getattr(args, option):
            command.append("--" + option.replace("_", "-"))
    status = run_public(command)
    if status == 0 and not args.plan_only and not args.prepare_only:
        replay(output / "result.json", output / "budget-analysis", budgets=(100, 300), caps=(32, 64))
        print(f"Budget comparison: {output / 'budget-analysis/budget-replay.md'}", flush=True)
    return status


if __name__ == "__main__":
    raise SystemExit(main())
