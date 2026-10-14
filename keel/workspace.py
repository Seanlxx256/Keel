from __future__ import annotations

import ast
import hashlib
import os
import subprocess
from pathlib import Path

from .core import Budget, Ledger, PolicyDenied, Trace, digest


IGNORED = {".git", ".keel", ".venv", "node_modules", "__pycache__"}
PROTECTED = {"tests", "test", "__tests__", ".github", ".git", ".keel"}


class Workspace:
    def __init__(self, root: Path, budget: Budget, ledger: Ledger, trace: Trace):
        self.root = root.resolve(strict=True)
        if not self.root.is_dir():
            raise ValueError("Repository must be a directory")
        self.budget, self.ledger, self.trace = budget, ledger, trace

    def path(self, relative: str, write=False) -> Path:
        candidate = Path(relative)
        if candidate.is_absolute() or candidate.drive or ".." in candidate.parts:
            raise PolicyDenied(f"Path must be relative and contained: {relative}")
        path = (self.root / candidate).resolve()
        if not path.is_relative_to(self.root) or path == self.root:
            raise PolicyDenied(f"Path escapes repository: {relative}")
        resolved_parts = {p.lower() for p in path.relative_to(self.root).parts}
        if resolved_parts & {".git", ".keel"}:
            raise PolicyDenied("Internal repository and run metadata are not tool-readable")
        if write:
            parts = {p.lower() for p in candidate.parts} | resolved_parts
            name = path.name.lower()
            if parts & PROTECTED or name.startswith("test_") or name.endswith(("_test.py", ".test.js", ".spec.ts", ".spec.js")):
                raise PolicyDenied(f"Implementer cannot modify protected path: {relative}")
        return path

    def files(self):
        for directory, dirs, names in os.walk(self.root, followlinks=False):
            dirs[:] = sorted(d for d in dirs if d not in IGNORED and not (Path(directory) / d).is_symlink())
            for name in sorted(names):
                path = Path(directory) / name
                if not path.is_symlink():
                    yield path.relative_to(self.root).as_posix(), path

    def snapshot(self):
        return {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in self.files()}

    def read(self, relative: str, role="implementer"):
        self.budget.charge_tool()
        path = self.path(relative)
        if path.stat().st_size > 1_000_000:
            raise ValueError("read_file supports files up to 1 MB")
        raw = path.read_bytes()
        key = digest(["read", relative, hashlib.sha256(raw).hexdigest()])
        result = self.ledger.cached(key)
        if result is None:
            value = raw.decode("utf-8")
            self.ledger.cache(key, value)
            result = {"value": value, "cache_hit": False, "repeat_count": 0}
        self.trace.emit(role, "tool_call", tool="read", path=relative,
                        cache_hit=result["cache_hit"], repeat_count=result["repeat_count"])
        return result

    def replace(self, relative: str, old: str, new: str):
        path = self.path(relative, write=True)
        if not old or old == new:
            raise ValueError("Replacement must have a nonempty old value and change content")
        text = self.read(relative)["value"]
        if text.count(old) != 1:
            raise ValueError(f"Expected exactly one occurrence in {relative}, found {text.count(old)}")
        updated = text.replace(old, new, 1)
        if path.suffix == ".py":
            ast.parse(updated, filename=relative)
        self.budget.charge_tool()
        path.write_bytes(updated.encode("utf-8"))
        self.trace.emit("implementer", "tool_call", tool="replace", path=relative)

    def search(self, query: str, limit=30, role="scout"):
        self.budget.charge_tool()
        matches = []
        for name, path in self.files():
            self.budget.check()
            if path.stat().st_size > 1_000_000:
                continue
            try:
                content = path.read_text(encoding="utf-8")
            except (UnicodeError, OSError):
                continue
            for number, line in enumerate(content.splitlines(), 1):
                if query.casefold() in line.casefold():
                    matches.append({"file": name, "line": number, "text": line[:400]})
                    if len(matches) >= limit:
                        break
            if len(matches) >= limit:
                break
        result = {"tier": "T0", "confidence": None, "index_ref": digest(self.snapshot()),
                  "matches": matches, "truncated": len(matches) >= limit}
        self.trace.emit(role, "tool_call", tool="search_code", query=query, matches=len(matches))
        return result

    def verify(self, commands: list[list[str]]):
        results = []
        for command in commands:
            self.budget.charge_tool()
            self.trace.emit("verifier", "command_started", command=command)
            try:
                # Commands are supplied by the operator, never by work items. No shell expansion.
                completed = subprocess.run(command, cwd=self.root, shell=False,
                                           stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                           timeout=self.budget.remaining)
                result = {"command": command, "returncode": completed.returncode,
                          "stdout": completed.stdout.decode("utf-8", errors="replace"),
                          "stderr": completed.stderr.decode("utf-8", errors="replace"), "timeout": False}
            except subprocess.TimeoutExpired as error:
                result = {"command": command, "returncode": None, "timeout": True,
                          "stdout": (error.stdout or b"").decode("utf-8", errors="replace"),
                          "stderr": (error.stderr or b"").decode("utf-8", errors="replace")}
            fact = self.ledger.add("test", "verifier", f"{command[0]}: {result['returncode']}", result)
            self.trace.emit("verifier", "command_finished", fact_id=fact,
                            returncode=result["returncode"], timeout=result["timeout"])
            results.append(result)
            if result["timeout"]:
                break
        return results
