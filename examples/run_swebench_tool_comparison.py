"""Freeze new tasks and compare local exploration with optional or required MCP exploration."""
import argparse
import json
import os
from pathlib import Path
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from examples.run_swebench_batch import prepare as prepare_batch, verify_plan
from examples.run_swebench_task import execute as run_task, check_reference, reference_policies
from examples.swebench_bridge import grade
from keel.core import digest
from keel.evaluation_protocol import file_hash, implementation_hashes
from keel.mcp_client import validate_servers


def tool_files(profile):
    files = {str(profile.resolve()): file_hash(profile)}
    for spec in json.loads(profile.read_text(encoding='utf-8')).values():
        for value in [spec.get('command', ''), *spec.get('args', [])]:
            path = Path(value)
            if path.is_absolute() and path.is_file():
                files[str(path)] = file_hash(path)
    return files


def prepare(root, dataset, model, harness, profile, output, seed=42, tool_policy='required'):
    if tool_policy not in {'required', 'optional'}:
        raise ValueError('Unknown tool policy')
    external_arm = 'mcp_' + tool_policy
    tools = json.loads(profile.read_text(encoding='utf-8'))
    validate_servers(tools)
    policies = [p for spec in tools.values() for p in spec['tools'].values() if 'scout' in p['roles']]
    if not policies or any(p.get('read_only') is not True for p in policies):
        raise ValueError('Comparison requires explicitly read-only authorized Scout MCP tools')
    plan = prepare_batch(root, dataset, model, harness, output, seed, count=3, repositories=3)
    plan['tool_comparison'] = {'profile': str(profile.resolve()), 'files': tool_files(profile),
        'steps': 6, 'policy': tool_policy, 'arms': ['local', external_arm],
        'scope': 'Matched local exploration versus MCP-enabled '+tool_policy+' policy; not a tool-only causal estimate.'}
    for i, row in enumerate(plan['tasks']):
        row['arm_order'] = ['local', external_arm] if i % 2 == 0 else [external_arm, 'local']
    plan['limits']['max_model_calls_batch'] = 30 * len(plan['tasks']) * 2
    plan['plan_sha256'] = digest({k: v for k, v in plan.items() if k != 'plan_sha256'})
    (output/'plan.json').write_text(json.dumps(plan, indent=2), encoding='utf-8')
    return plan


def verify(root, output):
    candidate=json.loads((output/'plan.json').read_text(encoding='utf-8'))
    plan = verify_continuation(root,output,candidate) if candidate.get('kind')=='reconstructed_continuation' else verify_plan(root, output)
    for name, expected in plan['tool_comparison']['files'].items():
        if file_hash(Path(name)) != expected:
            raise ValueError('External tool profile/launcher changed after freeze')
    return plan


def prepare_continuation(root, previous, reference, instance_id, output):
    old=json.loads((previous/'plan.json').read_text(encoding='utf-8'))
    if digest({k:v for k,v in old.items() if k!='plan_sha256'})!=old['plan_sha256']:
        raise ValueError('Original plan identity changed')
    rows=[row for row in old['tasks'] if row['instance_id']==instance_id]
    if len(rows)!=1 or old['tool_comparison'].get('policy')!='optional':
        raise ValueError('Select one task from the existing optional-tool protocol')
    row=rows[0]
    original=previous/row['directory']
    check_reference(original/'task',reference)
    history=json.loads((previous/'comparison.json').read_text(encoding='utf-8'))
    record=next(r for r in history['records'] if r['instance_id']==instance_id)
    if record.get('arms') or record.get('status')!='reference_failed_or_error':
        raise ValueError('Continuation only admits a task whose Agent arms never started')
    for path,expected in old['tool_comparison']['files'].items():
        if file_hash(Path(path))!=expected:
            raise ValueError('Original tool profile/launcher changed')
    if file_hash(Path(old['model_file']))!=old['model_sha256']:
        raise ValueError('Original model settings changed')
    output.mkdir(parents=True,exist_ok=False)
    directory=output/'task-1'; directory.mkdir()
    for name in ('task','reference'):
        shutil.copytree(original/name,directory/name)
    reference_files={str(path.resolve()):file_hash(path) for path in
        [reference/'grading.json',reference/'grader-input.json',
         *[reference/name for name in ('network-policy.json','plugin-policy.json','environment-overlay.json') if (reference/name).exists()]]}
    plan={'kind':'reconstructed_continuation','tasks':[{**row,'directory':'task-1','successful_reference':str(reference.resolve())}],
          'tool_comparison':old['tool_comparison'],'model_file':old['model_file'],'model_sha256':old['model_sha256'],
          'harness_python':old['harness_python'],'implementation':implementation_hashes(root),
          'reference_files':reference_files,'policies':reference_policies(reference),
          'previous_plan_sha256':old['plan_sha256'],'previous_result_sha256':file_hash(previous/'comparison.json'),
          'scope':'Separate reconstructed-environment continuation; original two completed pairs remain unchanged. No first-attempt or heldout claim.',
          'benchmark_ready':False}
    plan['plan_sha256']=digest(plan)
    (output/'plan.json').write_text(json.dumps(plan,indent=2),encoding='utf-8')
    verify(root,output)
    return plan


def verify_continuation(root,output,plan):
    if digest({k:v for k,v in plan.items() if k!='plan_sha256'})!=plan['plan_sha256']:
        raise ValueError('Continuation plan changed')
    if implementation_hashes(root)!=plan['implementation'] or file_hash(Path(plan['model_file']))!=plan['model_sha256']:
        raise ValueError('Continuation implementation/model changed')
    for name,expected in plan['reference_files'].items():
        if file_hash(Path(name))!=expected:
            raise ValueError('Continuation reference evidence changed')
    for row in plan['tasks']:
        directory=output/row['directory']
        if not directory.resolve().is_relative_to(output.resolve()):
            raise ValueError('Continuation task path escapes output')
        check_reference(directory/'task',Path(row['successful_reference']))
        for name,key in [('task/task-receipt.json','receipt_sha256'),('reference/predictions.jsonl','reference_sha256'),
                         ('reference/export-receipt.json','reference_receipt_sha256')]:
            if file_hash(directory/name)!=row[key]:
                raise ValueError('Continuation task/export changed')
    return plan


def summarize(records, external_arm='mcp_required'):
    paired = [r for r in records if all(r.get('arms', {}).get(a, {}).get('status') == 'completed'
                                     for a in ('local', external_arm))]
    counts = {'both_passed': 0, 'local_only': 0, 'mcp_only': 0, 'both_failed': 0}
    for row in paired:
        a, b = [row['arms'][arm].get('official_resolved') is True for arm in ('local', external_arm)]
        counts['both_passed' if a and b else 'local_only' if a else 'mcp_only' if b else 'both_failed'] += 1
    return {'planned_tasks': len(records), 'paired_completed': len(paired), 'outcomes': counts,
        'paired_success_rate': {arm: sum(r['arms'][arm].get('official_resolved') is True for r in paired)/len(paired)
                                if paired else None for arm in ('local', external_arm)},
        'unpaired_tasks': [r['instance_id'] for r in records if r not in paired],
        'limitations': 'Exploratory public tasks, one run per arm; no significance or causal claim. Failures retained; no task replacement.'}


def execute(root, output):
    plan = verify(root, output)
    with (output/'comparison-started.json').open('x', encoding='utf-8') as stream:
        json.dump({'plan_sha256': plan['plan_sha256']}, stream)
    external_arm = 'mcp_' + plan['tool_comparison'].get('policy', 'required')
    report = {'status': 'running', 'plan_sha256': plan['plan_sha256'], 'benchmark_ready': False,
              'scope':plan.get('scope','Matched exploratory tool-policy comparison'),
              'records': [{**row, 'status': 'not_started', 'arms': {}} for row in plan['tasks']]}
    def save():
        report['summary'] = summarize(report['records'], external_arm)
        (output/'comparison.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    save()
    try:
        for row in report['records']:
            verify(root, output)
            directory = output/row['directory']
            print('[Comparison] reference '+row['instance_id'], flush=True)
            try:
                reference_dir=Path(row['successful_reference']) if row.get('successful_reference') else directory/'reference-grade'
                reference = (json.loads((reference_dir/'grading.json').read_text(encoding='utf-8')) if row.get('successful_reference') else
                             grade(directory/'task', directory/'reference', reference_dir,python=plan['harness_python']))
                row['reference_resolved'] = reference.get('official_resolved')
                if reference.get('status') != 'graded' or reference.get('official_resolved') is not True:
                    row['status'] = 'reference_failed_or_error'
                    continue
                check_reference(directory/'task', reference_dir)
                for arm in row['arm_order']:
                    verify(root, output)
                    print(f"[Comparison] {row['instance_id']} arm={arm}", flush=True)
                    try:
                        trial = run_task(root, directory/'task', reference_dir,
                            json.loads(Path(plan['model_file']).read_text(encoding='utf-8')),
                            plan['harness_python'], directory/arm,
                            mcp_config=Path(plan['tool_comparison']['profile']) if arm == external_arm else None,
                            localization_tool_steps=plan['tool_comparison']['steps'],
                            require_external_tool=arm == 'mcp_required', local_exploration=True)
                        row['arms'][arm] = {k: trial.get(k) for k in ('status', 'official_resolved', 'runtime_status',
                            'failure', 'budget', 'verification_rounds', 'external_tool_calls', 'external_tool_validation','environment_policies','environment_scope')}
                    except Exception as error:
                        row['arms'][arm] = {'status': 'error', 'error_type': type(error).__name__}
                    save()
                    verify(root, output)
                row['status'] = 'completed'
            except Exception as error:
                row.update(status='error', error_type=type(error).__name__)
            finally:
                save()
            verify(root, output)
        verify(root, output)
        report['status'] = 'completed'
    except BaseException:
        report['status'] = 'stopped'
        raise
    finally:
        save()
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--dataset', type=Path)
    parser.add_argument('--model-config', type=Path)
    parser.add_argument('--harness-python', type=Path)
    parser.add_argument('--mcp-config', type=Path)
    parser.add_argument('--tool-policy', choices=('required', 'optional'))
    parser.add_argument('--continue-from',type=Path)
    parser.add_argument('--reference-grade',type=Path)
    parser.add_argument('--instance-id')
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    if args.execute:
        if any((args.dataset, args.model_config, args.harness_python, args.mcp_config, args.tool_policy,args.continue_from,args.reference_grade,args.instance_id)) or args.seed != 42:
            parser.error('Execute frozen output only')
        docker = Path('D:/Docker/Desktop/resources/bin')
        if not shutil.which('docker') and (docker/'docker.exe').is_file():
            os.environ['PATH'] = str(docker)+os.pathsep+os.environ.get('PATH', '')
        report = execute(root, args.output.resolve())
        print(json.dumps({'status': report['status'], 'summary': report['summary']}, indent=2))
    elif args.continue_from:
        if not args.reference_grade or not args.instance_id or any((args.dataset,args.model_config,args.harness_python,args.mcp_config,args.tool_policy)):
            parser.error('Continuation requires original run, successful reference grade and instance ID only')
        plan=prepare_continuation(root,args.continue_from.resolve(),args.reference_grade.resolve(),args.instance_id,args.output.resolve())
        print(json.dumps({'status':'prepared_only','tasks':plan['tasks'],'scope':plan['scope']},indent=2))
    else:
        if not all((args.dataset, args.model_config, args.harness_python, args.mcp_config)):
            parser.error('Preparation requires dataset, model config, harness python and MCP config')
        plan = prepare(root, args.dataset.resolve(), args.model_config.resolve(), args.harness_python.resolve(),
                       args.mcp_config.resolve(), args.output.resolve(), args.seed, args.tool_policy or 'required')
        print(json.dumps({'status': 'prepared_only', 'tasks': plan['tasks'], 'limits': plan['limits']}, indent=2))


if __name__ == '__main__':
    main()
