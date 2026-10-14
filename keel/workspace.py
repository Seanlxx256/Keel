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
    def __init__(self, root: Path, budget: Budget, ledger: Ledger, trace: Trace, runner=None):
        self.root = root.resolve(strict=True)
        if not self.root.is_dir():
            raise ValueError("Repository must be a directory")
        self.budget, self.ledger, self.trace = budget, ledger, trace
        self.runner = runner or CommandRunner()

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
        findings = audit_text(relative, text.encode("utf-8"), updated.encode("utf-8"))
        if findings:
            fact_id = self.ledger.add("decision", "auditor", "Static audit rejected edit", findings)
            self.trace.emit("auditor", "edit_rejected", fact_id=fact_id)
            raise AuditFailed(findings)
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
