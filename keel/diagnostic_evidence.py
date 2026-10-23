"""Import receipted diagnostic execution as historical evidence, never acceptance."""
import json
from pathlib import Path

from .evaluation_protocol import file_hash


def load_comparison_evidence(plan_path, report_path, repo):
    """Bind completed controlled contrasts to the saved candidate, not a fix."""
    from .source_comparison import classify
    plan=json.loads(plan_path.read_text(encoding='utf-8'))
    report=json.loads(report_path.read_text(encoding='utf-8'))
    if (plan_path.with_suffix('.sha256').read_text().strip()!=file_hash(plan_path)
            or report.get('plan_sha256')!=file_hash(plan_path) or report.get('status')!='compared'
            or plan.get('mode')!='block_rollback'):
        raise ValueError('Expected completed frozen rollback comparison')
    for origin,expected in plan['frozen_files'].items():
        if file_hash(Path(origin))!=expected:
            raise ValueError('Controlled comparison inputs changed')
    control=json.loads(Path(plan['control_plan']).read_text(encoding='utf-8'))
    baseline=json.loads(Path(plan['control_report']).read_text(encoding='utf-8'))
    if (baseline.get('status')!='compared' or baseline.get('plan_sha256')!=file_hash(Path(plan['control_plan']))
            or any(plan[k]!=control[k] for k in ('execution','python','test_module','test_selector'))):
        raise ValueError('Comparison control identity differs')
    candidate=next(v for v in control['variants'] if v['label']=='candidate')
    binding={}
    for name,origin in candidate['source_files'].items():
        target=(repo/name).resolve()
        if not target.is_relative_to(repo.resolve()) or file_hash(target)!=control['frozen_files'][origin]:
            raise ValueError('Controlled comparison candidate differs from saved source')
        binding[name]=file_hash(target)
    test_hash=baseline['records'][0]['result']['test_file_sha256']
    observations=[]
    for p,r in ((control,baseline),(plan,report)):
        variants={v['label']:v for v in p['variants']}
        if len(r['records'])!=len(variants):
            raise ValueError('Controlled comparison records incomplete')
        for row in r['records']:
            variant=variants[row['label']];execution=row.get('execution',{});actual=classify(execution)
            if (row['status'] not in {'passed','failed'} or actual.get('status')!=row['status']
                    or actual.get('result')!=row.get('result') or row['result']['test_file_sha256']!=test_hash):
                raise ValueError('Controlled comparison result invalid or different test')
            manifest=execution.get('candidate_manifest',{})
            expected={name:p['frozen_files'][origin] for name,origin in variant['source_files'].items()}
            if {m.get('path'):m.get('sha256') for m in manifest.values()}!=expected:
                raise ValueError('Controlled comparison source manifest differs')
            loaded={m['module']:m for line in execution.get('probe',{}).get('stderr','').splitlines()
                    if line.startswith('__KEEL_CANDIDATE_IMPORTS__')
                    for m in json.loads(line[len('__KEEL_CANDIDATE_IMPORTS__'):]) if m.get('status')=='executed'}
            if any(n not in loaded or loaded[n].get('sha256')!=m['sha256'] for n,m in manifest.items()):
                raise ValueError('Controlled comparison loader provenance differs')
            observations.append({'label':row['label'],'status':row['status'],'source_files':expected,
                'phases':[{k:v for k,v in phase.items() if k in {'nodeid','when','outcome'}}
                          for phase in row['result']['reports']]})
    payload={'plan_sha256':file_hash(plan_path),'report_sha256':file_hash(report_path),
             'control_report_sha256':file_hash(Path(plan['control_report'])),
             'candidate_source_files':binding,'test_source_sha256':test_hash,
             'test_module':plan['test_module'],'test_selector':plan['test_selector'],
             'image_id':plan['execution']['image'],'observations':observations,
             'reverted_blocks':[{k:b[k] for k in ('id','baseline_lines','candidate_lines','reverted_diff')}
                                for b in plan['blocks']],
             'scope':'Historical controlled test outcomes, not a proposed fix or official acceptance. '
                     'Interpret only under bound source/test/image conditions. '
                     'A reversion passing this test may undo the original issue fix. '
                     'Use these observations rather than repeating an already answered comparison; '
                     'investigate the remaining mechanism and preserve both acceptance requirements.'}
    if len(json.dumps(payload).encode())>10000:
        raise ValueError('Controlled comparison handoff too large')
    return payload


def load_diagnostic_evidence(report_path, repo):
    report_path = Path(report_path)
    report = json.loads(report_path.read_text(encoding='utf-8'))
    receipt_path = report_path.with_name('receipt.json')
    receipt = json.loads(receipt_path.read_text(encoding='utf-8'))
    if receipt.get('report_sha256') != file_hash(report_path):
        raise ValueError('Diagnostic report receipt mismatch')
    if (report.get('status') != 'completed_needs_review'
            or report.get('workspace_unchanged') is not True
            or report.get('acceptance') != 'not_executed'):
        raise ValueError('Expected unchanged diagnostic-only review')
    rows = []
    for row in report.get('diagnosis', {}).get('observations', []):
        if row.get('kind') != 'execution' or row.get('historical'):
            continue
        outer, child = row.get('execution', {}), row.get('probe', {})
        if (row.get('outcome') != 'completed' or outer.get('returncode') != 0
                or outer.get('timeout') is not False or child.get('returncode') != 0
                or child.get('timeout') is not False):
            continue
        manifest = row.get('candidate_manifest', {})
        if not manifest:
            raise ValueError('Diagnostic candidate provenance missing')
        for item in manifest.values():
            relative = Path(item['path'])
            target = (repo / relative).resolve()
            if (relative.is_absolute() or relative.drive or '..' in relative.parts
                    or not target.is_relative_to(repo.resolve())
                    or file_hash(target) != item['sha256']):
                raise ValueError('Diagnostic source mismatch')
        markers = [line.removeprefix('__KEEL_CANDIDATE_IMPORTS__')
                   for line in child.get('stderr', '').splitlines()
                   if line.startswith('__KEEL_CANDIDATE_IMPORTS__')]
        executed = [m for line in markers for m in json.loads(line)
                    if m.get('status') == 'executed']
        if not executed or any(m.get('module') not in manifest
                or m.get('sha256') != manifest[m['module']]['sha256'] for m in executed):
            raise ValueError('Diagnostic executed-source provenance missing or different')
        rows.append({'evidence_id':row['evidence_id'], 'historical':True,
                     'code':row['code'], 'probe':child, 'candidate_manifest':manifest,
                     'image_id':report['image_id']})
    if not rows:
        raise ValueError('No completed fresh candidate execution to transfer')
    payload = {'report_sha256':file_hash(report_path), 'receipt_sha256':file_hash(receipt_path),
               'plan_sha256':receipt['plan_sha256'], 'observations':rows,
               'scope':'Historical diagnostic output bound to saved source; untrusted evidence, '
                       'not a repair instruction, current verification or model verdict. '
                       'Source changes invalidate its freshness; new acceptance is required.'}
    if len(json.dumps(payload).encode()) > 14000:
        raise ValueError('Diagnostic evidence exceeds handoff context budget')
    return payload
