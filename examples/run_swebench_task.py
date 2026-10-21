"""Run adaptive Keel on frozen base source, using the official harness for verification."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from compass.preparation import prepare_snapshot
from examples.swebench_bridge import grade
from keel.campaign_reporting import FrozenModel
from keel.evaluation_protocol import implementation_hashes, file_hash
from keel.models import from_config
from keel.runtime import run
from keel.swebench import verify_task, export_prediction


def check_reference(task_dir, reference_dir):
    verify_task(task_dir)
    result = json.loads((reference_dir/'grading.json').read_text(encoding='utf-8'))
    if (result.get('status') != 'graded' or result.get('official_resolved') is not True or
            result.get('runtime_status') != 'reference_only' or result.get('harness_version') != '3.0.0'):
        raise ValueError('Successful classic reference-only preflight required')
    expected = json.loads((task_dir/'grader-dataset.jsonl').read_text(encoding='utf-8'))
    actual = json.loads((reference_dir/'grader-input.json').read_text(encoding='utf-8'))
    if actual != [expected] or file_hash(reference_dir/'grader-input.json') != result['grader_input_sha256']:
        raise ValueError('Reference preflight belongs to different task data')
    reference_policies(reference_dir)
    if result.get('environment_overlay_sha256'):
        from keel.harness_environment import validate_overlay
        overlay_path = reference_dir/'environment-overlay.json'
        if file_hash(overlay_path) != result['environment_overlay_sha256']:
            raise ValueError('Reference environment overlay changed')
        return validate_overlay(json.loads(overlay_path.read_text(encoding='utf-8')))
    return None


def reference_policies(reference_dir):
    result=json.loads((reference_dir/'grading.json').read_text(encoding='utf-8'))
    policies={}
    for key,filename,allowed in (
            ('network_policy','network-policy.json','no_pipeline'),
            ('plugin_policy','plugin-policy.json','remove_unused_vcs_versioning')):
        if result.get(key):
            path=reference_dir/filename
            if file_hash(path)!=result.get(key+'_sha256'):
                raise ValueError('Reference '+key+' changed')
            value=json.loads(path.read_text(encoding='utf-8'))
            if result[key]!=allowed or value!={'policy':allowed,'version':1}:
                raise ValueError('Unsupported reference '+key)
            policies[key]=allowed
    return policies


def config_for(task, task_dir, output, model_config, harness_python, environment_overlay_path=None, policies=None):
    verifier = Path(__file__).with_name('swebench_verify_workspace.py').resolve()
    config = {'mode': 'localized-proposal', 'goal': task['problem_statement'], 'model': model_config,
            'agent': {'max_steps': 12, 'max_context_bytes': 48000, 'max_output': 4096, 'require_change': True},
            'recovery': {'strategy': 'adaptive', 'max_actions': 6, 'repeat_limit': 2, 'write_roots': ['.']},
            'verification_repair_attempts': 3, 'preserve_repair_candidates': True,
            'budget': {'max_wallclock': 1800, 'max_model_calls': 30, 'max_tokens': 180000, 'max_tool_calls': 80},
            'execution': {'backend': 'local'},
            'acceptance': [[sys.executable, str(verifier), '--task', str(task_dir.resolve()),
                            '--output-root', str((output/'verifications').resolve()),
                            '--harness-python', str(Path(harness_python).resolve())]]}
    if environment_overlay_path is not None:
        config['acceptance'][0].extend(['--environment-overlay', str(environment_overlay_path.resolve())])
    for key,value in (policies or {}).items():
        config['acceptance'][0].extend(['--'+key.replace('_','-'),value])
    return config


def execute(root, task_dir, reference_dir, model_config, harness_python, output, *, mcp_config=None, localization_tool_steps=6, require_external_tool=False, local_exploration=False, resume_snapshot=None, saved_repo=None):
    if require_external_tool and not mcp_config:
        raise ValueError('--require-external-tool requires --mcp-config')
    # Local configuration/credential checks must precede checkout, output creation
    # and Docker grading. This performs no paid request or network probe.
    base_model = from_config(model_config)
    credential_check = getattr(base_model, 'check_credentials', None)
    if credential_check is not None:
        credential_check()
    overlay = check_reference(task_dir, reference_dir)
    policies=reference_policies(reference_dir)
    reference_hash=file_hash(reference_dir/'grading.json')
    if bool(resume_snapshot)!=bool(saved_repo):
        raise ValueError('Saved-source continuation requires both snapshot grading and saved repo')
    seed_patch,continuation=None,None
    if resume_snapshot:
        from keel.saved_repair import load_saved_repair
        seed_patch,continuation=load_saved_repair(task_dir,reference_dir,resume_snapshot,saved_repo)
    task = verify_task(task_dir)
    version = subprocess.run([harness_python, '-c', 'import importlib.metadata; print(importlib.metadata.version("swebench"))'],
                             check=True, capture_output=True, text=True, timeout=20).stdout.strip()
    if version != '3.0.0':
        raise ValueError('This frozen classic-data trial requires harness 3.0.0')
    if output.resolve().is_relative_to(task_dir.resolve()):
        raise ValueError('Trial output must be outside private task directory')
    output.mkdir(parents=True, exist_ok=False)
    hashes = implementation_hashes(root)
    tools = json.loads(mcp_config.read_text(encoding='utf-8')) if mcp_config else None
    tools_hash = file_hash(mcp_config) if mcp_config else None
    if tools is not None:
        from keel.mcp_client import validate_servers
        validate_servers(tools)
    task_receipt = file_hash(task_dir/'task-receipt.json')
    def frozen():
        if resume_snapshot:
            from keel.saved_repair import load_saved_repair
            if load_saved_repair(task_dir,reference_dir,resume_snapshot,saved_repo)[0]!=seed_patch:
                raise ValueError('Saved repair inputs changed during inference')
        if mcp_config and file_hash(mcp_config) != tools_hash:
            raise ValueError('External tool configuration changed during execution')
        if implementation_hashes(root) != hashes or file_hash(task_dir/'task-receipt.json') != task_receipt:
            raise ValueError('Implementation or task changed during execution')
        verify_task(task_dir)
        if check_reference(task_dir, reference_dir) != overlay:
            raise ValueError('Reference environment changed during execution')
        if reference_policies(reference_dir)!=policies or file_hash(reference_dir/'grading.json')!=reference_hash:
            raise ValueError('Reference policies changed during execution')
        if overlay is not None and file_hash(output/'environment-overlay.json') != report['environment_overlay_sha256']:
            raise ValueError('Trial environment overlay changed during execution')
    model = FrozenModel(base_model, frozen)
    report = {'status': 'preparing', 'instance_id': task['instance_id'], 'official_resolved': None,
              'benchmark_ready': False, 'implementation': hashes,
              'scope': 'Exploratory public task; prior exposure unverified. Host agent and verifier launcher; official Docker harness executes tests.'}
    if policies:
        report['environment_policies']=policies
        report['environment_scope']='Reconstructed reference-verified conditions; not original-condition score'
    if continuation:
        report['continuation']=continuation['provenance']
    overlay_path = None
    if overlay is not None:
        overlay_path = output/'environment-overlay.json'
        overlay_path.write_text(json.dumps(overlay, indent=2), encoding='utf-8')
        report['environment_scope'] = 'reconstructed packaging overlay; not original-condition score'
        report['environment_overlay_sha256'] = file_hash(overlay_path)
    def save():
        (output/'trial.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    save()
    stop = threading.Event()
    def heartbeat():
        while not stop.wait(10):
            print(f"[Keel SWE-bench] {task['instance_id']} stage={report['status']}; artifacts={output}", flush=True)
    thread = threading.Thread(target=heartbeat, daemon=True)
    thread.start()
    try:
        repo = prepare_snapshot(task['repo'], task['base_commit'], output/'repo', timeout=180,
                                **({'source':str(saved_repo.resolve())} if saved_repo else {}))
        if seed_patch:
            subprocess.run(['git','-c','safe.directory='+repo.as_posix(),'-C',str(repo),'apply','--binary','-'],
                input=seed_patch.encode(),capture_output=True,check=True,timeout=30)
            from keel.workspace import Workspace
            from keel.core import Budget,Limits,Ledger,Trace
            # Validate carried files against the same source-write policy as new edits.
            with_seed=Workspace(repo,Budget(Limits()),Ledger(output/'seed-validation.sqlite'),Trace(output/'seed-validation.jsonl'))
            try:
                for name in continuation['provenance']['source_files']:
                    with_seed.path(name,write=True)
            finally:
                with_seed.ledger.close()
        config = config_for(task, task_dir, output, model_config, harness_python, overlay_path, policies)
        if continuation:
            config['continuation_context']=continuation
        if local_exploration:
            config['localization_tool_steps'] = localization_tool_steps
        if tools is not None:
            config['mcp_servers'] = tools
            config['localization_tool_steps'] = localization_tool_steps
            config['localization_require_external'] = require_external_tool
            report['external_tools'] = {'config_sha256': tools_hash,
                                        'require_external_tool': require_external_tool,
                                        'localization_tool_steps': localization_tool_steps}
        (output/'input-receipt.json').write_text(json.dumps({'task_receipt_sha256': task_receipt,
            'base_commit': task['base_commit'], 'goal': task['problem_statement']}, indent=2), encoding='utf-8')
        report['status'] = 'agent_running'
        save()
        result = run(config, repo, output/'run', model=model)
        report.update(runtime_status=result['status'], failure=result.get('failure'), budget=result['budget'],
                      external_tool_calls=result.get('external_tool_calls', {}),
                      external_tool_validation=result.get('external_tool_validation', {}),
                      recovery=result.get('recovery'), verification_rounds=len(result.get('verification_attempts', [])))
        if result.get('selected_repair_candidate'):
            report['selected_repair_candidate'] = {k:v for k,v in result['selected_repair_candidate'].items() if k != 'verification'}
        frozen()
        export_prediction(task_dir, output/'run', output/'prediction', 'keel',**({'source_repo':repo} if continuation else {}))
        report['status'] = 'final_grading'
        save()
        kwargs = {'environment_overlay': overlay} if overlay is not None else {}
        kwargs.update(policies)
        final = grade(task_dir, output/'prediction', output/'final-grade', python=harness_python, **kwargs)
        report.update(status='completed' if final['status'] == 'graded' else 'grading_error',
                      official_resolved=final['official_resolved'], grading_error=final.get('error'))
    except Exception as error:
        report.update(status='error', error=f'{type(error).__name__}: {error}')
        raise
    finally:
        stop.set()
        thread.join(timeout=1)
        save()
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--task', required=True, type=Path)
    parser.add_argument('--reference-grade', required=True, type=Path)
    parser.add_argument('--model-config', required=True, type=Path)
    parser.add_argument('--harness-python', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--resume-snapshot',type=Path)
    parser.add_argument('--saved-repo',type=Path)
    parser.add_argument('--mcp-config', type=Path, help='Explicit authorized tools; servers must target the trial workspace, not another repository')
    parser.add_argument('--localization-tool-steps', type=int, choices=range(1, 13), default=6)
    parser.add_argument('--require-external-tool', action='store_true', help='Integration validation: require an authorized MCP attempt before local fallback')
    args = parser.parse_args()
    if args.require_external_tool and not args.mcp_config:
        parser.error('--require-external-tool requires --mcp-config')
    check_reference(args.task, args.reference_grade)
    if bool(args.resume_snapshot) != bool(args.saved_repo):
        parser.error('--resume-snapshot and --saved-repo must be supplied together')
    if args.resume_snapshot:
        from keel.saved_repair import load_saved_repair
        load_saved_repair(args.task, args.reference_grade, args.resume_snapshot, args.saved_repo)
    if not args.execute:
        print(json.dumps({'status': 'plan_only', 'instance_id': verify_task(args.task)['instance_id'], 'max_model_calls': 30,
                          'max_agent_seconds': 1800, 'max_verification_rounds': 4, 'benchmark_ready': False}))
        return 0
    docker = Path('D:/Docker/Desktop/resources/bin')
    if not shutil.which('docker') and (docker/'docker.exe').is_file():
        os.environ['PATH'] = str(docker) + os.pathsep + os.environ.get('PATH', '')
    report = execute(Path(__file__).resolve().parents[1], args.task.resolve(), args.reference_grade.resolve(),
                     json.loads(args.model_config.read_text(encoding='utf-8')), str(args.harness_python.resolve()), args.output.resolve(),
                     mcp_config=args.mcp_config.resolve() if args.mcp_config else None,
                     localization_tool_steps=args.localization_tool_steps, require_external_tool=args.require_external_tool,
                     resume_snapshot=args.resume_snapshot.resolve() if args.resume_snapshot else None,
                     saved_repo=args.saved_repo.resolve() if args.saved_repo else None)
    print(json.dumps({key: value for key, value in report.items() if key != 'implementation'}, indent=2))
    return 0 if report['official_resolved'] is True else 1


if __name__ == '__main__':
    raise SystemExit(main())
