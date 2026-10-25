import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from examples.run_swebench_task import config_for, check_reference
from examples.swebench_verify_workspace import workspace_patch, verify
from keel.swebench import prepare
from keel.evaluation_protocol import file_hash
from keel.runtime import validate


class SwebenchTaskTests(unittest.TestCase):
    def test_verified_seed_byte_recovery_precedes_diagnostic_check_and_agent(self):
        from examples.run_swebench_task import execute
        from types import SimpleNamespace
        import hashlib
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);row=self.task(root);reference=self.policy_reference(root,row)
            source=root/'source';repo=root/'repo';source.mkdir();repo.mkdir()
            (source/'sample.py').write_bytes(b'value=2\n');(repo/'sample.py').write_bytes(b'value=2\r\n')
            expected=hashlib.sha256(b'value=2\n').hexdigest()
            context={'verification':[{'returncode':1}],'changes':{},'provenance':{'source_files':{'sample.py':expected}}}
            evidence={'report_sha256':'fixture','observations':[{'candidate_manifest':{'sample':{'path':'sample.py','sha256':expected}}}]}
            def diagnostic(path,current):
                self.assertEqual(hashlib.sha256((current/'sample.py').read_bytes()).hexdigest(),expected)
                return evidence
            def agent(*args,**kwargs):
                self.assertEqual((repo/'sample.py').read_bytes(),b'value=2\n')
                return {'status':'passed','budget':{}}
            with patch('examples.run_swebench_task.subprocess.run',return_value=SimpleNamespace(stdout='3.0.0')), \
                    patch('examples.run_swebench_task.prepare_snapshot',return_value=repo), \
                    patch('keel.saved_repair.load_saved_repair',return_value=('seed',context)), \
                    patch('keel.diagnostic_evidence.load_diagnostic_evidence',side_effect=diagnostic), \
                    patch('examples.run_swebench_task.run',side_effect=agent), \
                    patch('examples.run_swebench_task.export_prediction'), \
                    patch('examples.run_swebench_task.grade',return_value={'status':'graded','official_resolved':True}):
                result=execute(root,root/'task',reference,{'name':'test'},'python',root/'trial',
                    resume_snapshot=root/'snapshot',saved_repo=source,diagnostic_report=root/'report.json')
            self.assertEqual(result['seed_restoration']['restored_files'],1)

    def test_empty_candidate_skips_grading_without_losing_runtime_failure(self):
        from examples.run_swebench_task import execute
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);row=self.task(root);reference=self.policy_reference(root,row)
            repo=root/'repo';repo.mkdir()
            failure={'category':'model_error','stage':'implementer','message':'ambiguous edit'}
            with patch('examples.run_swebench_task.subprocess.run',return_value=SimpleNamespace(stdout='3.0.0')), patch('examples.run_swebench_task.prepare_snapshot',return_value=repo), patch('examples.run_swebench_task.run',return_value={'status':'failed','budget':{},'failure':failure}), patch('examples.run_swebench_task.export_prediction',return_value={'empty_patch':True}), patch('examples.run_swebench_task.grade') as grader:
                report=execute(root,root/'task',reference,{'name':'test'},'python',root/'trial')
            grader.assert_not_called()
            self.assertEqual(report['failure'],failure)
            self.assertEqual(report['final_grading']['status'],'skipped_no_candidate')
            self.assertIsNone(report['official_resolved'])
            self.assertEqual(json.loads((root/'trial/trial.json').read_text())['status'],'unresolved')

    def test_shared_deadline_deducts_preparation_and_bounds_final_grade(self):
        from examples.run_swebench_task import execute
        from types import SimpleNamespace
        clock=[100.0]
        def prepared(*args, **kwargs):
            clock[0]+=100
            return repo
        def ran(config, *args, **kwargs):
            self.assertEqual(config['budget']['max_wallclock'],1080)
            clock[0]+=700
            return {'status':'failed','budget':{}}
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); row=self.task(root); reference=self.policy_reference(root,row)
            repo=root/'repo';repo.mkdir()
            with patch('examples.run_swebench_task.time.monotonic',side_effect=lambda:clock[0]), patch('examples.run_swebench_task.subprocess.run',return_value=SimpleNamespace(stdout='3.0.0')), patch('examples.run_swebench_task.prepare_snapshot',side_effect=prepared), patch('examples.run_swebench_task.run',side_effect=ran), patch('examples.run_swebench_task.export_prediction'), patch('examples.run_swebench_task.grade',return_value={'status':'graded','official_resolved':False}) as grader:
                result=execute(root,root/'task',reference,{'name':'test'},'python',root/'trial',total_seconds=1800)
            self.assertEqual(grader.call_args.kwargs['timeout'],980)
            self.assertEqual(result['shared_deadline']['agent_allocation_seconds'],1080)

    def test_shared_deadline_rejects_conflicting_inner_limit_before_dispatch(self):
        from examples.run_swebench_task import execute
        with self.assertRaisesRegex(ValueError,'not both'):
            execute(None,None,None,{},None,None,total_seconds=1800,budget_limits={'max_wallclock':600})

    def test_failed_unchanged_seed_skips_grade_but_changed_candidate_is_graded(self):
        from examples.run_swebench_task import execute
        from types import SimpleNamespace
        for current in ('seed','changed'):
            with self.subTest(current=current), tempfile.TemporaryDirectory() as temp:
                root=Path(temp);row=self.task(root);reference=self.policy_reference(root,row)
                repo=root/'repo';repo.mkdir()
                context={'verification':[{'returncode':1}], 'changes':{}, 'provenance':{'source_files':{}}}
                with patch('examples.run_swebench_task.subprocess.run',return_value=SimpleNamespace(stdout='3.0.0')), patch('examples.run_swebench_task.prepare_snapshot',return_value=repo), patch('keel.saved_repair.load_saved_repair',return_value=('seed',context)), patch('examples.run_swebench_task.run',return_value={'status':'failed','budget':{}}), patch('examples.run_swebench_task.export_prediction'), patch('keel.swebench.workspace_patch',return_value=current), patch('examples.run_swebench_task.grade',return_value={'status':'graded','official_resolved':False}) as grade:
                    report=execute(root,root/'task',reference,{'name':'test'},'python',root/'trial',resume_snapshot=root/'snapshot',saved_repo=repo)
                self.assertEqual(grade.call_count,int(current!='seed'))
                if current=='seed':
                    self.assertIsNone(report['official_resolved'])
                    self.assertEqual(report['final_grading']['status'],'skipped_unchanged_failed_seed')

    def test_diagnostic_execution_is_forwarded_in_saved_continuation(self):
        from examples.run_swebench_task import execute
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);row=self.task(root);reference=self.policy_reference(root,row)
            repo=root/'repo';repo.mkdir()
            context={'verification':[{'returncode':1}], 'changes':{}, 'provenance':{}}
            evidence={'report_sha256':'report-hash','observations':[{'historical':True}]}
            comparison={'report_sha256':'comparison-hash','observations':[{'label':'baseline','status':'passed'}]}
            probe_config={'execution':{'backend':'docker','image':'sha256:'+'b'*64},
                          'python':'/python','max_model_calls':3}
            with patch('examples.run_swebench_task.subprocess.run',return_value=SimpleNamespace(stdout='3.0.0')), \
                    patch('examples.run_swebench_task.prepare_snapshot',return_value=repo), \
                    patch('keel.saved_repair.load_saved_repair',return_value=('',context)), \
                    patch('keel.diagnostic_evidence.load_diagnostic_evidence',return_value=evidence) as loader, \
                    patch('keel.diagnostic_evidence.load_comparison_evidence',return_value=comparison), \
                    patch('examples.run_swebench_task.run',return_value={'status':'passed','budget':{}}) as agent, \
                    patch('examples.run_swebench_task.export_prediction'), \
                    patch('examples.run_swebench_task.grade',return_value={'status':'graded','official_resolved':True}):
                execute(root,root/'task',reference,{'name':'test'},'python',root/'trial',
                        resume_snapshot=root/'snapshot',saved_repo=repo,diagnostic_report=root/'probe-report.json',
                        diagnostic_execution=probe_config,comparison_plan=root/'comparison-plan.json',
                        comparison_report=root/'comparison-report.json')
            forwarded=agent.call_args.args[0]['continuation_context']
            self.assertEqual(forwarded['changes']['diagnostic_evidence'],evidence)
            self.assertEqual(forwarded['provenance']['diagnostic_report_sha256'],'report-hash')
            self.assertTrue(any(call.args[1]==repo for call in loader.call_args_list))
            self.assertEqual(agent.call_args.args[0]['diagnostic_execution'],probe_config)
            self.assertEqual(forwarded['changes']['controlled_comparisons'],comparison)

    def test_diagnostic_handoff_option_reaches_runtime(self):
        from examples.run_swebench_task import execute
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); row = self.task(root); reference = self.policy_reference(root,row)
            repo = root/'repo'; repo.mkdir()
            with patch('examples.run_swebench_task.subprocess.run',return_value=SimpleNamespace(stdout='3.0.0')), \
                    patch('examples.run_swebench_task.prepare_snapshot',return_value=repo), \
                    patch('examples.run_swebench_task.run',return_value={'status':'passed','budget':{}}) as agent, \
                    patch('examples.run_swebench_task.export_prediction'), \
                    patch('examples.run_swebench_task.grade',return_value={'status':'graded','official_resolved':True}):
                report=execute(root,root/'task',reference,{'name':'test'},'python',root/'trial',diagnostic_handoff=True)
            self.assertTrue(agent.call_args.args[0]['recovery']['diagnostic_handoff'])
            self.assertTrue(report['diagnostic_handoff'])
    def test_default_retained_image_scope_shared_by_verifier_and_final_grading(self):
        from examples.run_swebench_task import execute
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); row = self.task(root); reference = self.policy_reference(root, row)
            repo = root/'repo'; repo.mkdir()
            with patch('examples.run_swebench_task.subprocess.run', return_value=SimpleNamespace(stdout='3.0.0')), \
                    patch('examples.run_swebench_task.prepare_snapshot', return_value=repo), \
                    patch('examples.run_swebench_task.run', return_value={'status': 'passed', 'budget': {}}) as agent, \
                    patch('examples.run_swebench_task.export_prediction'), \
                    patch('examples.run_swebench_task.grade', return_value={'status': 'graded', 'official_resolved': True}) as grade:
                report = execute(root, root/'task', reference, {'name': 'test'}, 'python', root/'trial')
            scope = report['instance_cache_scope']
            self.assertEqual(len(scope), 32)
            command = agent.call_args.args[0]['acceptance'][0]
            self.assertEqual(command[command.index('--instance-cache-scope')+1], scope)
            self.assertEqual(grade.call_args.kwargs['instance_cache_scope'], scope)

    def test_infrastructure_preflight_stops_before_checkout_or_agent(self):
        from examples.run_swebench_task import execute
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); row = self.task(root); reference = self.policy_reference(root, row)
            with patch('examples.run_swebench_task.subprocess.run', return_value=SimpleNamespace(stdout='3.0.0')), \
                    patch('keel.verification_infrastructure.docker_health', return_value={'ready': False}), \
                    patch('examples.run_swebench_task.prepare_snapshot') as checkout, \
                    patch('examples.run_swebench_task.run') as agent, \
                    patch('examples.run_swebench_task.grade') as grade:
                report = execute(root, root/'task', reference, {'name': 'test'}, 'python', root/'trial',
                                 infrastructure_guard=True)
            self.assertEqual(report['status'], 'environment_blocked')
            self.assertIsNone(report['official_resolved'])
            self.assertEqual(json.loads((root/'trial/trial.json').read_text())['status'], 'environment_blocked')
            checkout.assert_not_called(); agent.assert_not_called(); grade.assert_not_called()

    def test_unavailable_runtime_preserves_prediction_and_skips_final_grade(self):
        from examples.run_swebench_task import execute
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); row = self.task(root); reference = self.policy_reference(root, row)
            repo = root/'repo'; repo.mkdir()
            with patch('examples.run_swebench_task.subprocess.run', return_value=SimpleNamespace(stdout='3.0.0')), \
                    patch('keel.verification_infrastructure.docker_health', return_value={'ready': True}), \
                    patch('examples.run_swebench_task.prepare_snapshot', return_value=repo), \
                    patch('examples.run_swebench_task.run', return_value={'status': 'failed', 'budget': {},
                        'failure': {'category': 'environment_blocked'}, 'infrastructure_attempts': [{'attempt': 0}]}), \
                    patch('examples.run_swebench_task.export_prediction') as export, \
                    patch('examples.run_swebench_task.grade') as grade:
                report = execute(root, root/'task', reference, {'name': 'test'}, 'python', root/'trial',
                                 infrastructure_guard=True)
            self.assertEqual(report['status'], 'environment_blocked')
            self.assertEqual(len(report['infrastructure_attempts']), 1)
            export.assert_called_once(); grade.assert_not_called()

    def test_extended_budget_is_explicit_and_keeps_default_limits(self):
        from examples.run_swebench_task import trial_budget
        self.assertEqual(trial_budget()['max_tokens'], 180000)
        extended = trial_budget(profile='extended')
        self.assertEqual(extended, {'max_model_calls': 60, 'max_tokens': 400000,
                                    'max_tool_calls': 160, 'max_wallclock': 3600})
        with self.assertRaises(ValueError):
            trial_budget({'max_model_calls': 60})
        with self.assertRaises(ValueError):
            trial_budget({'max_tokens': 400001}, profile='extended')
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = config_for(self.task(root), root/'task', root/'trial', {}, 'python', budget_profile='extended')
            self.assertEqual(config['recovery']['max_actions'], 12)
            self.assertEqual(config['recovery']['repeat_limit'], 2)
            self.assertEqual(config['verification_repair_attempts'], 8)
            validate(config)

    def test_missing_or_invalid_credentials_fail_before_any_experiment_work(self):
        import os
        from examples.run_swebench_task import execute
        from keel.core import ModelError
        config = {'provider': 'openai-compatible', 'name': 'fixture',
                  'base_url': 'https://example.invalid/v1', 'api_key_env': 'KEEL_TEST_PREFLIGHT_KEY'}
        for value in (None, 'invalid key'):
            with self.subTest(missing=value is None), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                with patch.dict(os.environ, {}, clear=True):
                    if value is not None:
                        os.environ['KEEL_TEST_PREFLIGHT_KEY'] = value
                    with patch('examples.run_swebench_task.check_reference') as reference, \
                         patch('examples.run_swebench_task.prepare_snapshot') as snapshot, \
                         patch('examples.run_swebench_task.subprocess.run') as process, \
                         patch('examples.run_swebench_task.run') as agent, \
                         patch('examples.run_swebench_task.grade') as grade:
                        with self.assertRaises(ModelError) as caught:
                            execute(root, root/'task', root/'reference', config, 'python', root/'trial')
                        self.assertNotIn('invalid key', str(caught.exception))
                        for operation in (reference, snapshot, process, agent, grade):
                            operation.assert_not_called()
                self.assertFalse((root/'trial').exists())

    def policy_reference(self,root,row):
        reference=root/'reference';reference.mkdir()
        (reference/'grader-input.json').write_text(json.dumps([row]))
        result={'status':'graded','official_resolved':True,'runtime_status':'reference_only',
                'harness_version':'3.0.0','grader_input_sha256':file_hash(reference/'grader-input.json')}
        for key,filename,value in [('network_policy','network-policy.json','no_pipeline'),
                                    ('plugin_policy','plugin-policy.json','remove_unused_vcs_versioning')]:
            (reference/filename).write_text(json.dumps({'policy':value,'version':1}))
            result[key]=value;result[key+'_sha256']=file_hash(reference/filename)
        (reference/'grading.json').write_text(json.dumps(result))
        return reference

    def test_recovered_policies_propagate_through_agent_verification_and_final_grade(self):
        self.check_policy_propagation(True)

    def test_inspection_ablation_disables_only_gate_and_retains_candidate_policy(self):
        self.check_policy_propagation(False)

    def test_progress_monitor_is_an_explicit_independent_toggle(self):
        self.check_policy_propagation(False, progress=True)

    def test_extended_profile_reaches_runtime_and_report(self):
        self.check_policy_propagation(False, progress=True, budget_profile='extended')

    def test_supervision_toggle_reaches_runtime_without_forcing_progress_or_inspection(self):
        self.check_policy_propagation(False, supervision=True)

    def check_policy_propagation(self, inspection, progress=False, budget_profile='standard', supervision=False):
        from examples.run_swebench_task import execute
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);row=self.task(root);reference=self.policy_reference(root,row)
            repo=root/'repo';repo.mkdir()
            with patch('examples.run_swebench_task.subprocess.run',return_value=SimpleNamespace(stdout='3.0.0')), \
                 patch('examples.run_swebench_task.prepare_snapshot',return_value=repo), \
                 patch('examples.run_swebench_task.run',return_value={'status':'passed','budget':{}}) as agent, \
                 patch('examples.run_swebench_task.export_prediction'), \
                 patch('examples.run_swebench_task.grade',return_value={'status':'graded','official_resolved':True}) as grade:
                report=execute(root,root/'task',reference,{'name':'test'},'python',root/'trial',
                               diagnostic_inspection=inspection,recovery_progress=progress,
                               diagnosis_supervision=supervision,budget_profile=budget_profile)
            self.assertEqual(agent.call_args.args[0]['require_diagnostic_inspection'],inspection)
            self.assertTrue(agent.call_args.args[0]['preserve_repair_candidates'])
            self.assertEqual(report['diagnostic_inspection'],inspection)
            self.assertEqual(agent.call_args.args[0]['recovery']['monitor_progress'], progress)
            self.assertEqual(report['recovery_progress'], progress)
            self.assertEqual(agent.call_args.args[0]['recovery']['diagnosis_supervision'], supervision)
            self.assertEqual(report['diagnosis_supervision'], supervision)
            self.assertEqual(report['budget_profile'], budget_profile)
            self.assertEqual(agent.call_args.args[0]['budget'], report['limits'])
            self.assertGreaterEqual(report['trial_wallclock_seconds'], 0)
            acceptance=agent.call_args.args[0]['acceptance'][0]
            self.assertIn('--network-policy',acceptance);self.assertIn('--plugin-policy',acceptance)
            self.assertEqual(grade.call_args.kwargs['network_policy'],'no_pipeline')
            self.assertEqual(grade.call_args.kwargs['plugin_policy'],'remove_unused_vcs_versioning')
            self.assertTrue(report['official_resolved'])
            (reference/'plugin-policy.json').write_text('{}')
            with self.assertRaisesRegex(ValueError,'plugin_policy changed'):
                check_reference(root/'task',reference)

    def test_intermediate_verifier_passes_both_policies_to_harness(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);self.task(root)
            with patch('examples.swebench_verify_workspace.workspace_patch',return_value='source diff'), \
                 patch('examples.swebench_verify_workspace.grade',return_value={'status':'graded','official_resolved':True,'run_id':'run'}) as grade:
                verify(root,root/'task',root/'verification','python',network_policy='no_pipeline',plugin_policy='remove_unused_vcs_versioning')
            self.assertEqual(grade.call_args.kwargs['plugin_policy'],'remove_unused_vcs_versioning')
            self.assertEqual(grade.call_args.kwargs['network_policy'],'no_pipeline')
    def test_reconstructed_overlay_is_bound_to_reference_and_propagated(self):
        from tests.test_harness_environment import plan
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            row = self.task(root)
            reference = root/'reference'
            reference.mkdir()
            (reference/'environment-overlay.json').write_text(json.dumps(plan()))
            (reference/'grader-input.json').write_text(json.dumps([row]))
            result = {'status':'graded','official_resolved':True,'runtime_status':'reference_only',
                'harness_version':'3.0.0','grader_input_sha256':file_hash(reference/'grader-input.json'),
                'environment_overlay_sha256':file_hash(reference/'environment-overlay.json')}
            (reference/'grading.json').write_text(json.dumps(result))
            self.assertEqual(check_reference(root/'task',reference),plan())
            config = config_for(row,root/'task',root/'trial',{},'python',reference/'environment-overlay.json')
            self.assertIn('--environment-overlay',config['acceptance'][0])
            (reference/'environment-overlay.json').write_text('{}')
            with self.assertRaisesRegex(ValueError,'overlay changed'):
                check_reference(root/'task',reference)
    def task(self, root):
        row = {'instance_id': 'org__lib-1', 'repo': 'org/lib', 'base_commit': 'a'*40,
               'problem_statement': 'Repair API behavior', 'patch': 'SECRET_GOLD', 'test_patch': 'SECRET_TEST'}
        source = root/'data.jsonl'
        source.write_text(json.dumps(row))
        prepare(source, row['instance_id'], root/'task')
        return row

    def test_config_uses_issue_only_and_official_feedback_loop(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            task = self.task(root)
            config = config_for(task, root/'task', root/'trial', {'name': 'test'}, 'harness-python')
            self.assertEqual(config['goal'], task['problem_statement'])
            self.assertNotIn('SECRET', json.dumps(config))
            self.assertEqual(config['recovery']['strategy'], 'adaptive')
            self.assertEqual(config['verification_repair_attempts'], 3)
            self.assertFalse(config['require_diagnostic_inspection'])
            self.assertTrue(config['preserve_repair_candidates'])
            self.assertIn('swebench_verify_workspace.py', config['acceptance'][0][1])
            validate(config)

    def test_unverified_reference_cannot_start_inference(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.task(root)
            (root/'reference').mkdir()
            (root/'reference/grading.json').write_text(json.dumps({'status': 'graded', 'official_resolved': False}))
            with self.assertRaisesRegex(ValueError, 'preflight'):
                check_reference(root/'task', root/'reference')

    def test_empty_patch_does_not_call_harness_or_claim_pass(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.task(root)
            with patch('examples.swebench_verify_workspace.workspace_patch', return_value=''), \
                 patch('examples.swebench_verify_workspace.grade') as grade:
                result = verify(root, root/'task', root/'verification', 'python')
            grade.assert_not_called()
            self.assertFalse(result['official_resolved'])

    def test_feedback_excludes_setup_and_test_patch(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.task(root)
            def grade(task, export, output, **kwargs):
                directory = output/'logs/run_evaluation/run/keel-verification/org__lib-1'
                directory.mkdir(parents=True)
                (directory/'report.json').write_text(json.dumps({'org__lib-1': {'tests_status': {'FAIL_TO_PASS': {'failure': ['case']}}}}))
                (directory/'test_output.txt').write_text('SECRET_TEST_PATCH\n>>>>> Start Test Output\ncase failed\n>>>>> End Test Output\nSETUP_SECRET')
                return {'status': 'graded', 'official_resolved': False, 'run_id': 'run'}
            with patch('examples.swebench_verify_workspace.workspace_patch', return_value='source diff'), \
                 patch('examples.swebench_verify_workspace.grade', side_effect=grade):
                feedback = verify(root, root/'task', root/'verification', 'python')
            self.assertNotIn('SECRET', json.dumps(feedback))
            self.assertIn('case failed', feedback['observed_test_output_tail'])

    def test_real_git_diff_is_bound_to_exact_base_commit(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            def git(*args):
                return subprocess.run(['git', '-c', 'safe.directory='+str(root), '-C', str(root), *args],
                                      check=True, capture_output=True).stdout.decode().strip()
            git('init', '-q')
            (root/'app.py').write_text('VALUE = 1\n')
            git('add', 'app.py')
            git('-c', 'user.name=Test', '-c', 'user.email=test@example.invalid', 'commit', '-qm', 'fixture')
            task = {'base_commit': git('rev-parse', 'HEAD')}
            (root/'app.py').write_text('VALUE = 2\n')
            diff = workspace_patch(root, task)
            self.assertIn('-VALUE = 1', diff)
            self.assertIn('+VALUE = 2', diff)
            with self.assertRaisesRegex(ValueError, 'HEAD'):
                workspace_patch(root, {'base_commit': 'b'*40})
