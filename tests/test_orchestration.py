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
