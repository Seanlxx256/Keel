import json
from pathlib import Path
import sys
import tempfile
import unittest
from keel.models import Reply
from keel.runtime import run


class Model:
    def __init__(self, scope):
        self.scope, self.messages = scope, []

    def complete_json(self, messages, **kwargs):
        self.messages.append(messages)
        value = self.scope if len(self.messages) == 1 else {
            'edits': [{'path': 'module.py', 'old': 'return 1', 'new': 'return 2'}], 'summary': 'Update version'}
        return Reply(json.dumps(value), 100)


class LocalizedProposalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root/'module.py').write_bytes(b'def version():\n    return 1\n')
        self.config = {'mode': 'localized-proposal', 'goal': 'Make version return 2',
            'budget': {'max_tool_calls': 30, 'max_model_calls': 3, 'max_tokens': 30000},
            'agent': {'max_context_bytes': 12000},
            'acceptance': [[sys.executable, '-c', 'import module; assert module.version() == 2']]}

    def test_model_localizes_then_existing_proposal_verifier_and_auditor_execute(self):
        model = Model({'files': ['module.py'], 'queries': ['def version']})
        result = run(self.config, self.root, self.root/'.keel/run', model=model)
        self.assertEqual(result['status'], 'passed')
        self.assertEqual(result['budget']['model_calls'], 2)
        self.assertEqual(result['budget']['tokens'], 200)
        self.assertEqual(len(model.messages), 2)
        self.assertIn('symbols', json.loads(model.messages[0][1]['content'])['structure'][0])
        patch_input = json.loads(model.messages[1][1]['content'])
        self.assertEqual(patch_input['allowed_files'], ['module.py'])
        self.assertIn('return 1', patch_input['evidence'][0]['windows'][0]['text'])
        self.assertEqual(result['verification'][0]['returncode'], 0)

    def test_invalid_localization_never_reaches_patch_call(self):
        for index, scope in enumerate([
            {'files': ['../outside.py'], 'queries': ['version']},
            {'files': ['module.py'], 'queries': ['missing anchor']},
            {'files': ['module.py'], 'queries': ['version'], 'extra': True}]):
            with self.subTest(scope=scope):
                model = Model(scope)
                result = run(self.config, self.root, self.root/f'.keel/run-{index}', model=model)
                self.assertEqual(result['status'], 'failed')
                self.assertEqual(result['failure']['stage'], 'scout')
                self.assertEqual(len(model.messages), 1)
                self.assertIn('return 1', (self.root/'module.py').read_text())

    def test_operator_scope_is_rejected_and_context_cap_cannot_silently_truncate(self):
        with self.assertRaises(ValueError):
            run({**self.config, 'proposal': {'files': ['module.py'], 'queries': ['version']}},
                self.root, self.root/'.keel/invalid')
        model = Model({})
        result = run({**self.config, 'agent': {'max_context_bytes': 20}},
            self.root, self.root/'.keel/capped', model=model)
        self.assertEqual(result['failure']['category'], 'budget_exhausted')
        self.assertEqual(model.messages, [])
