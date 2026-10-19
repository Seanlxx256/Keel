"""Prepare an opt-in Scout text-search profile bound to each active workspace."""
import argparse
import hashlib
import json
from pathlib import Path
import sys


def prepare(output):
    project=Path(__file__).resolve().parents[1]
    config=json.loads((project/'examples/mcp-compass-text.json').read_text(encoding='utf-8'))
    launcher=project/'examples/compass_mcp_entry.py'
    config['compass'].update(command=sys.executable,args=[str(launcher),'serve','--repo','.',
        '--enable-text-search'])
    output.mkdir(parents=True,exist_ok=False)
    path=output/'config.json';path.write_text(json.dumps(config,indent=2),encoding='utf-8')
    report=dict(status='configured',config=str(path.resolve()),python=sys.executable,
        tools_authorized=['mcp__compass__search_text'],roles=['scout'],model_calls=0,
        launcher_sha256=hashlib.sha256(launcher.read_bytes()).hexdigest(),
        scope='Configuration prepared only; no external process/LLM called. Repo follows active Workspace cwd.')
    (output/'setup.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True,type=Path)
    print(json.dumps(prepare(parser.parse_args().output.resolve()),indent=2))
