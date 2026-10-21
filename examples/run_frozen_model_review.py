"""Run frozen structured diagnostic prompts, preserving paid attempts and receipts.

This is a diagnostic review, not an automated repair or a quality score.
"""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from compass.progress import atomic_json
from keel.core import Budget, Limits, ModelError
from keel.evaluation_protocol import file_hash
from keel.models import from_config
from keel.recovery import validate_critic_decision, critic_length_warnings


def execute(plan_path, output, *, model=None):
    plan = json.loads(plan_path.read_text(encoding='utf-8'))
    identity = file_hash(plan_path)
    if identity != plan_path.with_suffix('.sha256').read_text().strip():
        raise ValueError('Frozen plan changed')
    for path, expected in plan['frozen_files'].items():
        if file_hash(Path(path)) != expected:
            raise ValueError('Frozen input changed: ' + path)
    requests = plan['requests']
    arms = [r['arm'] for r in requests]
    if not 1 <= len(arms) <= 2 or len(set(arms)) != len(arms) or not set(arms) <= {'summary', 'source'}:
        raise ValueError('Review requires one or two unique frozen summary/source arms')
    if model is None:
        model = from_config(json.loads(Path(plan['model_config']).read_text(encoding='utf-8')))
    if hasattr(model, 'check_credentials'):
        model.check_credentials()
    output.mkdir(parents=True, exist_ok=True)
    manifest = output/'manifest.json'
    expected = {'plan_sha256': identity}
    if manifest.exists():
        if json.loads(manifest.read_text()) != expected:
            raise ValueError('Output belongs to another plan')
    else:
        if list(output.iterdir()):
            raise ValueError('Unreceipted output; inspect before rerunning')
        atomic_json(manifest, expected)
    records = []
    for request in requests:
        name = request['arm']
        result_path = output/(name+'.json')
        receipt_path = output/(name+'.receipt.json')
        if result_path.exists():
            if not receipt_path.exists():
                raise ValueError('Unfinished paid attempt preserved; automatic retry disabled')
            receipt = json.loads(receipt_path.read_text())
            if receipt != {'plan_sha256': identity, 'result_sha256': file_hash(result_path)}:
                raise ValueError('Result receipt mismatch')
            record = json.loads(result_path.read_text(encoding='utf-8'))
            if record['status'] != 'completed':
                raise ValueError('Failed attempt cannot be reused')
            print('[Review] reuse '+name, flush=True)
        else:
            budget = Budget(Limits(max_model_calls=1, max_tokens=24000,
                                  max_tool_calls=1, max_wallclock=180))
            record = {'arm': name, 'status': 'pending', 'scope': plan['scope']}
            size = len(json.dumps(request['messages']).encode()) + len(json.dumps(request['schema']).encode())
            budget.allow_model(size, 1024)
            record['budget'] = budget.report()
            atomic_json(result_path, record)
            print('[Review] '+name+' one call; timeout 180s', flush=True)
            try:
                reply = model.complete_json(request['messages'], schema=request['schema'],
                                            timeout=budget.remaining, max_output=1024)
                record['raw_response'] = reply.content
                budget.charge_tokens(reply.tokens if reply.tokens is not None else size+len(reply.content.encode()))
                budget.check()
                value = json.loads(reply.content)
                validate_critic_decision(value)
                record.update(status='completed', response=value, response_warnings=critic_length_warnings(value))
            except Exception as error:
                if isinstance(error, ModelError) and error.tokens is not None:
                    budget.charge_tokens(error.tokens)
                record.update(status='failed', error_type=type(error).__name__)
                if isinstance(error, ValueError):
                    record['validation_error'] = str(error)[:600]
                raise
            finally:
                record['budget'] = budget.report()
                atomic_json(result_path, record)
            atomic_json(receipt_path, {'plan_sha256': identity, 'result_sha256': file_hash(result_path)})
        records.append(record)
    report = {'status': 'completed_needs_review', 'plan_sha256': identity, 'records': records,
              'scope': plan['scope'], 'automatic_quality_score': None}
    atomic_json(output/'report.json', report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    if not args.execute:
        plan = json.loads(args.plan.read_text(encoding='utf-8'))
        print(json.dumps({'status': 'plan_only', 'max_model_calls': len(plan['requests'])}))
        return
    report = execute(args.plan.resolve(), args.output.resolve())
    print(json.dumps({'status': report['status'], 'report': str(args.output/'report.json')}))


if __name__ == '__main__':
    main()
