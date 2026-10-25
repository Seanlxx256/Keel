import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from examples.run_swebench_batch import select, prepare, execute, verify_plan,prepare_continuation


class SwebenchBatchTests(unittest.TestCase):
    def test_strict_batch_exit_requires_agent_runtime_and_official_acceptance(self):
        from examples.run_swebench_batch import main
        for runtime,accepted,expected in [('passed',True,0),('failed',True,1),('passed',False,1)]:
            with self.subTest(runtime=runtime,accepted=accepted),patch('sys.argv',[
                    'batch','--output','unused','--execute','--require-all-resolved']),patch(
                    'examples.run_swebench_batch.shutil.which',return_value='docker'),patch(
                    'examples.run_swebench_batch.execute',return_value={'records':[
                        {'runtime_status':runtime,'official_resolved':accepted}]}):
                self.assertEqual(main(),expected)

    def test_archived_failure_continuation_skips_duplicate_initial_grade_and_launches_fresh_agent(self):
        from tests.test_reference_network_recovery import ReferenceNetworkRecoveryTests
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);task,export,failed=ReferenceNetworkRecoveryTests().fixture(root)
            (root/'examples').mkdir();model=root/'model.json';model.write_text('{}')
            plan=prepare_continuation(root,task,failed,model,root/'python',root/'batch',
                preparation_roots=[root],trial_options={'record_model_transcript':True,'budget_limits':{'max_model_calls':2}})
            def pipeline(t,e,f,out,**kwargs):
                self.assertEqual(f,failed)
                target=out/'1-apt_retry';target.mkdir(parents=True)
                (target/'grading.json').write_text(json.dumps({'status':'graded','official_resolved':True,
                    'instance_cache':{'scope':'a'*32,'cache_level':'instance'},'environment_scope':'reconstructed'}))
                return {'status':'reference_verified','reference_grade':str(target)}
            with patch('examples.run_swebench_batch.grade') as grader,patch(
                    'keel.reference_pipeline.recover_pipeline',side_effect=pipeline),patch(
                    'examples.run_swebench_batch.run_task',return_value={'status':'completed','runtime_status':'passed',
                        'official_resolved':True}) as agent:
                result=execute(root,root/'batch')
            grader.assert_not_called()
            self.assertEqual(result['counts']['agent_executed'],1)
            self.assertEqual(agent.call_args.kwargs['budget_limits'],{'max_model_calls':2})
            self.assertTrue(agent.call_args.kwargs['record_model_transcript'])
            self.assertNotIn('saved_repo',agent.call_args.kwargs)
            self.assertEqual(result['records'][0]['instance_id'],plan['tasks'][0]['instance_id'])
            next(failed.rglob('build_image.log')).write_text('changed')
            with self.assertRaisesRegex(ValueError,'preparation evidence changed'):
                verify_plan(root,root/'batch')

    def test_discovery_roots_are_frozen_and_only_verified_recovery_enters_original_agent(self):
        for success in (True,False):
            with self.subTest(success=success),tempfile.TemporaryDirectory() as temp:
                root=Path(temp);evidence=root/'evidence';evidence.mkdir()
                plan=self.fixture(root,recover_network=True,recover_compatibility=True,preparation_roots=[evidence])
                self.assertEqual(plan['reference_pipeline']['preparation_roots'],[str(evidence.resolve())])
                def pipeline(task,export,failed,out,**kwargs):
                    self.assertEqual(kwargs['preparation_roots'],[str(evidence.resolve())])
                    if not success:return {'status':'environment_unresolved','reference_grade':None}
                    target=out/'1-apt_retry';target.mkdir(parents=True)
                    (target/'grading.json').write_text(json.dumps({'status':'graded','official_resolved':True,
                        'environment_scope':'reconstructed','instance_cache':{'scope':'b'*32,'cache_level':'instance'}}))
                    return {'status':'reference_verified','reference_grade':str(target)}
                grades=[{'status':'grading_error','official_resolved':None}]+[{'status':'graded','official_resolved':True}]*2
                with patch('examples.run_swebench_batch.grade',side_effect=grades),patch(
                        'keel.reference_pipeline.recover_pipeline',side_effect=pipeline),patch(
                        'examples.run_swebench_batch.run_task',return_value={'status':'completed',
                            'runtime_status':'passed','official_resolved':True}) as agent:
                    result=execute(root,root/'batch')
                first=root/'batch'/plan['tasks'][0]['directory']
                self.assertEqual(result['records'][0]['instance_id'],plan['tasks'][0]['instance_id'])
                if success:
                    self.assertEqual(agent.call_args_list[0].args[1],first/'task')
                    self.assertEqual(agent.call_args_list[0].args[2],first/'reference-pipeline/1-apt_retry')
                    self.assertTrue(agent.call_args_list[0].kwargs['reuse_reference_image'])
                    self.assertEqual(agent.call_count,3)
                else:
                    self.assertEqual(agent.call_count,2)
                    self.assertEqual(result['records'][0]['status'],'reference_failed_or_error')
                    self.assertNotIn(first/'task',[call.args[1] for call in agent.call_args_list])

    def test_discovery_configuration_rejected_before_output_without_combined_recovery(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);evidence=root/'evidence';evidence.mkdir()
            with self.assertRaisesRegex(ValueError,'combined'):
                self.fixture(root,preparation_roots=[evidence])
            self.assertFalse((root/'batch').exists())

    def test_joint_recovery_chains_then_automatically_launches_original_task(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);plan=self.fixture(root,recover_network=True,recover_compatibility=True)
            self.assertEqual(plan['reference_pipeline']['model_calls'],0)
            def pipeline(task,export,failed,out,**kwargs):
                self.assertLessEqual(kwargs['timeout'],1800)
                target=out/'2-apt_retry';target.mkdir(parents=True)
                result={'status':'graded','official_resolved':True,'environment_scope':'reconstructed',
                        'instance_cache':{'scope':'a'*32,'cache_level':'instance'}}
                (target/'grading.json').write_text(json.dumps(result))
                return {'status':'reference_verified','reference_grade':str(target),'stages':[]}
            grades=[{'status':'graded','official_resolved':False}]+[{'status':'graded','official_resolved':True}]*2
            with patch('examples.run_swebench_batch.grade',side_effect=grades), \
                    patch('keel.reference_pipeline.recover_pipeline',side_effect=pipeline) as chain, \
                    patch('examples.run_swebench_batch.run_task',return_value={
                        'status':'completed','runtime_status':'passed','official_resolved':True}) as agent:
                result=execute(root,root/'batch')
            chain.assert_called_once()
            self.assertEqual(agent.call_args_list[0].kwargs['reuse_reference_image'],True)
            self.assertEqual(result['counts']['agent_executed'],3)
            self.assertEqual(result['records'][0]['instance_id'],plan['tasks'][0]['instance_id'])

    def test_configurable_five_repository_selection(self):
        rows = [{'instance_id': f'r{i}__lib-1', 'repo': f'r{i}/lib'} for i in range(6)]
        chosen = select(rows, set(), set(), count=5, repositories=5)
        self.assertEqual(len(chosen), 5)
        self.assertEqual(len({row['repo'] for row in chosen}), 5)

    def rows(self):
        return [{'instance_id': f'{repo}__lib-{number}', 'repo': f'{repo}/lib',
                 'base_commit': 'a'*40, 'problem_statement': 'Issue', 'patch': 'gold', 'test_patch': 'tests'}
                for repo in ('alpha', 'beta', 'gamma') for number in range(1, 4)]

    def fixture(self, root, **settings):
        (root/'examples').mkdir()
        (root/'examples/evaluation_development_registry.json').write_text('{"tasks":[]}')
        source = root/'data.json'
        source.write_text(json.dumps(self.rows()))
        model = root/'model.json'
        model.write_text('{"name":"test"}')
        with patch('examples.run_swebench_batch.seen_tasks', return_value=(set(), {}, [])):
            return prepare(root, source, model, root/'python', root/'batch', **settings)

    def test_exposure_scan_skips_environments_but_keeps_experiment_receipts(self):
        from examples.run_swebench_batch import seen_tasks
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            env=root/'.keel/tools/.venv';env.mkdir(parents=True)
            (env/'fixture.json').write_text('"ignored__fixture-1"')
            run=root/'.keel/runs';run.mkdir()
            (run/'trial.json').write_text('"actual__task-2"')
            seen,receipts,_=seen_tasks(root)
            self.assertEqual(seen,{'actual__task-2'})
            self.assertEqual(len(receipts),1)

    def test_exposure_scan_deadline_aborts_instead_of_freezing_partial_exclusions(self):
        from examples.run_swebench_batch import seen_tasks
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'docs').mkdir()
            with patch('examples.run_swebench_batch.time.monotonic',side_effect=[0,121]):
                with self.assertRaises(TimeoutError):seen_tasks(root)

    def test_seeded_selection_excludes_seen_tasks_and_is_order_independent(self):
        rows = self.rows()
        excluded = {'alpha__lib-1'}
        chosen = select(rows, excluded, {'gamma/lib'})
        self.assertEqual(chosen, select(list(reversed(rows)), excluded, {'gamma/lib'}))
        self.assertEqual(len(chosen), 3)
        self.assertEqual(len({row['repo'] for row in chosen}), 2)
        self.assertNotIn('alpha__lib-1', [row['instance_id'] for row in chosen])

    def test_settings_drift_rejected_before_any_harness_or_model_call(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.fixture(root)
            (root/'model.json').write_text('{"name":"changed"}')
            with patch('examples.run_swebench_batch.grade') as grade:
                with self.assertRaisesRegex(ValueError, 'settings changed'):
                    execute(root, root/'batch')
                grade.assert_not_called()

    def test_failed_reference_remains_in_fixed_list_and_later_tasks_continue(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            plan = self.fixture(root)
            calls = []
            def reference(*args, **kwargs):
                calls.append(args)
                return {'status': 'graded', 'official_resolved': len(calls) != 1}
            with patch('examples.run_swebench_batch.grade', side_effect=reference), \
                 patch('examples.run_swebench_batch.run_task', return_value={'status': 'completed',
                       'runtime_status': 'failed', 'official_resolved': False}) as run:
                result = execute(root, root/'batch')
            self.assertEqual(len(result['records']), 3)
            self.assertEqual(result['records'][0]['instance_id'], plan['tasks'][0]['instance_id'])
            self.assertEqual(result['counts']['reference_failed_or_error'], 1)
            self.assertEqual(result['counts']['agent_executed'], 2)
            self.assertEqual(run.call_count, 2)
            self.assertEqual(result['counts']['resolved'], 0)
            self.assertEqual(len({row['instance_id'] for row in result['records']}), 3)
            with self.assertRaises(FileExistsError):
                execute(root, root/'batch')

    def test_network_recovery_is_opt_in_and_hands_verified_reference_to_agent(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);plan=self.fixture(root,recover_network=True)
            self.assertEqual(plan['network_recovery']['max_steps'],4)
            grades=[{'status':'grading_error','official_resolved':None}]+[{'status':'graded','official_resolved':True}]*2
            recovered={'status':'reference_verified_reconstructed','grading':{'status':'graded','official_resolved':True}}
            with patch('examples.run_swebench_batch.grade',side_effect=grades), patch('keel.reference_network_recovery.failure_inputs'), patch('keel.reference_network_recovery.recover_reference_network',return_value=recovered) as recovery, patch('examples.run_swebench_batch.run_task',return_value={'status':'completed','runtime_status':'passed','official_resolved':True}) as agent:
                result=execute(root,root/'batch')
            recovery.assert_called_once()
            self.assertEqual(agent.call_args_list[0].args[2],root/'batch'/plan['tasks'][0]['directory']/'network-recovery/reference-grade')
            self.assertEqual(result['records'][0]['environment_scope'],'reconstructed APT transport policy')
            self.assertEqual(result['counts']['resolved_reconstructed_environment'],1)

    def test_changed_reference_cannot_enter_trial(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            plan = self.fixture(root)
            reference = root/'batch'/plan['tasks'][0]['directory']/'reference/predictions.jsonl'
            reference.write_text('{}')
            with self.assertRaisesRegex(ValueError, 'reference changed'):
                verify_plan(root, root/'batch')

    def test_compatibility_recovery_automatically_hands_fresh_reference_to_agent(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);plan=self.fixture(root,recover_compatibility=True)
            self.assertEqual(plan['compatibility_recovery']['model_calls'],0)
            grades=[{'status':'graded','official_resolved':False}]+[{'status':'graded','official_resolved':True}]*2
            recovered={'status':'reference_verified_reconstructed','grading':{'status':'graded','official_resolved':True}}
            with patch('examples.run_swebench_batch.grade',side_effect=grades), \
                    patch('keel.reference_recovery.recover_reference',return_value=recovered) as recovery, \
                    patch('examples.run_swebench_batch.run_task',return_value={
                        'status':'completed','runtime_status':'passed','official_resolved':True}) as agent:
                result=execute(root,root/'batch')
            recovery.assert_called_once()
            self.assertEqual(agent.call_args_list[0].args[2],root/'batch'/plan['tasks'][0]['directory']/'compatibility-recovery/reference-grade')
            self.assertEqual(result['counts']['resolved_reconstructed_environment'],1)
