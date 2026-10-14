"""Small provider boundary; only this module knows the HTTP wire format."""
from __future__ import annotations

import json
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


def from_config(config: dict) -> Model:
    if config.get("provider", "ollama") != "ollama":
        raise ValueError("Supported model provider: ollama")
    return OllamaModel(config.get("name", ""), config.get("base_url", "http://localhost:11434"),
                       num_ctx=config.get("num_ctx"), num_gpu=config.get("num_gpu"))
