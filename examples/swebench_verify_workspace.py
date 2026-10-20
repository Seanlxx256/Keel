"""Trusted verifier launcher: submit the current base-relative diff to the official harness."""
import argparse
import contextlib
import json
from pathlib import Path
import subprocess
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from examples.swebench_bridge import grade
from keel.evaluation_protocol import file_hash
from keel.swebench import verify_task, workspace_patch
from keel.verification_feedback import failure_feedback


def verify(repo, task_dir, output, harness_python, timeout=600, environment_overlay=None, network_policy=None, plugin_policy=None):
    task = verify_task(task_dir)
    patch = workspace_patch(repo, task)
    output.mkdir(parents=True, exist_ok=False)
    prediction = {'instance_id': task['instance_id'], 'model_name_or_path': 'keel-verification', 'model_patch': patch}
    export = output/'export'
    export.mkdir()
    (export/'predictions.jsonl').write_text(json.dumps(prediction)+'\n', encoding='utf-8')
    receipt = {'instance_id': task['instance_id'], 'runtime_status': 'verification_in_progress',
               'predictions_sha256': file_hash(export/'predictions.jsonl'),
               'task_receipt_sha256': file_hash(task_dir/'task-receipt.json')}
    (export/'export-receipt.json').write_text(json.dumps(receipt), encoding='utf-8')
    if not patch.strip():
        return {'official_resolved': False, 'reason': 'No source patch; inspect issue and modify source', 'empty_patch': True}
    with (output/'launcher.log').open('w', encoding='utf-8') as stream, contextlib.redirect_stdout(stream):
        kwargs = {'environment_overlay': environment_overlay} if environment_overlay is not None else {}
        if network_policy:
            kwargs['network_policy']=network_policy
        if plugin_policy:
            kwargs['plugin_policy']=plugin_policy
        result = grade(task_dir, export, output/'grading', python=harness_python, timeout=timeout, **kwargs)
    feedback = {'official_resolved': result['official_resolved'], 'grading_status': result['status'],
                'error': result.get('error')}
    feedback['failure_kind'] = ('none' if result['official_resolved'] is True else
                                'test_failure' if result['status'] == 'graded' else 'grading_error')
    if 'TimeoutExpired' in str(result.get('error', '')):
        feedback['failure_kind'] = 'grading_timeout'
    feedback['artifact_directory'] = str(output.resolve())
    reports = list((output/'grading/logs').glob('*/'+result['run_id']+'/*/'+task['instance_id']+'/report.json'))
    if len(reports) == 1:
        report = json.loads(reports[0].read_text(encoding='utf-8'))[task['instance_id']]
        observed = ''
        log = reports[0].with_name('test_output.txt')
        if log.is_file():
            text = log.read_text(encoding='utf-8', errors='replace')
            # Exclude setup commands and test-patch application; expose observed test output only.
            if '>>>>> Start Test Output' in text and '>>>>> End Test Output' in text:
                observed = text.split('>>>>> Start Test Output', 1)[1].split('>>>>> End Test Output', 1)[0]
        feedback.update(failure_feedback(report.get('tests_status'), observed))
    (output/'feedback.json').write_text(json.dumps(feedback, indent=2), encoding='utf-8')
    return feedback


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--task', required=True, type=Path)
    parser.add_argument('--output-root', required=True, type=Path)
    parser.add_argument('--harness-python', required=True)
    parser.add_argument('--environment-overlay', type=Path)
    parser.add_argument('--network-policy',choices=['no_pipeline'])
    parser.add_argument('--plugin-policy',choices=['remove_unused_vcs_versioning'])
    args = parser.parse_args()
    try:
        overlay = json.loads(args.environment_overlay.read_text(encoding='utf-8')) if args.environment_overlay else None
        feedback = verify(Path.cwd(), args.task.resolve(), args.output_root.resolve()/uuid.uuid4().hex,
                          args.harness_python, environment_overlay=overlay, network_policy=args.network_policy,plugin_policy=args.plugin_policy)
        print(json.dumps(feedback))
        return 0 if feedback['official_resolved'] is True else (2 if feedback['official_resolved'] is None else 1)
    except Exception as error:
        print(json.dumps({'official_resolved': None, 'grading_status': 'infrastructure_error', 'error': f'{type(error).__name__}: {error}'}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
