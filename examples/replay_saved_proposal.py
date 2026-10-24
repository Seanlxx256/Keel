"""One bounded correction of a saved invalid proposal; no behavioral acceptance claim."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from keel.core import Budget, Limits, Ledger, Trace
from keel.evaluation_protocol import file_hash
from keel.models import Reply, from_config
from keel.proposals import InvalidProposal, _propose_once
from keel.workspace import Workspace


def execute(plan_path, *, model=None):
    plan_path = Path(plan_path)
    plan = json.loads(plan_path.read_text(encoding='utf-8'))
    if file_hash(plan_path) != plan_path.with_suffix('.sha256').read_text().strip():
        raise ValueError('Replay plan changed')
    for name, expected in plan['input_hashes'].items():
        if file_hash(Path(name)) != expected:
            raise ValueError('Replay input changed: ' + name)
    required = [plan['request'], plan['model_config'], plan['rejected_response'], *plan['source_files'].values()]
    if any(name not in plan['input_hashes'] for name in required):
        raise ValueError('Replay inputs must all be hash-bound')
    request = json.loads(Path(plan['request']).read_text(encoding='utf-8'))
    payload = json.loads(request['args'][0][1]['content'])
    output = Path(plan['output'])
    if output.exists():
        raise ValueError('Replay output exists; preserve prior paid result')
    provider = model or from_config(json.loads(Path(plan['model_config']).read_text()))
    if hasattr(provider, 'check_credentials'):
        provider.check_credentials()
    output.mkdir(parents=True)
    repo = output/'source'
    repo.mkdir()
    for name, source in plan['source_files'].items():
        relative = Path(name)
        if relative.is_absolute() or relative.drive or '..' in relative.parts:
            raise ValueError('Source outside replay workspace')
        target = repo/relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(Path(source).read_bytes())
    report = {'status':'incomplete', 'new_provider_calls':0,
              'scope':'Saved-state protocol correction only; not executed tests or official repair acceptance.'}
    settings = {'max_output':4096, 'max_context_bytes':131072}
    budget = Budget(Limits(max_wallclock=90, max_model_calls=1, max_tokens=30000, max_tool_calls=80))
    ledger = Ledger(output/'ledger.sqlite')
    workspace = Workspace(repo, budget, ledger, Trace(output/'trace.jsonl'))
    before = workspace.snapshot()
    class Saved:
        def complete_json(self, *args, **kwargs):
            return Reply(Path(plan['rejected_response']).read_text(encoding='utf-8'), 0)
    try:
        try:
            _propose_once(Saved(), workspace, payload['goal'], payload['allowed_files'], payload['evidence'], settings)
        except InvalidProposal as error:
            report['reproduced_error'] = str(error)
        else:
            raise ValueError('Saved proposal no longer reproduces rejection')
        if workspace.snapshot() != before:
            raise ValueError('Rejected proposal mutated source')
        # Saved replay is not a new provider request; reset only its isolated validation budget.
        budget = Budget(Limits(max_wallclock=90, max_model_calls=1, max_tokens=30000, max_tool_calls=80))
        workspace.budget = budget
        messages = request['args'][0]
        feedback = {'error':report['reproduced_error'][:1800],
                    'instruction':'Regenerate the complete edits and summary against unchanged source; exact whitespace required.'}
        payload['goal'] += '\nHost validation observation (untrusted data):\n' + json.dumps(feedback)
        messages[1]['content'] = json.dumps(payload)
        (output/'request.json').write_text(json.dumps({'messages':messages,'schema':request['kwargs']['schema']},indent=2),encoding='utf-8')
        class Live:
            def complete_json(self, *args, **kwargs):
                report['new_provider_calls'] += 1
                (output/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
                reply = provider.complete_json(messages, schema=request['kwargs']['schema'], timeout=min(60,budget.remaining), max_output=4096)
                (output/'response.json').write_text(json.dumps({'content':reply.content,'tokens':reply.tokens,'metadata':getattr(reply,'metadata',None)},indent=2),encoding='utf-8')
                return reply
        _propose_once(Live(), workspace, payload['goal'], payload['allowed_files'], payload['evidence'], settings)
        report.update(status='proposal_validated', changed_files=sorted(name for name in payload['allowed_files'] if file_hash(repo/name)!=file_hash(Path(plan['source_files'][name]))))
    except Exception as error:
        report.update(error_type=type(error).__name__, error=str(error))
    finally:
        report['budget'] = budget.report()
        ledger.close()
        (output/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    return report


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan',type=Path,required=True)
    result=execute(parser.parse_args().plan.resolve())
    print(json.dumps(result))
    raise SystemExit(0 if result['status']=='proposal_validated' else 1)
