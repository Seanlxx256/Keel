"""Compare fixed synchronous/asynchronous pipe controls; no MCP server or API calls."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from compass.progress import atomic_json
from keel.ipc import probe_async_stdio, probe_sync_stdio


def execute(output,*,timeout=8):
    from keel.mcp_preflight import validate_policy
    validate_policy({'timeout_seconds':timeout})
    output=Path(output)
    # Create required sink before work; preserve all earlier attempts.
    output.mkdir(parents=True,exist_ok=False)
    report={'status':'running','python':sys.executable,'model_calls':0,'mcp_tool_calls':0,
            'scope':'Current shell/interpreter fixed pipe controls; no configured MCP server, permissions or readiness certification',
            'checks':{}}
    atomic_json(output/'report.json',report)
    for name,probe in [('sync_stdio',probe_sync_stdio),('async_stdio',probe_async_stdio)]:
        print('[MCP host] '+name+'; timeout <= '+str(timeout)+'s',flush=True)
        report['checks'][name]=probe(sys.executable,timeout=timeout)
        atomic_json(output/'report.json',report)
    sync=report['checks']['sync_stdio']['status'];asynchronous=report['checks']['async_stdio']['status']
    report['status']='available' if sync==asynchronous=='ok' else 'unavailable'
    report['observation']=('async_only_unavailable' if sync=='ok' and asynchronous!='ok'
                           else 'both_controls_available' if report['status']=='available' else 'pipe_controls_unavailable')
    atomic_json(output/'report.json',report)
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--timeout',type=float,default=8)
    args=parser.parse_args()
    result=execute(args.output,timeout=args.timeout)
    print(json.dumps(result),flush=True)
    sys.exit(0 if result['status']=='available' else 1)
