import copy
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
import urllib.error
from unittest.mock import patch

from keel.core import ModelError
from keel.models import CompatibleChatModel, NoRedirect, from_config
from keel.runtime import run


def response():
    return {'model': 'reported-revision', 'system_fingerprint': 'fp-fixture',
        'choices': [{'finish_reason': 'stop', 'message': {'role': 'assistant', 'content': '{}'}}],
        'usage': {'prompt_tokens': 10, 'completion_tokens': 5, 'total_tokens': 15}}


class Response:
    def __init__(self, payload): self.raw = json.dumps(payload).encode()
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def read(self, limit): return self.raw[:limit]


class CompatibleModelTests(unittest.TestCase):
    def test_factory_adapter_completes_proposal_through_runtime_and_keeps_key_out_of_artifacts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'app.py').write_text('VERSION = 1\n')
            config = {'mode': 'proposal', 'goal': 'Upgrade VERSION to 2',
                'proposal': {'files': ['app.py'], 'queries': ['VERSION']},
                'model': {'provider': 'openai-compatible', 'name': 'requested',
                    'base_url': 'https://provider.example/v1', 'api_key_env': 'KEEL_TEST_MODEL_KEY'},
                'acceptance': [[sys.executable, '-c', 'import app; assert app.VERSION == 2']]}
            data = response()
            data['choices'][0]['message']['content'] = json.dumps({'summary': 'Proposed version update',
                'edits': [{'path': 'app.py', 'old': 'VERSION = 1', 'new': 'VERSION = 2'}]})
            with patch('keel.models.urllib.request.build_opener') as opener:
                opener.return_value.open.return_value = Response(data)
                result = run(config, root, root/'.keel/run')
            self.assertEqual(result['status'], 'passed')
            self.assertEqual(result['budget']['tokens'], 15)
            trace = (root/'.keel/run/trace.jsonl').read_text()
            self.assertIn('reported-revision', trace)
            self.assertNotIn('fixture-secret', trace + json.dumps(result))

    def setUp(self):
        self.env = patch.dict(os.environ, {'KEEL_TEST_MODEL_KEY': 'fixture-secret'})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.model = CompatibleChatModel('requested', 'https://provider.example/v1', api_key_env='KEEL_TEST_MODEL_KEY')

    def test_wire_contract_credentials_and_metadata_without_mutating_messages(self):
        messages = [{'role': 'system', 'content': 'Return JSON.'}, {'role': 'user', 'content': 'Task'}]
        original = copy.deepcopy(messages)
        with patch('keel.models.urllib.request.build_opener') as opener:
            opener.return_value.open.return_value = Response(response())
            reply = self.model.complete_json(messages, schema={'type': 'object'}, timeout=3, max_output=128)
            request = opener.return_value.open.call_args.args[0]
            payload = json.loads(request.data)
            self.assertEqual(request.full_url, 'https://provider.example/v1/chat/completions')
            self.assertEqual(request.get_header('Authorization'), 'Bearer fixture-secret')
            self.assertNotIn('fixture-secret', request.data.decode())
            self.assertEqual(payload['max_completion_tokens'], 128)
            self.assertEqual(payload['response_format'], {'type': 'json_object'})
            self.assertNotIn('temperature', payload)
            self.assertFalse(payload['stream'])
            self.assertEqual(reply.tokens, 15)
            self.assertEqual(reply.metadata['reported_model'], 'reported-revision')
        self.assertEqual(messages, original)

    def test_strict_schema_and_explicit_legacy_token_field(self):
        model = CompatibleChatModel('requested', 'https://provider.example/v1', api_key_env='KEEL_TEST_MODEL_KEY',
            response_mode='json_schema', token_limit_field='max_tokens', temperature=0)
        schema = {'type': 'object', 'properties': {}, 'required': [], 'additionalProperties': False}
        with patch('keel.models.urllib.request.build_opener') as opener:
            opener.return_value.open.return_value = Response(response())
            model.complete_json([], schema=schema, timeout=1, max_output=64)
            payload = json.loads(opener.return_value.open.call_args.args[0].data)
            self.assertEqual(payload['response_format']['json_schema']['schema'], schema)
            self.assertTrue(payload['response_format']['json_schema']['strict'])
            self.assertEqual(payload['max_tokens'], 64)
            with self.assertRaises(ModelError):
                model.complete_json([], schema={'oneOf': []}, timeout=1, max_output=64)
            self.assertEqual(opener.return_value.open.call_count, 1)

    def test_truncation_refusal_and_malformed_usage_are_rejected(self):
        for variant in ['length', 'refusal', 'usage', 'null_message']:
            data = response()
            if variant == 'length': data['choices'][0]['finish_reason'] = 'length'
            elif variant == 'refusal': data['choices'][0]['message']['refusal'] = 'refused'
            elif variant == 'null_message': data['choices'][0]['message'] = None
            else: data['usage']['total_tokens'] = True
            with self.subTest(variant=variant), patch('keel.models.urllib.request.build_opener') as opener:
                opener.return_value.open.return_value = Response(data)
                with self.assertRaises(ModelError) as caught:
                    self.model.complete([], timeout=1, max_output=64)
                self.assertEqual(caught.exception.tokens, None if variant == 'usage' else 15)

    def test_errors_do_not_echo_credentials_or_retry(self):
        for status in [302, 401, 429, 500]:
            with self.subTest(status=status), patch('keel.models.urllib.request.build_opener') as opener:
                opener.return_value.open.side_effect = urllib.error.HTTPError('https://provider.example', status,
                    'fixture-secret', {}, io.BytesIO(b'fixture-secret'))
                with self.assertRaises(ModelError) as caught:
                    self.model.complete([], timeout=1, max_output=64)
                self.assertNotIn('fixture-secret', str(caught.exception))
                self.assertEqual(opener.return_value.open.call_count, 1)
        self.assertIsNone(NoRedirect().redirect_request(None, None, 302, '', {}, 'https://other.example'))

    def test_missing_credential_and_unsafe_or_inline_config_fail_before_network(self):
        with patch.dict(os.environ, {}, clear=True), patch('keel.models.urllib.request.build_opener') as opener:
            with self.assertRaises(ModelError): self.model.complete([], timeout=1, max_output=64)
            opener.assert_not_called()
        for url in ['https://user:secret@example.com/v1', 'https://example.com/v1?key=secret',
                    'http://example.com/v1', 'https://example.com/v1#secret']:
            with self.subTest(url=url), self.assertRaises(ValueError):
                CompatibleChatModel('model', url)
        with self.assertRaises(ValueError):
            from_config({'provider': 'openai-compatible', 'name': 'm', 'base_url': 'https://example.com/v1', 'api_key': 'fixture-secret'})

    def test_rejected_remote_completion_usage_is_charged_by_runtime(self):
        for mode in ['agent', 'proposal']:
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root/'app.py').write_text('VERSION = 1\n')
                config = {'mode': mode, 'goal': 'Upgrade VERSION', 'acceptance': [[sys.executable, '-c', 'pass']]}
                if mode == 'proposal': config['proposal'] = {'files': ['app.py'], 'queries': ['VERSION']}
                data = response()
                data['choices'][0]['finish_reason'] = 'length'
                with patch('keel.models.urllib.request.build_opener') as opener:
                    opener.return_value.open.return_value = Response(data)
                    result = run(config, root, root/'.keel/run', model=self.model)
                self.assertEqual(result['status'], 'failed')
                self.assertEqual(result['budget']['model_calls'], 1)
                self.assertEqual(result['budget']['tokens'], 15)
                self.assertEqual((root/'app.py').read_text(), 'VERSION = 1\n')
