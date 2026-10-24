import json
from pathlib import Path
import sys
import tempfile
import unittest
from keel.models import Reply
from keel.runtime import run


class ProposalValidationFeedbackTests(unittest.TestCase):
    def test_duplicate_match_feedback_drives_unique_edit_without_partial_write(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            initial='def left():\n    return 1\n\ndef right():\n    return 1\n'
            (root/'app.py').write_text(initial)
            class Model:
                calls=0
                def complete_json(inner,messages,**kwargs):
                    inner.calls+=1
                    if inner.calls==1:
                        old,new='    return 1','    return 2'
                    else:
                        self.assertEqual((root/'app.py').read_text(),initial)
                        feedback=messages[1]['content']
                        self.assertIn('def left()',feedback)
                        self.assertIn('def right()',feedback)
                        self.assertIn('uniquely identify',feedback)
                        old,new='def right():\n    return 1','def right():\n    return 2'
                    return Reply(json.dumps({'summary':'update right','edits':[{'path':'app.py','old':old,'new':new}]}),10)
            config={'mode':'proposal','goal':'Update right only','proposal':{'files':['app.py'],'queries':['return']},'verification_repair_attempts':1,'budget':{'max_model_calls':2},'acceptance':[[sys.executable,'-B','-c','import app; assert app.left()==1 and app.right()==2']]}
            result=run(config,root,root/'.keel/run',model=Model())
            self.assertEqual(result['status'],'passed')
            self.assertIn('def left():\n    return 1', (root/'app.py').read_text())

    def trial(self, calls=2, policy=False, repeat_bad=False, oversized=False, cap=None):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        (root/'app.py').write_bytes(b'VALUE = 1\nOTHER = 3\n')
        if policy:
            (root/'tests').mkdir()
            (root/'tests/test_app.py').write_bytes(b'VALUE = 1\n')
        class Model:
            def __init__(self):
                self.messages = []
            def complete_json(self, messages, **kwargs):
                self.messages.append(messages)
                bad = len(self.messages) == 1 or repeat_bad
                value = {'summary': 'update', 'edits': [{'path': 'tests/test_app.py' if policy else 'app.py',
                         'old': 'VALUE = 1\n', 'new': 'VALUE = 2' if bad else 'VALUE = 2\n'}]}
                if bad and oversized:
                    value['summary'] = 'invalid response padding ' * 1000
                return Reply(json.dumps(value), 10)
        model = Model()
        config = {'mode': 'proposal', 'goal': 'Update VALUE and preserve OTHER',
            'proposal': {'files': ['app.py'], 'queries': ['VALUE']},
            'verification_repair_attempts': 1, 'budget': {'max_model_calls': calls},
            'acceptance': [[sys.executable, '-B', '-c', 'import app; assert app.VALUE == 2 and app.OTHER == 3']]}
        if cap is not None:
            config['agent'] = {'max_context_bytes': cap}
        result = run(config, root, root/'.keel/run', model=model)
        return result, model, (root/'app.py').read_bytes()

    def test_invalid_syntax_feedback_fixes_batch_against_unchanged_source(self):
        result, model, source = self.trial()
        self.assertEqual(result['status'], 'passed')
        self.assertEqual(result['budget']['model_calls'], 2)
        self.assertIn('Invalid patch proposal:', model.messages[1][1]['content'])
        evidence = json.loads(model.messages[1][1]['content'])['evidence']
        self.assertIn('VALUE = 1', json.dumps(evidence))
        self.assertEqual(source, b'VALUE = 2\nOTHER = 3\n')
        self.assertTrue(any(f['summary'] == 'Proposal rejected before writes' for f in result['facts']))

    def test_budget_exhaustion_does_not_write_or_reset_budget(self):
        result, model, source = self.trial(calls=1)
        self.assertEqual(result['failure']['category'], 'budget_exhausted')
        self.assertEqual(len(model.messages), 1)
        self.assertEqual(source, b'VALUE = 1\nOTHER = 3\n')

    def test_policy_failure_never_retries(self):
        result, model, source = self.trial(policy=True)
        self.assertEqual(result['failure']['category'], 'policy_denied')
        self.assertEqual(len(model.messages), 1)

    def test_repeated_invalid_batch_stops_at_one_retry(self):
        result, model, source = self.trial(repeat_bad=True)
        self.assertEqual(result['failure']['category'], 'model_error')
        self.assertEqual(len(model.messages), 2)
        self.assertEqual(source, b'VALUE = 1\nOTHER = 3\n')

    def test_oversized_rejected_response_is_explicitly_omitted_without_losing_source(self):
        result, model, source = self.trial(oversized=True, cap=4000)
        self.assertEqual(result['status'], 'passed')
        self.assertEqual(len(model.messages), 2)
        payload = json.loads(model.messages[1][1]['content'])
        self.assertIn('proposal_omitted', payload['goal'])
        self.assertIn('proposal_sha256', payload['goal'])
        self.assertNotIn('invalid response padding', payload['goal'])
        self.assertIn('VALUE = 1\nOTHER = 3\n', payload['evidence'][0]['windows'][0]['text'])
        self.assertEqual(source, b'VALUE = 2\nOTHER = 3\n')

    def test_compact_feedback_still_respects_input_cap(self):
        from keel.proposals import proposal_request, source_evidence
        evidence = [source_evidence('app.py', 'VALUE = 1\nOTHER = 3\n', ['VALUE'])]
        _, _, size = proposal_request('Update VALUE and preserve OTHER', ['app.py'], evidence, {})
        result, model, source = self.trial(oversized=True, cap=size)
        self.assertEqual(result['failure']['category'], 'budget_exhausted')
        self.assertEqual(len(model.messages), 1)
        self.assertEqual(source, b'VALUE = 1\nOTHER = 3\n')
