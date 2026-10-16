"""Analyze saved trials without model calls or modification of source artifacts."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from keel.trial_diagnostics import analyze


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--trial', type=Path, action='append', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    reports = [analyze(path) for path in args.trial]
    with args.output.open('x', encoding='utf-8') as stream:
        json.dump({'trials': reports, 'new_model_calls': 0}, stream, indent=2)
    print(json.dumps({'output': str(args.output), 'trials': len(reports), 'new_model_calls': 0}, indent=2))


if __name__ == '__main__':
    main()
