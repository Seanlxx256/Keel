"""Model-free LangGraph write-approval fixture; retains artifacts for inspection."""
import argparse
import json
from pathlib import Path
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from keel.runtime import run


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--decision', choices=['interactive', 'approve', 'deny'], default='interactive')
    args = parser.parse_args()
    output = Path(__file__).resolve().parents[1] / '.keel' / 'approval-demo' / uuid.uuid4().hex
    repo = output / 'repo'
    repo.mkdir(parents=True, exist_ok=False)
    (repo / 'app.py').write_text('VERSION = 1\n', encoding='utf-8')
    config = {'goal': 'Approve scoped version change', 'orchestrator': 'langgraph',
              'approval_before_write': True, 'queries': ['VERSION'],
              'work_items': [{'id': 'edit', 'edits': [{'path': 'app.py', 'old': 'VERSION = 1', 'new': 'VERSION = 2'}]}],
              'acceptance': [[sys.executable, '-c', 'import app; assert app.VERSION == 2']]}
    def approval(request):
        print(json.dumps(request, indent=2), flush=True)
        if args.decision != 'interactive':
            return args.decision == 'approve'
        try:
            return input('Type APPROVE to change this fixture: ').strip() == 'APPROVE'
        except EOFError:
            return False
    print(f'Artifacts: {output}', flush=True)
    result = run(config, repo, output / 'run', approval=approval)
    summary = {'status': result['status'], 'approval': result.get('approval'),
               'orchestration': result['orchestration'], 'budget': result['budget'],
               'failure': result['failure'], 'source': (repo / 'app.py').read_text(encoding='utf-8')}
    (output / 'summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    print(json.dumps(summary, indent=2))
    return 0 if result['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
