"""Exercise an operator-configured MCP tool without an LLM."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from keel.core import Budget, Limits, Ledger, Trace
from keel.workspace import Workspace
from keel.mcp_client import McpTools, McpToolError
from keel.gateway import ToolGateway


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',required=True,type=Path)
    parser.add_argument('--repo',required=True,type=Path)
    parser.add_argument('--tool',required=True)
    group=parser.add_mutually_exclusive_group()
    group.add_argument('--arguments',default=None)
    group.add_argument('--arguments-file',type=Path)
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=False)
    ledger=Ledger(args.output/'ledger.sqlite')
    report={'status':'failed','model_calls':0,'python':sys.executable}
    try:
        workspace=Workspace(args.repo.resolve(),Budget(Limits(max_tool_calls=3,max_wallclock=120)),ledger,Trace(args.output/'trace.jsonl'))
        workspace.mcp_tools=McpTools(json.loads(args.config.read_text(encoding='utf-8')),workspace)
        raw=args.arguments_file.read_text(encoding='utf-8') if args.arguments_file else args.arguments or '{}'
        result=ToolGateway('scout',workspace).call(args.tool,json.loads(raw))
        report.update(status='completed',fact_id=result['fact_id'])
    except Exception as error:
        # Avoid printing arbitrary server error text or credentials.
        report['error_type']=type(error).__name__
        if isinstance(error,McpToolError):
            report['diagnostic']=str(error)
    finally:
        ledger.close()
        (args.output/'check.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report))
    return 0 if report['status']=='completed' else 1


if __name__=='__main__':
    raise SystemExit(main())
