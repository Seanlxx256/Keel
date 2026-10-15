import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from keel.core import Budget, Limits, PolicyDenied
from keel.orchestration import execute, PHASES
from keel.runtime import run

HAS_GRAPH = importlib.util.find_spec('langgraph') is not None


class OrchestrationTests(unittest.TestCase):
    def test_native_failure_routes_to_critic_without_later_stages(self):
        seen = []
        result = {'failure': None}
        stages = {name: lambda name=name: seen.append(name) for name in (*PHASES, 'critic')}
        def fail():
            seen.append('planner')
            raise PolicyDenied('scope')
        stages['planner'] = fail
        def error(exc):
            result['failure'] = {'category': 'policy_denied'}
        report = execute('native', stages, result, error, None, Budget(Limits()))
        self.assertEqual(seen, ['scout', 'planner', 'critic'])
        self.assertEqual(report['completed_nodes'], seen)

    def test_missing_adapter_dependency_fails_before_artifacts_or_edits(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / 'run'
            config = {'goal': 'Inspect', 'orchestrator': 'langgraph',
                      'acceptance': [[sys.executable, '-c', 'pass']]}
            with patch('keel.adapters.langgraph.require_dependencies', side_effect=ValueError('missing langgraph')):
                with self.assertRaisesRegex(ValueError, 'missing langgraph'):
                    run(config, root, output)
            self.assertFalse(output.exists())

    @unittest.skipUnless(HAS_GRAPH, 'Optional LangGraph dependencies are not installed')
    def test_real_stategraph_parity_and_checkpoint_contents(self):
        from langgraph.checkpoint.sqlite import SqliteSaver
        import sqlite3
        from contextlib import closing
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            results = {}
            for engine in ['native', 'langgraph']:
                repo = root / engine
                repo.mkdir()
                (repo / 'app.py').write_text('VERSION = 1\n')
                config = {'goal': 'Upgrade', 'orchestrator': engine,
                    'work_items': [{'id': 'edit', 'edits': [{'path': 'app.py', 'old': 'VERSION = 1', 'new': 'VERSION = 2'}]}],
                    'acceptance': [[sys.executable, '-c', 'import app; assert app.VERSION == 2']]}
                output = repo / '.keel' / 'run'
                result = run(config, repo, output)
                self.assertEqual(result['status'], 'passed', result)
                self.assertEqual(result['orchestration']['completed_nodes'], list(PHASES))
                results[engine] = result
                if engine == 'langgraph':
                    self.assertGreater(result['orchestration']['checkpoints'], 5)
                    with closing(sqlite3.connect(output / 'checkpoints.sqlite', check_same_thread=False)) as connection:
                        saved = SqliteSaver(connection).get_tuple({'configurable': {'thread_id': output.name}})
                        values = saved.checkpoint['channel_values']
                        self.assertEqual(values['completed'], list(PHASES))
                        self.assertEqual(values['budget']['tool_calls'], result['budget']['tool_calls'])
                        self.assertNotIn('messages', values)
                        self.assertNotIn('originals', values)
            self.assertEqual(results['native']['audit'], results['langgraph']['audit'])
            self.assertEqual(results['native']['orchestration']['completed_nodes'], results['langgraph']['orchestration']['completed_nodes'])

    @unittest.skipUnless(HAS_GRAPH, 'Optional LangGraph dependencies are not installed')
    def test_real_graph_executes_agent_sessions_with_shared_ledger(self):
        from keel.models import Reply
        class Model:
            def __init__(self):
                self.actions = iter([
                    {"tool": "read_file", "arguments": {"path": "app.py"}},
                    {"final": {"summary": "Upgrade version", "files": ["app.py"]}},
                    {"final": [{"id": "edit", "description": "Set VERSION to 2", "files": ["app.py"]}]},
                    {"tool": "read_file", "arguments": {"path": "app.py"}},
                    {"tool": "replace", "arguments": {"path": "app.py", "old": "VERSION = 1", "new": "VERSION = 2"}},
                    {"final": "Updated version"},
                ])
            def complete(self, *args, **kwargs):
                return Reply(json.dumps(next(self.actions)), 10)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'app.py').write_text('VERSION = 1\n')
            result = run({'goal': 'Upgrade', 'mode': 'agent', 'orchestrator': 'langgraph',
                          'context_handoff': True, 'budget': {'max_tokens': 100000},
                          'acceptance': [[sys.executable, '-c', 'import app; assert app.VERSION == 2']]},
                         root, root / '.keel' / 'run', model=Model())
            self.assertEqual(result['status'], 'passed', result)
            self.assertEqual(result['budget']['model_calls'], 6)
            self.assertEqual(result['memory']['handed_off_facts'], 2)

    @unittest.skipUnless(HAS_GRAPH, 'Optional LangGraph dependencies are not installed')
    def test_real_graph_policy_failure_routes_once_to_critic(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'app.py').write_text('VERSION = 1\n')
            config = {'goal': 'Denied', 'orchestrator': 'langgraph',
                'work_items': [{'id': 'bad', 'edits': [{'path': 'tests/protected.py', 'old': '1', 'new': '2'}]}],
                'acceptance': [[sys.executable, '-c', 'pass']]}
            result = run(config, root, root / '.keel' / 'run')
            self.assertEqual(result['failure']['category'], 'policy_denied')
            self.assertEqual(result['orchestration']['completed_nodes'], ['scout', 'planner', 'critic'])
            self.assertEqual(sum(f['role'] == 'critic' and f['kind'] == 'failed_attempt' for f in result['facts']), 1)
            self.assertEqual((root / 'app.py').read_text(), 'VERSION = 1\n')


@unittest.skipUnless(HAS_GRAPH, 'Optional LangGraph dependencies are not installed')
class ApprovalTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        (self.root / 'app.py').write_text('VERSION = 1\n')
        self.output = self.root / '.keel' / 'run'
        self.config = {'goal': 'Upgrade', 'orchestrator': 'langgraph', 'approval_before_write': True,
                      'work_items': [{'id': 'edit', 'edits': [{'path': 'app.py', 'old': 'VERSION = 1', 'new': 'VERSION = 2'}]}],
                      'acceptance': [[sys.executable, '-c', 'import app; assert app.VERSION == 2']]}

    def execute(self, callback):
        return run(self.config, self.root, self.output, approval=callback)

    def test_interrupt_precedes_writes_and_resume_does_not_replay_stages(self):
        def approve(request):
            self.assertEqual((self.root / 'app.py').read_text(), 'VERSION = 1\n')
            self.assertEqual(request['files'], ['app.py'])
            self.assertTrue((self.output / 'checkpoints.sqlite').is_file())
            events = [json.loads(line) for line in (self.output / 'trace.jsonl').read_text().splitlines()]
            self.assertFalse(any(e['event'] == 'item_started' for e in events))
            return True
        result = self.execute(approve)
        self.assertEqual(result['status'], 'passed', result)
        self.assertEqual(result['approval']['status'], 'approved')
        self.assertEqual(result['orchestration']['approval_interruptions'], 1)
        events = [json.loads(line) for line in (self.output / 'trace.jsonl').read_text().splitlines()]
        for event in ['plan_ready', 'item_started', 'item_completed', 'command_started', 'approval_decided', 'approval_resumed']:
            self.assertEqual(sum(e['event'] == event for e in events), 1, event)
        self.assertEqual(result['budget']['tool_calls'], 3)

    def test_denial_and_non_boolean_decisions_never_write(self):
        result = self.execute(lambda request: False)
        self.assertEqual(result['failure']['category'], 'policy_denied')
        self.assertEqual((self.root / 'app.py').read_text(), 'VERSION = 1\n')
        self.assertFalse(result['verification'])
        self.assertEqual(result['orchestration']['completed_nodes'], ['scout', 'planner', 'approval', 'critic'])
        self.output = self.root / '.keel' / 'invalid'
        result = self.execute(lambda request: 'yes')
        self.assertEqual(result['failure']['category'], 'execution_error')
        self.assertEqual((self.root / 'app.py').read_text(), 'VERSION = 1\n')

    def test_changed_workspace_invalidates_approval(self):
        def change(request):
            (self.root / 'app.py').write_text('VERSION = 77\n')
            return True
        result = self.execute(change)
        self.assertEqual(result['failure']['category'], 'policy_denied')
        self.assertIn('Workspace changed', result['failure']['message'])
        self.assertEqual((self.root / 'app.py').read_text(), 'VERSION = 77\n')
        self.assertFalse(result['verification'])

    def test_changed_plan_invalidates_approval(self):
        def change(request):
            self.config['work_items'][0]['edits'][0]['new'] = 'VERSION = 9'
            return True
        result = self.execute(change)
        self.assertEqual(result['failure']['category'], 'policy_denied')
        self.assertEqual((self.root / 'app.py').read_text(), 'VERSION = 1\n')

    def test_tool_budget_is_not_reset_after_resume(self):
        self.config.update(queries=['VERSION'], budget={'max_tool_calls': 2})
        def approve(request):
            self.assertEqual(request['budget']['tool_calls'], 1)
            return True
        result = self.execute(approve)
        self.assertEqual(result['failure']['category'], 'budget_exhausted')
        self.assertEqual(result['budget']['tool_calls'], 2)
        self.assertEqual((self.root / 'app.py').read_text(), 'VERSION = 1\n')

    def test_budget_expired_while_waiting_refuses_resume(self):
        expired = [False]
        original = Budget.remaining.fget
        def approve(request):
            expired[0] = True
            return True
        with patch.object(Budget, 'remaining', property(lambda budget: 0 if expired[0] else original(budget))):
            result = self.execute(approve)
        self.assertEqual(result['failure']['category'], 'budget_exhausted')
        self.assertEqual((self.root / 'app.py').read_text(), 'VERSION = 1\n')

    def test_approval_requires_explicit_host_callback(self):
        with self.assertRaisesRegex(ValueError, 'callback'):
            run(self.config, self.root, self.output)
        self.assertFalse(self.output.exists())

    def test_model_calls_and_tokens_are_preserved_across_approval(self):
        from keel.models import Reply
        from types import SimpleNamespace
        actions = iter([
            {"tool": "read_file", "arguments": {"path": "app.py"}},
            {"final": {"summary": "Upgrade version", "files": ["app.py"]}},
            {"final": [{"id": "edit", "description": "Set VERSION to 2", "files": ["app.py"]}]},
            {"tool": "read_file", "arguments": {"path": "app.py"}},
            {"tool": "replace", "arguments": {"path": "app.py", "old": "VERSION = 1", "new": "VERSION = 2"}},
            {"final": "Updated version"},
        ])
        model = SimpleNamespace(complete=lambda *args, **kwargs: Reply(json.dumps(next(actions)), 10))
        config = {key: value for key, value in self.config.items() if key != 'work_items'}
        config.update(mode='agent', budget={'max_tokens': 100000})
        def approve(request):
            self.assertEqual(request['budget']['model_calls'], 3)
            self.assertEqual(request['budget']['tokens'], 30)
            return True
        result = run(config, self.root, self.output, model=model, approval=approve)
        self.assertEqual(result['status'], 'passed', result)
        self.assertEqual(result['budget']['model_calls'], 6)
        self.assertEqual(result['budget']['tokens'], 60)
