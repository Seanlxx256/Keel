"""Score query/code pairs with installed Sentence Transformers; input contains no labels."""
import argparse
import hashlib
from importlib import metadata
import json
import math
from pathlib import Path
import time


def stable_order(scores, count):
    if len(scores) != count or any(not math.isfinite(float(s)) for s in scores):
        raise ValueError('Expected one finite score per original candidate')
    return sorted(range(count), key=lambda i: (-float(scores[i]), i))


def run(input_path, output):
    raw = input_path.read_bytes()
    config = json.loads(raw)
    report = {'status': 'running', 'stage': 'load_model', 'input_sha256': hashlib.sha256(raw).hexdigest(),
              'generation_model_calls': 0, 'pair_count': 0, 'new_pair_count': 0, 'reused_pair_count': 0, 'jobs': []}
    def save():
        temporary = output.with_suffix('.tmp')
        temporary.write_text(json.dumps(report, indent=2), encoding='utf-8')
        temporary.replace(output)
    started = time.monotonic()
    save()
    try:
        cached = {job['id']: job for job in config.get('completed_jobs', [])}
        if len(cached) != len(config.get('completed_jobs', [])):
            raise ValueError('Duplicate completed job')
        pending = [job for job in config['jobs'] if job['id'] not in cached]
        model = None
        if pending:
            import torch
            from sentence_transformers import CrossEncoder
            torch.manual_seed(0)
            torch.set_num_threads(4)
            model = CrossEncoder(config['model'], revision=config.get('revision'), device='cpu',
                max_length=512, cache_folder=config['cache'], trust_remote_code=False,
                local_files_only=config.get('local_files_only', False))
        report.update(model=config['model'], requested_revision=config.get('revision'),
            resolved_revision=getattr(getattr(getattr(model, 'model', None), 'config', None), '_commit_hash', None),
            versions={name: metadata.version(name) for name in ('sentence-transformers', 'torch', 'transformers')} if pending else {},
            max_pair_tokens=512, truncation='Upstream tokenizer truncation; full query and source range supplied',
            device='cpu', load_seconds=time.monotonic()-started)
        for job in config['jobs']:
            report['stage'] = 'score:'+job['id']
            save()
            pairs = [(job['query'], d['text']) for d in job['documents']]
            if job['id'] in cached:
                previous = cached[job['id']]
                if stable_order(previous['scores'], len(pairs)) != previous['order']:
                    raise ValueError('Cached scoring order mismatch')
                report['jobs'].append({**previous, 'reused': True})
                report['pair_count'] += len(pairs)
                report['reused_pair_count'] += len(pairs)
                save()
                continue
            begin = time.monotonic()
            scores = [float(s) for s in model.predict(pairs, batch_size=8, show_progress_bar=False)] if pairs else []
            order = stable_order(scores, len(pairs))
            report['jobs'].append({'id': job['id'], 'scores': scores, 'order': order,
                                   'seconds': time.monotonic()-begin})
            report['pair_count'] += len(pairs)
            report['new_pair_count'] += len(pairs)
            save()
        report.update(status='completed', stage='finished')
    except Exception as error:
        report.update(status='failed', error_type=type(error).__name__, error=str(error)[:2000])
    report['seconds'] = time.monotonic()-started
    save()
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    run(args.input, args.output)
