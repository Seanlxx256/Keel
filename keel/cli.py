import argparse
import json
from pathlib import Path

from .runtime import new_run_directory, run


def main():
    parser = argparse.ArgumentParser(description="Keel reliability runtime: explicit and model-driven plans")
    sub = parser.add_subparsers(dest="command", required=True)
    execute = sub.add_parser("run", help="Execute a task in a disposable working copy")
    execute.add_argument("config", type=Path)
    execute.add_argument("--repo", type=Path, required=True)
    replay = sub.add_parser("replay", help="Print recorded run events")
    replay.add_argument("run_dir", type=Path)
    recall = sub.add_parser("recall", help="Retrieve a complete ledger entry")
    recall.add_argument("run_dir", type=Path)
    recall.add_argument("fact_id", type=int)
    args = parser.parse_args()
    try:
        if args.command == "run":
            config = json.loads(args.config.read_text(encoding="utf-8"))
            result = run(config, args.repo, new_run_directory(args.repo))
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result["status"] == "passed" else 1
        if args.command == "replay":
            print((args.run_dir / "trace.jsonl").read_text(encoding="utf-8"), end="")
        else:
            from .core import Ledger
            path = args.run_dir / "ledger.sqlite"
            if not path.is_file():
                raise ValueError("Ledger does not exist")
            ledger = Ledger(path)
            try:
                print(json.dumps(ledger.recall(args.fact_id), ensure_ascii=False, indent=2))
            finally:
                ledger.close()
        return 0
    except (ValueError, OSError, KeyError) as error:
        parser.exit(2, f"keel: {error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
