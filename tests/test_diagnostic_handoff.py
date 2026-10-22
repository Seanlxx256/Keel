from contextlib import closing
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from keel.core import Budget, BudgetExceeded, InvalidSelection, Ledger, Limits, RecoveryStopped, Trace
from keel.diagnostic_handoff import observation, validate_review, citation_matches
from keel.models import Reply
from keel.recovery import RecoveryController
from keel.workspace import Workspace


class HandoffTests(unittest.TestCase):
    def test_aligned_cannot_request_replacement_even_when_it_repeats_current_scope(self):
        catalog = [{'evidence_id': 's0', 'path': 'module.py', 'text': 'return value'}]
        value = {'verdict': 'aligned', 'reason': 'The selected source contains the operation',
                 'answer': 'Inspect the selected operation',
                 'citations': [{'evidence_id': 's0', 'quote': 'return value'}],
                 'replacement_files': ['module.py']}
        with self.assertRaisesRegex(InvalidSelection, 'replacement_files='):
            validate_review(value, catalog, ['module.py'], ['module.py'])
        value['replacement_files'] = []
        self.assertIs(validate_review(value, catalog, ['module.py'], ['module.py']), value)

    def test_only_line_ending_differences_are_accepted_and_reported(self):
        catalog=[{'evidence_id':'s0','path':'render.py','text':'def render(value):\r\n    return str(value)\r\n'}]
        value={'verdict':'aligned','reason':'Inspect conversion','answer':'render converts',
            'citations':[{'evidence_id':'s0','quote':'def render(value):\n    return str(value)'}], 'replacement_files':[]}
        self.assertIs(validate_review(value,catalog,['render.py'],['render.py']),value)
        self.assertEqual(citation_matches(value,catalog)[0]['match'],'line_endings_only')
        for quote in ['def render(value):\n  return str(value)', 'def render(value):\n    return int(value)',
                      '"def render(value):"', 'def render(value):\n\treturn str(value)']:
            with self.subTest(quote=quote):
                value['citations'][0]['quote']=quote
                with self.assertRaises(InvalidSelection): validate_review(value,catalog,['render.py'],['render.py'])

    def fixture(self, root, ledger):
        (root/'core').mkdir(); (root/'tests').mkdir(); (root/'.keel').mkdir()
        (root/'core/render.py').write_text('def render(value):\n    return str(value)\n')
        (root/'helpers.py').write_text('def helper(value):\n    return value\n')
        (root/'tests/test_render.py').write_text('def test_render():\n    assert False\n')
        ws = Workspace(root, Budget(Limits(max_tokens=100000)), ledger, Trace(root/'.keel/trace.jsonl'))
        controller = RecoveryController({'strategy': 'adaptive', 'max_actions': 6,
            'write_roots': ['.'], 'diagnostic_handoff': True}, ws)
        controller.current_decision = {'next_check': 'TARGET: core/render.py::render and tests/test_render.py. QUESTION: inspect render before changing helpers.',
                                       'hypothesis': 'Rendering may change a value'}
        return controller

    def scope(self, root, name):
        return {'files': [name], 'locations': {name: [1]},
                'source_sha256': {name: hashlib.sha256((root/name).read_bytes()).hexdigest()}}

    def test_dropped_target_is_observed_without_giving_test_write_permission(self):
        with tempfile.TemporaryDirectory() as temp, closing(Ledger(Path(temp)/'facts.sqlite')) as ledger:
            root = Path(temp)/'repo'; root.mkdir(); controller = self.fixture(root, ledger)
            view = observation(controller.ws, controller.current_decision, self.scope(root, 'helpers.py'))
            self.assertIn('core/render.py', view['referenced_paths_not_selected'])
            self.assertIn('tests/test_render.py', view['referenced_read_paths'])
            self.assertEqual(view['check_execution'], 'not_established')

    def test_redirect_relocalizes_before_returning_scope_and_preserves_source(self):
        with tempfile.TemporaryDirectory() as temp, closing(Ledger(Path(temp)/'facts.sqlite')) as ledger:
            root = Path(temp)/'repo'; root.mkdir(); controller = self.fixture(root, ledger)
            class Model:
                calls = []
                def complete_json(self, messages, **kwargs):
                    data = json.loads(messages[1]['content']); self.calls.append(data)
                    target = next(r for r in data['source_evidence'] if r['path'] == 'core/render.py')
                    first = len(self.calls) == 1
                    return Reply(json.dumps({'verdict': 'redirect' if first else 'aligned',
                        'reason': 'The requested rendering target needs inspection', 'answer': 'The source shows render handles serialization',
                        'citations': [{'evidence_id': target['evidence_id'], 'quote': 'def render'}],
                        'replacement_files': ['core/render.py'] if first else []}), 10)
            model = Model(); before = controller.ws.snapshot()
            with patch('keel.localization.localize', side_effect=[self.scope(root, 'helpers.py'), self.scope(root, 'core/render.py')]) as localize:
                result = controller.localize(model, 'Check rendering', {'max_context_bytes': 24000},
                    allowed_files=['helpers.py', 'core/render.py'])
            self.assertEqual(result['files'], ['core/render.py'])
            self.assertEqual(localize.call_args_list[1].kwargs['allowed_files'], ['core/render.py'])
            self.assertEqual(before, controller.ws.snapshot())
            self.assertEqual(controller.ws.budget.model_calls, 2)
            self.assertNotIn('tests/test_render.py', model.calls[0]['replacement_choices'])
            self.assertIn('aligned requires replacement_files=[]', model.calls[0]['instruction'])
            self.assertIn('blocked requires replacement_files=[]', model.calls[0]['instruction'])
            self.assertIn('_handoff_evidence', result)
            self.assertEqual(controller.handoff_reviews[0]['verdict'], 'redirect')

    def test_false_citation_or_readonly_redirect_is_rejected(self):
        catalog = [{'evidence_id': 's0', 'path': 'module.py', 'text': 'return value'}]
        value = {'verdict': 'redirect', 'reason': 'inspect', 'answer': 'unknown',
                 'citations': [{'evidence_id': 's0', 'quote': 'invented'}], 'replacement_files': ['module.py']}
        with self.assertRaises(InvalidSelection): validate_review(value, catalog, ['module.py'], ['other.py'])
        value['citations'][0]['quote'] = 'return value'; value['replacement_files'] = ['tests/test_module.py']
        with self.assertRaises(InvalidSelection): validate_review(value, catalog, ['module.py'], ['other.py'])

    def test_blocked_handoff_stops_without_source_write(self):
        with tempfile.TemporaryDirectory() as temp, closing(Ledger(Path(temp)/'facts.sqlite')) as ledger:
            root = Path(temp)/'repo'; root.mkdir(); controller = self.fixture(root, ledger); before = controller.ws.snapshot()
            class Model:
                def complete_json(self, messages, **kwargs):
                    row = json.loads(messages[1]['content'])['source_evidence'][0]
                    return Reply(json.dumps({'verdict': 'blocked', 'reason': 'Runtime observation unavailable', 'answer': 'Source alone cannot decide',
                        'citations': [{'evidence_id': row['evidence_id'], 'quote': row['text'][:10]}], 'replacement_files': []}), 10)
            with patch('keel.localization.localize', return_value=self.scope(root, 'helpers.py')):
                with self.assertRaises(RecoveryStopped):
                    controller.localize(Model(), 'Check', {'max_context_bytes': 24000}, allowed_files=['helpers.py', 'core/render.py'])
            self.assertEqual(before, controller.ws.snapshot())

    def test_redirect_does_not_reset_shared_model_budget(self):
        with tempfile.TemporaryDirectory() as temp, closing(Ledger(Path(temp)/'facts.sqlite')) as ledger:
            root = Path(temp)/'repo'; root.mkdir(); controller = self.fixture(root, ledger)
            controller.ws.budget.limits.max_model_calls = 1
            class Model:
                calls = 0
                def complete_json(self, messages, **kwargs):
                    self.calls += 1
                    row = next(r for r in json.loads(messages[1]['content'])['source_evidence'] if r['path']=='core/render.py')
                    return Reply(json.dumps({'verdict': 'redirect', 'reason': 'Inspect requested target', 'answer': 'render handles conversion',
                        'citations': [{'evidence_id': row['evidence_id'], 'quote': 'def render'}],
                        'replacement_files': ['core/render.py']}), 10)
            model = Model()
            with patch('keel.localization.localize', side_effect=[self.scope(root,'helpers.py'),self.scope(root,'core/render.py')]):
                with self.assertRaises(BudgetExceeded):
                    controller.localize(model,'Check',{'max_context_bytes':24000},allowed_files=['helpers.py','core/render.py'])
            self.assertEqual(model.calls,1)

    def test_runtime_redirects_wrong_scope_before_implementer_writes(self):
        import sys
        from keel.runtime import run
        with tempfile.TemporaryDirectory() as temp, closing(Ledger(Path(temp)/'facts.sqlite')) as ledger:
            root=Path(temp)/'repo';root.mkdir();self.fixture(root,ledger)
            helper_before=(root/'helpers.py').read_bytes()
            class Model:
                def complete_json(self,messages,**kwargs):
                    fields=kwargs['schema']['properties'];data=json.loads(messages[1]['content'])
                    if 'action' in fields:
                        value={'action':'replan','reason':'Inspect rendering','hypothesis':'Conversion needs checking',
                            'evidence':'Observed failed check','next_check':'TARGET: core/render.py::render. QUESTION: inspect render conversion.',
                            'previous_attempt_assessment':'No current probe yet'}
                    elif 'handoff' in data:
                        source=next(r for r in data['source_evidence'] if r['path']=='core/render.py')
                        redirect=data['handoff']['selected_edit_paths']==['helpers.py']
                        value={'verdict':'redirect' if redirect else 'aligned','reason':'Inspect conversion target',
                            'answer':'render returns the converted value','citations':[{'evidence_id':source['evidence_id'],'quote':'def render'}],
                            'replacement_files':['core/render.py'] if redirect else []}
                    else:
                        value={'summary':'Uppercase conversion','edits':[{'path':'core/render.py',
                            'old':'return str(value)','new':'return str(value).upper()'}]}
                        if 'diagnostic_check' in data:
                            source=data['evidence'][0]
                            value['diagnostic_answer']={'question':data['diagnostic_check']['next_check'],
                                'status':'source_answer','answer':'render returns str without uppercasing; change its returned value',
                                'hypothesis_update':'supported','missing_evidence':'',
                                'citations':[{'path':source['path'],'sha256':source['sha256'],'quote':'return str(value)'}]}
                    return Reply(json.dumps(value),10)
            config={'mode':'localized-proposal','goal':'Uppercase the rendered value',
                'recovery':{'strategy':'adaptive','max_actions':6,'write_roots':['.'],'diagnostic_handoff':True},
                'continuation_context':{'verification':[{'returncode':1,'stdout':'AssertionError','stderr':''}],
                                        'changes':{},'provenance':{}},
                'agent':{'max_context_bytes':24000},'budget':{'max_tokens':100000},
                'acceptance':[[sys.executable,'-B','-c',"from core.render import render; assert render('x') == 'X'"]]}
            with patch('keel.localization.localize',side_effect=[self.scope(root,'helpers.py'),self.scope(root,'core/render.py')]):
                result=run(config,root,root/'.keel/run',model=Model())
            self.assertEqual(result['status'],'passed')
            self.assertEqual((root/'helpers.py').read_bytes(),helper_before)
            self.assertEqual(result['plans'][0]['items'][0]['files'],['core/render.py'])
            self.assertEqual([row['verdict'] for row in result['recovery']['handoff_reviews']],['redirect','aligned'])
