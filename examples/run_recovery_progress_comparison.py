"""Freeze and execute one cost-bounded development pair using the shared task runner."""
import argparse
from importlib.util import find_spec
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from compass.progress import atomic_json
from examples.run_swebench_task import check_reference, execute
from keel.evaluation_protocol import file_hash, implementation_hashes
from keel.models import from_config
from keel.saved_repair import load_saved_repair
from keel.swebench import verify_task

LIMITS = {'max_model_calls': 12, 'max_tokens': 80000, 'max_wallclock': 900, 'max_tool_calls': 80}
PATH_KEYS = ('task', 'reference_grade', 'model_config', 'harness_python', 'resume_snapshot', 'saved_repo', 'mcp_config')


def validate_host(inputs):
    if inputs.get('mcp_config') and find_spec('mcp') is None:
        raise ValueError('Selected host Python lacks the MCP client; prepare/run using the configured environment')


def validate_inputs(inputs):
    paths = {key: Path(value) if value else None for key, value in inputs.items()}
    check_reference(paths['task'], paths['reference_grade'])
    patch, context = load_saved_repair(paths['task'], paths['reference_grade'],
                                      paths['resume_snapshot'], paths['saved_repo'])
    return paths, context


def prepare(root, output, inputs):
    validate_host(inputs)
    paths, context = validate_inputs(inputs)
    frozen = [paths['task']/'task-receipt.json', paths['reference_grade']/'grading.json',
              paths['resume_snapshot']/'snapshot-grade.json', paths['model_config'], paths['harness_python']]
    if paths['mcp_config']:
        frozen.append(paths['mcp_config'])
    plan = {'version': 1, 'root': str(root), 'inputs': inputs,
            'instance_id': verify_task(paths['task'])['instance_id'],
            'implementation': implementation_hashes(root),
            'frozen_files': {str(path): file_hash(path) for path in frozen},
            'continuation': context['provenance'], 'limits_per_arm': LIMITS,
            'host_python': sys.executable,
            'arms': [{'name': 'baseline', 'recovery_progress': False},
                     {'name': 'progress', 'recovery_progress': True}],
            'scope': 'One exposed development task, one new attempt per arm, fixed baseline-first order. '
                     'No independent/generalized efficacy or statistical claim.',
            'decision_rule': 'Compare runtime and official resolution first; retain costs and feedback exposure. '
                             'Both failed means no efficacy winner. Lower cost alone is insufficient.',
            'stop_rule': 'No paid retry. Stop the pair on incomplete, infrastructure or model error. '
                         'Reuse only matching receipted completed arms.',
            'cost_boundary': 'Per-arm Agent limits exclude source preparation and final Docker grading. '
                             'Intermediate grading consumes Agent time; final grading has its own runner timeout.'}
    output.mkdir(parents=True, exist_ok=False)
    atomic_json(output/'plan.json', plan)
    (output/'plan.sha256').write_text(file_hash(output/'plan.json'), encoding='ascii')
    return plan


def validate_plan(root, output):
    plan = json.loads((output/'plan.json').read_text(encoding='utf-8'))
    if file_hash(output/'plan.json') != (output/'plan.sha256').read_text().strip():
        raise ValueError('Frozen plan changed')
    if (plan['root'] != str(root) or plan['host_python'] != sys.executable
            or plan['implementation'] != implementation_hashes(root) or plan['limits_per_arm'] != LIMITS):
        raise ValueError('Frozen implementation/interpreter/limits changed; preserve this plan')
    validate_host(plan['inputs'])
    for name, expected in plan['frozen_files'].items():
        if file_hash(Path(name)) != expected:
            raise ValueError('Frozen input changed: ' + name)
    paths, context = validate_inputs(plan['inputs'])
    if context['provenance'] != plan['continuation']:
        raise ValueError('Saved source/feedback provenance changed')
    return plan, paths


def verify_completed(directory, arm, plan):
    raw = directory/'trial.json'
    receipt_path = directory/'comparison-receipt.json'
    if not raw.is_file() or not receipt_path.is_file():
        raise ValueError('Existing arm has no completed receipt; preserve it, no automatic paid retry')
    receipt = json.loads(receipt_path.read_text(encoding='utf-8'))
    if file_hash(raw) != receipt['trial_sha256']:
        raise ValueError('Completed trial receipt mismatch')
    row = json.loads(raw.read_text(encoding='utf-8'))
    validate_trial(row, arm, plan)
    grading = directory/'final-grade'/'grading.json'
    if file_hash(grading) != receipt['grading_sha256']:
        raise ValueError('Final grading receipt mismatch')
    trace = directory/'run'/'trace.jsonl'
    if (file_hash(trace) if trace.exists() else None) != receipt['trace_sha256']:
        raise ValueError('Trial trace receipt mismatch')
    verdict = json.loads(grading.read_text(encoding='utf-8'))
    if verdict.get('status') != 'graded' or verdict.get('official_resolved') != row['official_resolved'] or verdict.get('infra_failure'):
        raise ValueError('No matching infrastructure-free official grading')
    return row


def validate_trial(row, arm, plan):
    if (row.get('status') != 'completed' or type(row.get('official_resolved')) is not bool
            or row.get('implementation') != plan['implementation']
            or row.get('recovery_progress') is not arm['recovery_progress']
            or row.get('diagnostic_inspection') is not False
            or row.get('limits') != plan['limits_per_arm']
            or row.get('budget', {}).get('limits') != plan['limits_per_arm']
            or row.get('continuation') != plan['continuation']):
        raise ValueError('Trial is incomplete or differs from the frozen comparison')
    if (row.get('failure') or {}).get('category') in {'model_error', 'unexpected_termination'}:
        raise ValueError('Model/transport interruption; preserve the arm and stop without paid retry')
    if row.get('grading_error'):
        raise ValueError('Final grading error; stop the pair')


def execute_pair(root, output):
    plan, paths = validate_plan(root, output)
    # Validate every existing output before authorizing another paid arm.
    for arm in plan['arms']:
        directory = output/arm['name']
        if directory.exists():
            verify_completed(directory, arm, plan)
    report = {'status': 'running', 'plan_sha256': file_hash(output/'plan.json'),
              'records': [], 'scope': plan['scope'], 'cost_boundary': plan['cost_boundary']}
    try:
        for arm in plan['arms']:
            validate_plan(root, output)
            directory = output/arm['name']
            if directory.exists():
                print('[Recovery pair] reuse ' + arm['name'], flush=True)
                row = verify_completed(directory, arm, plan)
            else:
                model_config = json.loads(paths['model_config'].read_text(encoding='utf-8'))
                model = from_config(model_config)
                if hasattr(model, 'check_credentials'):
                    model.check_credentials()
                print('[Recovery pair] start ' + arm['name'], flush=True)
                row = execute(root, paths['task'], paths['reference_grade'], model_config,
                    str(paths['harness_python']), directory, mcp_config=paths['mcp_config'],
                    resume_snapshot=paths['resume_snapshot'], saved_repo=paths['saved_repo'],
                    diagnostic_inspection=False, recovery_progress=arm['recovery_progress'], budget_limits=LIMITS)
                validate_trial(row, arm, plan)
                atomic_json(directory/'comparison-receipt.json', {
                    'trial_sha256': file_hash(directory/'trial.json'),
                    'grading_sha256': file_hash(directory/'final-grade'/'grading.json'),
                    'trace_sha256': file_hash(directory/'run'/'trace.jsonl')
                        if (directory/'run'/'trace.jsonl').exists() else None})
                row = verify_completed(directory, arm, plan)
            progress = (row.get('recovery') or {}).get('progress', {})
            report['records'].append({'arm': arm['name'], 'official_resolved': row['official_resolved'],
                'runtime_status': row['runtime_status'], 'budget': row['budget'],
                'failure': row.get('failure'), 'verification_rounds': row.get('verification_rounds'),
                'progress_rounds': len(progress.get('rounds', [])),
                'feedback_dispatches': feedback_dispatches(directory),
                'trial_sha256': file_hash(directory/'trial.json')})
            atomic_json(output/'comparison.json', report)
        a, b = report['records']
        report['status'] = 'completed'
        report['outcome'] = ('both_failed_no_efficacy_winner' if not a['official_resolved'] and not b['official_resolved']
            else 'both_passed_compare_cost_descriptively' if a['official_resolved'] and b['official_resolved']
            else 'one_arm_passed_development_observation_only')
        report['treatment_exposure'] = ('feedback_dispatched' if b['feedback_dispatches'] else
                                       'no_confirmed_feedback_exposure_do_not_infer_benefit')
    except Exception as error:
        report.update(status='incomplete', error_type=type(error).__name__)
        raise
    finally:
        atomic_json(output/'comparison.json', report)
    return report


def feedback_dispatches(directory):
    path = directory/'run'/'trace.jsonl'
    if not path.exists():
        return None
    return sum(row.get('event') == 'llm_call_started' and row.get('role') == 'critic'
               and row.get('recovery_progress_context') is True
               for row in (json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--execute', action='store_true')
    for key in PATH_KEYS:
        parser.add_argument('--'+key.replace('_', '-'), type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output = args.output.resolve()
    if args.execute:
        if any(getattr(args, key) is not None for key in PATH_KEYS):
            parser.error('Execution uses frozen inputs; provide only --output and --execute')
        report = execute_pair(root, output)
        print(json.dumps(report, indent=2))
    else:
        if any(getattr(args, key) is None for key in PATH_KEYS if key != 'mcp_config'):
            parser.error('Preparation requires task/reference/model/harness/snapshot/saved-repo paths')
        inputs = {key: str(getattr(args, key).resolve()) if getattr(args, key) else None for key in PATH_KEYS}
        plan = prepare(root, output, inputs)
        print(json.dumps({'status': 'prepared', 'instance_id': plan['instance_id'],
                          'limits_per_arm': LIMITS, 'scope': plan['scope']}))


if __name__ == '__main__':
    main()
