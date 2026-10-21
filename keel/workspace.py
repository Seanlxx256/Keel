from __future__ import annotations

import ast
import hashlib
import os
from pathlib import Path

from .audit import audit_text, protected_path, read_junit
from .core import AuditFailed, Budget, Ledger, PolicyDenied, Trace, digest
from .execution import CommandRunner, normalize_acceptance


IGNORED = {".git", ".keel", ".compass", ".venv", ".venv-deps", "node_modules", "__pycache__"}


class Workspace:
    def __init__(self, root: Path, budget: Budget, ledger: Ledger, trace: Trace, runner=None,
                 retrieval=None, retrieval_model=None, memoization=True):
        if type(memoization) is not bool:
            raise ValueError("memoization must be boolean")
        self.memoization = memoization
        self.tool_metrics = {}
        self.snapshot_calls = self.snapshot_bytes = 0
        self.root = root.resolve(strict=True)
        if not self.root.is_dir():
            raise ValueError("Repository must be a directory")
        self.budget, self.ledger, self.trace = budget, ledger, trace
        self.runner = runner or CommandRunner()
        self.retrieval = retrieval or {}
        from compass.retrieval import validate_retrieval
        validate_retrieval(self.retrieval)
        self.retrieval_model = retrieval_model

    @property
    def compass_enabled(self):
        return self.retrieval.get("provider") == "compass"

    def _retrieval_record(self, role):
        def record(event, data):
            fact_id = self.ledger.add("decision", role, event, data)
            self.trace.emit(role, event, fact_id=fact_id)
        return record

    def _compass_index(self, role):
        from compass.index import open_index
        self.budget.check()
        index = open_index(self.root, auto_update=self.retrieval.get("auto_update", False),
                           record=self._retrieval_record(role))
        try:
            self.budget.check()
        except Exception:
            index.close()
            raise
        return index

    def find_symbol(self, name, role="implementer"):
        if not self.compass_enabled:
            raise ValueError("Compass retrieval is not enabled")
        self.budget.charge_tool()
        with self._compass_index(role) as index:
            result = index.find_symbol(name)
        self.trace.emit(role, "tool_call", tool="find_symbol", name=name)
        return result

    def get_context(self, file, line, role="implementer"):
        if not self.compass_enabled:
            raise ValueError("Compass retrieval is not enabled")
        self.budget.charge_tool()
        with self._compass_index(role) as index:
            result = index.context(file, line)
        self.trace.emit(role, "tool_call", tool="get_context", file=file, line=line)
        return result

    def get_symbols_overview(self, file, *, depth=1, limit=20, offset=0, max_bytes=12000, role='scout'):
        if not self.compass_enabled:
            raise ValueError('Compass retrieval is not enabled')
        self.path(file)  # Preserve host path/protected-metadata read policy.
        self.budget.charge_tool()
        with self._compass_index(role) as index:
            result = index.overview(file, depth=depth, limit=limit, offset=offset, max_bytes=max_bytes)
        self.trace.emit(role, 'tool_call', tool='get_symbols_overview', file=file, offset=offset)
        return result

    def path(self, relative: str, write=False) -> Path:
        candidate = Path(relative)
        if candidate.is_absolute() or candidate.drive or ".." in candidate.parts:
            raise PolicyDenied(f"Path must be relative and contained: {relative}")
        path = (self.root / candidate).resolve()
        if not path.is_relative_to(self.root) or path == self.root:
            raise PolicyDenied(f"Path escapes repository: {relative}")
        resolved_parts = {p.lower() for p in path.relative_to(self.root).parts}
        if resolved_parts & {".git", ".keel", ".compass", ".venv-deps"}:
            raise PolicyDenied("Internal repository and run metadata are not tool-readable")
        if write:
            if protected_path(relative) or protected_path(path.relative_to(self.root).as_posix()):
                raise PolicyDenied(f"Implementer cannot modify protected path: {relative}")
            if path.exists() and path.stat().st_nlink > 1:
                raise PolicyDenied(f"Implementer cannot modify hard-linked files: {relative}")
        return path

    def files(self):
        for directory, dirs, names in os.walk(self.root, followlinks=False):
            dirs[:] = sorted(d for d in dirs if d not in IGNORED and not (Path(directory) / d).is_symlink())
            for name in sorted(names):
                path = Path(directory) / name
                if not path.is_symlink():
                    yield path.relative_to(self.root).as_posix(), path

    def snapshot(self):
        self.snapshot_calls += 1
        snapshot = {}
        for name, path in self.files():
            raw = path.read_bytes()
            self.snapshot_bytes += len(raw)
            snapshot[name] = hashlib.sha256(raw).hexdigest()
        return snapshot

    def _count_observation(self, tool, hit):
        row = self.tool_metrics.setdefault(tool, {"requests": 0, "cache_hits": 0, "computations": 0})
        row["requests"] += 1
        row["cache_hits"] += int(hit)
        row["computations"] += int(not hit)

    def _memoized(self, tool, arguments, compute, role):
        """Only deterministic local observations; never cache writes or verification."""
        self.budget.charge_tool()
        before = self.snapshot()
        key = digest(["local-observation-v1", str(self.root), tool, arguments, before])
        cached = self.ledger.cached(key) if self.memoization else None
        self._count_observation(tool, cached is not None)
        value = cached["value"] if cached else compute(before)
        if self.snapshot() != before:
            raise ValueError("Repository changed during memoized observation; retry the tool")
        if cached is None and self.memoization:
            self.ledger.cache(key, value)
        self.trace.emit(role, "tool_cache", tool=tool, cache_hit=cached is not None,
                        repeat_count=cached["repeat_count"] if cached else 0)
        return value, {"cache_hit": cached is not None,
                       "repeat_count": cached["repeat_count"] if cached else 0}

    def list_files(self, role="scout"):
        value, metadata = self._memoized("list_files", {}, lambda snapshot: sorted(snapshot), role)
        self.trace.emit(role, "tool_call", tool="list_files", **metadata)
        return {"files": value, **metadata}

    def read(self, relative: str, role="implementer"):
        self.budget.charge_tool()
        path = self.path(relative)
        if path.stat().st_size > 1_000_000:
            raise ValueError("read_file supports files up to 1 MB")
        raw = path.read_bytes()
        key = digest(["read", relative, hashlib.sha256(raw).hexdigest()])
        result = self.ledger.cached(key) if self.memoization else None
        self._count_observation("read_file", result is not None)
        if result is None:
            value = raw.decode("utf-8")
            if self.memoization:
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
        findings = audit_text(relative, text.encode("utf-8"), updated.encode("utf-8"))
        if findings:
            fact_id = self.ledger.add("decision", "auditor", "Static audit rejected edit", findings)
            self.trace.emit("auditor", "edit_rejected", fact_id=fact_id)
            raise AuditFailed(findings)
        self.budget.charge_tool()
        path.write_bytes(updated.encode("utf-8"))
        self.trace.emit("implementer", "tool_call", tool="replace", path=relative)

    def search(self, query: str, limit=30, role="scout", *, paths=None):
        scoped = None
        if paths is not None:
            if (not isinstance(paths, list) or not 1 <= len(paths) <= 32 or
                    any(not isinstance(name, str) for name in paths) or len(set(paths)) != len(paths)):
                raise ValueError('Search paths must be 1..32 unique relative paths')
            scoped = [(name, self.path(name)) for name in paths]
        if self.compass_enabled and scoped is None:
            from compass.retrieval import Retriever, routing_from_dict
            with self._compass_index(role) as index:
                result = Retriever(index, routing=routing_from_dict(self.retrieval.get("routing")),
                                   model=self.retrieval_model if self.retrieval.get("allow_t2") else None,
                                   budget=self.budget, record=self._retrieval_record(role)).retrieve(query, limit)
            result["matches"] = [{"file": row["path"], "line": row["start_line"], "text": row["signature"][:400]}
                                 for row in result["results"]]
            self.trace.emit(role, "tool_call", tool="search_code", query=query, matches=len(result["matches"]), tier=result["tier"])
            return result
        def compute(snapshot):
            matches = []
            for name, path in (scoped if scoped is not None else self.files()):
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
            return {"tier": "T0", "confidence": None, "index_ref": digest(snapshot),
                    "matches": matches, "truncated": len(matches) >= limit}
        arguments = {"query": query, "limit": limit}
        if paths is not None:
            arguments['paths'] = paths
        value, metadata = self._memoized("search_code", arguments, compute, role)
        result = {**value, **metadata}
        self.trace.emit(role, "tool_call", tool="search_code", matches=len(result["matches"]), **metadata)
        return result

    def verify(self, commands, phase="final"):
        results = []
        for index, spec in enumerate(normalize_acceptance(commands)):
            self.budget.charge_tool()
            reports = self.trace.path.parent / "reports" / phase / str(index)
            report_path = reports / "report.xml"
            command = list(spec["command"])
            if spec["junit"]:
                # Each invocation gets a new directory; old reports are never reused.
                reports.mkdir(parents=True, exist_ok=False)
                reports.chmod(0o777)
                target = "/keel-reports/report.xml" if self.runner.backend == "docker" else str(report_path.resolve())
                command = [part.replace("{junit}", target) for part in command]
            self.trace.emit("verifier", "command_started", command=command, phase=phase)
            result = self.runner.run(command, self.root, self.budget.remaining,
                                     reports=reports.resolve() if spec["junit"] else None)
            result.update(command=spec["command"], junit_required=spec["junit"])
            if spec["junit"]:
                result["report_path"] = str(report_path)
                try:
                    result["metadata"] = read_junit(report_path)
                except ValueError as error:
                    result["metadata_error"] = str(error)
            fact = self.ledger.add("test", "verifier", f"{phase}: {command[0]}: {result['returncode']}", result)
            self.trace.emit("verifier", "command_finished", fact_id=fact,
                            returncode=result["returncode"], timeout=result["timeout"], phase=phase)
            results.append(result)
            if result["timeout"]:
                break
        return results
