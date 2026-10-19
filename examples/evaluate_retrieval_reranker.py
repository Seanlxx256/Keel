"""Controlled reranking of frozen candidates: same ranges, packing and scoring."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from compass.benchmarks import load_swe_instance
from compass.index import fingerprint
from examples.compare_retrieval_alternatives import score
from examples.reranker_worker import stable_order


def evaluate(source, external, output, python, *, model='cross-encoder/ms-marco-MiniLM-L6-v2',
             revision=None, timeout=1800, local_files_only=False, model_cache=None, resume_from=None):
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    inputs = {}
    def read(path):
        path = Path(path).resolve(strict=True)
        raw = path.read_bytes()
        inputs[str(path)] = hashlib.sha256(raw).hexdigest()
        return json.loads(raw)
    report = {'status': 'preparing', 'records': [], 'excluded': [], 'generation_model_calls': 0,
        'benchmark_ready': False, 'line_budget': 100, 'symbol_line_cap': 32, 'inputs_sha256': inputs,
        'model': model, 'revision': revision,
        'implementation_sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in
            (Path(__file__), Path(__file__).with_name('reranker_worker.py'),
             Path(__file__).with_name('compare_retrieval_alternatives.py'),
             Path(__file__).parents[1]/'compass/benchmarks.py')},
        'limitations': 'Exposed development sample. General MS MARCO reranker, not code-specialized. '
            'No changed ranges, new retrieval or snippet policy. Token truncation is upstream max_length=512. '
            'No held-out or agent-repair claim; candidate pools differ across engines.'}
    def save():
        (output/'evaluation.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    save()
    try:
        batch = read(source)
        source_hash = inputs[str(source.resolve())]
        external_reports = [read(p) for p in external]
        if any(r['source_sha256'] != source_hash or r['line_budget'] != 100 or r['symbol_line_cap'] != 32
               for r in external_reports):
            raise ValueError('External source or packing policy mismatch')
        jobs, context, snapshots = [], {}, {}
        for item in batch['instances']:
            dataset = Path(item['measurements'][0]['sweep']).parent.parent/'instance.jsonl'
            read(dataset)
            instance = load_swe_instance(dataset, item['instance_id'], Path(item['snapshot']))
            snapshots[instance['repo']] = fingerprint(Path(instance['repo']))
            pools = []
            for measurement in item['measurements']:
                if measurement['ranking'] != 'code-aware':
                    continue
                path = Path(measurement['sweep']).parent/'runs.jsonl'
                raw = path.read_bytes()
                inputs[str(path.resolve())] = hashlib.sha256(raw).hexdigest()
                runs = [json.loads(s) for s in raw.decode().splitlines() if s.strip()]
                selected = [r for r in runs if r['mode'] == 't1' and r['status'] == 'passed' and r['line_budget'] == 100]
                if len(selected) != 1:
                    raise ValueError('Expected one cached Compass baseline per task')
                saved = selected[0]['result']
                pools.append(('compass_cached_code-aware', saved['index_ref'],
                    [{**r, 'start_line': r['start'], 'end_line': r['end']} for r in saved['candidates']]))
            if len(pools) != 1:
                raise ValueError('Missing or duplicate Compass baseline')
            for measured in external_reports:
                for row in measured['records']:
                    if row['instance'] != instance['id'] or row['engine'] not in ('serena_symbols', 'cocoindex_semantic'):
                        continue
                    if row['status'] != 'ok':
                        report['excluded'].append({'instance': row['instance'], 'engine': row['engine'], 'status': row['status']})
                        continue
                    if (row['index_ref'] != pools[0][1] or
                            row['query_sha256'] != hashlib.sha256(instance['query'].encode()).hexdigest() or
                            row['dataset_sha256'] != inputs[str(dataset.resolve())]):
                        raise ValueError('Query/index/dataset identity mismatch')
                    pools.append((row['engine'], row['index_ref'], row['candidates']))
            for engine, index_ref, rows in pools:
                job_id = instance['id']+':'+engine
                if job_id in context:
                    raise ValueError('Duplicate task/engine')
                baseline = score(rows, instance)
                documents = []
                for r in baseline['candidates']:
                    content = (Path(instance['repo'])/r['path']).read_bytes().decode('utf-8').splitlines(keepends=True)
                    text = r['path']+'\n'+''.join(content[r['start_line']-1:r['end_line']])
                    documents.append({'text': text, 'text_sha256': hashlib.sha256(text.encode()).hexdigest()})
                jobs.append({'id': job_id, 'query': instance['query'], 'documents': documents})
                context[job_id] = (instance, engine, index_ref, baseline)
        worker_input, worker_output = output/'query-code-only.json', output/'worker-result.json'
        completed_jobs = []
        if resume_from and (resume_from/'worker-result.json').is_file():
            old_input_path = resume_from/'query-code-only.json'
            old_input = json.loads(old_input_path.read_text(encoding='utf-8'))
            old_output = json.loads((resume_from/'worker-result.json').read_text(encoding='utf-8'))
            old_report = json.loads((resume_from/'evaluation.json').read_text(encoding='utf-8'))
            if (old_output['input_sha256'] != hashlib.sha256(old_input_path.read_bytes()).hexdigest() or
                    old_input['model'] != model or old_input.get('revision') != revision or
                    old_report['implementation_sha256']['reranker_worker.py'] != report['implementation_sha256']['reranker_worker.py']):
                raise ValueError('Prior reranker identity/configuration mismatch')
            old_requests = {j['id']: j for j in old_input['jobs']}
            new_requests = {j['id']: j for j in jobs}
            for finished in old_output['jobs']:
                if finished['id'] not in new_requests:
                    continue
                if old_requests[finished['id']] != new_requests[finished['id']]:
                    raise ValueError('Prior scored query/code differs')
                completed_jobs.append(finished)
            report['resume_from'] = str(resume_from)
            report['resume_worker_sha256'] = hashlib.sha256((resume_from/'worker-result.json').read_bytes()).hexdigest()
        worker_input.write_text(json.dumps({'model': model, 'revision': revision,
            'cache': str((model_cache or output.parent/'reranker-model-cache').resolve()),
            'local_files_only': local_files_only, 'jobs': jobs, 'completed_jobs': completed_jobs}), encoding='utf-8')
        request_hash = hashlib.sha256(worker_input.read_bytes()).hexdigest()
        env = dict(os.environ, PYTHONUTF8='1', HF_HUB_ETAG_TIMEOUT='10', HF_HUB_DOWNLOAD_TIMEOUT='30')
        report['status'] = 'running'
        save()
        started = time.monotonic()
        with (output/'worker.log').open('wb') as log:
            with subprocess.Popen([str(python.resolve(strict=True)), str(Path(__file__).with_name('reranker_worker.py')),
                    '--input', str(worker_input), '--output', str(worker_output)],
                    stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, env=env) as process:
                while process.poll() is None:
                    remaining = timeout-(time.monotonic()-started)
                    if remaining <= 0:
                        process.kill()
                        process.wait()
                        raise TimeoutError('Reranker worker wall-clock budget exhausted')
                    try:
                        process.wait(timeout=min(10, remaining))
                    except subprocess.TimeoutExpired:
                        status = json.loads(worker_output.read_text()) if worker_output.exists() else {}
                        print('[Reranker] '+status.get('stage', 'starting')+'; log: '+str(output/'worker.log'), flush=True)
        if process.returncode or not worker_output.exists():
            raise RuntimeError('Worker did not finish; inspect worker.log')
        measured = read(worker_output)
        report['worker_status'] = measured['status']
        if measured['input_sha256'] != request_hash or hashlib.sha256(worker_input.read_bytes()).hexdigest() != request_hash:
            raise ValueError('Worker input identity mismatch')
        if measured['status'] != 'completed':
            raise RuntimeError(measured.get('error', 'Reranker worker failed'))
        if len(measured['jobs']) != len(context) or len({r['id'] for r in measured['jobs']}) != len(context):
            raise ValueError('Worker job coverage mismatch')
        for job in measured['jobs']:
            instance, engine, index_ref, baseline = context[job['id']]
            rows = baseline['candidates']
            order = stable_order(job['scores'], len(rows))
            if order != job['order']:
                raise ValueError('Worker order does not match scores')
            reranked = score([rows[i] for i in order], instance)
            report['records'].append({'instance': instance['id'], 'engine': engine, 'index_ref': index_ref,
                'baseline': baseline['metrics'], 'reranked': reranked['metrics'], 'candidate_count': len(rows),
                'order': order, 'scores': job['scores'], 'predictions': reranked['predictions'],
                'seconds': job['seconds']})
        report['summary'] = []
        for engine in sorted({r['engine'] for r in report['records']}):
            group = [r for r in report['records'] if r['engine'] == engine]
            report['summary'].append({'engine': engine, 'paired_tasks': len(group), **{
                arm: {key: statistics.mean(r[arm][key] for r in group) for key in
                      ('line_recall', 'line_precision', 'hit_file_rate')}
                for arm in ('baseline', 'reranked')}})
        report.update(status='completed', inference_pairs=measured['pair_count'],
            new_inference_pairs=measured.get('new_pair_count', measured['pair_count']),
            reused_inference_pairs=measured.get('reused_pair_count', 0))
        for repo, expected in snapshots.items():
            if fingerprint(Path(repo)) != expected:
                raise ValueError('Source snapshot changed during reranking')
        for path, expected in inputs.items():
            if hashlib.sha256(Path(path).read_bytes()).hexdigest() != expected:
                raise ValueError('Input artifact changed during reranking')
    except Exception as error:
        report.update(status='failed', error_type=type(error).__name__, error=str(error)[:2000])
    save()
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True, type=Path)
    parser.add_argument('--external', required=True, nargs='+', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--python', type=Path, default=Path('.keel/tools/cocoindex-venv/Scripts/python.exe'))
    parser.add_argument('--model', default='cross-encoder/ms-marco-MiniLM-L6-v2')
    parser.add_argument('--revision')
    parser.add_argument('--timeout', type=int, default=1800)
    parser.add_argument('--local-files-only', action='store_true')
    parser.add_argument('--model-cache', type=Path)
    args = parser.parse_args()
    result = evaluate(args.source, args.external, args.output, args.python, model=args.model,
        revision=args.revision, timeout=args.timeout, local_files_only=args.local_files_only,
        model_cache=args.model_cache)
    print(json.dumps({k: v for k, v in result.items() if k in ('status', 'summary', 'error')}, indent=2))
    sys.exit(0 if result['status'] == 'completed' else 1)
