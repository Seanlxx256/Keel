"""Freeze or verify a local evaluation plan; never executes models or tasks."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from keel.evaluation_protocol import freeze, verify, verify_results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--plan', type=Path)
    action.add_argument('--verify', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--results', type=Path, help='Validate a complete first-attempt result envelope with --verify')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    if args.plan:
        if args.results:
            parser.error('--results requires --verify')
        if not args.output:
            parser.error('--plan requires --output')
        result = freeze(root, json.loads(args.plan.read_text(encoding='utf-8')))
        with args.output.open('x', encoding='utf-8') as stream:
            json.dump(result, stream, indent=2)
        print(json.dumps({'status': 'preregistered_only', 'protocol_sha256': result['protocol_sha256'],
                          'tasks': len(result['tasks']), 'benchmark_ready': False}, indent=2))
    else:
        if args.output:
            parser.error('--verify does not accept --output')
        frozen = json.loads(args.verify.read_text(encoding='utf-8'))
        result = verify_results(root, frozen, json.loads(args.results.read_text(encoding='utf-8'))) if args.results else verify(root, frozen)
        print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
