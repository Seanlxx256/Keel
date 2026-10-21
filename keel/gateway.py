from __future__ import annotations

import json
import hashlib
import time
import uuid

from .core import PolicyDenied


TOOLS = {
    "list_files": "{} -> repository file names",
    "search_code": '{"query": "literal text", "paths": ["optional/relative/file.py"]} -> literal matches and ledger reference; paths restrict the search',
    "read_file": '{"path": "relative/path"} -> ledger reference and text preview',
    "read_page": '{"path": "relative/path", "start_line": 1} -> source page capped at 80 lines/3000 characters; pass returned next_line as start_line for the next page',
    "read_lines": '{"path": "relative/path", "start_line": 1, "end_line": 40} -> bounded source window; oversized requests return a partial page capped at 80 lines/3000 characters; follow returned next_line',
    "recall": '{"fact_id": 1, "offset": 0} -> next 4000 characters of stored evidence',
}

LOCAL_CONTRACTS = {
    'list_files': ({}, {}), 'read_file': ({'path': str}, {}),
    'search_code': ({'query': str}, {'paths': list}), 'find_symbol': ({'name': str}, {}),
    'get_context': ({'file': str, 'line': int}, {}),
    'get_symbols_overview': ({'file': str}, {'depth': int, 'offset': int, 'limit': int, 'max_bytes': int}),
    'replace': ({'path': str, 'old': str, 'new': str}, {}),
    'recall': ({'fact_id': int}, {'offset': int}),
    'read_lines': ({'path': str, 'start_line': int, 'end_line': int}, {}),
    'read_page': ({'path': str, 'start_line': int}, {}),
}



class ToolGateway:
    """Role-scoped local tool boundary; workspace operations own budget charges."""

    def __init__(self, role, workspace, *, allowed_files=()):
        if role not in {"scout", "planner", "implementer"}:
            raise PolicyDenied(f"No agent tools available to role: {role}")
        self.role, self.ws = role, workspace
        self.allowed_files = frozenset(allowed_files)
        self.visible_facts = set()
        self.observed_facts = set()
        self.read_evidence = {}

    def accept_evidence(self, source, fact_ids):
        """Trusted host-only handoff; deliberately absent from the model tool catalog."""
        if source.ws is not self.ws or not isinstance(fact_ids, list) or len(fact_ids) > 16 or any(
                type(fact_id) is not int or fact_id not in source.visible_facts for fact_id in fact_ids):
            raise PolicyDenied("Handoff requires visible evidence from the same workspace (at most 16 facts)")
        facts = {row["fact_id"]: row for row in self.ws.ledger.summaries()}
        selected = []
        for fact_id in dict.fromkeys(fact_ids):
            fact = facts[fact_id]
            if fact["role"] != source.role or fact["kind"] not in {"file", "symbol"}:
                raise PolicyDenied("Only role-owned file or symbol evidence can be handed off")
            selected.append((fact_id, fact, self.ws.ledger.recall(fact_id)))
        references = []
        for original, fact, payload in selected:
            copied = self.ws.ledger.add(fact["kind"], self.role, fact["summary"], payload)
            self.visible_facts.add(copied)
            if original in source.read_evidence:
                self.read_evidence[copied] = dict(source.read_evidence[original])
            self.ws.trace.emit(self.role, "evidence_handoff", source_role=source.role,
                               source_fact_id=original, fact_id=copied)
            text = json.dumps(payload, ensure_ascii=False)
            references.append({"fact_id": copied, "source_fact_id": original,
                               "preview": text[:4000], "truncated": len(text) > 4000})
        return references

    def catalog(self):
        tools = dict(TOOLS)
        if self.ws.compass_enabled:
            tools['get_symbols_overview'] = '{"file":"relative/file.py","depth":1,"offset":0} -> compact paged file outline; follow next_offset, then read selected source'
            tools.update(find_symbol='{"name": "symbol name"} -> exact symbol matches',
                         get_context='{"file": "relative/path.py", "line": 1} -> containing symbol and graph neighbors')
        if self.role == "implementer":
            tools["replace"] = '{"path": "declared file", "old": "unique text", "new": "replacement"}'
        if getattr(self.ws, "mcp_tools", None):
            tools.update(self.ws.mcp_tools.catalog(self.role))
        return tools

    def action_schema(self, *, excluded=()):
        branches = []
        for tool in self.catalog():
            if tool in excluded:
                continue
            arguments = {'type': 'object'}
            if tool.startswith('mcp__'):
                arguments = self.ws.mcp_tools.policy(tool).get('input_schema',arguments)
            if tool in LOCAL_CONTRACTS:
                required, optional = LOCAL_CONTRACTS[tool]
                arguments.update(properties={key: {'type': 'string' if kind is str else 'integer'}
                    for key, kind in {**required, **optional}.items()}, required=list(required),
                    additionalProperties=False)
                if tool == 'search_code':
                    arguments['properties']['paths'] = {'type':'array','minItems':1,'maxItems':32,'items':{'type':'string'}}
                if tool == 'read_lines':
                    for name in ('start_line', 'end_line'):
                        arguments['properties'][name]['minimum'] = 1
                    arguments['properties']['end_line']['description'] = 'Requested inclusive end. Host returns at most 80 lines/3000 characters and reports truncation/next_line.'
                if tool == 'read_page':
                    arguments['properties']['start_line']['minimum'] = 1
            branches.append({'type': 'object', 'properties': {
                'tool': {'type': 'string', 'enum': [tool]}, 'arguments': arguments},
                'required': ['tool', 'arguments'], 'additionalProperties': False})
        return {'oneOf': branches}

    def call(self, tool, args):
        call_id = uuid.uuid4().hex
        started = time.monotonic()
        status = "failed"
        error_type = None
        self.ws.trace.emit(self.role, "gateway_call_started", call_id=call_id,
                           tool=tool if isinstance(tool, str) else "<invalid>", transport=(
                               'mcp_'+self.ws.mcp_tools.transport(tool).replace('-','_')
                               if isinstance(tool,str) and tool in self.catalog() and tool.startswith('mcp__') else 'local'))
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
            if isinstance(tool, str) and tool.startswith('mcp__'):
                metrics = getattr(self.ws, 'external_tool_metrics', {})
                counts = metrics.setdefault(tool, {'completed': 0, 'failed': 0, 'denied': 0})
                counts[status] += 1
                self.ws.external_tool_metrics = metrics
            self.ws.trace.emit(self.role, "gateway_call_finished", call_id=call_id,
                               status=status, error_type=error_type,
                               seconds=max(0, time.monotonic() - started))

    @staticmethod
    def _validate(tool, args):
        required, optional = LOCAL_CONTRACTS[tool]
        if not isinstance(args, dict) or set(required) - args.keys() or args.keys() - (required.keys() | optional.keys()):
            raise ValueError(f"Invalid arguments for {tool}")
        for name, value in args.items():
            expected = {**required, **optional}[name]
            if type(value) is not expected:
                raise ValueError(f"{name} must be {expected.__name__}")
        if tool == "get_context" and args["line"] < 1:
            raise ValueError("line must be positive")
        if tool == 'read_page' and args['start_line'] < 1:
            raise ValueError('start_line must be positive')
        if tool == 'read_lines' and not (1 <= args['start_line'] <= args['end_line']):
            raise ValueError('read_lines requires positive inclusive bounds with end_line >= start_line')

    def _dispatch(self, tool, args):
        if tool in {'read_lines', 'read_page'}:
            value = self.ws.read(args['path'], role=self.role)
            lines = value['value'].splitlines(keepends=True)
            start = args['start_line']
            requested_end = start + 79 if tool == 'read_page' else args['end_line']
            end = min(start + 79, requested_end, len(lines))
            if start > len(lines):
                raise ValueError('start_line is outside file')
            selected, size = [], 0
            for line in lines[start-1:end]:
                if size + len(line) > 3000:
                    break
                selected.append(line)
                size += len(line)
            if not selected:
                raise ValueError('Source line exceeds read_lines character limit; use read_file and recall')
            last = start + len(selected) - 1
            payload = {'path': args['path'], 'start_line': start, 'end_line': last,
                'requested_end_line': requested_end,
                'truncated': last < min(requested_end, len(lines)),
                'total_lines': len(lines), 'text': ''.join(selected),
                'next_line': last + 1 if last < len(lines) else None,
                'source_sha256': hashlib.sha256(value['value'].encode('utf-8')).hexdigest()}
            fact_id = self.ws.ledger.add('file', self.role, 'read_lines evidence', payload)
            self.visible_facts.add(fact_id)
            self.observed_facts.add(fact_id)
            self.ws.trace.emit(self.role, 'ledger_write', fact_id=fact_id)
            return {'fact_id': fact_id, **payload}
        if tool.startswith("mcp__"):
            value = self.ws.mcp_tools.call(self.role, tool, args)
            fact_id = self.ws.ledger.add("symbol", self.role, tool + " evidence", value)
            self.visible_facts.add(fact_id)
            self.observed_facts.add(fact_id)
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
            if offset >= len(text):
                raise ValueError("offset is outside stored evidence; no further page exists")
            self.ws.trace.emit(self.role, "tool_call", tool="recall", fact_id=fact_id, offset=offset)
            return {"text": text[offset:offset + 4000], "next_offset": offset + 4000 if len(text) > offset + 4000 else None}
        if tool == "list_files":
            value = self.ws.list_files(role=self.role)
            kind = "file"
        elif tool == "read_file":
            value = self.ws.read(args["path"], role=self.role)
            canonical = self.ws.path(args['path']).relative_to(self.ws.root).as_posix()
            source_hash = hashlib.sha256(value['value'].encode('utf-8')).hexdigest()
            for previous, evidence in self.read_evidence.items():
                if previous in self.observed_facts and evidence == {'path': canonical, 'sha256': source_hash}:
                    return {'fact_id': previous, 'unchanged': True,
                        'message': 'Already read this unchanged file. Use search_code to locate relevant lines, then read_lines; use recall for stored evidence.'}
            kind = "file"
        elif tool == "search_code":
            if not isinstance(args["query"], str) or not args["query"].strip():
                raise ValueError("query must be nonempty text")
            value = self.ws.search(args["query"], role=self.role, **({"paths":args["paths"]} if "paths" in args else {}))
            kind = "symbol"
        elif tool == "find_symbol":
            value = self.ws.find_symbol(args["name"], role=self.role)
            kind = "symbol"
        elif tool == "get_context":
            value = self.ws.get_context(args["file"], args["line"], role=self.role)
            kind = "symbol"
        elif tool == 'get_symbols_overview':
            value = self.ws.get_symbols_overview(**args, role=self.role)
            kind = 'symbol'
        else:
            raise PolicyDenied(f"Unknown tool: {tool}")
        fact_id = self.ws.ledger.add(kind, self.role, tool + " evidence", value)
        self.visible_facts.add(fact_id)
        self.observed_facts.add(fact_id)
        if tool == "read_file":
            canonical = self.ws.path(args["path"]).relative_to(self.ws.root).as_posix()
            self.read_evidence[fact_id] = {"path": canonical,
                "sha256": hashlib.sha256(value["value"].encode("utf-8")).hexdigest()}
        text = json.dumps(value, ensure_ascii=False)
        self.ws.trace.emit(self.role, "ledger_write", fact_id=fact_id)
        return {"fact_id": fact_id, "preview": text[:4000], "truncated": len(text) > 4000}

