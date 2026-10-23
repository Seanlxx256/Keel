import json
import unittest
import contextlib
import io
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

from keel.source_comparison import classify, comparison_code, compare_sources, rollback_blocks
from keel.evaluation_protocol import file_hash


class SourceComparisonTests(unittest.TestCase):
    def test_rollback_partition_ignores_line_endings_and_preserves_candidate_bytes(self):
        rows=rollback_blocks('left=1\nkeep=True\nright=1\n',
                             'left=2\r\nkeep=True\r\nright=2\r\n')
        self.assertEqual(len(rows),2)
        self.assertEqual(rows[0]['source'],'left=1\r\nkeep=True\r\nright=2\r\n')
        self.assertEqual(rows[1]['source'],'left=2\r\nkeep=True\r\nright=1\r\n')
        self.assertTrue(all(row['syntax']=='valid' for row in rows))

    def test_rollback_keeps_invalid_partial_variant_labeled(self):
        rows=rollback_blocks('if True:\n    # keep\n    value=1\n',
                             '# removed\n    # keep\nvalue=1\n')
        self.assertEqual(len(rows),2)
        self.assertTrue(any(row['syntax'].startswith('invalid:') for row in rows))

    def rollback_fixture(self, root):
        common={'execution':{'backend':'docker','image':'sha256:'+'b'*64},'python':'/python',
                'test_module':'package.tests.test_module','test_selector':'Suite::test_one'}
        control=root/'control-plan.json';control.write_text(json.dumps(common))
        report=root/'control-report.json';report.write_text(json.dumps({'status':'compared',
            'same_test_source':True,'plan_sha256':file_hash(control),
            'outcomes':{'baseline':'passed','candidate':'failed'},
            'records':[{'result':{'test_file_sha256':'test-hash'}}]}))
        good=root/'good.py';good.write_text('value=1\n')
        bad=root/'bad.py';bad.write_text('def broken(:\n')
        plan={**common,'mode':'block_rollback','control_plan':str(control),'control_report':str(report),
              'variants':[{'label':'revert-1','source_files':{'module.py':str(good)}},
                          {'label':'revert-2','source_files':{'module.py':str(bad)}}],
              'frozen_files':{str(p):file_hash(p) for p in (control,report,good,bad)}}
        path=root/'plan.json';path.write_text(json.dumps(plan));path.with_suffix('.sha256').write_text(file_hash(path))
        return path,good,report

    def test_rollback_reuses_control_and_skips_syntax_invalid_variant(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);path,source,_=self.rollback_fixture(root);sha=file_hash(source)
            test={'exitcode':0,'test_file_sha256':'test-hash','reports':[
                {'nodeid':'tests::Suite::test_one','when':'call','outcome':'passed'}]}
            result={'outcome':'completed','candidate_manifest':{'module':{'path':'module.py','sha256':sha}},
                    'probe':{'stdout':'__KEEL_REGRESSION__'+json.dumps(test),
                             'stderr':'__KEEL_CANDIDATE_IMPORTS__'+json.dumps([
                                 {'module':'module','sha256':sha,'status':'executed'}])}}
            with patch('keel.source_comparison.run_probe',return_value=result) as executor:
                value=compare_sources(path,root/'out')
            self.assertEqual(executor.call_count,1)
            self.assertEqual(value['outcomes'],{'revert-1':'passed','revert-2':'invalid_syntax'})
            self.assertIn('reused_control',value)
            with patch('keel.source_comparison.run_probe') as executor:
                resumed=compare_sources(path,root/'resumed',resume_from=root/'out/report.json')
                executor.assert_not_called()
            self.assertTrue(resumed['records'][0]['reused'])
            self.assertEqual(resumed['status'],'compared')
            self.assertIn('prior_budget',resumed['resume'])

    def test_resume_rejects_different_plan_before_execution(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);path,_,_=self.rollback_fixture(root)
            old=root/'old.json';old.write_text(json.dumps({'plan_sha256':'wrong'}))
            with patch('keel.source_comparison.run_probe') as executor:
                with self.assertRaisesRegex(ValueError,'plan differs'):
                    compare_sources(path,root/'out',resume_from=old)
                executor.assert_not_called()

    def test_changed_control_is_rejected_before_execution(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);path,_,report=self.rollback_fixture(root);report.write_text('{}')
            with patch('keel.source_comparison.run_probe') as executor:
                with self.assertRaisesRegex(ValueError,'control evidence changed'):
                    compare_sources(path,root/'out')
                executor.assert_not_called()

    def test_hypothesis_cache_is_writable_before_pytest_and_test_loading(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);test=root/'package/tests/test_module.py'
            test.parent.mkdir(parents=True);test.write_text('pass\n')
            cache=root/'cache';cache.mkdir()
            original_import=__import__
            def import_checked(name,*args,**kwargs):
                if name=='pytest':
                    self.assertEqual(os.environ['HYPOTHESIS_STORAGE_DIRECTORY'],str(cache))
                return original_import(name,*args,**kwargs)
            def run(args,plugins):
                self.assertEqual(os.environ['HYPOTHESIS_STORAGE_DIRECTORY'],str(cache))
                plugins[0].pytest_runtest_logreport(SimpleNamespace(
                    nodeid='test_module.py::Suite::test_one',when='call',outcome='passed',failed=False))
                return 0
            before=Path.cwd();output=io.StringIO()
            try:
                with patch.dict(os.environ,{},clear=False), \
                        patch.dict('sys.modules',{'pytest':SimpleNamespace(main=run)}), \
                        patch('tempfile.mkdtemp',return_value=str(cache)) as mk, \
                        patch('builtins.__import__',side_effect=import_checked), \
                        patch('importlib.import_module',return_value=SimpleNamespace(__file__=str(test))), \
                        contextlib.redirect_stdout(output):
                    exec(comparison_code('package.tests.test_module','Suite::test_one'),{})
                    self.assertEqual(mk.call_args.kwargs['dir'],'/tmp')
            finally:os.chdir(before)
            value=json.loads(output.getvalue().split('__KEEL_REGRESSION__')[1])
            self.assertEqual(value['exitcode'],0)
            self.assertEqual(value['hypothesis_storage'],str(cache))

    def result(self, outcome='passed', phase='call', rc=0):
        value={'exitcode':rc,'test_file_sha256':'hash','reports':[
            {'nodeid':'tests.py::test_one','when':phase,'outcome':outcome}]}
        return {'outcome':'completed','probe':{'stdout':'__KEEL_REGRESSION__'+json.dumps(value)}}

    def test_exact_pass_and_call_failure_are_distinct(self):
        self.assertEqual(classify(self.result())['status'],'passed')
        self.assertEqual(classify(self.result('failed',rc=1))['status'],'failed')

    def test_setup_failure_skip_and_timeout_are_not_test_results(self):
        self.assertEqual(classify(self.result('failed','setup',1))['status'],'unavailable')
        self.assertEqual(classify(self.result('skipped'))['status'],'unavailable')
        self.assertEqual(classify({'outcome':'script_timeout'})['status'],'unavailable')

    def test_missing_or_multiple_calls_are_unavailable(self):
        self.assertEqual(classify({'outcome':'completed','probe':{'stdout':'log'}})['status'],'unavailable')
        row=self.result();value=json.loads(row['probe']['stdout'].split('__KEEL_REGRESSION__')[1])
        value['reports']*=2;row['probe']['stdout']='__KEEL_REGRESSION__'+json.dumps(value)
        self.assertEqual(classify(row)['status'],'unavailable')

    def test_code_compiles_and_target_is_exact(self):
        code=comparison_code('package.tests.test_module','Suite::test_one')
        compile(code,'<paired-check>','exec')
        self.assertIn('pytest_runtest_logreport',code)
        for module,selector in [('package;evil','test_one'),('package.tests','-k all')]:
            with self.assertRaises(ValueError):comparison_code(module,selector)
