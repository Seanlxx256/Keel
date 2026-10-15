"""Small live schema-choice probe, not a coding benchmark or agent repair."""
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from keel.gateway import ToolGateway
from keel.models import OllamaModel


def main(output=None):
    output = output or Path(__file__).resolve().parents[1]/'.keel/protocol-probes'/uuid.uuid4().hex
    output.mkdir(parents=True)
    print(f'Artifacts: {output}', flush=True)
    gateway = ToolGateway('scout', SimpleNamespace(compass_enabled=False))
    final = {'type': 'object', 'properties': {'final': {'type': 'object', 'properties': {
        'summary': {'type': 'string'}, 'files': {'type': 'array', 'items': {'type': 'string'}}},
        'required': ['summary', 'files'], 'additionalProperties': False}},
        'required': ['final'], 'additionalProperties': False}
    tool = gateway.action_schema()
    variants = {'nested_tools_first': {'oneOf': [tool, final]},
                'flat_final_first': {'oneOf': [final, *tool['oneOf']]}}
    messages = [{'role': 'system', 'content': 'You are Scout. Return exactly one JSON action: tool/arguments or final. '
        'Scout only identifies affected files; it does not edit. Once evidence identifies the file, finish.'},
        {'role': 'user', 'content': 'Goal: change API_VERSION from 1 to 2. Tool read_file already returned '
         'app.py contents: API_VERSION = 1. Evidence is complete. Return final with summary and files ["app.py"]. Do not call another tool.'}]
    model = OllamaModel('keel-chat', num_ctx=4096, num_gpu=0)
    records = []
    for name, schema in variants.items():
        record = {'variant': name}
        try:
            reply = model.complete_json(messages, schema=schema, timeout=90, max_output=128)
            record.update(response=reply.content, tokens=reply.tokens)
            action = json.loads(reply.content)
            record['returned_final'] = set(action) == {'final'}
        except Exception as error:
            record['error'] = str(error)
        records.append(record)
        (output/'probe.json').write_text(json.dumps({'messages': messages, 'records': records,
            'limitations': 'Two schema variants on one explicit completion prompt; not a task success or causal runtime evaluation.'}, indent=2), encoding='utf-8')
        print(json.dumps(record), flush=True)
    patch_schema = {'type': 'object', 'properties': {'old': {'type': 'string'}, 'new': {'type': 'string'}},
                    'required': ['old', 'new'], 'additionalProperties': False}
    source = 'API_VERSION = 1\n\ndef greeting(name):\n    return "Hello, " + name\n'
    patch_messages = [{'role': 'system', 'content': 'Propose a minimal exact text replacement. Return JSON old/new strings. Do not claim tools or tests ran.'},
        {'role': 'user', 'content': 'Change API_VERSION from 1 to 2 and preserve greeting(name). Source:\n' + source}]
    record = {'variant': 'direct_patch_control', 'code_executed': False}
    try:
        reply = model.complete_json(patch_messages, schema=patch_schema, timeout=90, max_output=128)
        replacement = json.loads(reply.content)
        old, new = replacement['old'], replacement['new']
        record.update(response=reply.content, tokens=reply.tokens,
            exact_control_patch=bool(old) and source.count(old) == 1
                and source.replace(old, new) == source.replace('API_VERSION = 1', 'API_VERSION = 2'))
    except Exception as error:
        record['error'] = str(error)
    records.append(record)
    (output/'patch-control.json').write_text(json.dumps({'messages': patch_messages, 'record': record,
        'limitations': 'One synthetic patch-generation control, no autonomous tool execution, Docker acceptance or real repair.'}, indent=2), encoding='utf-8')
    print(json.dumps(record), flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
