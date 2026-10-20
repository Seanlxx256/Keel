import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from examples.run_swebench_tool_comparison import execute, summarize, verify
from examples.run_swebench_tool_comparison import prepare_continuation
from keel.evaluation_protocol import file_hash
from keel.core import digest


class ComparisonTests(unittest.TestCase):
    def test_continuation_runs_only_unstarted_task_and_reuses_successful_reference(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);old=root/'old';old.mkdir();directory=old/'task-3';directory.mkdir()
            task=directory/'task';task.mkdir();(task/'task-receipt.json').write_text('{}')
            export=directory/'reference';export.mkdir()
            for name in ('predictions.jsonl','export-receipt.json'):(export/name).write_text('{}')
            model=root/'model.json';model.write_text('{}')
            tools=root/'tools.json';tools.write_text('{}')
            row={'instance_id':'org__lib-3','directory':'task-3','arm_order':['local','mcp_optional'],
                'receipt_sha256':file_hash(task/'task-receipt.json'),'reference_sha256':file_hash(export/'predictions.jsonl'),
                'reference_receipt_sha256':file_hash(export/'export-receipt.json')}
            plan={'tasks':[row],'model_file':str(model),'model_sha256':file_hash(model),'harness_python':'python',
                  'tool_comparison':{'policy':'optional','profile':str(tools),'files':{str(tools):file_hash(tools)},'steps':6}}
            plan['plan_sha256']=digest(plan);(old/'plan.json').write_text(json.dumps(plan))
            (old/'comparison.json').write_text(json.dumps({'records':[{'instance_id':row['instance_id'],'status':'reference_failed_or_error','arms':{}}]}))
            before=file_hash(old/'comparison.json')
            reference=root/'successful';reference.mkdir()
            (reference/'grader-input.json').write_text('[]')
            (reference/'grading.json').write_text(json.dumps({'status':'graded','official_resolved':True}))
            output=root/'new'
            with patch('examples.run_swebench_tool_comparison.check_reference'), \
                 patch('examples.run_swebench_tool_comparison.run_task',return_value={'status':'completed','official_resolved':True}) as agent, \
                 patch('examples.run_swebench_tool_comparison.grade') as grade:
                prepare_continuation(root,old,reference,row['instance_id'],output)
                report=execute(root,output)
            grade.assert_not_called()
            self.assertEqual(agent.call_count,2)
            self.assertEqual(report['summary']['planned_tasks'],1)
            self.assertEqual(file_hash(old/'comparison.json'),before)
            (reference/'grading.json').write_text('{}')
            with self.assertRaisesRegex(ValueError,'reference evidence changed'):
                verify(root,output)
    def plan(self, root):
        model = root/'model.json'
        model.write_text('{}')
        return {'plan_sha256': 'frozen', 'tasks': [{'instance_id': 'repo__repo-1', 'directory': 'task-1',
            'arm_order': ['mcp_required', 'local']}], 'harness_python': 'python', 'model_file': str(model),
            'tool_comparison': {'profile': 'tools.json', 'steps': 6}}

    def test_both_arms_share_inputs_exploration_and_reference_with_fixed_order(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            plan = self.plan(root)
            with patch('examples.run_swebench_tool_comparison.verify', return_value=plan), \
                 patch('examples.run_swebench_tool_comparison.check_reference'), \
                 patch('examples.run_swebench_tool_comparison.grade', return_value={'status': 'graded', 'official_resolved': True}), \
                 patch('examples.run_swebench_tool_comparison.run_task', return_value={'status': 'completed', 'official_resolved': False}) as run:
                result = execute(root, root)
            self.assertEqual(run.call_count, 2)
            first, second = run.call_args_list
            self.assertTrue(first.kwargs['require_external_tool'])
            self.assertFalse(second.kwargs['require_external_tool'])
            self.assertIsNone(second.kwargs['mcp_config'])
            for call in (first, second):
                self.assertTrue(call.kwargs['local_exploration'])
                self.assertEqual(call.kwargs['localization_tool_steps'], 6)
            self.assertEqual(first.args[1:5], second.args[1:5])
            self.assertEqual(result['summary']['outcomes']['both_failed'], 1)

    def test_reference_failure_prevents_both_arms_without_task_replacement(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with patch('examples.run_swebench_tool_comparison.verify', return_value=self.plan(root)), \
                 patch('examples.run_swebench_tool_comparison.grade', return_value={'status': 'grading_error', 'official_resolved': None}), \
                 patch('examples.run_swebench_tool_comparison.run_task') as run:
                report = execute(root, root)
            run.assert_not_called()
            self.assertEqual(report['records'][0]['status'], 'reference_failed_or_error')
            self.assertEqual(report['summary']['paired_completed'], 0)
            self.assertIsNone(report['summary']['paired_success_rate']['local'])

    def test_optional_profile_is_available_but_never_required(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            plan = self.plan(root)
            plan['tool_comparison']['policy'] = 'optional'
            plan['tasks'][0]['arm_order'] = ['mcp_optional', 'local']
            with patch('examples.run_swebench_tool_comparison.verify', return_value=plan), \
                 patch('examples.run_swebench_tool_comparison.check_reference'), \
                 patch('examples.run_swebench_tool_comparison.grade', return_value={'status': 'graded', 'official_resolved': True}), \
                 patch('examples.run_swebench_tool_comparison.run_task', return_value={
                     'status': 'completed', 'official_resolved': True, 'external_tool_calls': {}}) as run:
                result = execute(root, root)
            external, local = run.call_args_list
            self.assertEqual(external.kwargs['mcp_config'], Path('tools.json'))
            self.assertIsNone(local.kwargs['mcp_config'])
            self.assertFalse(external.kwargs['require_external_tool'])
            self.assertFalse(local.kwargs['require_external_tool'])
            self.assertEqual(result['summary']['paired_success_rate']['mcp_optional'], 1)
            self.assertEqual(result['records'][0]['arms']['mcp_optional']['external_tool_calls'], {})

    def test_completed_model_failure_counts_and_missing_arm_is_explicit(self):
        records = [{'instance_id': 'one', 'arms': {'local': {'status': 'completed', 'official_resolved': False},
                    'mcp_required': {'status': 'completed', 'official_resolved': True}}},
                   {'instance_id': 'two', 'arms': {'local': {'status': 'completed', 'official_resolved': True}}}]
        result = summarize(records)
        self.assertEqual(result['outcomes']['mcp_only'], 1)
        self.assertEqual(result['unpaired_tasks'], ['two'])

    def test_changed_tool_file_rejects_execution(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            file = root/'launcher.py'
            file.write_text('before')
            plan = {'tool_comparison': {'files': {str(file): file_hash(file)}}}
            (root/'plan.json').write_text(json.dumps(plan))
            file.write_text('after')
            with patch('examples.run_swebench_tool_comparison.verify_plan', return_value=plan):
                with self.assertRaisesRegex(ValueError, 'changed after freeze'):
                    verify(root, root)
