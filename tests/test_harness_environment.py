import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from keel.harness_environment import apply_overlay, overlay_key, validate_overlay
from keel.models import Reply
from keel.swebench import prepare, reference_prediction
from examples.recover_swebench_environment import recover


def plan(**extra):
    return {'pins':['pip==24.0','setuptools==65.5.0'], 'no_build_isolation':True,
            'hypothesis':'Historical backend requires compatible packaging tools',
            'evidence':'Editable installation failed in the build log',
            'reason':'Test compatibility without source or test changes', **extra}


class EnvironmentTests(unittest.TestCase):
    def test_overlay_changes_only_installation_and_isolates_cache(self):
        spec = SimpleNamespace(repo_script_list=['conda activate testbed','python -m pip install -e .'],
            eval_script_list=['conda activate testbed','pytest tests/test_app.py'],env_script_list=['original env'],
            instance_image_tag='latest',PASS_TO_PASS=['untouched'])
        apply_overlay(spec,plan())
        self.assertIn('--no-build-isolation',spec.repo_script_list[-1])
        self.assertEqual(spec.eval_script_list,['conda activate testbed','pytest tests/test_app.py'])
        self.assertEqual(spec.PASS_TO_PASS,['untouched'])
        self.assertTrue(spec.instance_image_tag.startswith('keel-env-'))
        before = list(spec.repo_script_list)
        apply_overlay(spec,plan())
        self.assertEqual(before,spec.repo_script_list)
        self.assertEqual(overlay_key(plan()),overlay_key(plan(pins=list(reversed(plan()['pins'])))))

    def test_untrusted_plans_cannot_supply_commands_dependencies_or_ranges(self):
        for pins in (['pip==24.0; echo x'],['numpy==1.26.0'],['pip>=24'],['pip==24.0','pip==23.0']):
            with self.subTest(pins=pins), self.assertRaises(ValueError):
                validate_overlay(plan(pins=pins))

    def fixture(self, root):
        row={'instance_id':'org__lib-1','repo':'org/lib','base_commit':'a'*40,
             'problem_statement':'issue','patch':'PRIVATE_GOLD','test_patch':'PRIVATE_TEST'}
        (root/'data.jsonl').write_text(json.dumps(row))
        prepare(root/'data.jsonl',row['instance_id'],root/'task')
        reference_prediction(root/'task',root/'reference')
        failed=root/'failed'
        failed.mkdir()
        (failed/'grading.json').write_text(json.dumps({'status':'grading_error','runtime_status':'reference_only'}))
        (failed/'grader-input.json').write_text(json.dumps([row]))
        logs=failed/'logs/build_images/instances/image'
        logs.mkdir(parents=True)
        (logs/'build_image.log').write_text('ERROR: build_editable hook missing')
        repo=root/'repo';repo.mkdir()
        (repo/'pyproject.toml').write_text('[build-system]\nrequires = ["setuptools"]')
        return failed,repo

    def run_recovery(self, root, replies, grades, mcp_servers=None):
        failed,repo=self.fixture(root)
        calls=[]
        class Model:
            def complete_json(self,messages,**kwargs):
                calls.append(messages)
                return Reply(json.dumps(replies[len(calls)-1]),10)
        def grade(task,export,output,**kwargs):
            value=grades.pop(0)
            output.mkdir()
            (output/'grading.json').write_text(json.dumps(value))
            log=output/'logs/build_images/instances/image';log.mkdir(parents=True)
            (log/'build_image.log').write_text('new packaging error')
            self.assertIn('environment_overlay',kwargs)
            return value
        with patch('examples.recover_swebench_environment.prepare_snapshot',return_value=repo), \
             patch('examples.recover_swebench_environment.grade',side_effect=grade) as grader:
            result=recover(root/'task',root/'reference',failed,root/'recovery',Model(),'python',
                           attempts=min(len(replies),5),max_steps=len(replies),mcp_servers=mcp_servers)
        self.assertNotIn('PRIVATE_',json.dumps(calls))
        return result,calls,grader.call_count

    def test_failed_build_is_observed_and_new_recipe_is_revalidated(self):
        with tempfile.TemporaryDirectory() as temp:
            result,calls,count=self.run_recovery(Path(temp),[plan(),plan(pins=['pip==23.3.2'])],
                [{'status':'grading_error','official_resolved':None}, {'status':'graded','official_resolved':True}])
            self.assertEqual(result['status'],'reference_verified_reconstructed')
            self.assertEqual(count,2)
            self.assertIn('new packaging error',json.dumps(calls[1]))

    def test_repeat_is_not_rebuilt_and_test_failure_does_not_trigger_environment_tuning(self):
        with tempfile.TemporaryDirectory() as temp:
            result,_,count=self.run_recovery(Path(temp),[plan(),plan(reason='Different wording')],
                [{'status':'grading_error','official_resolved':None}])
            self.assertEqual(count,1)
            self.assertEqual(result['attempts'][-1]['status'],'invalid_plan')
        with tempfile.TemporaryDirectory() as temp:
            result,_,count=self.run_recovery(Path(temp),[plan(),plan()],
                [{'status':'graded','official_resolved':False}])
            self.assertEqual(count,1)
            self.assertEqual(result['status'],'environment_unresolved')
            self.assertIn('requires a successful inspection',result['attempts'][-1]['error'])

    def test_reference_failure_can_inspect_then_rebuild_with_observed_evidence(self):
        inspect={'action':'inspect','modules':['json'],'distributions':['setuptools'],
                 'pins':[],'no_build_isolation':False,'hypothesis':'Check installed backend',
                 'evidence':'Import-related test failures','reason':'Inspect before changing versions','evidence_ids':[]}
        rebuilt={**plan(pins=['setuptools==65.5.1']), 'action':'rebuild','conclusion':'undetermined','modules':[],
                 'distributions':[],'evidence_ids':['inspection-2']}
        with tempfile.TemporaryDirectory() as temp, \
             patch('examples.recover_swebench_environment.inspect_image',
                   return_value={'returncode':0,'stdout':'setuptools installed at /testbed','stderr':''}):
            result,calls,count=self.run_recovery(Path(temp),[plan(),inspect,rebuilt],
                [{'status':'graded','official_resolved':False},{'status':'graded','official_resolved':True}])
            self.assertEqual(result['status'],'reference_verified_reconstructed')
            self.assertEqual(count,2)
            self.assertIn('setuptools installed at /testbed',json.dumps(calls[2]))
            self.assertTrue((Path(temp)/'recovery/inspection-2.json').is_file())

    def test_failed_inspection_cannot_authorize_rebuild(self):
        inspect={'action':'inspect','modules':['json'],'distributions':[],
                 'pins':[],'no_build_isolation':False,'evidence_ids':[]}
        rebuilt={**plan(pins=['pip==23.0']), 'action':'rebuild','modules':[],
                 'distributions':[],'evidence_ids':['inspection-2']}
        with tempfile.TemporaryDirectory() as temp, \
             patch('examples.recover_swebench_environment.inspect_image',return_value={'returncode':1,'stderr':'Docker unavailable'}):
            result,_,count=self.run_recovery(Path(temp),[plan(),inspect,rebuilt],
                [{'status':'graded','official_resolved':False}])
            self.assertEqual(count,1)
            self.assertIn('successful inspection',result['attempts'][-1]['error'])

    def test_failed_tool_does_not_authorize_non_environment_conclusion(self):
        inspect={'action':'inspect','modules':['json'],'distributions':[]}
        premature={'action':'stop','conclusion':'non_environment_hypothesis',
                   'evidence_ids':['inspection-1'],'reason':'Installation succeeded so environment is healthy'}
        honest={'action':'stop','conclusion':'undetermined','evidence_ids':[],
                'reason':'Container inspection failed; runtime compatibility remains unknown'}
        with tempfile.TemporaryDirectory() as temp, \
             patch('examples.recover_swebench_environment.inspect_image',return_value={'returncode':125,'stderr':'Engine unavailable'}):
            result,calls,count=self.run_recovery(Path(temp),[inspect,premature,honest],[])
            self.assertEqual(count,0)
            self.assertEqual(result['attempts'][0]['status'],'inspection_failed')
            self.assertEqual(result['attempts'][1]['status'],'invalid_plan')
            self.assertIn('Cannot infer',json.dumps(calls[2]))
            self.assertEqual(result['conclusion'],'undetermined')
            self.assertFalse(result['root_cause_verified'])

    def test_timeout_can_be_observed_then_an_alternative_inspection_used(self):
        import subprocess
        first={'action':'inspect','modules':['setuptools'],'distributions':[]}
        alternative={'action':'inspect','modules':[],'distributions':['setuptools']}
        rebuild={**plan(),'action':'rebuild','modules':[],'distributions':[],
                 'evidence_ids':['inspection-2']}
        with tempfile.TemporaryDirectory() as temp, \
             patch('examples.recover_swebench_environment.inspect_image',side_effect=[
                 subprocess.TimeoutExpired('probe',1),{'returncode':0,'stdout':'version metadata available'}]):
            result,calls,count=self.run_recovery(Path(temp),[first,alternative,rebuild],
                [{'status':'graded','official_resolved':True}])
            self.assertEqual(result['status'],'reference_verified_reconstructed')
            self.assertEqual(count,1)
            self.assertIn('TimeoutExpired',json.dumps(calls[1]))
            self.assertEqual(result['attempts'][0]['status'],'inspection_failed')

    def test_repeated_inspections_stop_at_step_budget_without_extra_tools(self):
        inspect={'action':'inspect','modules':['json'],'distributions':[]}
        with tempfile.TemporaryDirectory() as temp, \
             patch('examples.recover_swebench_environment.inspect_image',return_value={'returncode':1}) as probe:
            result,_,count=self.run_recovery(Path(temp),[inspect,inspect,inspect],[])
            self.assertEqual(probe.call_count,1)
            self.assertEqual(count,0)
            self.assertEqual(result['budget']['model_calls'],3)
            self.assertEqual(result['reason'],'ReAct step limit reached')

    def test_external_mcp_observation_can_inform_environment_recovery(self):
        servers={'diagnostics':{'command':'operator-installed-server','tools':{'lookup':{
            'roles':['scout'],'read_only':True,'description':'Read environment package metadata',
            'input_schema':{'type':'object'}}}}}
        tool={'action':'tool','tool':'mcp__diagnostics__lookup','arguments':{'package':'setuptools'}}
        rebuild={**plan(),'action':'rebuild','tool':'','arguments':{},'evidence_ids':['tool-1']}
        with tempfile.TemporaryDirectory() as temp, \
             patch('keel.mcp_client.McpTools.call',return_value={'content':[{'type':'text','text':'external package evidence'}]}) as call:
            result,calls,count=self.run_recovery(Path(temp),[tool,rebuild],
                [{'status':'graded','official_resolved':True}],servers)
            self.assertEqual(result['status'],'reference_verified_reconstructed')
            self.assertEqual(count,1)
            self.assertIn('external package evidence',json.dumps(calls[1]))
            call.assert_called_once_with('scout','mcp__diagnostics__lookup',{'package':'setuptools'})
