import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

from keel.models import Reply
from keel.runtime import run


HAS_GRAPH = importlib.util.find_spec('langgraph') is not None


class AdaptiveTests(unittest.TestCase):
    def workspace(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        (root/'pkg').mkdir()
        for name in ('wrong', 'actual'):
            (root/f'pkg/{name}.py').write_text('def value():\n    return 1\n', encoding='utf-8')
        (root/'outside.py').write_text('VALUE = 1\n', encoding='utf-8')
        return root

    def config(self, engine='native'):
        return {'mode': 'localized-proposal', 'orchestrator': engine, 'goal': 'Return 3 from actual.value',
                'agent': {'require_change': True, 'max_context_bytes': 24000},
                'recovery': {'max_actions': 5, 'repeat_limit': 1, 'strategy': 'adaptive', 'write_roots': ['pkg']},
                'budget': {'max_model_calls': 20, 'max_tokens': 200000},
                'acceptance': [[sys.executable, '-B', '-c', 'from pkg.actual import value; assert value() == 3']]}

    def model(self, responses):
        class Model:
            def __init__(self):
                self.calls = []
            def complete_json(self, messages, **kwargs):
                self.calls.append(messages)
                response = responses[len(self.calls)-1]
                if 'action' in response:
                    response = {**response, 'hypothesis': 'Current implementation returns the wrong value.',
                        'evidence': 'Assertion failed after the current source edit.',
                        'next_check': 'Read the current value function and compare its return with the assertion.',
                        'previous_attempt_assessment': 'The earlier edit did not satisfy the observed assertion.'}
                return Reply(json.dumps(response), 10)
        return Model()

    def patch(self, name, old, new):
        return {'edits': [{'path': f'pkg/{name}.py', 'old': f'return {old}', 'new': f'return {new}'}], 'summary': 'update'}

    def replan_replies(self):
        return [{'files': ['pkg/wrong.py']}, {'locations': ['pkg/wrong.py:1']}, self.patch('wrong', 1, 2),
                {'action': 'replan', 'reason': 'The failing function is in another module; inspect it and undo the unrelated edit.'},
                {'files': ['pkg/actual.py', 'pkg/wrong.py']}, {'locations': ['pkg/actual.py:1', 'pkg/wrong.py:1']},
                {'edits': [*self.patch('actual', 1, 3)['edits'], *self.patch('wrong', 2, 1)['edits']],
                 'summary': 'Fix actual and restore unrelated wrong module'}]

    def check_replan(self, engine):
        root = self.workspace()
        model = self.model(self.replan_replies())
        result = run(self.config(engine), root, root/'.keel/run', model=model)
        self.assertEqual(result['status'], 'passed', result.get('failure'))
        self.assertEqual(result['budget']['model_calls'], 7)
        expected = ['scout', 'planner', 'implementer', 'verifier', 'critic',
                    'scout', 'planner', 'implementer', 'verifier', 'auditor']
        self.assertEqual(result['orchestration']['completed_nodes'], expected)
        self.assertEqual([row['role'] for row in result['state_machine']['history']], expected)
        self.assertEqual(len(result['plans']), 2)
        self.assertEqual(len(result['verification_attempts']), 2)
        self.assertEqual(result['audit']['changed_files'], ['pkg/actual.py'])
        self.assertIn('return 1', (root/'pkg/wrong.py').read_text())
        self.assertIn('AssertionError', str(model.calls[3]))
        self.assertEqual(result['recovery']['used_actions'], 1)
        observation = json.loads(model.calls[3][1]['content'])
        self.assertIn('+    return 2', str(observation['current_changes']))
        self.assertIn('next_check', result['recovery']['diagnoses'][0])
        self.assertIn('Perform the Critic next_check', str(model.calls[4]))
        return root, result

    def test_saved_failure_enters_critic_then_repairs_with_shared_budget(self):
        root = self.workspace()
        config = self.config()
        config['budget']['max_model_calls'] = 4
        config['continuation_context'] = {
            'verification': [{'returncode': 1, 'stdout': 'AssertionError: saved value is 1', 'stderr': ''}],
            'changes': {'diff': 'saved partial modification'},
            'provenance': {'scope': 'new attempt'}}
        model = self.model([{'action': 'replan', 'reason': 'Inspect saved value'},
                            {'files': ['pkg/actual.py']}, {'locations': ['pkg/actual.py:1']},
                            self.patch('actual', 1, 3)])
        result = run(config, root, root/'.keel/run', model=model)
        self.assertEqual(result['status'], 'passed', result.get('failure'))
        self.assertEqual(result['budget']['model_calls'], 4)
        self.assertEqual(result['state_machine']['history'][0]['role'], 'critic')
        self.assertIn('saved value is 1', str(model.calls[0]))
        self.assertIn('Inspect saved value', str(model.calls[1]))
        self.assertEqual(result['recovery']['used_actions'], 1)

    def test_saved_failure_review_cannot_reset_model_budget(self):
        root = self.workspace()
        config = self.config()
        config['budget']['max_model_calls'] = 1
        config['continuation_context'] = {
            'verification': [{'returncode': 1, 'stdout': 'AssertionError', 'stderr': ''}],
            'changes': {}, 'provenance': {}}
        model = self.model([{'action': 'replan', 'reason': 'Inspect source'}])
        result = run(config, root, root/'.keel/run', model=model)
        self.assertEqual(result['failure']['category'], 'budget_exhausted')
        self.assertEqual(len(model.calls), 1)

    def test_second_diagnosis_receives_previous_hypothesis_and_current_diff(self):
        root = self.workspace()
        responses = [{'files': ['pkg/actual.py']}, {'locations': ['pkg/actual.py:1']},
            self.patch('actual', 1, 2), {'action': 'repair', 'reason': 'Inspect observed wrong value'},
            self.patch('actual', 2, 4), {'action': 'repair', 'reason': 'Earlier correction is disproved'},
            self.patch('actual', 4, 3)]
        model = self.model(responses)
        result = run(self.config(), root, root/'.keel/run', model=model)
        self.assertEqual(result['status'], 'passed', result.get('failure'))
        observation = json.loads(model.calls[5][1]['content'])
        self.assertEqual(len(observation['previous_diagnoses']), 1)
        self.assertIn('+    return 4', str(observation['current_changes']))
        self.assertEqual(len(result['recovery']['diagnoses']), 2)

    def test_progress_feedback_binds_prior_question_to_real_receipts_without_extra_calls(self):
        root = self.workspace()
        config = self.config()
        config['recovery']['monitor_progress'] = True
        model = self.model([{'files': ['pkg/actual.py']}, {'locations': ['pkg/actual.py:1']},
            self.patch('actual', 1, 2), {'action': 'repair', 'reason': 'Inspect observed wrong value'},
            self.patch('actual', 2, 4), {'action': 'repair', 'reason': 'Earlier correction is disproved'},
            self.patch('actual', 4, 3)])
        result = run(config, root, root/'.keel/run', model=model)
        self.assertEqual(result['status'], 'passed', result.get('failure'))
        self.assertEqual(len(model.calls), 7)
        self.assertNotIn('previous_check_observations', json.loads(model.calls[3][1]['content']))
        observed = json.loads(model.calls[5][1]['content'])['previous_check_observations']
        self.assertEqual(observed['question'], result['recovery']['diagnoses'][0]['next_check'])
        self.assertEqual(observed['check_execution'], 'not_established')
        self.assertEqual(observed['verification_comparison']['status'], 'incomparable')
        rows = result['recovery']['progress']['rounds']
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[-1]['terminal_status'], 'passed')
        self.assertTrue(all(row['verification_fact_ids'] for row in rows))

    def test_no_effective_repair_reselects_fresh_source_before_retry(self):
        root = self.workspace()
        model = self.model([{'files': ['pkg/actual.py']}, {'locations': ['pkg/actual.py:1']},
            self.patch('actual', 1, 2), {'action': 'repair', 'reason': 'Inspect wrong value'},
            self.patch('actual', 2, 2), {'locations': ['pkg/actual.py:1']}, self.patch('actual', 2, 3)])
        result = run(self.config(), root, root/'.keel/run', model=model)
        self.assertEqual(result['status'], 'passed', result.get('failure'))
        self.assertIn('previous proposal did not change current source', str(model.calls[5]))
        self.assertIn('return 2', str(model.calls[6]))

    def test_native_replans_wrong_localization_and_preserves_initial_audit_baseline(self):
        self.check_replan('native')

    @unittest.skipUnless(HAS_GRAPH, 'Optional LangGraph dependencies not installed')
    def test_graph_replans_through_real_checkpointed_nodes(self):
        root, result = self.check_replan('langgraph')
        self.assertGreater(result['orchestration']['checkpoints'], 10)
        self.assertTrue((root/'.keel/run/checkpoints.sqlite').is_file())

    def test_critic_can_continue_current_plan_or_stop_explicitly(self):
        for action in ('repair', 'stop'):
            with self.subTest(action=action):
                root = self.workspace()
                responses = [{'files': ['pkg/actual.py']}, {'locations': ['pkg/actual.py:1']},
                             self.patch('actual', 1, 2), {'action': action, 'reason': 'Observed assertion failure'}]
                if action == 'repair':
                    responses.append(self.patch('actual', 2, 3))
                result = run(self.config(), root, root/'.keel/run', model=self.model(responses))
                if action == 'repair':
                    self.assertEqual(result['status'], 'passed', result.get('failure'))
                    self.assertEqual(result['orchestration']['completed_nodes'][4:6], ['critic', 'implementer'])
                else:
                    self.assertEqual(result['failure']['category'], 'recovery_stopped')
                    self.assertEqual(result['orchestration']['completed_nodes'][-1], 'critic')

    def test_global_budget_exhaustion_prevents_critic_or_new_scout_calls(self):
        root = self.workspace()
        config = self.config()
        config['budget']['max_model_calls'] = 3
        model = self.model(self.replan_replies())
        result = run(config, root, root/'.keel/run', model=model)
        self.assertEqual(result['failure']['category'], 'budget_exhausted')
        self.assertEqual(len(model.calls), 3)
        self.assertIn('return 1', (root/'pkg/actual.py').read_text())

    def test_host_write_roots_are_required_before_any_artifact(self):
        root = self.workspace()
        for roots in ([], ['../escape'], ['missing'], [{}]):
            with self.subTest(roots=roots):
                config = self.config()
                config['recovery']['write_roots'] = roots
                with self.assertRaises(ValueError):
                    run(config, root, root/'output')
                self.assertFalse((root/'output').exists())

    def test_replanning_cannot_authorize_source_outside_host_roots(self):
        root = self.workspace()
        config = self.config()
        config['mode'] = 'agent'
        responses = [
            {'final': {'summary': 'wrong module', 'files': ['pkg/wrong.py']}},
            {'final': [{'id': 'first', 'description': 'update', 'files': ['pkg/wrong.py']}]},
            {'tool': 'replace', 'arguments': {'path': 'pkg/wrong.py', 'old': 'return 1', 'new': 'return 2'}},
            {'final': 'updated'},
            {'action': 'replan', 'reason': 'inspect another module'},
            {'final': {'summary': 'outside module', 'files': ['outside.py']}},
            {'final': [{'id': 'second', 'description': 'update', 'files': ['outside.py']}]}]
        model = self.model(responses)
        result = run(config, root, root/'.keel/run', model=model)
        self.assertEqual(result['failure']['category'], 'policy_denied')
        self.assertIn('write_roots', result['failure']['message'])
        self.assertEqual((root/'outside.py').read_text(), 'VALUE = 1\n')
        self.assertEqual(len(model.calls), 7)

    def test_invalid_critic_decision_receives_feedback_before_correct_route(self):
        root = self.workspace()
        responses = [{'files': ['pkg/actual.py']}, {'locations': ['pkg/actual.py:1']},
                     self.patch('actual', 1, 2), {'action': 'declare_success', 'reason': 'unsupported'},
                     {'action': 'repair', 'reason': 'Correct the observed value'}, self.patch('actual', 2, 3)]
        model = self.model(responses)
        result = run(self.config(), root, root/'.keel/run', model=model)
        self.assertEqual(result['status'], 'passed', result.get('failure'))
        self.assertIn('host_decision_error', model.calls[4][1]['content'])
        self.assertEqual(result['recovery']['used_actions'], 2)

    @unittest.skipUnless(HAS_GRAPH, 'Optional LangGraph dependencies not installed')
    def test_revised_plan_requires_second_approval_before_new_writes(self):
        for second_approved in (True, False):
            with self.subTest(approved=second_approved):
                root = self.workspace()
                config = self.config('langgraph')
                config['approval_before_write'] = True
                requests = []
                def approve(request):
                    requests.append(request)
                    self.assertIn('return 1', (root/'pkg/actual.py').read_text())
                    return True if len(requests) == 1 else second_approved
                result = run(config, root, root/'.keel/run', model=self.model(self.replan_replies()), approval=approve)
                self.assertEqual(len(requests), 2)
                self.assertEqual([request['revision'] for request in requests], [0, 1])
                self.assertEqual(result['orchestration']['approval_interruptions'], 2)
                self.assertEqual(result['status'], 'passed' if second_approved else 'failed', result.get('failure'))
                if not second_approved:
                    self.assertIn('return 1', (root/'pkg/actual.py').read_text())
