"""Zero-model normal imports of actual frozen candidate edit modules."""
from contextlib import closing
import json
from pathlib import Path

from compass.progress import atomic_json
from .candidate_imports import module_manifest
from .core import Budget, Ledger, Limits, Trace
from .diagnostic_probe import run_probe
from .evaluation_protocol import file_hash
from .workspace import Workspace


def check_imports(plan_path, output, *, targets=None):
    plan = json.loads(plan_path.read_text(encoding='utf-8'))
    identity = file_hash(plan_path)
    if identity != plan_path.with_suffix('.sha256').read_text().strip():
        raise ValueError('Frozen source plan changed')
    targets = targets if targets is not None else plan.get('edit_files')
    if (not isinstance(targets,list) or not targets or len(set(targets))!=len(targets)
            or any(name not in plan['source_files'] for name in targets)):
        raise ValueError('Specify unique candidate import paths from the frozen source catalog')
    # Historical implementation hashes are NOT upgraded to new experiment results.
    # Only source inputs are reused; current preflight implementation is recorded.
    for name, origin in plan['source_files'].items():
        expected = plan['frozen_files'].get(origin)
        if not expected or file_hash(Path(origin)) != expected:
            raise ValueError('Frozen candidate source changed: '+name)
    output.mkdir(parents=True, exist_ok=False)
    record = {'status':'running', 'model_calls':0, 'source_plan_sha256':identity,
              'image':plan['probe_image'], 'python':plan['probe_python'],
              'implementation':{name:file_hash(Path(__file__).with_name(name)) for name in
                                ('probe_preflight.py','candidate_imports.py','diagnostic_probe.py')},
              'scope':'Normal imports only; no model, task fix, function probe or acceptance. Current implementation against historical frozen source.'}
    atomic_json(output/'report.json',record)
    try:
        root=output/'workspace';root.mkdir()
        for name, origin in plan['source_files'].items():
            target=(root/name).resolve()
            if not target.is_relative_to(root.resolve()):
                raise ValueError('Candidate source path escapes workspace')
            target.parent.mkdir(parents=True,exist_ok=True)
            target.write_bytes(Path(origin).read_bytes())
        manifest=module_manifest(root,targets)
        if not manifest or len(manifest)!=len(targets):
            raise ValueError('Every candidate edit file must identify a Python import module')
        record['target_modules']=manifest
        # All names come from validated paths, never from a task-specific probe.
        code=('import importlib,json\n'
              'for name in '+repr(list(manifest))+':\n'
              '    try:\n'
              '        module=importlib.import_module(name)\n'
              '        print(json.dumps({"module":name,"file":module.__file__,"package":module.__package__}))\n'
              '    except BaseException:\n'
              '        import sys\n'
              '        parents=[]\n'
              '        for count in range(1,len(name.split("."))):\n'
              '            parent_name=".".join(name.split(".")[:count])\n'
              '            parent=sys.modules.get(parent_name)\n'
              '            parents.append({"module":parent_name,"file":getattr(parent,"__file__",None),'
              '"origin":getattr(getattr(parent,"__spec__",None),"origin",None),'
              '"paths":[str(p) for p in getattr(parent,"__path__",[])]})\n'
              '        print(json.dumps({"import_error":name,"parents":parents,"sys_path":sys.path}))\n'
              '        raise\n')
        record['check_code']=code
        budget=Budget(Limits(max_tool_calls=1,max_wallclock=30))
        with closing(Ledger(output/'ledger.sqlite')) as ledger:
            workspace=Workspace(root,budget,ledger,Trace(output/'trace.jsonl'))
            before=workspace.snapshot()
            result=run_probe(workspace,{'backend':'docker','image':plan['probe_image']},
                             plan['probe_python'],code,candidate_imports=True)
            record.update(result=result,budget=budget.report(),workspace_unchanged=workspace.snapshot()==before)
        if result['outcome']=='completed':
            child=result['probe']
            imports=[json.loads(line) for line in child['stdout'].splitlines() if line.strip().startswith('{')]
            markers=[line.split('__KEEL_CANDIDATE_IMPORTS__',1)[1] for line in child['stderr'].splitlines()
                     if line.startswith('__KEEL_CANDIDATE_IMPORTS__')]
            loaded=json.loads(markers[-1]) if markers else []
            by_name={r['module']:r for r in loaded if r.get('status')=='executed'}
            observed={r['module']:r for r in imports}
            valid=all(name in observed and name in by_name and by_name[name]['sha256']==row['sha256']
                      and observed[name]['file']=='/workspace/'+row['path'].replace('\\','/')
                      for name,row in manifest.items())
            record.update(imported_modules=imports,loaded_candidates=loaded,
                          status='passed' if valid and record['workspace_unchanged'] else 'provenance_failed')
        else:
            record['status']={'script_failed':'import_failed','script_timeout':'timeout',
                              'executor_timeout':'timeout','executor_failed':'execution_unavailable'}[result['outcome']]
    except Exception as error:
        record.update(status='check_error',error_type=type(error).__name__,reason=str(error)[:1500])
    finally:
        atomic_json(output/'report.json',record)
    return record
