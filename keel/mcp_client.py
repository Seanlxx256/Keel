"""Explicitly configured MCP stdio tools using the optional official v1 SDK."""
from __future__ import annotations

import asyncio
import json
import math
import re

from .core import PolicyDenied


class McpToolError(ValueError):
    pass


def validate_servers(servers):
    if not isinstance(servers, dict):
        raise ValueError('mcp_servers must be an object')
    for name, spec in servers.items():
        if not isinstance(name, str) or (not re.fullmatch(r'[A-Za-z0-9_-]+', name) or '__' in name):
            raise ValueError('MCP server names must contain letters, digits, underscores or hyphens')
        if not isinstance(spec, dict) or set(spec) - {'command', 'args', 'tools', 'timeout'}:
            raise ValueError('Invalid MCP server configuration')
        if not isinstance(spec.get('command'), str) or not spec['command'].strip():
            raise ValueError('MCP server requires an executable command')
        if not isinstance(spec.get('args', []), list) or any(not isinstance(a, str) for a in spec.get('args', [])):
            raise ValueError('MCP args must be a string array')
        timeout = spec.get('timeout', 30)
        if type(timeout) not in {int, float} or not math.isfinite(timeout) or not 0 < timeout <= 300:
            raise ValueError('MCP timeout must be positive and at most 300 seconds')
        if not isinstance(spec.get('tools'), dict) or not spec['tools']:
            raise ValueError('MCP tools require an explicit nonempty allowlist')
        for tool, policy in spec['tools'].items():
            if not isinstance(tool, str) or not re.fullmatch(r'[A-Za-z0-9_.-]+', tool):
                raise ValueError('Invalid MCP tool name')
            if not isinstance(policy, dict) or set(policy) != {'roles', 'description'}:
                raise ValueError('Each MCP tool requires roles and description')
            roles = policy['roles']
            if not isinstance(roles, list) or not roles or any(not isinstance(r, str) or r not in {'scout', 'planner', 'implementer'} for r in roles):
                raise ValueError('Invalid MCP tool roles')
            if not isinstance(policy['description'], str) or not policy['description'].strip():
                raise ValueError('MCP tool requires an operator-supplied description and argument contract')


class McpTools:
    def __init__(self, servers, workspace):
        validate_servers(servers)
        self.servers, self.ws = servers, workspace

    def catalog(self, role):
        return {f'mcp__{server}__{tool}': policy['description']
                for server, spec in self.servers.items() for tool, policy in spec['tools'].items()
                if role in policy['roles']}

    def call(self, role, alias, arguments):
        if alias not in self.catalog(role):
            raise PolicyDenied('MCP tool is not allowed for this role')
        if not isinstance(arguments, dict):
            raise ValueError('MCP arguments must be an object')
        # Match exact generated aliases; never infer executable commands from model text.
        matches = [(server, tool, spec) for server, spec in self.servers.items()
                   for tool in spec['tools'] if f'mcp__{server}__{tool}' == alias]
        if len(matches) != 1:
            raise ValueError('Ambiguous MCP tool alias')
        server, tool, spec = matches[0]
        self.ws.budget.charge_tool()
        timeout = min(spec.get('timeout', 30), self.ws.budget.remaining)
        log = self.ws.trace.path.parent / f'mcp-{server}.stderr.log'
        try:
            with log.open('a', encoding='utf-8') as stderr:
                return asyncio.run(asyncio.wait_for(self._invoke(spec, tool, arguments, stderr), timeout))
        except (PolicyDenied, McpToolError):
            raise
        except Exception as error:
            # Server error strings may contain environment values or credentials.
            raise McpToolError(f'MCP request failed ({type(error).__name__}); inspect server stderr log') from None

    async def _invoke(self, spec, tool, arguments, stderr):
        try:
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client
            from jsonschema import Draft202012Validator
        except ImportError:
            raise McpToolError('MCP client requires pip install -e ".[mcp]"') from None
        parameters = StdioServerParameters(command=spec['command'], args=spec.get('args', []),
                                           cwd=str(self.ws.root))
        async with stdio_client(parameters, errlog=stderr) as (reader, writer):
            async with ClientSession(reader, writer) as session:
                await session.initialize()
                tools, cursor, seen = [], None, set()
                for _ in range(100):
                    page = await session.list_tools(**({'cursor': cursor} if cursor else {}))
                    tools.extend(page.tools)
                    cursor = page.nextCursor
                    if not cursor:
                        break
                    if cursor in seen:
                        raise McpToolError('Repeated MCP tool pagination cursor')
                    seen.add(cursor)
                else:
                    raise McpToolError('MCP tool discovery exceeded pagination limit')
                found = [entry for entry in tools if entry.name == tool]
                if len(found) != 1:
                    raise McpToolError('Allowlisted MCP tool is missing or duplicated on server')
                validator = Draft202012Validator(found[0].inputSchema)
                if not validator.is_valid(arguments):
                    raise McpToolError('MCP arguments do not match the server input schema')
                result = await session.call_tool(tool, arguments=arguments)
                if result.isError:
                    raise McpToolError('MCP server returned a tool error')
                value = result.model_dump(mode='json', by_alias=True, exclude_none=True)
                if len(json.dumps(value, ensure_ascii=False).encode('utf-8')) > 1_000_000:
                    raise McpToolError('MCP result exceeds 1 MB')
                return value
