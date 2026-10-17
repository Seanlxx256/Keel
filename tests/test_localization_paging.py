import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from keel.core import Budget, BudgetExceeded, Limits
from keel.localization import select
from keel.models import Reply


class PagingTests(unittest.TestCase):
    def test_all_path_pages_are_seen_and_each_request_fits(self):
        paths = [f'package/subpackage_{i}/module_with_a_long_name.py' for i in range(100)]
        workspace = SimpleNamespace(budget=Budget(Limits(max_model_calls=100, max_tokens=1000000)),
                                    trace=Mock(), ledger=Mock())
        seen, sizes = set(), []
        class Model:
            def complete_json(self, messages, schema, **kwargs):
                sizes.append(len(json.dumps(messages).encode()) + len(json.dumps(schema).encode()))
                payload = json.loads(messages[1]['content'])
                seen.update(payload['paths'])
                return Reply(json.dumps({'files': [payload['paths'][-1]]}), 10)
        selected = select(Model(), workspace, 'Locate repair', {'max_context_bytes': 1800},
                          stage='files', data={'paths': paths}, keys=('files',), instruction='Select files.')
        self.assertEqual(seen, set(paths))
        self.assertGreater(len(sizes), 1)
        self.assertTrue(all(size <= 1800 for size in sizes))
        self.assertIn(selected['files'][0], paths)

    def test_paging_shares_model_budget(self):
        workspace = SimpleNamespace(budget=Budget(Limits(max_model_calls=1, max_tokens=1000000)),
                                    trace=Mock(), ledger=Mock())
        model = Mock()
        def reply(messages, **kwargs):
            payload = json.loads(messages[1]['content'])
            return Reply(json.dumps({'files': [payload['paths'][0]]}), 10)
        model.complete_json.side_effect = reply
        with self.assertRaises(BudgetExceeded):
            select(model, workspace, 'repair', {'max_context_bytes': 1500}, stage='files',
                   data={'paths': ['package/'+'x'*100+str(i)+'.py' for i in range(100)]},
                   keys=('files',), instruction='Select files.')
        self.assertEqual(model.complete_json.call_count, 1)
