from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


class BudgetExceeded(RuntimeError):
    pass


class PolicyDenied(RuntimeError):
    pass


class AuditFailed(PolicyDenied):
    def __init__(self, findings):
        self.findings = findings
        super().__init__("Audit rejected changes: " + ", ".join(f["rule"] for f in findings))


class ModelError(RuntimeError):
    pass


@dataclass
class Limits:
    max_wallclock: float = 300
    max_tool_calls: int = 100
    max_tokens: int = 20000
    max_model_calls: int = 40

    def __post_init__(self):
        if min(self.max_wallclock, self.max_tool_calls, self.max_tokens, self.max_model_calls) <= 0:
            raise ValueError("All budget limits must be positive")


class Budget:
    def __init__(self, limits: Limits):
        self.limits = limits
        self.started = time.monotonic()
        self.tool_calls = 0
        self.tokens = 0
        self.model_calls = 0

    def allow_model(self, input_estimate: int, output_limit: int):
        self.check()
        if self.model_calls >= self.limits.max_model_calls:
            raise BudgetExceeded("Model-call budget exhausted")
        if self.tokens + input_estimate + output_limit > self.limits.max_tokens:
            raise BudgetExceeded("Insufficient token budget for next model call")
        self.model_calls += 1

    def charge_tokens(self, count: int):
        self.tokens += count
        if self.tokens > self.limits.max_tokens:
            raise BudgetExceeded("Token budget exhausted")

    @property
    def remaining(self) -> float:
        return max(0, self.limits.max_wallclock - (time.monotonic() - self.started))

    def check(self):
        if self.remaining <= 0:
            raise BudgetExceeded("Wall-clock budget exhausted")

    def charge_tool(self):
        self.check()
        if self.tool_calls >= self.limits.max_tool_calls:
            raise BudgetExceeded("Tool-call budget exhausted")
        self.tool_calls += 1

    def report(self):
        return {"tool_calls": self.tool_calls, "tokens": self.tokens, "model_calls": self.model_calls,
                "wallclock_seconds": round(time.monotonic() - self.started, 3),
                "limits": asdict(self.limits)}


class Trace:
    def __init__(self, path: Path, telemetry=None):
        self.path = path
        self.sequence = 0
        self.telemetry = telemetry

    def emit(self, role: str, event: str, **data):
        self.sequence += 1
        record = {"sequence": self.sequence, "time": time.time(),
                  "role": role, "event": event, **data}
        if self.telemetry is not None:
            self.telemetry.observe(record)
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")


class Ledger:
    KINDS = {"file", "test", "symbol", "decision", "failed_attempt"}

    def __init__(self, path: Path):
        self.db = sqlite3.connect(path)
        self.db.execute("CREATE TABLE IF NOT EXISTS facts "
                        "(id INTEGER PRIMARY KEY, kind TEXT, role TEXT, summary TEXT, payload TEXT)")
        self.db.execute("CREATE TABLE IF NOT EXISTS cache "
                        "(key TEXT PRIMARY KEY, payload TEXT, hits INTEGER NOT NULL DEFAULT 0)")
        self.db.commit()

    def add(self, kind: str, role: str, summary: str, payload: Any) -> int:
        if kind not in self.KINDS:
            raise ValueError(f"Unknown fact kind: {kind}")
        cursor = self.db.execute("INSERT INTO facts(kind,role,summary,payload) VALUES(?,?,?,?)",
                                 (kind, role, summary, json.dumps(payload, ensure_ascii=False)))
        self.db.commit()
        return cursor.lastrowid

    def recall(self, fact_id: int):
        row = self.db.execute("SELECT payload FROM facts WHERE id=?", (fact_id,)).fetchone()
        if row is None:
            raise KeyError(fact_id)
        return json.loads(row[0])

    def summaries(self):
        return [dict(zip(("fact_id", "kind", "role", "summary"), row)) for row in
                self.db.execute("SELECT id,kind,role,summary FROM facts ORDER BY id")]

    def cached(self, key: str):
        row = self.db.execute("SELECT payload,hits FROM cache WHERE key=?", (key,)).fetchone()
        if row is None:
            return None
        self.db.execute("UPDATE cache SET hits=hits+1 WHERE key=?", (key,))
        self.db.commit()
        return {"value": json.loads(row[0]), "cache_hit": True, "repeat_count": row[1] + 1}

    def cache(self, key: str, value: Any):
        self.db.execute("INSERT OR REPLACE INTO cache(key,payload,hits) VALUES(?,?,0)",
                        (key, json.dumps(value, ensure_ascii=False)))
        self.db.commit()

    def close(self):
        self.db.close()


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
