"""One live synthetic proposal edit; acceptance reads text without importing generated code."""
import json
from pathlib import Path
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from keel.runtime import run


def main():
    output = Path(__file__).resolve().parents[1]/'.keel/proposal-controls'/uuid.uuid4().hex
    repo = output/'repo'
    repo.mkdir(parents=True)
    print(f'Artifacts: {output}', flush=True)
    (repo/'app.py').write_text('API_VERSION = 1\n', encoding='utf-8')
    config = {'mode': 'proposal', 'goal': 'Change API_VERSION in app.py from 1 to 2.',
        'proposal': {'files': ['app.py'], 'queries': ['API_VERSION']},
        'model': {'provider': 'ollama', 'name': 'keel-chat', 'num_ctx': 4096, 'num_gpu': 0},
        'agent': {'max_output': 256, 'max_context_bytes': 12000},
        'budget': {'max_wallclock': 180, 'max_tokens': 100000, 'max_model_calls': 1, 'max_tool_calls': 20},
        'acceptance': [[sys.executable, '-c', 'from pathlib import Path; assert Path("app.py").read_text() == "API_VERSION = 2\\n"']]}
    result = run(config, repo, output/'run')
    summary = {'status': result['status'], 'failure': result['failure'], 'budget': result['budget'],
        'changed_files': result.get('audit', {}).get('changed_files', []),
        'source': (repo/'app.py').read_text(), 'benchmark_ready': False,
        'limitations': 'One synthetic constant edit, local text-only acceptance. No generated source execution, Docker or real repair claim.'}
    (output/'summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    print(json.dumps(summary, indent=2))
    return 0 if result['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
