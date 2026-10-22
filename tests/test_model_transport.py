import http.client
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from keel.campaign_reporting import FrozenModel
from keel.core import Budget, BudgetExceeded, Limits, ModelError, ModelTransportError
from keel.models import Reply


class TransportTests(unittest.TestCase):
    def invoke(self, replies, *, calls=4, tokens=20000, retries=1):
        class Provider:
            requests = []
            def complete_json(self, messages, **kwargs):
                self.requests.append((messages, kwargs))
                reply = replies[len(self.requests)-1]
                if isinstance(reply, Exception):
                    raise reply
                return reply
        provider = Provider()
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        transcript = Path(temp.name)/'calls.jsonl'
        model = FrozenModel(provider, lambda: None, transcript, transport_retries=retries)
        budget = Budget(Limits(max_model_calls=calls, max_tokens=tokens))
        model.bind_budget(budget)
        budget.allow_model(100, 100)
        return provider, model, budget, transcript

    def dispatch(self, model):
        with patch('keel.model_transport.time.sleep'):
            return model.complete_json([{'role': 'user', 'content': 'inspect'}],
                                       schema={'type': 'object'}, timeout=30, max_output=100)

    def test_disconnect_retries_same_messages_and_records_unknown_usage(self):
        provider, model, budget, transcript = self.invoke([ModelTransportError('disconnected'), Reply('{}', 15)])
        reply = self.dispatch(model); budget.charge_tokens(reply.tokens)
        self.assertEqual(len(provider.requests), 2)
        self.assertEqual(provider.requests[0][0], provider.requests[1][0])
        self.assertEqual(budget.model_calls, 2)
        self.assertGreater(budget.tokens, 15)
        self.assertEqual(len(budget.report()['transport_unknown_reservations']), 1)
        events = [json.loads(x)['event'] for x in transcript.read_text().splitlines()]
        self.assertEqual(events.count('request'), 2)
        self.assertEqual(events.count('response'), 1)
        self.assertIn('transport_failure', events)

    def test_retry_cannot_reset_model_call_or_token_limits(self):
        for calls, tokens in [(1, 20000), (4, 200)]:
            with self.subTest(calls=calls):
                provider, model, budget, _ = self.invoke([ModelTransportError('disconnected')], calls=calls, tokens=tokens)
                with self.assertRaises(BudgetExceeded): self.dispatch(model)
                self.assertEqual(len(provider.requests), 1)

    def test_protocol_or_credential_errors_do_not_retry(self):
        provider, model, _, _ = self.invoke([ModelError('invalid response')])
        with self.assertRaises(ModelError): self.dispatch(model)
        self.assertEqual(len(provider.requests), 1)

    def test_time_budget_stops_retry_before_second_dispatch(self):
        from unittest.mock import PropertyMock
        provider, model, _, _ = self.invoke([ModelTransportError('disconnect')])
        with patch.object(Budget, 'remaining', new_callable=PropertyMock, return_value=1):
            with self.assertRaises(BudgetExceeded): self.dispatch(model)
        self.assertEqual(len(provider.requests), 1)

    def test_known_failed_usage_charged_once_before_retry(self):
        _, model, budget, _ = self.invoke([ModelTransportError('disconnect', tokens=8), Reply('{}', 15)])
        reply = self.dispatch(model); budget.charge_tokens(reply.tokens)
        self.assertEqual(budget.tokens, 23)

    def test_terminal_failure_is_recorded_and_not_charged_twice(self):
        provider, model, budget, _ = self.invoke([ModelTransportError('first', tokens=8), ModelTransportError('second', tokens=9)])
        with self.assertRaises(ModelTransportError) as caught: self.dispatch(model)
        self.assertIsNone(caught.exception.tokens)
        self.assertEqual(budget.tokens, 17)
        self.assertEqual(len(provider.requests), 2)

    def test_provider_marks_actual_remote_disconnect_as_transient(self):
        import os
        from keel.models import CompatibleChatModel
        with patch.dict(os.environ, {'TEST_PROVIDER_KEY': 'fixture'}), \
                patch('keel.models.urllib.request.build_opener') as opener:
            opener.return_value.open.side_effect = http.client.RemoteDisconnected('closed')
            model = CompatibleChatModel('fixture', 'https://example.invalid', api_key_env='TEST_PROVIDER_KEY')
            with self.assertRaises(ModelTransportError):
                model.complete([], timeout=1, max_output=100)
            self.assertEqual(opener.return_value.open.call_count, 1)

    def test_runtime_binds_retry_to_its_budget(self):
        import sys
        from keel.runtime import run
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); (root/'app.py').write_text('VALUE = 1\n')
            class Provider:
                calls = 0
                def complete_json(self, messages, **kwargs):
                    self.calls += 1
                    if self.calls == 1: raise ModelTransportError('disconnect')
                    return Reply(json.dumps({'summary': 'change', 'edits': [
                        {'path': 'app.py', 'old': 'VALUE = 1', 'new': 'VALUE = 2'}]}), 15)
            model = FrozenModel(Provider(), lambda: None, transport_retries=1)
            model.transcript = root/'.keel/model.jsonl'; model.transcript.parent.mkdir()
            config = {'mode': 'proposal', 'goal': 'Return 2',
                'proposal': {'files': ['app.py'], 'queries': ['VALUE']},
                'budget': {'max_model_calls': 2, 'max_tokens': 20000},
                'acceptance': [[sys.executable, '-B', '-c', 'import app; assert app.VALUE == 2']]}
            with patch('keel.model_transport.time.sleep'):
                result = run(config, root, root/'.keel/run', model=model)
            self.assertEqual(result['status'], 'passed')
            self.assertEqual(result['budget']['model_calls'], 2)
            self.assertEqual(len(result['budget']['transport_unknown_reservations']), 1)
