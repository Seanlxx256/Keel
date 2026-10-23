import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
import warnings
import io
import contextlib
from unittest.mock import patch,Mock
from keel.harness_plugins import apply_plugin_policy,POLICY,PROGRAM
from keel.reference_recovery import recover_reference
from keel.swebench import prepare,reference_prediction


class ReferenceRecoveryTests(unittest.TestCase):
    def fixture(self,root):
        row={'instance_id':'org__lib-1','repo':'org/lib','base_commit':'a'*40,
             'problem_statement':'issue','patch':'REFERENCE','test_patch':'TEST'}
        data=root/'data.jsonl';data.write_text(json.dumps(row))
        prepare(data,row['instance_id'],root/'task');reference_prediction(root/'task',root/'reference')
        failed=root/'failed';failed.mkdir()
        (failed/'grading.json').write_text(json.dumps({'status':'graded','runtime_status':'reference_only',
            'official_resolved':False,'network_policy':'no_pipeline'}))
        (failed/'grader-input.json').write_text(json.dumps([row]))
        log=failed/'logs/run_evaluation/run/reference/id/test_output.txt';log.parent.mkdir(parents=True)
        log.write_text('DeprecationWarning release-branch-semver vcs_versioning')
        return failed

    def inspection(self,dependents=None):
        return {'returncode':0,'stdout':json.dumps({'baseline':{'passed':False},'providers':[
            {'distribution':'vcs-versioning','isolated_call':{'passed':False,'error_type':'DeprecationWarning'}},
            {'distribution':'setuptools-scm','isolated_call':{'passed':True}}],
            'dependent_distributions':{'vcs-versioning':dependents or []}})}

    def test_evidence_gate_executes_repair_and_grading_without_manual_handoff(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);failed=self.fixture(root)
            grader=Mock(return_value={'status':'graded','official_resolved':True})
            with patch('keel.reference_recovery.inspect_image',return_value=self.inspection()):
                result=recover_reference(root/'task',root/'reference',failed,root/'recovery',python='python',timeout=300,grader=grader)
            self.assertEqual(result['status'],'reference_verified_reconstructed')
            self.assertEqual(grader.call_args.kwargs['plugin_policy'],POLICY)
            self.assertEqual(grader.call_args.kwargs['network_policy'],'no_pipeline')
            self.assertLessEqual(grader.call_args.kwargs['timeout'],300)

    def test_grading_timeout_never_exceeds_original_budget_after_float_rounding(self):
        # (212.18 + 300) - 212.18 is 300.00000000000006.
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);failed=self.fixture(root)
            grader=Mock(return_value={'status':'graded','official_resolved':True})
            with patch('keel.reference_recovery.inspect_image',return_value=self.inspection()), patch('keel.reference_recovery.time.monotonic',return_value=212.18):
                result=recover_reference(root/'task',root/'reference',failed,root/'recovery',python='python',timeout=300,grader=grader)
            self.assertEqual(result['status'],'reference_verified_reconstructed')
            self.assertEqual(grader.call_args.kwargs['timeout'],300)

    def test_required_provider_is_never_removed(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);failed=self.fixture(root);grader=Mock()
            with patch('keel.reference_recovery.inspect_image',return_value=self.inspection(['required-by'])):
                result=recover_reference(root/'task',root/'reference',failed,root/'recovery',python='python',timeout=300,grader=grader)
            self.assertEqual(result['status'],'environment_unresolved');grader.assert_not_called()

    def test_live_guard_refuses_removal_if_a_required_dependency_appears(self):
        bad=SimpleNamespace(group='setuptools_scm.version_scheme',name='release-branch-semver')
        distributions=[SimpleNamespace(metadata={'Name':'vcs-versioning'},entry_points=[bad],requires=[]),
                       SimpleNamespace(metadata={'Name':'new-consumer'},entry_points=[],requires=['vcs-versioning>=2'])]
        with patch('importlib.metadata.distributions',return_value=distributions), \
             patch.dict('sys.modules',{'setuptools_scm':SimpleNamespace(),
                                      'setuptools_scm.git':SimpleNamespace(parse=lambda root:object())}), \
             patch('subprocess.run') as process:
            with self.assertRaisesRegex(RuntimeError,'required by'):
                exec(compile(PROGRAM,'<repair>','exec'),{})
        process.assert_not_called()

    def test_plugin_policy_changes_environment_only_and_rechecks_after_eval_install(self):
        original=['conda activate testbed','python -m pip install -e .']
        spec=SimpleNamespace(repo_script_list=list(original),eval_script_list=original+['pytest tests/test.py'],
            env_script_list=['unchanged'],instance_image_tag='keel-network-no-pipeline-v1')
        apply_plugin_policy(spec,POLICY)
        self.assertEqual(spec.eval_script_list[-1],'pytest tests/test.py')
        self.assertEqual(spec.env_script_list,['unchanged'])
        self.assertTrue(spec.instance_image_tag.endswith('-scm-recovery-v1'))
        self.assertIn('python -m pip install -e .',spec.repo_script_list)
        previous=list(spec.repo_script_list);apply_plugin_policy(spec,POLICY)
        self.assertEqual(previous,spec.repo_script_list)
        self.assertIn("warnings.simplefilter('error',DeprecationWarning)",PROGRAM)
        self.assertIn("'pip','check'",PROGRAM)
