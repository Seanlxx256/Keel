from contextlib import closing
import json
from pathlib import Path
import tempfile
import unittest

from keel.core import Budget, Ledger, Limits, Trace, InvalidSelection
from keel.models import Reply
from keel.recovery import RecoveryController, CRITIC_QUESTIONS
from keel.workspace import Workspace


class CriticPromptTests(unittest.TestCase):
    def test_all_questions_reach_structured_and_json_object_models_without_extra_calls(self):
        for structured in (True, False):
            with self.subTest(structured=structured), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                with closing(Ledger(root/'ledger.sqlite')) as ledger:
                    ws = Workspace(root, Budget(Limits()), ledger, Trace(root/'trace.jsonl'))
                    controller = RecoveryController({'max_actions': 2}, ws)
                    answer = {'action': 'replan', 'reason': 'A permitted locating check remains',
                        'hypothesis': 'Input conversion may reject whitespace; branch not supplied',
                        'evidence': 'LOCATION: unknown, no call frame. ESTABLISHED: exception only. '
                                    'RULED_OUT: none. UNKNOWN: failing phase.',
                        'previous_attempt_assessment': 'EXECUTION: not established. RESULT: no probe receipt. '
                                                       'UPDATE: hypothesis remains unresolved.',
                        'next_check': 'TARGET: failure report call frame. QUESTION: which call failed? '
                                      'SUPPORT: conversion call fails. REFUTE: a different call fails.'}
                    class Model:
                        calls = 0
                        def respond(self, messages, **kwargs):
                            self.calls += 1; self.messages = messages; self.kwargs = kwargs
                            return Reply(json.dumps(answer), 25)
                    model = Model()
                    if structured:
                        model.complete_json = model.respond
                    else:
                        model.complete = model.respond
                    result = controller.decide(model, 'Investigate conversion', [],
                        [{'returncode': 1, 'timeout': False, 'stdout': 'ValueError: invalid input'}],
                        {'max_context_bytes': 18000})
                    self.assertEqual(result, answer)
                    self.assertEqual(model.calls, 1)
                    self.assertEqual(ws.budget.model_calls, 1)
                    self.assertEqual(ws.budget.tool_calls, 0)
                    prompt = model.messages[0]['content']
                    embedded = json.loads(prompt.split('JSON schema: ', 1)[1])
                    for field, description in CRITIC_QUESTIONS.items():
                        # Same contract is embedded for providers ignoring schemas.
                        self.assertEqual(embedded['properties'][field]['description'], description)
                    self.assertIn('Unknown is allowed', prompt)
                    self.assertIn('exception tail alone', prompt)
                    if structured:
                        self.assertEqual(model.kwargs['schema']['properties']['next_check']['maxLength'], 1000)

    def test_missing_answer_field_is_rejected_before_routing(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with closing(Ledger(root/'ledger.sqlite')) as ledger:
                ws = Workspace(root, Budget(Limits()), ledger, Trace(root/'trace.jsonl'))
                controller = RecoveryController({'max_actions': 2}, ws)
                class Model:
                    def complete_json(self, *args, **kwargs):
                        return Reply(json.dumps({'action': 'replan', 'reason': 'Inspect more'}), 10)
                with self.assertRaises(InvalidSelection):
                    controller.decide(Model(), 'Investigate', [], [], {'max_context_bytes': 18000})
                self.assertEqual(controller.decisions, [])
