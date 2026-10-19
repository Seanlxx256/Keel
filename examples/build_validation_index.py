"""Bounded index-build subprocess with durable vector checkpoints and progress."""
import argparse
import json
from pathlib import Path
import sys
import time
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from compass.index import build_index, RepositoryIndex
from compass.vectors import OllamaEmbedder
from compass.progress import atomic_json
from keel.experience import ExperienceStore, RecoverySession


def build(repo, output, model, timeout):
    started = time.monotonic()
    latest = {}
    store = ExperienceStore(Path(__file__).resolve().parents[1]/'.keel/experience/operations.sqlite')
    recovery = RecoverySession(task=str(output.resolve()), store=store, max_actions=2,
                               deadline=started+timeout)
    def save(value):
        publisher = RecoverySession(task=str(output.resolve()), store=store, max_actions=7,
                                    deadline=started+timeout+5)
        atomic_json(output, value, recovery=publisher)
    last_progress = {'time': 0, 'stage': None}
    def progress(value):
        latest.update(value)
        now = time.monotonic()
        if value['stage'] == last_progress['stage'] and now-last_progress['time'] < 1:
            return
        last_progress.update(time=now, stage=value['stage'])
        try:
            save({'status': 'running', 'model_digest': model_digest, **value})
        except PermissionError as error:
            # Telemetry is best effort; vector checkpoints remain mandatory.
            print('Progress publish sharing violation (index continues): '+str(error), file=sys.stderr, flush=True)
    embedder = OllamaEmbedder(model, 'http://localhost:11434', timeout=120, num_batch=32)
    embedder.keep_alive = '5m'
    save({'status': 'running', 'stage': 'model_identity'})
    try:
        with urllib.request.urlopen('http://localhost:11434/api/tags', timeout=10) as response:
            inventory = json.load(response)
        matches = [r for r in inventory['models'] if r['name'] in (model, model+':latest')]
        if len(matches) != 1 or not matches[0].get('digest'):
            raise ValueError('Cannot establish embedding model identity')
        model_digest = matches[0]['digest']
        embedder.checkpoint_identity = {'spec': embedder.spec, 'model_digest': model_digest}
        try:
            with RepositoryIndex(repo) as current:
                if not current.stale and current.metadata['parser'] == 'tree-sitter' and \
                        current.metadata['vector_store'] == 'sqlite' and current.metadata['embedding'] == embedder.spec and \
                        current.metadata.get('embedding_checkpoint_identity') == embedder.checkpoint_identity:
                    save({'status': 'completed', 'stage': 'reused_index', 'generation': current.metadata['generation']})
                    return
        except (OSError, ValueError):
            pass
        metadata = build_index(repo, parser='tree-sitter', vector_store='sqlite', embedder=embedder,
            progress=progress,
            max_wallclock=timeout, checkpoint_vectors=True, embedding_attempts=3, recovery=recovery)
        save({'status': 'completed', 'stage': 'finished', 'generation': metadata['generation'],
              'update': metadata['update'], 'model_digest': model_digest, 'recovery': recovery.events})
    except Exception as error:
        save({**latest, 'status': 'failed', 'error_type': type(error).__name__, 'error': str(error)[:1500],
              'failure_category': 'budget_exhausted' if isinstance(error, TimeoutError) else getattr(error, 'category', 'index_error'),
              'worker_elapsed_seconds': round(time.monotonic()-started, 2), 'wallclock_limit': timeout,
              'cause_type': type(error.__cause__).__name__ if error.__cause__ else None, 'recovery': recovery.events})
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', required=True, type=Path)
    parser.add_argument('--progress', required=True, type=Path)
    parser.add_argument('--model', required=True)
    parser.add_argument('--timeout', type=float, default=1800)
    args = parser.parse_args()
    build(args.repo, args.progress, args.model, args.timeout)
