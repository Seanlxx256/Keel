"""Zero-model paired regression checks through the existing isolated probe runner."""
from contextlib import closing
import ast
import difflib
import json
from pathlib import Path
import re

from compass.progress import atomic_json
from .core import Budget, Ledger, Limits, Trace
from .diagnostic_probe import run_probe
from .evaluation_protocol import file_hash
from .workspace import Workspace


def rollback_blocks(baseline, candidate):
    """Revert one logical-line edit at a time, preserving candidate line endings.

    These are independent contrasts, not ddmin or proof of minimal causality.
    Return syntax-invalid partial variants too, explicitly labeled.
    """
    from .proposals import source_newline_edit
    a,b=baseline.splitlines(keepends=True),candidate.splitlines(keepends=True)
    rows=[]
    for tag,a1,a2,b1,b2 in difflib.SequenceMatcher(
            None,baseline.splitlines(),candidate.splitlines(),autojunk=False).get_opcodes():
        if tag=='equal':
            continue
        _,replacement=source_newline_edit(candidate,'',''.join(a[a1:a2]))
        value=''.join(b[:b1])+replacement+''.join(b[b2:])
        try:
            ast.parse(value);syntax='valid'
        except SyntaxError as error:
            syntax='invalid: '+str(error)
        rows.append({'baseline_lines':[a1+1,a2],'candidate_lines':[b1+1,b2],
                     'source':value,'syntax':syntax})
    return rows


def comparison_code(module, selector):
    if not re.fullmatch(r'[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+', module):
        raise ValueError('Expected a qualified test module')
    if not re.fullmatch(r'[A-Za-z_]\w*(?:::[A-Za-z_]\w*)*', selector):
        raise ValueError('Expected an exact test class/function selector')
    return (
        'import importlib,hashlib,json,os,tempfile\nfrom pathlib import Path\n'
        '# Set storage before pytest plugins or test modules import Hypothesis.\n'
        'os.environ["HYPOTHESIS_STORAGE_DIRECTORY"]=tempfile.mkdtemp(prefix="keel-hypothesis-",dir="/tmp")\n'
        'import pytest\n'
        f'm=importlib.import_module({module!r})\np=Path(m.__file__).resolve()\n'
        f'os.chdir(p.parents[{len(module.split("."))-1}])\n'
        'class Record:\n'
        '    def __init__(self): self.rows=[]\n'
        '    def pytest_runtest_logreport(self,report):\n'
        '        self.rows.append({"nodeid":report.nodeid,"when":report.when,"outcome":report.outcome,'
        '"error":str(report.longrepr)[:1800] if report.failed else ""})\n'
        'rec=Record()\n'
        f'rc=pytest.main([str(p)+"::"+{selector!r},"-q","--override-ini=addopts=",'
        '"-p","no:cacheprovider"],plugins=[rec])\n'
        'print("__KEEL_REGRESSION__"+json.dumps({"exitcode":int(rc),"test_file_sha256":'
        'hashlib.sha256(p.read_bytes()).hexdigest(),"reports":rec.rows,'
        '"hypothesis_storage":os.environ["HYPOTHESIS_STORAGE_DIRECTORY"]}))\n'
    )


def classify(result):
    if result.get('outcome') != 'completed':
        return {'status':'unavailable'}
    markers=[line[len('__KEEL_REGRESSION__'):] for line in result['probe']['stdout'].splitlines()
             if line.startswith('__KEEL_REGRESSION__')]
    if len(markers)!=1:
        return {'status':'unavailable','reason':'Missing structured single-test result'}
    value=json.loads(markers[0]); rows=value.get('reports',[])
    calls=[r for r in rows if r.get('when')=='call']
    if len({r.get('nodeid') for r in rows})!=1 or len(calls)!=1:
        return {'status':'unavailable','result':value,'reason':'Target did not execute exactly once'}
    state=('passed' if value['exitcode']==0 and all(r['outcome']=='passed' for r in rows)
           else 'failed' if value['exitcode']==1 and calls[0]['outcome']=='failed'
           else 'unavailable')
    return {'status':state,'result':value}


def compare_sources(plan_path, output, *, resume_from=None):
    plan=json.loads(plan_path.read_text(encoding='utf-8'))
    identity=file_hash(plan_path)
    if plan_path.with_suffix('.sha256').read_text().strip()!=identity:
        raise ValueError('Comparison plan changed')
    from .diagnostic_execution import validate_probe_config
    validate_probe_config({'execution':plan['execution'],'python':plan['python'],'max_model_calls':1})
    code=comparison_code(plan['test_module'],plan['test_selector'])
    variants=plan['variants']
    rollback=plan.get('mode')=='block_rollback'
    reference=None
    if rollback:
        if not 1 <= len(variants) <= 8 or len({v['label'] for v in variants})!=len(variants):
            raise ValueError('Rollback requires 1..8 uniquely labeled variants')
        for name in ('control_plan','control_report'):
            if file_hash(Path(plan[name]))!=plan['frozen_files'][plan[name]]:
                raise ValueError('Rollback control evidence changed')
        control=json.loads(Path(plan['control_plan']).read_text(encoding='utf-8'))
        reference=json.loads(Path(plan['control_report']).read_text(encoding='utf-8'))
        if (reference.get('status')!='compared' or reference.get('same_test_source') is not True
                or reference.get('plan_sha256')!=file_hash(Path(plan['control_plan']))
                or reference.get('outcomes')!={'baseline':'passed','candidate':'failed'}
                or any(plan[k]!=control[k] for k in ('execution','python','test_module','test_selector'))):
            raise ValueError('Rollback requires compatible completed baseline-pass/candidate-fail control')
    elif len(variants)!=2 or [v['label'] for v in variants]!=['baseline','candidate']:
        raise ValueError('Expected frozen baseline/candidate pair')
    for variant in variants:
        if not re.fullmatch(r'[A-Za-z0-9_-]+',variant['label']):
            raise ValueError('Invalid comparison variant label')
        for name,origin in variant['source_files'].items():
            p=Path(name)
            if p.is_absolute() or p.drive or '..' in p.parts or not name.endswith('.py'):
                raise ValueError('Invalid candidate source path')
            if file_hash(Path(origin))!=plan['frozen_files'][origin]:
                raise ValueError('Frozen comparison source changed')
    reused={}
    prior=None
    if resume_from is not None:
        prior=json.loads(resume_from.read_text(encoding='utf-8'))
        if prior.get('plan_sha256')!=identity:
            raise ValueError('Resume comparison plan differs')
        if set(prior.get('implementation',{}))!={'source_comparison.py','diagnostic_probe.py','candidate_imports.py','execution.py'}:
            raise ValueError('Resume implementation inventory missing or unknown')
        for name,old_hash in prior.get('implementation',{}).items():
            if name!='source_comparison.py' and file_hash(Path(__file__).with_name(name))!=old_hash:
                raise ValueError('Resume executor implementation differs: '+name)
        by_label={v['label']:v for v in variants}
        for row in prior.get('records',[]):
            if row.get('label') not in by_label or row.get('status') not in {'passed','failed'}:
                continue
            variant=by_label[row['label']]; execution=row.get('execution',{})
            if classify(execution).get('status')!=row['status']:
                raise ValueError('Resume test result differs from raw execution')
            expected={name:plan['frozen_files'][origin] for name,origin in variant['source_files'].items()}
            manifest=execution.get('candidate_manifest',{})
            if {v.get('path'):v.get('sha256') for v in manifest.values()}!=expected:
                raise ValueError('Resume candidate source differs')
            loaded={m['module']:m for line in execution.get('probe',{}).get('stderr','').splitlines()
                    if line.startswith('__KEEL_CANDIDATE_IMPORTS__')
                    for m in json.loads(line[len('__KEEL_CANDIDATE_IMPORTS__'):]) if m.get('status')=='executed'}
            if any(name not in loaded or loaded[name].get('sha256')!=item['sha256'] for name,item in manifest.items()):
                raise ValueError('Resume execution provenance differs')
            raw=classify(execution)['result']
            if row.get('result')!=raw or (reference and raw['test_file_sha256']!=reference['records'][0]['result']['test_file_sha256']):
                raise ValueError('Resume test source/result differs')
            reused[row['label']]={**row,'reused':True,'reuse_report_sha256':file_hash(resume_from)}
    output.mkdir(parents=True,exist_ok=False)
    report={'status':'running','model_calls':0,'plan_sha256':identity,'records':[],
            'implementation':{name:file_hash(Path(__file__).with_name(name)) for name in
                              ('source_comparison.py','diagnostic_probe.py','candidate_imports.py','execution.py')},
            'runtime_adaptation':'Hypothesis storage in isolated /tmp before pytest import; same policy for both variants, warnings unchanged.',
            'scope':'Paired diagnostic test, same immutable image and installed test source. '
                    'Not official harness score, task repair, or a root-cause proof.'}
    atomic_json(output/'report.json',report)
    if resume_from is not None:
        report['resume']={'report_sha256':file_hash(resume_from),'path':str(resume_from),
                         'prior_budget':prior.get('budget'),
                         'previous_implementation':prior.get('implementation'),
                         'migration':'Comparison orchestration adds validated resume; executor modules unchanged. Reused observations are historical.'}
    if reference is not None:
        report['reused_control']={'report_sha256':file_hash(Path(plan['control_report'])),
            'plan_sha256':reference['plan_sha256'],'outcomes':reference['outcomes'],
            'scope':'Historical control retained, not rerun. Runtime migration is explicit in this plan.'}
    budget=Budget(Limits(max_wallclock=120 if rollback else 60,max_tool_calls=len(variants)))
    try:
        for variant in variants:
            if variant['label'] in reused:
                report['records'].append(reused[variant['label']])
                atomic_json(output/'report.json',report)
                continue
            directory=output/variant['label'];workspace_root=directory/'workspace';workspace_root.mkdir(parents=True)
            for name,origin in variant['source_files'].items():
                target=workspace_root/name;target.parent.mkdir(parents=True,exist_ok=True)
                target.write_bytes(Path(origin).read_bytes())
            try:
                for name in variant['source_files']:
                    ast.parse((workspace_root/name).read_bytes(),filename=name)
            except SyntaxError as error:
                if not rollback:
                    raise
                report['records'].append({'label':variant['label'],'status':'invalid_syntax',
                                          'reason':str(error),'scope':'Partial rollback invalid, not a test failure'})
                atomic_json(output/'report.json',report)
                continue
            with closing(Ledger(directory/'ledger.sqlite')) as ledger:
                ws=Workspace(workspace_root,budget,ledger,Trace(directory/'trace.jsonl'))
                result=run_probe(ws,plan['execution'],plan['python'],code,candidate_imports=True)
            row={'label':variant['label'],'execution':result,**classify(result)}
            markers=[line[len('__KEEL_CANDIDATE_IMPORTS__'):] for line in result.get('probe',{}).get('stderr','').splitlines()
                     if line.startswith('__KEEL_CANDIDATE_IMPORTS__')]
            loaded={m['module']:m for line in markers for m in json.loads(line) if m.get('status')=='executed'}
            manifest=result.get('candidate_manifest',{})
            if not manifest or any(name not in loaded or loaded[name].get('sha256')!=item['sha256']
                                   for name,item in manifest.items()):
                row.update(status='unavailable',reason='Candidate module execution provenance not established')
            report['records'].append(row);atomic_json(output/'report.json',report)
            if reference is not None and row.get('result',{}).get('test_file_sha256')!=reference['records'][0]['result']['test_file_sha256']:
                row.update(status='unavailable',reason='Rollback test source differs from control')
            if row['status']=='unavailable':
                report['status']='incomplete';break
        if rollback and len(report['records'])==len(variants) and all(r['status'] in {'passed','failed','invalid_syntax'} for r in report['records']):
            report.update(status='compared',outcomes={r['label']:r['status'] for r in report['records']},
                          scope='Single-block rollback diagnostics; syntax-invalid variants excluded. '
                                'Pass identifies a test-specific contrast, not a complete repair or interaction-free cause.')
        elif not rollback and len(report['records'])==2 and all(r['status'] in {'passed','failed'} for r in report['records']):
            a,b=report['records']
            same_tests=a['result']['test_file_sha256']==b['result']['test_file_sha256']
            report.update(status='compared' if same_tests else 'incomparable',
                          same_test_source=same_tests,
                          outcomes={r['label']:r['status'] for r in report['records']})
    except Exception as error:
        report.update(status='incomplete',error_type=type(error).__name__,reason=str(error)[:1000])
    finally:
        report['budget']=budget.report();atomic_json(output/'report.json',report)
    return report
