import json
from pathlib import Path
import tempfile
import unittest

from keel.diagnostic_evidence import load_diagnostic_evidence, load_comparison_evidence
from keel.evaluation_protocol import file_hash


class DiagnosticEvidenceTests(unittest.TestCase):
    def fixture(self, root):
        repo=root/'repo';repo.mkdir();source=repo/'sample.py';source.write_text('value=1\n')
        sha=file_hash(source)
        row={'kind':'execution','outcome':'completed','evidence_id':'observation-1','code':'print(1)',
             'execution':{'returncode':0,'timeout':False},
             'candidate_manifest':{'sample':{'path':'sample.py','sha256':sha}},
             'probe':{'returncode':0,'timeout':False,'stdout':'1',
                      'stderr':'__KEEL_CANDIDATE_IMPORTS__'+json.dumps([
                          {'module':'sample','status':'executed','sha256':sha}])}}
        report={'status':'completed_needs_review','workspace_unchanged':True,
                'acceptance':'not_executed','image_id':'sha256:fixture',
                'diagnosis':{'observations':[row], 'assessment':{'answer':'Unverified opinion'}}}
        path=root/'report.json'
        return repo,path,report

    def save(self,path,report):
        path.write_text(json.dumps(report))
        path.with_name('receipt.json').write_text(json.dumps(
            {'report_sha256':file_hash(path),'plan_sha256':'fixture'}))

    def test_transfers_raw_execution_without_model_verdict(self):
        with tempfile.TemporaryDirectory() as t:
            repo,path,report=self.fixture(Path(t));self.save(path,report)
            value=load_diagnostic_evidence(path,repo)
            self.assertEqual(value['observations'][0]['probe']['stdout'],'1')
            self.assertTrue(value['observations'][0]['historical'])
            self.assertNotIn('Unverified opinion',json.dumps(value))

    def test_changed_source_and_changed_report_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            repo,path,report=self.fixture(Path(t));self.save(path,report)
            (repo/'sample.py').write_text('value=2\n')
            with self.assertRaisesRegex(ValueError,'source mismatch'):load_diagnostic_evidence(path,repo)
            path.write_text('{}')
            with self.assertRaisesRegex(ValueError,'receipt mismatch'):load_diagnostic_evidence(path,repo)

    def test_historical_only_and_missing_loader_execution_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            repo,path,report=self.fixture(Path(t));row=report['diagnosis']['observations'][0]
            row['historical']=True;self.save(path,report)
            with self.assertRaisesRegex(ValueError,'No completed'):load_diagnostic_evidence(path,repo)
            row['historical']=False;row['probe']['stderr']='';self.save(path,report)
            with self.assertRaisesRegex(ValueError,'provenance missing'):load_diagnostic_evidence(path,repo)

    def test_path_escape_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            repo,path,report=self.fixture(Path(t))
            report['diagnosis']['observations'][0]['candidate_manifest']['sample']['path']='../escape.py'
            self.save(path,report)
            with self.assertRaisesRegex(ValueError,'source mismatch'):load_diagnostic_evidence(path,repo)


class ComparisonEvidenceTests(unittest.TestCase):
    def fixture(self, root):
        repo=root/'repo';repo.mkdir();(repo/'module.py').write_text('value=2\n')
        common={'execution':{'backend':'docker','image':'sha256:'+'b'*64},'python':'/python',
                'test_module':'package.tests.test_one','test_selector':'Suite::test_one'}
        sources={}
        for label,value in [('baseline',1),('candidate',2),('revert-1',1)]:
            p=root/(label+'.py');p.write_text(f'value={value}\n');sources[label]=p
        def row(label,status):
            sha=file_hash(sources[label]);test={'exitcode':0 if status=='passed' else 1,
                'test_file_sha256':'test-hash','reports':[{'nodeid':'test_one','when':'call','outcome':status}]}
            return {'label':label,'status':status,'result':test,'execution':{
                'outcome':'completed','candidate_manifest':{'module':{'path':'module.py','sha256':sha}},
                'probe':{'stdout':'__KEEL_REGRESSION__'+json.dumps(test),
                    'stderr':'__KEEL_CANDIDATE_IMPORTS__'+json.dumps([{'module':'module','sha256':sha,'status':'executed'}])}}}
        cp=root/'control-plan.json';cp.write_text(json.dumps({**common,
            'variants':[{'label':l,'source_files':{'module.py':str(sources[l])}} for l in ('baseline','candidate')],
            'frozen_files':{str(p):file_hash(p) for p in sources.values()}}))
        cr=root/'control-report.json';cr.write_text(json.dumps({'status':'compared',
            'plan_sha256':file_hash(cp),'records':[row('baseline','passed'),row('candidate','failed')]}))
        plan={**common,'mode':'block_rollback','control_plan':str(cp),'control_report':str(cr),
              'variants':[{'label':'revert-1','source_files':{'module.py':str(sources['revert-1'])}}],
              'blocks':[{'id':1,'baseline_lines':[1,1],'candidate_lines':[1,1],'reverted_diff':'observed diff'}],
              'frozen_files':{str(p):file_hash(p) for p in (cp,cr,*sources.values())}}
        pp=root/'plan.json';pp.write_text(json.dumps(plan));pp.with_suffix('.sha256').write_text(file_hash(pp))
        rp=root/'report.json';rp.write_text(json.dumps({'status':'compared','plan_sha256':file_hash(pp),
                                                       'records':[row('revert-1','passed')]}))
        return pp,rp,repo

    def test_compact_controlled_results_bound_to_current_candidate(self):
        with tempfile.TemporaryDirectory() as t:
            args=self.fixture(Path(t));value=load_comparison_evidence(*args)
            self.assertEqual([r['status'] for r in value['observations']],['passed','failed','passed'])
            self.assertEqual(value['candidate_source_files']['module.py'],file_hash(args[2]/'module.py'))

    def test_changed_candidate_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            args=self.fixture(Path(t));(args[2]/'module.py').write_text('value=3\n')
            with self.assertRaisesRegex(ValueError,'candidate differs'):load_comparison_evidence(*args)

    def test_claimed_status_cannot_override_raw_result(self):
        with tempfile.TemporaryDirectory() as t:
            args=self.fixture(Path(t));r=json.loads(args[1].read_text());r['records'][0]['status']='failed'
            args[1].write_text(json.dumps(r))
            with self.assertRaisesRegex(ValueError,'result invalid'):load_comparison_evidence(*args)

    def test_control_tamper_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            args=self.fixture(Path(t));(Path(t)/'control-report.json').write_text('{}')
            with self.assertRaisesRegex(ValueError,'inputs changed'):load_comparison_evidence(*args)

