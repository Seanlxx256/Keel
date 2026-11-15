"""Explicitly configured MCP stdio tools using the optional official v1 SDK."""
from __future__ import annotations

import asyncio
import json
import math
import re
import os
import contextvars
import uuid
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

from .core import PolicyDenied
from .async_process_lifecycle import run_request


class McpToolError(ValueError):
    pass


class McpTransportUnavailable(McpToolError):
    """Host transport setup failed before a tool RPC was dispatched."""


_request_state=contextvars.ContextVar('keel_mcp_request_state',default=None)


def request_phase(stage,**fields):
    state=_request_state.get()
    if state is not None:state.update(stage=stage,**fields)


def nested_os_error(error):
    if isinstance(error,OSError):return error
    if isinstance(error,BaseExceptionGroup):
        for child in error.exceptions:
            found=nested_os_error(child)
            if found is not None:return found
    return None


def nested_tool_error(error):
    """Recover only host-generated diagnostics from SDK task groups, never raw server exceptions."""
    if isinstance(error,McpToolError):
        return error
    if isinstance(error,BaseExceptionGroup):
        for child in error.exceptions:
            found=nested_tool_error(child)
            if found is not None:
                return found
    return None


def validate_servers(servers, *, discovery=False):
    if not isinstance(servers, dict):
        raise ValueError('mcp_servers must be an object')
    for name, spec in servers.items():
        if not isinstance(name, str) or (not re.fullmatch(r'[A-Za-z0-9_-]+', name) or '__' in name):
            raise ValueError('MCP server names must contain letters, digits, underscores or hyphens')
        if not isinstance(spec, dict) or set(spec) - {'transport', 'command', 'args', 'tools', 'timeout', 'url', 'headers_env', 'env'}:
            raise ValueError('Invalid MCP server configuration')
        transport = spec.get('transport', 'stdio')
        if transport not in ('stdio','streamable-http'):
            raise ValueError('MCP transport must be stdio or streamable-http')
        if transport == 'stdio' and (not isinstance(spec.get('command'), str) or not spec['command'].strip()):
            raise ValueError('MCP server requires an executable command')
        if transport == 'stdio' and set(spec) & {'url','headers_env'}:
            raise ValueError('HTTP fields cannot be used for stdio')
        if transport == 'streamable-http':
            parsed = urlsplit(spec.get('url',''))
            if (parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username or parsed.password or parsed.fragment or
                    (parsed.scheme=='http' and parsed.hostname not in ('localhost','127.0.0.1','::1'))):
                raise ValueError('Remote MCP requires HTTPS; HTTP allowed only on loopback; no URL credentials')
            if set(spec) & {'command','args','env'}:
                raise ValueError('Stdio fields cannot be used for HTTP')
        for field in ('env','headers_env'):
            mapping=spec.get(field,{})
            if not isinstance(mapping,dict) or any(not isinstance(k,str) or not re.fullmatch(r'[A-Za-z0-9_-]+',k) or
                not isinstance(v,str) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*',v) for k,v in mapping.items()):
                raise ValueError('MCP credentials must reference environment variable names')
        if not isinstance(spec.get('args', []), list) or any(not isinstance(a, str) for a in spec.get('args', [])):
            raise ValueError('MCP args must be a string array')
        timeout = spec.get('timeout', 30)
        if type(timeout) not in {int, float} or not math.isfinite(timeout) or not 0 < timeout <= 300:
            raise ValueError('MCP timeout must be positive and at most 300 seconds')
        if not isinstance(spec.get('tools', {}), dict) or (not discovery and not spec.get('tools')):
            raise ValueError('MCP tools require an explicit nonempty allowlist')
        for tool, policy in spec.get('tools', {}).items():
            if not isinstance(tool, str) or not re.fullmatch(r'[A-Za-z0-9_.-]+', tool):
                raise ValueError('Invalid MCP tool name')
            if not isinstance(policy, dict) or not {'roles','description'}<=policy.keys() or set(policy)-{'roles','description','input_schema','read_only'}:
                raise ValueError('Each MCP tool requires roles and description')
            if 'input_schema' in policy and (not isinstance(policy['input_schema'],dict) or policy['input_schema'].get('type')!='object'):
                raise ValueError('MCP input_schema must describe an object')
            if 'read_only' in policy and type(policy['read_only']) is not bool:
                raise ValueError('MCP read_only must be boolean')
            roles = policy['roles']
            if not isinstance(roles, list) or not roles or any(not isinstance(r, str) or r not in {'scout', 'planner', 'implementer'} for r in roles):
                raise ValueError('Invalid MCP tool roles')
            if not isinstance(policy['description'], str) or not policy['description'].strip():
                raise ValueError('MCP tool requires an operator-supplied description and argument contract')


class McpTools:
    def __init__(self, servers, workspace, *, discovery=False, before_tool_call=None, after_tool_result=None, request_control=None):
        validate_servers(servers, discovery=discovery)
        self.servers, self.ws = servers, workspace
        self.before_tool_call,self.after_tool_result=before_tool_call,after_tool_result
        self.request_control=request_control

    def catalog(self, role):
        return {f'mcp__{server}__{tool}': policy['description']
                for server, spec in self.servers.items() for tool, policy in spec.get('tools', {}).items()
                if role in policy['roles']}

    def discover(self, server):
        """Operator-only schema discovery; never grants role permissions or calls a tool."""
        if server not in self.servers:
            raise ValueError('Unknown configured MCP server')
        return self._request(server,self.servers[server],None,None)

    def policy(self, alias):
        for server,spec in self.servers.items():
            for tool,policy in spec['tools'].items():
                if alias == f'mcp__{server}__{tool}':
                    return policy
        raise PolicyDenied('Unknown MCP tool alias')

    def transport(self, alias):
        for server,spec in self.servers.items():
            if any(alias==f'mcp__{server}__{tool}' for tool in spec['tools']):
                return spec.get('transport','stdio')
        raise PolicyDenied('Unknown MCP tool alias')

    @staticmethod
    def _environment(mapping):
        values={}
        for key,name in mapping.items():
            value=os.environ.get(name)
            if not value:
                raise McpToolError('Required MCP credential environment variable is missing: '+name)
            values[key]=value
        return values

    @asynccontextmanager
    async def _connection(self,spec,stderr):
        if spec.get('transport','stdio')=='streamable-http':
            from mcp.client.streamable_http import streamablehttp_client
            async with streamablehttp_client(spec['url'],headers=self._environment(spec.get('headers_env',{})),
                                             timeout=spec.get('timeout',30)) as (reader,writer,_):
                yield reader,writer
        else:
            from mcp import StdioServerParameters
            from mcp.client.stdio import stdio_client
            parameters=StdioServerParameters(command=spec['command'],args=spec.get('args',[]),
                cwd=str(self.ws.root),env=self._environment(spec.get('env',{})) or None)
            async with stdio_client(parameters,errlog=stderr) as streams:
                yield streams

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
        return self._request(server,spec,tool,arguments)

    def _request(self, server, spec, tool, arguments):
        self.ws.budget.charge_tool()
        timeout = min(spec.get('timeout', 30), self.ws.budget.remaining)
        log = self.ws.trace.path.parent / f'mcp-{server}.stderr.log'
        state={'stage':'request','tool_dispatch_started':False,'reply_received':False,
               'transport':spec.get('transport','stdio')}
        token=_request_state.set(state)
        try:
            with log.open('a', encoding='utf-8') as stderr:
                factory=lambda:asyncio.wait_for(self._invoke(spec,tool,arguments,stderr),timeout)
                return (run_request(factory,control=self.request_control) if self.request_control is not None else run_request(factory))
        except asyncio.CancelledError:
            raise self._record_failure(server,McpToolError('MCP request cancelled; inspect lifecycle evidence'),state) from None
        except PolicyDenied:
            raise
        except Exception as error:
            raise self._record_failure(server,error,state) from None
        finally:_request_state.reset(token)

    def _record_failure(self,server,error,state):
        host_error=nested_tool_error(error);os_error=nested_os_error(error)
        startup=(not state['tool_dispatch_started'] and state['stage']=='transport_start'
                 and os_error is not None and host_error is None)
        category=('transport_unavailable' if startup else 'tool_outcome_unknown'
                  if state['tool_dispatch_started'] and not state['reply_received'] else 'tool_or_protocol_error')
        failure={**state,'category':category,'error_type':type(error).__name__,'automatic_retry':False,
                 'scope':'Host-observed stage; no claim that external processes or side effects never occurred'}
        if os_error is not None:
            failure['os_error']={'type':type(os_error).__name__,
                **{name:getattr(os_error,name) for name in ('errno','winerror') if type(getattr(os_error,name,None)) is int}}
        if startup:
            result=McpTransportUnavailable('MCP transport startup unavailable ('+type(os_error).__name__+'); no tool RPC dispatched')
        else:
            result=host_error or McpToolError('MCP request failed ('+type(error).__name__+'); inspect host failure receipt')
        artifact=self.ws.trace.path.parent/('mcp-'+server+'.failure-'+uuid.uuid4().hex+'.json')
        from compass.progress import atomic_json
        try:atomic_json(artifact,failure)
        except Exception:
            from .governance import GovernanceUnavailable
            raise GovernanceUnavailable('Required MCP failure receipt could not be saved') from None
        result.failure={**failure,'artifact':str(artifact)}
        return result

    async def _invoke(self, spec, tool, arguments, stderr):
        request_phase('dependencies')
        try:
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client
            from jsonschema import Draft202012Validator
        except ImportError:
            raise McpToolError('MCP client requires pip install -e ".[mcp]"') from None
        request_phase('transport_start')
        async with self._connection(spec,stderr) as (reader, writer):
            request_phase('initialize')
            async with ClientSession(reader, writer) as session:
                await session.initialize()
                request_phase('discovery')
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
                if tool is None:
                    names=[entry.name for entry in tools]
                    if len(names)!=len(set(names)):
                        raise McpToolError('MCP tool discovery returned duplicate names')
                    value={'tools':[{'name':entry.name,'description':getattr(entry,'description',None),
                        'input_schema':entry.inputSchema} for entry in tools],
                        'scope':'Untrusted server metadata; discovery does not authorize any tools'}
                    if len(json.dumps(value).encode('utf-8'))>1_000_000:
                        raise McpToolError('MCP discovery result exceeds 1 MB')
                    return value
                found = [entry for entry in tools if entry.name == tool]
                if len(found) != 1:
                    raise McpToolError('Allowlisted MCP tool is missing or duplicated on server')
                request_phase('validation')
                validator = Draft202012Validator(found[0].inputSchema)
                if not validator.is_valid(arguments):
                    raise McpToolError('MCP arguments do not match the server input schema')
                policy=spec['tools'][tool]
                if 'input_schema' in policy and not Draft202012Validator(policy['input_schema']).is_valid(arguments):
                    raise McpToolError('MCP arguments do not match the operator input schema')
                if self.before_tool_call is not None:self.before_tool_call()
                request_phase('tool_dispatch',tool_dispatch_started=True)
                result = await session.call_tool(tool, arguments=arguments)
                request_phase('tool_result',reply_received=True)
                if self.after_tool_result is not None:self.after_tool_result()
                if result.isError:
                    # Preserve untrusted error evidence without echoing potential secrets.
                    artifact=self.ws.trace.path.parent/'mcp-tool-error.json'
                    payload=result.model_dump(mode='json',by_alias=True,exclude_none=True) if hasattr(result,'model_dump') else {'isError':True}
                    text=json.dumps(payload,ensure_ascii=False)
                    if len(text.encode('utf-8'))<=1_000_000:
                        artifact.write_text(text,encoding='utf-8')
                    raise McpToolError('MCP server returned a tool error; inspect mcp-tool-error.json if present (untrusted server output)')
                value = result.model_dump(mode='json', by_alias=True, exclude_none=True)
                if len(json.dumps(value, ensure_ascii=False).encode('utf-8')) > 1_000_000:
                    raise McpToolError('MCP result exceeds 1 MB')
                return value
