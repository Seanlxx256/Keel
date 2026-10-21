"""Exercise production supervision on a frozen saved diagnosis, without repairs."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from compass.progress import atomic_json
from keel.core import Budget, Ledger, Limits, Trace, RecoveryStopped, InvalidSelection
from keel.evaluation_protocol import file_hash
from keel.models import Reply, from_config
from keel.recovery import RecoveryController, validate_critic_decision
from keel.workspace import Workspace


def execute(plan_path, output, *, model=None):
    plan = json.loads(plan_path.read_text(encoding='utf-8'))
    identity = file_hash(plan_path)
    if identity != plan_path.with_suffix('.sha256').read_text().strip():
        raise ValueError('Frozen plan changed')
    for path, expected in plan['frozen_files'].items():
        if file_hash(Path(path)) != expected:
            raise ValueError('Frozen input changed: '+path)
    validate_critic_decision(plan['diagnosis'])
    if output.exists():
        receipt = json.loads((output/'receipt.json').read_text()) if (output/'receipt.json').is_file() else None
        if not receipt or not (output/'report.json').is_file() or receipt != {
                'plan_sha256': identity, 'report_sha256': file_hash(output/'report.json')}:
            raise ValueError('Unfinished or altered review preserved; no automatic paid retry')
        return json.loads((output/'report.json').read_text(encoding='utf-8'))
    if model is None:
        model = from_config(json.loads(Path(plan['model_config']).read_text(encoding='utf-8')))
    if hasattr(model, 'check_credentials'):
        model.check_credentials()
    output.mkdir(parents=True, exist_ok=False)
    (output/'workspace').mkdir()
    budget = Budget(Limits(max_model_calls=4, max_tokens=60000, max_tool_calls=1, max_wallclock=360))
    ledger = Ledger(output/'ledger.sqlite')
    trace = Trace(output/'trace.jsonl')
    controller = RecoveryController({'strategy': 'adaptive', 'max_actions': 4,
        'write_roots': ['.'], 'diagnosis_supervision': True},
        Workspace(output/'workspace', budget, ledger, trace))
    report = {'status': 'running', 'plan_sha256': identity, 'scope': plan['scope'],
              'original_diagnosis': plan['diagnosis'], 'new_provider_calls': 0}
    atomic_json(output/'report.json', report)

    class SavedThenLive:
        cached = False
        calls = 0
        def complete_json(self, messages, **kwargs):
            if not self.cached:
                self.cached = True
                trace.emit('critic', 'saved_diagnosis_replayed', scope='No provider call or new paid tokens')
                return Reply(json.dumps(plan['diagnosis']), 0)
            self.calls += 1
            if self.calls > 3:
                raise RuntimeError('Live supervision call cap exceeded')
            report['new_provider_calls'] = self.calls
            report['pending_provider_call'] = self.calls
            report['budget'] = budget.report()
            atomic_json(output/'report.json', report)
            print(f'[Supervision] live call {self.calls}/3; timeout <=120s', flush=True)
            kwargs['timeout'] = min(kwargs['timeout'], 120)
            return model.complete_json(messages, **kwargs)

    proxy = SavedThenLive()
    try:
        report['final_diagnosis'] = controller.decide(proxy, plan['goal'], plan['current_plan'],
            plan['verification'], {'max_context_bytes': 32000, 'max_output': 1024},
            source_review=plan['source_review'])
        report['status'] = 'completed_needs_review'
    except RecoveryStopped as error:
        report.update(status='supervision_stopped', reason=str(error))
    except Exception as error:
        report.update(status='incomplete', error_type=type(error).__name__)
        if isinstance(error, InvalidSelection):
            report['validation_error'] = str(error)
    finally:
        report.update(new_provider_calls=proxy.calls, budget=budget.report(), recovery=controller.report(),
                      final_diagnosis_provenance='Model output only; no probe, source edit or task acceptance.')
        if report['status'] != 'incomplete':
            report.pop('pending_provider_call', None)
        atomic_json(output/'report.json', report)
        ledger.close()
    if report['status'] != 'incomplete':
        atomic_json(output/'receipt.json', {'plan_sha256': identity, 'report_sha256': file_hash(output/'report.json')})
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    if not args.execute:
        print(json.dumps({'status': 'plan_only', 'max_new_provider_calls': 3})); return 0
    report = execute(args.plan.resolve(), args.output.resolve())
    print(json.dumps({'status': report['status'], 'new_provider_calls': report['new_provider_calls'],
                      'report': str(args.output/'report.json')}))
    return 1 if report['status'] == 'incomplete' else 0


if __name__ == '__main__':
    raise SystemExit(main())
