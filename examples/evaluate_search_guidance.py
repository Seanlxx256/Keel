"""Small synthetic tool-contract evaluation; no task-repair efficacy claims."""
import argparse
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from keel.core import Budget, Limits, Ledger, Trace
from keel.gateway import ToolGateway
from keel.models import from_config
from keel.workspace import Workspace


# Independent of historical repository examples; labels never enter model input.
CASES = [
    ('identifier', 'def refresh_session():\n    return 1\n',
     'Locate refresh_session and its implementation.', 'refresh_session'),
    ('phrase', '# cache entry expired\nVALUE = 1\n',
     'Find the exact diagnostic text: cache entry expired', 'cache entry expired'),
    ('case', 'def normalize_packet():\n    return 1\n',
     'A failure record names NORMALIZE_PACKET. Locate its definition.', 'normalize_packet'),
    ('miss', 'def flush_queue():\n    return 1\n',
     'The literal query "flush_queue execution path" returned no matches. Locate flush_queue.', 'flush_queue'),
    ('decoy', 'def load_profile():\n    return 1\n',
     'Locate load_profile in module.py; other.py contains a decoy with the same name.', 'load_profile'),
    ('absent', 'VALUE = 1\n',
     'Search for missing_handler. If no matches occur, decide whether this proves the behavior is absent.', None),
]
SCHEMA = {'type': 'object', 'properties': {
    'query': {'type': 'string', 'minLength': 1, 'maxLength': 200},
    'paths': {'type': 'array', 'items': {'type': 'string'}, 'minItems': 1, 'maxItems': 1},
    'zero_hits_prove_absence': {'type': 'boolean'}},
    'required': ['query', 'paths', 'zero_hits_prove_absence'], 'additionalProperties': False}


def score(workspace, response, expected):
    if (not isinstance(response, dict) or set(response) != set(SCHEMA['required'])
            or response['paths'] != ['module.py']
            or not isinstance(response['query'], str) or not 1 <= len(response['query']) <= 200
            or type(response['zero_hits_prove_absence']) is not bool):
        return {'passed': False, 'reason': 'invalid_contract'}
    result = ToolGateway('scout', workspace).call('search_code', {
        'query': response['query'], 'paths': response['paths']})
    matches = workspace.ledger.recall(result['fact_id'])['matches']
    located = (any(expected.casefold() in row['text'].casefold() for row in matches)
               if expected else response['query'].casefold() == 'missing_handler' and not matches)
    return {'passed': bool(located and not response['zero_hits_prove_absence']),
            'match_count': len(matches), 'matches': matches}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--guidance', type=Path, required=True)
    parser.add_argument('--model-config', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    guidance_bytes = args.guidance.read_bytes()
    guidance = json.loads(guidance_bytes)
    model = None
    if args.execute:
        if not args.model_config:
            parser.error('--execute requires --model-config')
        model = from_config(json.loads(args.model_config.read_text(encoding='utf-8')))
        if hasattr(model, 'check_credentials'):
            model.check_credentials()
    args.output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    report = {'status': 'prepared', 'model_calls': 0, 'tokens': 0, 'records': [],
              'implementation_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'model_config_sha256': hashlib.sha256(args.model_config.read_bytes()).hexdigest() if args.model_config else None,
              'guidance_sha256': hashlib.sha256(guidance_bytes).hexdigest(),
              'cases_sha256': hashlib.sha256(json.dumps(CASES).encode()).hexdigest(),
              'limits': {'model_calls': 12, 'per_call_timeout': 45, 'max_output': 256},
              'scope': 'Six synthetic search-selection cases, one sample per arm; not repair efficacy or statistical evidence.'}
    try:
        if model:
            for index, (case_id, source, task, expected) in enumerate(CASES):
                # Counterbalance arm order; neither arm sees the other's answer.
                arms = ['baseline', 'candidate'] if index % 2 == 0 else ['candidate', 'baseline']
                for arm in arms:
                    if time.monotonic() - started >= 600:
                        raise TimeoutError('Evaluation wall-clock budget exhausted')
                    messages = [{'role': 'system', 'content': 'Choose a search_code request. Return only the requested JSON. '
                                 + guidance['baseline' if arm == 'baseline' else 'candidate']},
                                {'role': 'user', 'content': task + '\nReadable target: module.py'}]
                    report['model_calls'] += 1
                    reply = model.complete_json(messages, schema=SCHEMA, timeout=45, max_output=256)
                    report['tokens'] += reply.tokens or 0
                    (args.output/f'{case_id}-{arm}-reply.json').write_text(
                        json.dumps({'content': reply.content, 'tokens': reply.tokens, 'metadata': reply.metadata}, indent=2),
                        encoding='utf-8')
                    response = json.loads(reply.content)
                    with tempfile.TemporaryDirectory() as temporary:
                        root = Path(temporary)
                        (root/'module.py').write_bytes(source.encode())
                        (root/'other.py').write_bytes(b'def load_profile():\n    return 999\n')
                        with closing(Ledger(root/'ledger.sqlite')) as ledger:
                            workspace = Workspace(root, Budget(Limits(max_tool_calls=1)), ledger, Trace(root/'trace.jsonl'))
                            outcome = score(workspace, response, expected)
                    report['records'].append({'case': case_id, 'arm': arm, 'response': response, **outcome})
                    (args.output/'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
            report['status'] = 'completed'
    except Exception as error:
        report.update(status='incomplete', error_type=type(error).__name__)
        raise
    finally:
        report['seconds'] = time.monotonic() - started
        (args.output/'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
