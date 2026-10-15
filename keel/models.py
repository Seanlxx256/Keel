"""Small provider boundary; only this module knows the HTTP wire format."""
from __future__ import annotations

import json
import math
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlsplit

from .core import ModelError


@dataclass
class Reply:
    content: str
    tokens: int | None = None
    metadata: dict | None = None


class Model(Protocol):
    def complete(self, messages: list[dict], *, timeout: float, max_output: int) -> Reply: ...


class OllamaModel:
    def __init__(self, model: str, base_url: str = "http://localhost:11434", *, num_ctx=None, num_gpu=None):
        parsed = urlsplit(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("Model endpoint must be an HTTP(S) URL without embedded credentials")
        if not isinstance(model, str) or not model.strip():
            raise ValueError("A model name is required")
        self.model, self.url = model, base_url.rstrip("/") + "/api/chat"
        if num_ctx is not None and (type(num_ctx) is not int or not 1024 <= num_ctx <= 131072):
            raise ValueError("num_ctx must be an integer from 1024 to 131072")
        if num_gpu is not None and (type(num_gpu) is not int or num_gpu < 0):
            raise ValueError("num_gpu must be a nonnegative integer")
        self.num_ctx, self.num_gpu = num_ctx, num_gpu

    def complete(self, messages, *, timeout, max_output):
        return self._complete(messages, timeout=timeout, max_output=max_output, response_format="json")

    def complete_json(self, messages, *, schema, timeout, max_output):
        return self._complete(messages, timeout=timeout, max_output=max_output, response_format=schema)

    def _complete(self, messages, *, timeout, max_output, response_format):
        options = {"num_predict": max_output, "temperature": 0}
        if self.num_ctx is not None:
            options.update(num_ctx=self.num_ctx, num_batch=32)
        if self.num_gpu is not None:
            options["num_gpu"] = self.num_gpu
        request = urllib.request.Request(self.url, data=json.dumps({
            "model": self.model, "messages": messages, "stream": False, "format": response_format,
            **({"keep_alive": 0} if self.num_ctx is not None else {}),
            "options": options,
        }).encode(), headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read(4_000_001)
            if len(raw) > 4_000_000:
                raise ModelError("Model response exceeds 4 MB")
            payload = json.loads(raw)
            content = payload["message"]["content"]
            if not isinstance(content, str) or payload.get("done") is not True:
                raise ModelError("Incomplete or invalid model response")
            usage = [payload.get("prompt_eval_count"), payload.get("eval_count")]
            if any(type(n) is not int or n < 0 for n in usage):
                raise ModelError("Model response is missing valid token usage")
            return Reply(content, sum(usage))
        except urllib.error.HTTPError as error:
            raise ModelError(f"Model HTTP request failed with status {error.code}") from None
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise ModelError(f"Invalid or unavailable model response ({type(error).__name__})") from None


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, new_url):
        return None


class CompatibleChatModel:
    """Explicit Chat Completions endpoint; credentials are environment references."""
    def __init__(self, model, base_url, *, api_key_env='KEEL_MODEL_API_KEY',
                 response_mode='json_object', token_limit_field='max_completion_tokens', temperature=None):
        parsed = urlsplit(base_url)
        if (parsed.scheme not in {'http', 'https'} or not parsed.hostname or parsed.username
                or parsed.password or parsed.query or parsed.fragment):
            raise ValueError('Compatible endpoint requires an HTTP(S) base URL without credentials, query or fragment')
        if parsed.scheme == 'http' and parsed.hostname not in {'localhost', '127.0.0.1', '::1'}:
            raise ValueError('Remote compatible endpoints require HTTPS')
        if not isinstance(model, str) or not model.strip() or len(model) > 200:
            raise ValueError('A model name is required')
        if not isinstance(api_key_env, str) or not re.fullmatch('[A-Za-z_][A-Za-z0-9_]*', api_key_env):
            raise ValueError('api_key_env must name an environment variable')
        if response_mode not in {'json_object', 'json_schema'} or token_limit_field not in {'max_tokens', 'max_completion_tokens'}:
            raise ValueError('Unsupported compatible response mode or token limit field')
        if temperature is not None and (type(temperature) not in {float, int} or not math.isfinite(temperature) or not 0 <= temperature <= 2):
            raise ValueError('temperature must be finite and between 0 and 2')
        self.model, self.url = model, base_url.rstrip('/') + '/chat/completions'
        self.api_key_env, self.response_mode = api_key_env, response_mode
        self.token_limit_field, self.temperature = token_limit_field, temperature

    def check_credentials(self):
        key = os.environ.get(self.api_key_env)
        if not key:
            raise ModelError('Missing model credential environment variable: ' + self.api_key_env)
        if any(character.isspace() for character in key):
            raise ModelError('Invalid model credential environment value')
        return key

    def complete(self, messages, *, timeout, max_output):
        return self._complete(messages, schema=None, timeout=timeout, max_output=max_output)

    def complete_json(self, messages, *, schema, timeout, max_output):
        return self._complete(messages, schema=schema, timeout=timeout, max_output=max_output)

    def _complete(self, messages, *, schema, timeout, max_output):
        key = self.check_credentials()
        messages = [dict(message) for message in messages]
        format_spec = {'type': 'json_object'}
        if schema is not None and self.response_mode == 'json_schema':
            if schema.get('type') != 'object':
                raise ModelError('Strict compatible schema requires a root object; use json_object for union action protocols')
            format_spec = {'type': 'json_schema', 'json_schema': {'name': 'keel_output', 'strict': True, 'schema': schema}}
        elif schema is not None:
            contract = ' Return JSON satisfying this output contract: ' + json.dumps(schema)
            if messages and messages[0].get('role') == 'system':
                messages[0]['content'] += contract
            else:
                messages.insert(0, {'role': 'system', 'content': contract})
        payload = {'model': self.model, 'messages': messages, 'stream': False,
                   self.token_limit_field: max_output, 'response_format': format_spec}
        if self.temperature is not None:
            payload['temperature'] = self.temperature
        request = urllib.request.Request(self.url, data=json.dumps(payload).encode(),
            headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + key}, method='POST')
        known_tokens = None
        try:
            # Never forward credentials through redirects or silently retry paid calls.
            with urllib.request.build_opener(NoRedirect()).open(request, timeout=timeout) as response:
                raw = response.read(4_000_001)
            if len(raw) > 4_000_000:
                raise ModelError('Model response exceeds 4 MB')
            result = json.loads(raw)
            usage = result['usage']
            counts = [usage['prompt_tokens'], usage['completion_tokens'], usage['total_tokens']]
            if any(type(count) is not int or count < 0 for count in counts) or counts[2] != sum(counts[:2]):
                raise ModelError('Model response has invalid token usage')
            known_tokens = counts[2]
            choices = result['choices']
            if not isinstance(choices, list) or len(choices) != 1:
                raise ModelError('Expected exactly one completion', tokens=counts[2])
            choice = choices[0]
            message = choice['message']
            content = message.get('content')
            if (choice.get('finish_reason') != 'stop' or message.get('refusal') or message.get('tool_calls')
                    or message.get('role') != 'assistant' or not isinstance(content, str) or not content.strip()):
                raise ModelError('Model completion was refused, truncated or incomplete', tokens=counts[2])
            metadata = {'provider': 'openai-compatible', 'requested_model': self.model}
            for field in ('model', 'system_fingerprint'):
                if isinstance(result.get(field), str):
                    metadata['reported_' + field] = result[field]
            return Reply(content, counts[2], metadata)
        except urllib.error.HTTPError as error:
            error.close()
            raise ModelError(f'Model HTTP request failed with status {error.code}') from None
        except (OSError, ValueError, KeyError, TypeError, IndexError, AttributeError) as error:
            raise ModelError(f'Invalid or unavailable model response ({type(error).__name__})', tokens=known_tokens) from None


def from_config(config: dict) -> Model:
    provider = config.get('provider', 'ollama')
    if provider == 'openai-compatible':
        allowed = {'provider', 'name', 'base_url', 'api_key_env', 'response_mode', 'token_limit_field', 'temperature'}
        if set(config) - allowed:
            raise ValueError('Unknown compatible model settings; use api_key_env, never an inline key')
        return CompatibleChatModel(config.get('name', ''), config.get('base_url', ''),
            **{key: config[key] for key in allowed - {'provider', 'name', 'base_url'} if key in config})
    if provider != 'ollama':
        raise ValueError('Supported model providers: ollama, openai-compatible')
    return OllamaModel(config.get("name", ""), config.get("base_url", "http://localhost:11434"),
                       num_ctx=config.get("num_ctx"), num_gpu=config.get("num_gpu"))
