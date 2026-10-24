import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import sys
import io
import contextlib
import unittest
from unittest.mock import Mock,patch

from keel.dependency_compatibility import (resolution_request,validate_resolution,validate_policy,
    apply_compatibility_policy,APPLY_PROGRAM,RESOLVE_PROGRAM)
from keel.environment_probe import DEPENDENCY_PROGRAM
from keel.environment_probe import run_image_program
from keel.reference_recovery import recover_reference
from tests import test_reference_recovery as reference_fixture


class DependencyCompatibilityTests(unittest.TestCase):
    def evidence(self):
        return {'versions':{'consumer-lib':'4.0','provider-lib':'1.0','pip':'25.0'},
            'conflicts':[{'consumer':'consumer-lib','provider':'provider-lib',
                          'requirement':'provider-lib>=2','installed_version':'1.0'}],
            'editable_distributions':[],'module_distributions':{'consumer_lib':['consumer-lib']}}

    def trace(self):return '/env/site-packages/consumer_lib/__init__.py:20: ImportError dependency incompatible'

    def test_resolver_cannot_change_provider_or_invent_consumers(self):
        request=resolution_request(self.evidence(),failure_text=self.trace())
        for pins in ({'provider-lib':'2.0'},{'other':'1.0'},{'consumer-lib':'4.0'}):
            with self.assertRaises(ValueError):validate_resolution(request,{'status':'resolved','pins':pins})
        self.assertEqual(validate_resolution(request,{'status':'resolved','pins':{'consumer-lib':'3.0'}}),
                         {'pins':{'consumer-lib':'3.0'},'anchors':{'provider-lib':'1.0'}})

    def test_editable_project_and_verifier_tools_cannot_be_replaced(self):
        evidence=self.evidence();evidence['editable_distributions']=['consumer-lib']
        with self.assertRaises(ValueError):resolution_request(evidence,failure_text=self.trace())
        with self.assertRaises(ValueError):validate_policy({'pins':{'pytest':'7.0'},'anchors':{'provider-lib':'1.0'}})

    def test_compatibility_adapter_preserves_test_commands_and_reapplies_after_installs(self):
        policy={'pins':{'consumer-lib':'3.0'},'anchors':{'provider-lib':'1.0'}}
        spec=SimpleNamespace(repo_script_list=['git reset --hard original','python -m pip install -e .'],
            eval_script_list=['python -m pip install -e .','pytest original_tests'],instance_image_tag='base')
        apply_compatibility_policy(spec,policy)
        self.assertEqual(spec.repo_script_list[:2],['git reset --hard original','python -m pip install -e .'])
        self.assertEqual(spec.eval_script_list[-1],'pytest original_tests')
        before=list(spec.repo_script_list);apply_compatibility_policy(spec,policy)
        self.assertEqual(before,spec.repo_script_list)
        with self.assertRaises(ValueError):apply_compatibility_policy(spec,{'pins':{'consumer-lib':'2.0'},'anchors':{'provider-lib':'1.0'}})

    def test_controller_observation_to_resolution_to_fresh_grade_without_manual_handoff(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);failed=reference_fixture.ReferenceRecoveryTests().fixture(root)
            log=next(failed.rglob('test_output.txt'));log.write_text(log.read_text()+'\n'+self.trace())
            image=failed/'logs/build_images/instances/sweb.eval.x86_64.org__lib-1__retained'
            image.mkdir(parents=True);(image/'Dockerfile').write_text('FROM retained:base')
            responses=[{'returncode':0,'base_image_id':'sha256:'+'a'*64,'stdout':json.dumps(self.evidence())},
                {'returncode':0,'base_image_id':'sha256:'+'a'*64,'stdout':json.dumps({'status':'resolved','pins':{'consumer-lib':'3.0'}})}]
            grader=Mock(return_value={'status':'graded','official_resolved':True})
            with patch('keel.reference_recovery.inspect_image',return_value=reference_fixture.ReferenceRecoveryTests().inspection()), \
                    patch('keel.reference_recovery.run_image_program',side_effect=responses) as action:
                result=recover_reference(root/'task',root/'reference',failed,root/'out',python='python',timeout=900,grader=grader)
            self.assertEqual(result['status'],'reference_verified_reconstructed')
            self.assertEqual(len(result['actions']),2)
            self.assertEqual(grader.call_args.kwargs['compatibility_policy']['pins'],{'consumer-lib':'3.0'})
            self.assertTrue(action.call_args.kwargs['network'])
            self.assertEqual(result['model_calls'],0)

    def test_unsupported_or_broad_resolver_output_stops_before_grading(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);failed=reference_fixture.ReferenceRecoveryTests().fixture(root)
            next(failed.rglob('test_output.txt')).write_text(self.trace())
            image=failed/'logs/build_images/instances/sweb.eval.x86_64.org__lib-1__retained'
            image.mkdir(parents=True);(image/'Dockerfile').write_text('FROM retained:base')
            grader=Mock()
            responses=[{'returncode':0,'base_image_id':'sha256:'+'a'*64,'stdout':json.dumps(self.evidence())},
                       {'returncode':0,'base_image_id':'sha256:'+'a'*64,'stdout':json.dumps({'status':'resolved','pins':{'provider-lib':'2.0'}})}]
            with patch('keel.reference_recovery.run_image_program',side_effect=responses):
                result=recover_reference(root/'task',root/'reference',failed,root/'out',python='python',timeout=900,grader=grader)
            self.assertEqual(result['status'],'environment_unresolved');grader.assert_not_called()

    def test_reference_receipt_binds_compatibility_policy(self):
        from examples.run_swebench_task import reference_policies
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);p=root/'compatibility-policy.json'
            p.write_text(json.dumps({'pins':{'consumer-lib':'3.0'},'anchors':{'provider-lib':'1.0'}}))
            (root/'grading.json').write_text(json.dumps({'compatibility_policy_sha256':hashlib.sha256(p.read_bytes()).hexdigest()}))
            self.assertEqual(reference_policies(root)['compatibility_policy'],str(p.resolve()))
            p.write_text('{}')
            with self.assertRaises(ValueError):reference_policies(root)

    def test_embedded_programs_compile(self):
        for program in (APPLY_PROGRAM,RESOLVE_PROGRAM,DEPENDENCY_PROGRAM):compile(program,'compatibility','exec')

    def test_live_application_rejects_editable_target_before_install(self):
        policy={'pins':{'consumer-lib':'3.0'},'anchors':{'provider-lib':'1.0'}}
        dist=SimpleNamespace(metadata={'Name':'consumer-lib'},version='4.0',requires=[],
                             read_text=lambda _:json.dumps({'dir_info':{'editable':True}}))
        provider=SimpleNamespace(metadata={'Name':'provider-lib'},version='1.0',requires=[])
        with patch('importlib.metadata.distributions',return_value=[dist,provider]), \
                patch('importlib.metadata.distribution',return_value=dist), \
                patch.object(sys,'argv',['apply',json.dumps(policy)]),patch('subprocess.run') as process:
            with self.assertRaisesRegex(RuntimeError,'editable'):exec(APPLY_PROGRAM,{})
        process.assert_not_called()

    def test_live_application_rejects_new_reverse_dependency_conflict(self):
        policy={'pins':{'consumer-lib':'3.0'},'anchors':{'provider-lib':'1.0'}}
        consumer=SimpleNamespace(metadata={'Name':'consumer-lib'},version='4.0',requires=['provider-lib>=2'],read_text=lambda _:None)
        provider=SimpleNamespace(metadata={'Name':'provider-lib'},version='1.0',requires=[])
        neighbor=SimpleNamespace(metadata={'Name':'neighbor'},version='1.0',requires=['consumer-lib>=4'])
        def install(*a,**k):
            consumer.version='3.0';consumer.requires=['provider-lib>=1']
        with patch('importlib.metadata.distributions',return_value=[consumer,provider,neighbor]), \
                patch('importlib.metadata.distribution',return_value=consumer), \
                patch.object(sys,'argv',['apply',json.dumps(policy)]),patch('subprocess.run',side_effect=install):
            with self.assertRaisesRegex(RuntimeError,'introduced dependency'):exec(APPLY_PROGRAM,{})

    def test_final_cache_identity_includes_compatibility_implementation(self):
        from keel.harness_cache import apply_cache_scope
        def spec():
            return SimpleNamespace(base_image_key='base:latest',env_image_key='env:latest',
                instance_dockerfile='FROM env:latest',env_script_list=[],
                repo_script_list=['python -m pip install -e .'],eval_script_list=['pytest original'],instance_image_tag='base')
        policy={'pins':{'consumer-lib':'3.0'},'anchors':{'provider-lib':'1.0'}}
        first=apply_cache_scope(apply_compatibility_policy(spec(),policy),'a'*32).instance_image_tag
        with patch('keel.dependency_compatibility.APPLY_PROGRAM',APPLY_PROGRAM+'\n# implementation migration'):
            second=apply_cache_scope(apply_compatibility_policy(spec(),policy),'a'*32).instance_image_tag
        self.assertNotEqual(first,second)

    def test_container_image_drift_is_not_reported_as_success(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            def runner(args,**kwargs):
                kwargs['log_path'].write_text('{}' if args[1]=='run' else '')
                return SimpleNamespace(returncode=0)
            versions=[SimpleNamespace(stdout='sha256:'+'a'*64),SimpleNamespace(stdout='sha256:'+'b'*64)]
            with patch('keel.environment_probe.subprocess.run',side_effect=versions), \
                    patch('examples.swebench_bridge.run_harness',side_effect=runner):
                result=run_image_program('fixture:latest','print("{}")',{},root/'out',timeout=45)
            self.assertEqual(result['returncode'],1)
            self.assertEqual(result['error_type'],'ValueError')

    def test_resolver_backtracks_instead_of_installing_new_unapproved_dependencies(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);request=resolution_request(self.evidence(),failure_text=self.trace());calls=[]
            actual_path=type(root)
            def map_path(value):return root/actual_path(value).name
            def pip(args,**kwargs):
                calls.append((args,kwargs))
                rows=[{'metadata':{'name':'consumer-lib','version':'3.0' if len(calls)==1 else '2.0'}}]
                if len(calls)==1:rows.append({'metadata':{'name':'new-dependency','version':'1.0'}})
                else:self.assertIn('new-dependency<0',(root/'keel-compat-constraints.txt').read_text())
                (root/'keel-compat-resolver.json').write_text(json.dumps({'install':rows}))
                return SimpleNamespace(returncode=0)
            stdout=io.StringIO()
            with patch('pathlib.Path',side_effect=map_path),patch.object(sys,'argv',['resolver',json.dumps(request)]), \
                    patch('subprocess.run',side_effect=pip),contextlib.redirect_stdout(stdout):
                exec(RESOLVE_PROGRAM,{})
            result=json.loads(stdout.getvalue())
            self.assertEqual(result['pins'],{'consumer-lib':'2.0'})
            self.assertEqual(result['resolver_rounds'],2)
            self.assertTrue(all(0<kwargs['timeout']<=150 for _,kwargs in calls))

    def test_large_unrelated_inventory_does_not_expand_repair_scope(self):
        evidence=self.evidence()
        for index in range(8):
            name='unrelated-'+str(index)
            evidence['versions'][name]='2.0'
            evidence['conflicts'].append({'consumer':name,'provider':'provider-lib','requirement':'provider-lib>=2'})
        request=resolution_request(evidence,failure_text=self.trace())
        self.assertEqual(request['consumers'],['consumer-lib'])
        self.assertEqual(len(request['scope_evidence']['unrelated_or_handled_conflicts']),8)

    def test_failed_trace_does_not_authorize_fixing_unrelated_conflicts(self):
        with self.assertRaisesRegex(ValueError,'No declared conflicts linked'):
            resolution_request(self.evidence(),failure_text='/workspace/project.py:1 ImportError')

    def test_separately_handled_provider_is_excluded_even_if_on_trace(self):
        evidence=self.evidence()
        evidence['versions']['handled-plugin']='2.0'
        evidence['module_distributions']['handled_plugin']=['handled-plugin']
        evidence['conflicts'].append({'consumer':'handled-plugin','provider':'provider-lib','requirement':'provider-lib>=2'})
        request=resolution_request(evidence,failure_text=self.trace()+'\n/env/site-packages/handled_plugin/api.py:1',
                                   handled_consumers={'handled-plugin'})
        self.assertEqual(request['consumers'],['consumer-lib'])
