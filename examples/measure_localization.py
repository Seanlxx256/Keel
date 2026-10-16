"""Measure existing localization preflight with a non-network model sentinel."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from keel.core import Budget, BudgetExceeded, Ledger, Limits, Trace
from keel.workspace import Workspace
from keel.localization import localize


class RequestReady(Exception):
    pass


class NoNetworkModel:
    def __init__(self):
        self.request_bytes = None

    def complete_json(self, messages, *, schema, **kwargs):
        self.request_bytes = len(json.dumps(messages).encode()) + len(json.dumps(schema).encode())
        raise RequestReady()


def measure(repo, output, *, cap=12000, tools=60):
    output.mkdir(parents=True, exist_ok=False)
    ledger = Ledger(output/'ledger.sqlite')
    budget = Budget(Limits(max_tool_calls=tools, max_tokens=180000, max_model_calls=30, max_wallclock=450))
    workspace = Workspace(repo, budget, ledger, Trace(output/'trace.jsonl'))
    before = workspace.snapshot()
    model = NoNetworkModel()
    report = {'repository': str(repo.resolve()), 'cap_bytes': cap, 'tool_limit': tools,
        'new_model_calls': 0, 'scope': 'First request preflight only; file selection in hierarchical mode. No selected-file, anchor or repair-context measurement'}
    try:
        localize(model, workspace, 'Repair a dependency compatibility issue in this repository.',
            {'max_context_bytes': cap, 'max_output': 1024})
        raise AssertionError('Sentinel was not reached or preflight did not stop')
    except RequestReady:
        report.update(status='request_fits', request_bytes=model.request_bytes)
    except BudgetExceeded as error:
        report.update(status='budget_blocked', error=str(error))
    except (OSError, ValueError) as error:
        report.update(status='input_error', error=f'{type(error).__name__}: {error}')
    finally:
        report['source_unchanged'] = workspace.snapshot() == before
        report['tool_calls'] = budget.tool_calls
        report['snapshot_bytes'] = workspace.snapshot_bytes
        ledger.close()
    events = [json.loads(line) for line in (output/'trace.jsonl').read_text().splitlines()]
    progress = [event for event in events if event['event'] == 'localization_structure']
    report['last_structure_files'] = progress[-1]['files'] if progress else 0
    report['last_structure_bytes'] = progress[-1]['bytes'] if progress else 0
    report['input_inventory'] = before
    (output/'measurement.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    return {k: v for k, v in report.items() if k != 'input_inventory'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, action='append', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    reports = [measure(repo, args.output/f'repo-{i:03}') for i, repo in enumerate(args.repo, 1)]
    (args.output/'summary.json').write_text(json.dumps(reports, indent=2), encoding='utf-8')
    print(json.dumps(reports, indent=2))


if __name__ == '__main__':
    main()
