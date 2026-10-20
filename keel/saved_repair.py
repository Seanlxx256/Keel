"""Bind saved source and independently observed failures for a new repair attempt."""
import hashlib
import json
from pathlib import Path
from .evaluation_protocol import file_hash
from .swebench import verify_task, workspace_patch
from .verification_feedback import failure_feedback


def load_saved_repair(task_dir,reference_dir,snapshot_dir,repo):
    task=verify_task(task_dir)
    receipt=json.loads((snapshot_dir/'snapshot-grade.json').read_text(encoding='utf-8'))
    if receipt.get('status')!='graded' or receipt.get('official_resolved') is not False:
        raise ValueError('A failed completed saved-source grading is required')
    if receipt.get('reference_grade_sha256')!=file_hash(reference_dir/'grading.json'):
        raise ValueError('Saved grading reference conditions differ')
    grading=snapshot_dir/'grading'
    grade=json.loads((grading/'grading.json').read_text(encoding='utf-8'))
    if grade.get('runtime_status')!='saved_snapshot_only' or grade.get('official_resolved') is not False:
        raise ValueError('Expected saved-source-only failed grading')
    if json.loads((grading/'grader-input.json').read_text(encoding='utf-8'))!=[json.loads((task_dir/'grader-dataset.jsonl').read_text(encoding='utf-8'))]:
        raise ValueError('Saved grading belongs to a different task')
    if receipt.get('grading') != grade or grade.get('status') != 'graded' or grade.get('infra_failure'):
        raise ValueError('Saved grading receipt differs from completed grading')
    files=receipt.get('source_files',{})
    from .audit import protected_path
    for name in files:
        candidate=Path(name)
        target=(repo/candidate).resolve()
        if (candidate.is_absolute() or candidate.drive or '..' in candidate.parts
                or not target.is_relative_to(repo.resolve()) or protected_path(name)
                or target.suffix != '.py' or any(part.is_symlink() for part in (repo/candidate, *(repo/candidate).parents) if part.is_relative_to(repo.resolve()))):
            raise ValueError('Saved repair contains an invalid source path')
    if not files or any(file_hash(repo/name)!=value for name,value in files.items()):
        raise ValueError('Saved source changed after grading')
    patch=workspace_patch(repo,task)
    if hashlib.sha256(patch.encode()).hexdigest()!=receipt['patch_sha256']:
        raise ValueError('Saved patch differs from graded snapshot')
    reports=list((grading/'logs/run_evaluation').rglob('report.json'))
    if len(reports)!=1 or file_hash(reports[0])!=grade.get('report_sha256'):
        raise ValueError('Saved grading report changed or missing')
    report=json.loads(reports[0].read_text(encoding='utf-8'))[task['instance_id']]
    output=reports[0].with_name('test_output.txt')
    text=output.read_text(encoding='utf-8',errors='replace')
    if '>>>>> Start Test Output' not in text or '>>>>> End Test Output' not in text:
        raise ValueError('No isolated test output boundaries')
    text=text.split('>>>>> Start Test Output',1)[1].split('>>>>> End Test Output',1)[0]
    feedback=failure_feedback(report.get('tests_status'),text)
    if not feedback.get('failed_tests'):
        raise ValueError('No actual test failure evidence for source repair')
    feedback.update(failure_kind='test_failure',official_resolved=False,grading_status='graded')
    provenance={'snapshot_receipt_sha256':file_hash(snapshot_dir/'snapshot-grade.json'),
                'saved_patch_sha256':receipt['patch_sha256'],'source_files':files,
                'audit_scope':'New-attempt edits only; inherited changes do not gain retrospective audit certification',
                'scope':'New attempt seeded from saved source; fresh budgets, not conversation recovery or first-attempt score'}
    context={'verification':[{'returncode':1,'timeout':False,'stdout':json.dumps(feedback),'stderr':''}],
             'changes':{'changes':[{'diff':patch[:6000],'omitted_diff_characters':max(0,len(patch)-6000)}],
                        'scope':'Validated saved base-relative diff; inspect source where omitted'},'provenance':provenance}
    return patch,context
