import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from keel.core import Budget, BudgetExceeded, Limits
from examples.run_autonomous_campaign import campaign, solver_config


class CampaignTests(unittest.TestCase):
    def test_candidate_failure_is_retained_and_next_candidate_runs_automatically(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            library = root/'frozen-base'
            (library/'tests').mkdir(parents=True)
            (library/'library.py').write_text('VALUE = 1')
            (library/'tests/test_library.py').write_text('assert True')
            import hashlib
            frozen_sha = hashlib.sha256((library/'tests/test_library.py').read_bytes()).hexdigest()
            candidates = [{'repository': 'org/library', 'number': i, 'title': 'Compatibility',
                           'base_commit': 'a'*40, 'gold_commit': 'b'*40} for i in (1, 2)]
            def collect(repository, fetch, **kwargs):
                for row in candidates:
                    kwargs['on_candidate'](row)
            factory = {'candidate': candidates[1], 'status': 'transition_verified',
                       'images': {'new': 'sha256:'+'c'*64},
                       'recipe': {'new': 'dependency==2.0'},
                       'attempts': [{'cells': {'base_new': {'stdout': 'observed failure'}}}],
                       'test_roots': ['tests'], 'frozen_tests': {'tests/test_library.py': frozen_sha}}
            def solve(config, repo, output, model):
                self.assertNotIn('b'*40, json.dumps(config))
                (repo/'library.py').write_text('VALUE = 2')
                return {'status': 'passed', 'failure': None,
                        'budget': {'model_calls': 2, 'tokens': 100, 'tool_calls': 3}}
            api = Mock()
            api.receipts = []
            with patch('examples.run_autonomous_campaign.GitHub', return_value=api), \
                 patch('examples.run_autonomous_campaign.from_config', return_value=Mock()), \
                 patch('examples.run_autonomous_campaign.implementation_hashes', return_value={}), \
                 patch('examples.run_autonomous_campaign.collect', side_effect=collect), \
                 patch('examples.run_autonomous_campaign.prepare_snapshot', return_value=library), \
                 patch('examples.run_autonomous_campaign.construct', side_effect=[ValueError('unsupported native build'), (factory, {'base': library})]), \
                 patch('examples.run_autonomous_campaign.run', side_effect=solve):
                result = campaign(root, root/'campaign', {}, repositories=['org/library'])
            self.assertEqual(result['status'], 'completed')
            self.assertEqual([r['status'] for r in result['records']], ['candidate_error', 'completed'])
            self.assertEqual(result['counts']['repairs_passed'], 1)
            self.assertIn('unsupported native build', result['records'][0]['error'])
            self.assertEqual(result['budget']['model_calls'], 2)
            self.assertTrue((root/'campaign/collected-repo-1.jsonl').is_file())
            self.assertEqual((library/'library.py').read_text(), 'VALUE = 1')

    def test_solver_cannot_get_an_extra_call_after_campaign_budget_exhaustion(self):
        budget = Budget(Limits(max_model_calls=1))
        budget.model_calls = 1
        with self.assertRaises(BudgetExceeded):
            solver_config({}, {}, [], budget, 24000)
