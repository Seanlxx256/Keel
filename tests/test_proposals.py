import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from keel.models import Reply
from keel.runtime import run


class ProposalTests(unittest.TestCase):
    def test_token_policy_integration_preserves_shared_accounting(self):
        self.config['agent']['proposal_context_policy']={'model_context_tokens':32768,
            'max_input_tokens':16000,'safety_tokens':256,'max_request_bytes':24000}
        result,_=self.execute([{'path':'app.py','old':'VERSION = 1','new':'VERSION = 2'}])
        self.assertEqual(result['status'],'passed')
        rows=[json.loads(line) for line in (self.root/'.keel/run/trace.jsonl').read_text().splitlines()]
        admitted=next(row for row in rows if row['event']=='proposal_token_admitted')
        self.assertEqual(admitted['estimator'],'utf8_bytes_conservative')
        self.assertEqual(admitted['output_reserved_tokens'],1024)
        self.assertFalse(admitted['provider_exact'])

    def test_explicit_proposal_headroom_is_validated_and_admission_is_traced(self):
        self.config['agent']['proposal_context_hard_bytes']=13200
        result,_=self.execute([{'path':'app.py','old':'VERSION = 1','new':'VERSION = 2'}])
        self.assertEqual(result['status'],'passed')
        rows=[json.loads(line) for line in (self.root/'.keel/run/trace.jsonl').read_text().splitlines()]
        admission=next(row for row in rows if row['event']=='proposal_context_admitted')
        self.assertEqual(admission['soft_limit_bytes'],12000)
        self.assertEqual(admission['hard_limit_bytes'],13200)

    def test_bugfix_policy_rejects_comment_only_before_writes_or_verification(self):
        self.config['agent']['require_python_ast_change']=True
        result,_=self.execute([{'path':'app.py','old':'VERSION = 1',
                               'new':'# clarified\nVERSION = 1'}])
        self.assertIn('comments/formatting', result['failure']['message'])
        self.assertEqual(result['verification'], [])
        self.assertEqual((self.root/'app.py').read_text(),'VERSION = 1\n')

    def test_bugfix_policy_accepts_real_syntax_change(self):
        self.config['agent']['require_python_ast_change']=True
        result,_=self.execute([{'path':'app.py','old':'VERSION = 1','new':'VERSION = 2'}])
        self.assertEqual(result['status'],'passed')

    def test_comment_updates_remain_allowed_without_bugfix_policy(self):
        result,_=self.execute([{'path':'app.py','old':'VERSION = 1',
                               'new':'# clarified\nVERSION = 1'}])
        self.assertNotIn('comments/formatting',result.get('failure',{}).get('message',''))
        self.assertIn('# clarified',(self.root/'app.py').read_text())

    def test_proposal_schema_enumerates_current_evidenced_targets(self):
        from keel.proposals import proposal_request
        evidence = [{'path': 'current.py', 'windows': []}]
        for structured in (True, False):
            messages, schema, _ = proposal_request('Historical target: previous.py',
                ['current.py', 'previous.py'], evidence, {}, structured=structured)
            self.assertEqual(schema['properties']['edits']['items']['properties']['path']['enum'], ['current.py'])
            self.assertEqual(json.loads(messages[1]['content'])['allowed_files'], ['current.py'])
            from keel.decision_guidance import DECISION_QUESTIONS
            self.assertEqual(json.loads(messages[1]['content'])['decision_questions'], DECISION_QUESTIONS)
            for label in ('FACTS', 'ALTERNATIVES', 'CHOICE', 'SUCCESS', 'SWITCH'):
                self.assertIn(label, schema['properties']['summary']['description'])
            if not structured:
                self.assertIn('"enum": ["current.py"]', messages[0]['content'])

    def test_lf_proposal_matches_crlf_source_and_preserves_file_bytes(self):
        (self.root/'app.py').write_bytes(b'VERSION = 1\r\n# untouched\r\n')
        result, _ = self.execute([{'path': 'app.py', 'old': 'VERSION = 1\n',
                                  'new': 'VERSION = 2\nEXTRA = True\n'}])
        self.assertEqual(result['status'], 'passed', result.get('failure'))
        self.assertEqual((self.root/'app.py').read_bytes(),
                         b'VERSION = 2\r\nEXTRA = True\r\n# untouched\r\n')

    def test_crlf_proposal_preserves_lf_source(self):
        (self.root/'app.py').write_bytes(b'VERSION = 1\n# untouched\n')
        result, _ = self.execute([{'path': 'app.py', 'old': 'VERSION = 1\r\n',
                                  'new': 'VERSION = 2\r\n'}])
        self.assertEqual(result['status'], 'passed', result.get('failure'))
        self.assertEqual((self.root/'app.py').read_bytes(),b'VERSION = 2\n# untouched\n')

    def test_newline_alignment_keeps_ambiguity_and_atomic_batch_checks(self):
        before=b'VERSION = 1\r\n# repeated\r\n# repeated\r\n'
        (self.root/'app.py').write_bytes(before)
        result, _ = self.execute([
            {'path':'app.py','old':'VERSION = 1\n','new':'VERSION = 2\n'},
            {'path':'app.py','old':'# repeated\n','new':'# changed\n'}])
        self.assertIn('matched 2 occurrences',result['failure']['message'])
        self.assertEqual((self.root/'app.py').read_bytes(),before)

    def test_newline_only_proposal_is_not_an_effective_change(self):
        before=b'VERSION = 1\r\n'
        (self.root/'app.py').write_bytes(before)
        result, _ = self.execute([{'path':'app.py','old':'VERSION = 1\n','new':'VERSION = 1\r\n'}])
        self.assertIn('no effective changes',result['failure']['message'])
        self.assertEqual((self.root/'app.py').read_bytes(),before)

    def test_mixed_newlines_are_not_guessed_and_content_is_not_fuzzy(self):
        from keel.proposals import source_newline_edit
        old,new='VERSION = 1\n','VERSION = 2\n'
        self.assertEqual(source_newline_edit('VERSION = 1\r\n# mixed\n',old,new),(old,new))
        before=b'VERSION = 1\r\n'
        (self.root/'app.py').write_bytes(before)
        result, _ = self.execute([{'path':'app.py','old':'VERSION  = 1\n','new':new}])
        self.assertIn('matched 0 occurrences',result['failure']['message'])
        self.assertEqual((self.root/'app.py').read_bytes(),before)

    def test_definition_anchor_includes_function_tail_without_fabricating_source(self):
        from keel.proposals import source_evidence, proposal_request
        from keel.core import BudgetExceeded
        text = '# padding\n' * 45 + 'def encode(value):\n' + '    # unchanged\n' * 20 + '    return old_api(value)\n'
        evidence = source_evidence('fixture.py', text, ['def encode'])
        rendered = ''.join(window['text'] for window in evidence['windows'])
        self.assertIn('return old_api(value)', rendered)
        for window in evidence['windows']:
            self.assertEqual(window['text'], ''.join(text.splitlines(keepends=True)[window['start_line']-1:window['end_line']]))
        with self.assertRaises(BudgetExceeded):
            proposal_request('Repair', ['fixture.py'], [evidence], {'max_context_bytes': 100})

    def test_dependency_evidence_reaches_proposal_without_widening_scope(self):
        request = {'distribution': 'fixture', 'version': '1.0', 'symbols': ['portal']}
        self.config['proposal']['dependencies'] = [request]
        evidence = {'distribution': 'fixture', 'version': '1.0', 'records': [{'module': 'fixture.thread', 'symbol': 'portal'}]}
        with patch('keel.dependency_evidence.collect', return_value=[evidence]):
            result, model = self.execute([{'path': 'app.py', 'old': 'VERSION = 1', 'new': 'VERSION = 2'}])
        self.assertEqual(result['status'], 'passed')
        payload = json.loads(model.messages[1]['content'])
        self.assertEqual(payload['installed_dependency_evidence'], [evidence])
        self.assertEqual(payload['allowed_files'], ['app.py'])
    def test_correct_change_with_matching_preservation_entry_is_accepted(self):
        (self.root/'app.py').write_bytes(b'VERSION = 1\n\ndef greeting(name):\n    return "Hello, " + name\n')
        keep = 'def greeting(name):\n    return "Hello, " + name\n'
        result, _ = self.execute([
            {'path': 'app.py', 'old': 'VERSION = 1', 'new': 'VERSION = 2'},
            {'path': 'app.py', 'old': keep, 'new': keep}])
        self.assertEqual(result['status'], 'passed')
        normalization = [fact for fact in result['facts'] if fact['summary'] == 'Validated proposal normalization']
        self.assertEqual(len(normalization), 1)
        self.assertIn('return "Hello, " + name', (self.root/'app.py').read_text())

    def test_noop_only_proposal_is_not_success(self):
        result, _ = self.execute([{'path': 'app.py', 'old': 'VERSION = 1', 'new': 'VERSION = 1'}])
        self.assertEqual(result['failure']['category'], 'model_error')
        self.assertIn('no effective changes', result['failure']['message'])
        self.assertEqual(result['verification'], [])

    def test_fabricated_preservation_entry_still_invalidates_batch(self):
        result, _ = self.execute([
            {'path': 'app.py', 'old': 'VERSION = 1', 'new': 'VERSION = 2'},
            {'path': 'app.py', 'old': 'not in source', 'new': 'not in source'}])
        self.assertEqual(result['failure']['category'], 'model_error')
        self.assertIn('matched 0 occurrences', result['failure']['message'])
        self.assertEqual((self.root/'app.py').read_text(), 'VERSION = 1\n')

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root/'app.py').write_text('VERSION = 1\n')
        self.config = {'mode': 'proposal', 'goal': 'Upgrade VERSION to 2 in app.py',
            'proposal': {'files': ['app.py'], 'queries': ['VERSION']},
            'agent': {'max_context_bytes': 12000}, 'budget': {'max_tokens': 100000},
            'acceptance': [[sys.executable, '-c', 'import app; assert app.VERSION == 2']]}

    def execute(self, edits, callback=None):
        class Model:
            calls = 0
            def complete_json(inner, messages, **kwargs):
                inner.calls += 1
                inner.messages = messages
                self.assertIn('VERSION = 1', json.dumps(messages))
                if callback:
                    callback()
                return Reply(json.dumps({'summary': 'Proposed upgrade', 'edits': edits}), 25)
        model = Model()
        result = run(self.config, self.root, self.root/'.keel/run', model=model)
        return result, model

    def test_one_model_proposal_executes_all_roles_and_independent_acceptance(self):
        result, model = self.execute([{'path': 'app.py', 'old': 'VERSION = 1', 'new': 'VERSION = 2'}])
        self.assertEqual(result['status'], 'passed')
        self.assertEqual(result['mode'], 'proposal')
        self.assertEqual(model.calls, 1)
        self.assertEqual(result['budget']['model_calls'], 1)
        self.assertEqual(result['audit']['changed_files'], ['app.py'])
        self.assertEqual(result['verification'][0]['returncode'], 0)

    def test_entire_sequence_is_checked_before_first_write(self):
        result, model = self.execute([
            {'path': 'app.py', 'old': 'VERSION = 1', 'new': 'VERSION = 2'},
            {'path': 'app.py', 'old': 'not present', 'new': 'anything'}])
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['failure']['category'], 'model_error')
        self.assertEqual((self.root/'app.py').read_text(), 'VERSION = 1\n')

    def test_undeclared_writable_target_is_rejected_without_writes(self):
        (self.root/'other.py').write_text('VERSION = 1\n')
        result, _ = self.execute([{'path': 'other.py', 'old': '1', 'new': '2'}])
        self.assertEqual(result['failure']['category'], 'model_error')
        self.assertIn('outside current evidence scope', result['failure']['message'])
        self.assertEqual((self.root/'other.py').read_text(), 'VERSION = 1\n')

    def test_source_change_during_generation_is_denied(self):
        result, _ = self.execute([{'path': 'app.py', 'old': 'VERSION = 1', 'new': 'VERSION = 2'}],
            callback=lambda: (self.root/'app.py').write_text('VERSION = 3\n'))
        self.assertEqual(result['failure']['category'], 'policy_denied')
        self.assertEqual((self.root/'app.py').read_text(), 'VERSION = 3\n')

    def test_valid_syntax_wrong_answer_still_fails_verifier(self):
        result, _ = self.execute([{'path': 'app.py', 'old': 'VERSION = 1', 'new': 'VERSION = 3'}])
        self.assertEqual(result['failure']['category'], 'verification_failed')

    def test_input_limit_stops_before_model(self):
        self.config['agent']['max_context_bytes'] = 1
        result, model = self.execute([{'path': 'app.py', 'old': '1', 'new': '2'}])
        self.assertEqual(model.calls, 0)
        self.assertEqual(result['budget']['model_calls'], 0)
        self.assertEqual(result['failure']['category'], 'budget_exhausted')

    def test_invalid_python_is_rejected_before_write(self):
        result, _ = self.execute([{'path': 'app.py', 'old': 'VERSION = 1', 'new': 'VERSION = ('}])
        self.assertEqual(result['failure']['category'], 'model_error')
        self.assertEqual((self.root/'app.py').read_text(), 'VERSION = 1\n')

    def test_protected_source_is_rejected_before_model(self):
        (self.root/'tests').mkdir()
        (self.root/'tests/test_app.py').write_text('assert True\n')
        self.config['proposal']['files'] = ['tests/test_app.py']
        result, model = self.execute([])
        self.assertEqual(result['failure']['category'], 'policy_denied')
        self.assertEqual(model.calls, 0)
