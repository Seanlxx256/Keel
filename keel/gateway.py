from __future__ import annotations

import json
import time
import uuid

from .core import PolicyDenied


TOOLS = {
    "list_files": "{} -> repository file names",
    "search_code": '{"query": "literal text"} -> matches and ledger reference',
    "read_file": '{"path": "relative/path"} -> ledger reference and text preview',
    "recall": '{"fact_id": 1, "offset": 0} -> next 4000 characters of stored evidence',
}



class ToolGateway:
    """Role-scoped local tool boundary; workspace operations own budget charges."""

    def __init__(self, role, workspace, *, allowed_files=()):
        if role not in {"scout", "planner", "implementer"}:
            raise PolicyDenied(f"No agent tools available to role: {role}")
        self.role, self.ws = role, workspace
        self.allowed_files = frozenset(allowed_files)
        self.visible_facts = set()

    def catalog(self):
        tools = dict(TOOLS)
        if self.ws.compass_enabled:
            tools.update(find_symbol='{"name": "symbol name"} -> exact symbol matches',
                         get_context='{"file": "relative/path.py", "line": 1} -> containing symbol and graph neighbors')
        if self.role == "implementer":
            tools["replace"] = '{"path": "declared file", "old": "unique text", "new": "replacement"}'
        if getattr(self.ws, "mcp_tools", None):
            tools.update(self.ws.mcp_tools.catalog(self.role))
        return tools

    def call(self, tool, args):
        call_id = uuid.uuid4().hex
        started = time.monotonic()
        status = "failed"
        error_type = None
        self.ws.trace.emit(self.role, "gateway_call_started", call_id=call_id,
                           tool=tool if isinstance(tool, str) else "<invalid>", transport="mcp_stdio" if isinstance(tool, str) and tool.startswith("mcp__") else "local")
        try:
            if not isinstance(tool, str) or tool not in self.catalog():
                raise PolicyDenied(f"Tool unavailable to {self.role}: {tool}")
            if not tool.startswith("mcp__"):
                self._validate(tool, args)
            elif not isinstance(args, dict):
                raise ValueError("MCP arguments must be an object")
            self.ws.budget.check()
            result = self._dispatch(tool, args)
            self.ws.budget.check()
            status = "completed"
            return result
        except BaseException as error:
            error_type = type(error).__name__
            status = "denied" if isinstance(error, PolicyDenied) else "failed"
            raise
        finally:
            self.ws.trace.emit(self.role, "gateway_call_finished", call_id=call_id,
                               status=status, error_type=error_type,
                               seconds=max(0, time.monotonic() - started))

    @staticmethod
    def _validate(tool, args):
        contracts = {
            "list_files": ({}, {}),
            "read_file": ({"path": str}, {}),
            "search_code": ({"query": str}, {}),
            "find_symbol": ({"name": str}, {}),
            "get_context": ({"file": str, "line": int}, {}),
            "replace": ({"path": str, "old": str, "new": str}, {}),
            "recall": ({"fact_id": int}, {"offset": int}),
        }
        required, optional = contracts[tool]
        if not isinstance(args, dict) or set(required) - args.keys() or args.keys() - (required.keys() | optional.keys()):
            raise ValueError(f"Invalid arguments for {tool}")
        for name, value in args.items():
            expected = {**required, **optional}[name]
            if type(value) is not expected:
                raise ValueError(f"{name} must be {expected.__name__}")
        if tool == "get_context" and args["line"] < 1:
            raise ValueError("line must be positive")

    def _dispatch(self, tool, args):
        if tool.startswith("mcp__"):
            value = self.ws.mcp_tools.call(self.role, tool, args)
            fact_id = self.ws.ledger.add("symbol", self.role, tool + " evidence", value)
            self.visible_facts.add(fact_id)
            text = json.dumps(value, ensure_ascii=False)
            self.ws.trace.emit(self.role, "ledger_write", fact_id=fact_id)
            return {"fact_id": fact_id, "preview": text[:4000], "truncated": len(text) > 4000}
        if tool == "replace":
            path = args["path"]
            if path not in self.allowed_files:
                raise PolicyDenied(f"File is outside this work item's scope: {path}")
            self.ws.replace(path, args["old"], args["new"])
            return {"changed": path}
        if tool == "recall":
            fact_id, offset = args["fact_id"], args.get("offset", 0)
            if type(fact_id) is not int or fact_id not in self.visible_facts:
                raise PolicyDenied("Fact is not visible in this role session")
            if type(offset) is not int or offset < 0:
                raise ValueError("offset must be a nonnegative integer")
            self.ws.budget.charge_tool()
            text = json.dumps(self.ws.ledger.recall(fact_id), ensure_ascii=False)
            self.ws.trace.emit(self.role, "tool_call", tool="recall", fact_id=fact_id, offset=offset)
            return {"text": text[offset:offset + 4000], "next_offset": offset + 4000 if len(text) > offset + 4000 else None}
        if tool == "list_files":
            self.ws.budget.charge_tool()
            value = [name for name, _ in self.ws.files()]
            self.ws.trace.emit(self.role, "tool_call", tool=tool)
            kind = "file"
        elif tool == "read_file":
            value = self.ws.read(args["path"], role=self.role)
            kind = "file"
        elif tool == "search_code":
            if not isinstance(args["query"], str) or not args["query"].strip():
                raise ValueError("query must be nonempty text")
            value = self.ws.search(args["query"], role=self.role)
            kind = "symbol"
        elif tool == "find_symbol":
            value = self.ws.find_symbol(args["name"], role=self.role)
            kind = "symbol"
        elif tool == "get_context":
            value = self.ws.get_context(args["file"], args["line"], role=self.role)
            kind = "symbol"
        else:
            raise PolicyDenied(f"Unknown tool: {tool}")
        fact_id = self.ws.ledger.add(kind, self.role, tool + " evidence", value)
        self.visible_facts.add(fact_id)
        text = json.dumps(value, ensure_ascii=False)
        self.ws.trace.emit(self.role, "ledger_write", fact_id=fact_id)
        return {"fact_id": fact_id, "preview": text[:4000], "truncated": len(text) > 4000}

