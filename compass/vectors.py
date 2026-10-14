from __future__ import annotations

import hashlib
import json
import math
import re
import urllib.error
import urllib.request
from urllib.parse import urlsplit


def checked_vectors(vectors, count, dimensions=None):
    if not isinstance(vectors, list) or len(vectors) != count:
        raise ValueError("Embedding response count does not match input count")
    for vector in vectors:
        if not isinstance(vector, list) or not vector or any(type(v) not in {int, float} or not math.isfinite(v) for v in vector):
            raise ValueError("Embedding vectors must contain finite numbers")
        dimensions = dimensions or len(vector)
        if len(vector) != dimensions or not any(v != 0 for v in vector):
            raise ValueError("Embedding vectors must have consistent dimensions and nonzero length")
    return dimensions


class HashEmbedder:
    """Deterministic lexical feature hashing, NOT a semantic embedding model."""
    def __init__(self, dimensions=128):
        if type(dimensions) is not int or not 8 <= dimensions <= 4096:
            raise ValueError("Hash dimensions must be between 8 and 4096")
        self.dimensions = dimensions
        self.spec = {"provider": "hash", "dimensions": dimensions, "version": 1}

    def embed(self, texts):
        vectors = []
        for text in texts:
            vector = [0.0] * self.dimensions
            text = re.sub(r"([a-z])([A-Z])", r"\1 \2", text)
            for token in re.findall(r"[^\W_]+", text.casefold(), flags=re.UNICODE):
                hashed = hashlib.blake2b(token.encode(), digest_size=8).digest()
                vector[int.from_bytes(hashed[:4], "big") % self.dimensions] += 1 if hashed[4] % 2 else -1
            norm = math.sqrt(sum(v * v for v in vector))
            if not norm:
                vector[0], norm = 1.0, 1.0
            vectors.append([value / norm for value in vector])
        return vectors


class OllamaEmbedder:
    def __init__(self, model, base_url="http://localhost:11434", timeout=60, num_batch=None):
        parts = urlsplit(base_url)
        if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username or parts.password:
            raise ValueError("Embedding URL must use HTTP(S) without embedded credentials")
        if not isinstance(model, str) or not model.strip():
            raise ValueError("An embedding model name is required")
        if num_batch is not None and (type(num_batch) is not int or not 1 <= num_batch <= 2048):
            raise ValueError("Embedding num_batch must be an integer between 1 and 2048")
        self.model, self.base_url, self.timeout = model, base_url.rstrip("/"), timeout
        self.spec = {"provider": "ollama", "model": model, "base_url": self.base_url}
        self.num_batch = num_batch
        self.keep_alive = None
        if num_batch is not None:
            self.spec["num_batch"] = num_batch

    def embed(self, texts):
        if not texts:
            return []
        payload = {"model": self.model, "input": texts, "truncate": False}
        if self.keep_alive is not None:
            payload["keep_alive"] = self.keep_alive
        if self.num_batch is not None:
            payload["options"] = {"num_batch": self.num_batch}
        request = urllib.request.Request(self.base_url + "/api/embed", data=json.dumps(payload).encode(),
                                         headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read(16_000_001)
            if len(raw) > 16_000_000:
                raise ValueError("Embedding response exceeds 16 MB")
            vectors = json.loads(raw)["embeddings"]
            checked_vectors(vectors, len(texts))
            return vectors
        except urllib.error.HTTPError as error:
            detail = ""
            try:
                message = json.loads(error.read(4096)).get("error")
                if isinstance(message, str):
                    detail = ": " + " ".join(message.split())[:300]
            except (ValueError, OSError, AttributeError):
                pass
            raise ValueError(f"Embedding HTTP request failed with status {error.code}{detail}") from None
        except (OSError, KeyError, TypeError, json.JSONDecodeError):
            raise ValueError("Embedding endpoint is unavailable or returned an invalid response") from None


def embedder_from_spec(spec):
    if spec["provider"] == "hash":
        return HashEmbedder(spec["dimensions"])
    if spec["provider"] == "ollama":
        return OllamaEmbedder(spec["model"], spec["base_url"], num_batch=spec.get("num_batch"))
    raise ValueError("Unknown embedding provider")


class LanceVectors:
    def __init__(self, path):
        try:
            import lancedb
        except ImportError:
            raise ValueError("LanceDB is unavailable; install .[compass-vectors]") from None
        self.db = lancedb.connect(str(path))

    def write(self, records):
        if records:
            self.db.create_table("chunks", records, mode="overwrite")

    def search(self, vector, limit):
        table = self.db.open_table("chunks")
        return [{"id": row["id"], "distance": float(row["_distance"])} for row in
                table.search(vector).distance_type("cosine").limit(limit).to_list()]
