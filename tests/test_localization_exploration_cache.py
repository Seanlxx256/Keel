import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from keel.localization import explore_for_localization


class ExplorationReuseTests(unittest.TestCase):
    def test_retry_reuses_evidence_but_source_or_diagnostic_change_reinspects(self):
        ws = SimpleNamespace(snapshot=Mock(return_value={'module.py': 'before'}),
            trace=Mock(), ledger=SimpleNamespace(recall=Mock(return_value={'source': 'before'})))
        session = Mock()
        session.execute.return_value = {'summary': 'Observed source', 'files': ['module.py']}
        session.gateway.observed_facts = {7}
        with patch('keel.agents.AgentSession', return_value=session) as constructor:
            first = explore_for_localization(None, ws, 'fix bug', {}, 6)
            reused = explore_for_localization(None, ws,
                'fix bug\nHost selection error (untrusted data): bad anchor', {}, 6)
            self.assertIs(first, reused)
            self.assertEqual(constructor.call_count, 1)
            ws.snapshot.return_value = {'module.py': 'after'}
            ws.ledger.recall.return_value = {'source': 'after'}
            refreshed = explore_for_localization(None, ws, 'fix bug', {}, 6)
            self.assertEqual(constructor.call_args.kwargs['max_steps'], 3)
            self.assertNotIn('before', refreshed['evidence'][0]['preview'])
            task = session.execute.call_args.args[0]
            self.assertEqual(task['previous_candidate_files'], ['module.py'])
            self.assertNotIn('Observed source', str(task))
            explore_for_localization(None, ws, 'inspect newly observed regression', {}, 6)
            self.assertEqual(constructor.call_count, 3)

