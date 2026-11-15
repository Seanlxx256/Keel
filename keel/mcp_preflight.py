"""Zero-model transport capability checks; not MCP server acceptance."""
import importlib.util
import math
import platform
import sys

from .ipc import probe_async_stdio


def validate_policy(policy):
    if policy is None:return
    if not isinstance(policy,dict) or set(policy)-{'mode','timeout_seconds'}:
        raise ValueError('mcp_preflight accepts mode and timeout_seconds')
    if policy.get('mode','strict') not in ('strict','advisory'):raise ValueError('Invalid MCP preflight mode')
    timeout=policy.get('timeout_seconds',8)
    if type(timeout) not in (int,float) or not math.isfinite(timeout) or not 0<timeout<=15:
        raise ValueError('MCP preflight timeout must be positive and at most 15 seconds')


def check_host(servers,*,timeout=8):
    validate_policy({'timeout_seconds':timeout})
    from .mcp_client import validate_servers
    validate_servers(servers)
    report={'status':'not_required','interpreter':sys.executable,'python':platform.python_version(),
            'model_calls':0,'mcp_tool_calls':0,'checks':{},
            'scope':'Current host dependencies and bare async pipe capability only; no server/credential/tool acceptance'}
    if not servers:return report
    dependencies={name:importlib.util.find_spec(name) is not None for name in ('mcp','jsonschema')}
    report['checks']['dependencies']=dependencies
    if not all(dependencies.values()):
        report['status']='unavailable';return report
    if any(spec.get('transport','stdio')=='stdio' for spec in servers.values()):
        probe=probe_async_stdio(sys.executable,timeout=timeout)
        report['checks']['async_stdio']=probe
        report['status']='ok' if probe['status']=='ok' else 'unavailable'
    else:report['status']='ok'
    if any(spec.get('transport')=='streamable-http' for spec in servers.values()):
        report['checks']['remote_http']={'status':'not_probed','reason':'No remote credential or endpoint call in this host capability probe'}
    return report


def check_workspace(workspace,policy):
    """Check each execution host; never infer controller capability from worker."""
    validate_policy(policy)
    if policy is None:return {'status':'disabled','hosts':{},'model_calls':0,'mcp_tool_calls':0}
    workspace.budget.check()
    timeout=min(policy.get('timeout_seconds',8),max(.01,workspace.budget.remaining))
    tools=workspace.mcp_tools;local=getattr(tools,'local',tools)
    checks={}
    if getattr(local,'servers',{}):checks['worker_host']=check_host(local.servers,timeout=timeout)
    governance=getattr(workspace,'governance',None)
    if governance and (governance.config.get('mcp_broker') or {}).get('tools'):
        checks['controller_host']=governance.preflight_mcp(min(timeout,max(.01,workspace.budget.remaining)))
    status=('unavailable' if any(value['status']=='unavailable' for value in checks.values())
            else 'not_probed' if any(value['status']=='not_probed' for value in checks.values())
            else 'ok' if checks else 'not_required')
    return {'mode':policy.get('mode','strict'),'status':status,'hosts':checks,'model_calls':0,'mcp_tool_calls':0}
