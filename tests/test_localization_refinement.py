import json
from pathlib import Path
import sys
import tempfile
import unittest

from keel.models import Reply
from keel.runtime import run


class RefinementTests(unittest.TestCase):
    def trial(self, refine=True, calls=4):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        source = '# header\n'*45+'class Large:\n    def value(self):\n        return 1\n'+''.join(
            f'    def unrelated_{i}(self):\n        return "'+'x'*150+'"\n' for i in range(100))
        (root/'module.py').write_text(source)
        class Model:
            def __init__(self):
                self.messages = []
            def complete_json(self, messages, **kwargs):
                self.messages.append(messages)
                count = len(self.messages)
                if count == 1:
                    value = {'files': ['module.py']}
                elif count == 2 or not refine:
                    value = {'locations': ['module.py:46']}
                elif count == 3:
                    value = {'locations': ['module.py:47']}
                else:
                    value = {'edits': [{'path': 'module.py', 'old': 'return 1', 'new': 'return 2'}], 'summary': 'change'}
                return Reply(json.dumps(value), 10)
        model = Model()
        config = {'mode': 'localized-proposal', 'goal': 'Make Large.value return 2',
                  'budget': {'max_model_calls': calls}, 'agent': {'max_context_bytes': 12000},
                  'acceptance': [[sys.executable, '-B', '-c', 'import module; assert module.Large().value() == 2']]}
        result = run(config, root, root/'.keel/run', model=model)
        return result, model, (root/'module.py').read_text(), source

    def test_oversized_class_is_refined_to_complete_method(self):
        result, model, after, before = self.trial()
        self.assertEqual(result['status'], 'passed')
        self.assertEqual(result['budget']['model_calls'], 4)
        catalog = json.loads(model.messages[1][1]['content'])['structure'][0]
        self.assertGreater(catalog['definition_bytes'][0], 12000)
        feedback = json.loads(model.messages[2][1]['content'])
        self.assertIn('capacity_error', feedback)
        patch = json.loads(model.messages[3][1]['content'])
        self.assertIn('return 1', json.dumps(patch['evidence']))
        self.assertNotIn('unrelated_99', json.dumps(patch['evidence']))
        self.assertIn('unrelated_99', after)

    def test_repeated_oversize_stops_without_writes_or_unbounded_refinement(self):
        result, model, after, before = self.trial(refine=False)
        self.assertEqual(result['failure']['category'], 'budget_exhausted')
        self.assertEqual(len(model.messages), 3)
        self.assertEqual(after, before)

    def test_refinement_uses_original_model_budget(self):
        result, model, after, before = self.trial(calls=2)
        self.assertEqual(result['failure']['category'], 'budget_exhausted')
        self.assertEqual(len(model.messages), 2)
        self.assertEqual(after, before)
