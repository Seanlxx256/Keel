"""Demonstrate local observation caching and explicit evidence handoff without a model."""
import json
from pathlib import Path
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from keel.core import Budget, Ledger, Limits, Trace
from keel.gateway import ToolGateway
from keel.workspace import Workspace


def main():
    output = Path(__file__).resolve().parents[1] / '.keel' / 'memory-demo' / uuid.uuid4().hex
    repo = output / 'repo'
    repo.mkdir(parents=True, exist_ok=False)
    meta = repo / '.keel'
    meta.mkdir()
    source = repo / 'app.py'
    source.write_text('VALUE = 1\n', encoding='utf-8')
    ledger = Ledger(meta / 'ledger.sqlite')
    try:
        ws = Workspace(repo, Budget(Limits()), ledger, Trace(meta / 'trace.jsonl'))
        scout, planner = ToolGateway('scout', ws), ToolGateway('planner', ws)
        first = scout.call('search_code', {'query': 'VALUE'})
        second = planner.call('search_code', {'query': 'VALUE'})
        handoff = planner.accept_evidence(scout, [first['fact_id']])
        recalled = planner.call('recall', {'fact_id': handoff[0]['fact_id']})
        ws.list_files()
        listing = ws.list_files()
        ws.read('app.py')
        reading = ws.read('app.py')
        source.write_text('VALUE = 2\n', encoding='utf-8')
        fresh = ws.search('VALUE')
        checks = {
            'search_reused_across_roles': ledger.recall(second['fact_id'])['cache_hit'],
            'fresh_role_evidence_id': first['fact_id'] != second['fact_id'],
            'explicit_handoff_recall': 'VALUE = 1' in recalled['text'],
            'list_reused': listing['cache_hit'],
            'read_reused': reading['cache_hit'],
            'edit_invalidates_search': not fresh['cache_hit'] and fresh['matches'][0]['text'] == 'VALUE = 2',
        }
        result = {'all_passed': all(checks.values()), 'checks': checks,
                  'memory': ledger.statistics(), 'budget': ws.budget.report(),
                  'limitations': 'Deterministic local fixture; no model/token savings or MCP cache claim.'}
        (output / 'summary.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
        print(f'Artifacts: {output}')
        print(json.dumps(result, indent=2))
        return 0 if result['all_passed'] else 1
    finally:
        ledger.close()


if __name__ == '__main__':
    raise SystemExit(main())
