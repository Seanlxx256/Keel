"""Compare real retrieval backends on frozen SWE-Explore snapshots; no gold enters adapters."""
import argparse
import hashlib
from importlib import metadata
import json
from pathlib import Path
import sqlite3
import statistics
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from compass.benchmarks import load_swe_instance, pack_regions, region_metrics
from compass.index import RepositoryIndex, fingerprint
from compass.lexical import tokens


def paired_summary(records):
    baseline = {r['instance']: r for r in records
                if r['engine'] == 'compass_cached_code-aware' and r['status'] == 'ok'}
    result = []
    for engine in sorted({r['engine'] for r in records} - {'compass_cached_code-aware'}):
        matched = [r for r in records if r['engine'] == engine and r['status'] == 'ok'
                   and r['instance'] in baseline]
        result.append({'engine': engine, 'instances': [r['instance'] for r in matched],
            'paired_tasks': len(matched), **{key: {
                'external': statistics.mean(r['metrics'][key] for r in matched) if matched else None,
                'compass_cached_code-aware': statistics.mean(baseline[r['instance']]['metrics'][key]
                    for r in matched) if matched else None}
                for key in ('line_recall', 'line_precision', 'hit_file_rate')}})
    return result


def rank_external(engine, documents, query):
    terms = [tokens(row['embed_text']+'\n'+row['code']) for row in documents]
    wanted = tokens(query)
    if engine == 'sqlite_fts5':
        db = sqlite3.connect(':memory:')
        try:
            db.execute('CREATE VIRTUAL TABLE docs USING fts5(text, tokenize="unicode61 tokenchars \'_\'")')
            db.executemany('INSERT INTO docs(rowid,text) VALUES (?,?)',
                           ((i+1, ' '.join(t)) for i, t in enumerate(terms)))
            expression = ' OR '.join('"'+t+'"' for t in sorted(set(wanted)))
            ids = [r[0]-1 for r in db.execute('SELECT rowid FROM docs WHERE docs MATCH ? ORDER BY bm25(docs),rowid LIMIT 100',
                                            (expression,))] if expression else []
            version = sqlite3.sqlite_version
        finally:
            db.close()
    elif engine == 'rank_bm25':
        from rank_bm25 import BM25Okapi
        scores = BM25Okapi(terms).get_scores(wanted)
        ids = sorted(range(len(documents)), key=lambda i: (-float(scores[i]), i))[:100]
        ids = [i for i in ids if scores[i] > 0]
        version = metadata.version('rank-bm25')
    elif engine == 'bm25s':
        import bm25s
        corpus = bm25s.tokenize([' '.join(t) for t in terms], stopwords=[], show_progress=False)
        retriever = bm25s.BM25()
        retriever.index(corpus, show_progress=False)
        found, scores = retriever.retrieve(bm25s.tokenize([' '.join(wanted)], stopwords=[], show_progress=False),
                                           k=min(100, len(documents)), show_progress=False)
        ids = [int(i) for i, score in zip(found[0], scores[0]) if float(score) > 0]
        version = metadata.version('bm25s')
    else:
        raise ValueError('Unknown external lexical engine')
    return [documents[i] for i in ids], version


def score(rows, instance):
    # Engine output is untrusted; validate against source, not relevance labels.
    normalized = []
    root = Path(instance['repo']).resolve()
    for row in rows[:100]:
        path = (root/row['path']).resolve(strict=True)
        start, end = row['start_line'], row['end_line']
        if (not path.is_relative_to(root) or not path.is_file() or type(start) is not int or
                type(end) is not int or not 1 <= start <= end <= len(path.read_bytes().splitlines())):
            raise ValueError('Invalid candidate range')
        normalized.append({**row, 'path': path.relative_to(root).as_posix()})
    predictions = pack_regions(normalized, 100, 32)
    metrics = region_metrics(predictions, instance['core_regions'], instance['optional_regions'], instance['core_files'])
    ceiling = min(100, metrics['core_lines'])/metrics['core_lines']
    return {'metrics': metrics, 'predictions': predictions, 'candidates': normalized,
            'budget_recall_ceiling': ceiling, 'recall_fraction_of_ceiling': metrics['line_recall']/ceiling}


def run(source, output, serena_python=None, pyright_command=None, *, cocoindex_python=None,
        engines=None, embedding_model='Snowflake/snowflake-arctic-embed-xs', engine_timeout=900, resume_report=None,
        compatible_worker_hashes=None):
    output.mkdir(parents=True, exist_ok=False)
    source = source.resolve(strict=True)
    batch = json.loads(source.read_text(encoding='utf-8'))
    previous = json.loads(resume_report.read_text(encoding='utf-8')) if resume_report else None
    if previous and (previous['line_budget'] != 100 or previous['symbol_line_cap'] != 32):
        raise ValueError('Prior external packing policy differs')
    cocoindex_cache = Path(previous.get('cocoindex_model_cache', resume_report.parent.parent/'cocoindex-model-cache')) \
        if previous else output.parent/'cocoindex-model-cache'
    report = {'status': 'running', 'records': [], 'new_model_calls': 0, 'benchmark_ready': False,
        'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
        'implementation_sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (
            Path(__file__), Path(__file__).with_name('serena_retrieval_worker.py'),
            Path(__file__).with_name('cocoindex_retrieval_worker.py'))},
        'line_budget': 100, 'symbol_line_cap': 32,
        'cocoindex_model_cache': str(cocoindex_cache.resolve()),
        'limitations': 'Previously exposed three-task development sample. Lexical libraries share Compass chunks/analyzer; not full code-agent comparisons. Serena uses a disclosed deterministic identifier adapter, not an LLM Agent. Missing engines are unavailable, not zero recall.'}
    def save():
        summary = []
        for engine in sorted({r['engine'] for r in report['records']}):
            rows = [r for r in report['records'] if r['engine'] == engine]
            valid = [r for r in rows if r['status'] == 'ok']
            summary.append({'engine': engine, 'evaluated_tasks': len(valid), 'unavailable_or_failed': len(rows)-len(valid),
                **{key: statistics.mean(r['metrics'][key] for r in valid) if valid else None
                   for key in ('line_recall', 'line_precision', 'hit_file_rate', 'predicted_unique_lines')}})
        report['summary'] = summary
        report['paired_summary'] = paired_summary(report['records'])
        (output/'comparison.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    save()
    for number, item in enumerate(batch['instances'], 1):
        print('[Retrieval comparison] '+item['instance_id'], flush=True)
        sweep_path = Path(item['measurements'][0]['sweep'])
        dataset = sweep_path.parent.parent/'instance.jsonl'
        instance = load_swe_instance(dataset, item['instance_id'], Path(item['snapshot']))
        before = fingerprint(Path(instance['repo']))
        with RepositoryIndex(Path(instance['repo'])) as index:
            index.require_fresh()
            documents = [dict(r) for r in index.db.execute('SELECT * FROM symbols ORDER BY id')]
            index_ref = index.metadata['index_ref']
        for engine in (engines or ('sqlite_fts5', 'rank_bm25', 'bm25s', 'serena_symbols')):
            started = time.monotonic()
            row = {'instance': instance['id'], 'engine': engine, 'index_ref': index_ref,
                   'query_sha256': hashlib.sha256(instance['query'].encode()).hexdigest(),
                   'dataset_sha256': hashlib.sha256(dataset.read_bytes()).hexdigest()}
            try:
                old = [r for r in previous['records'] if r['instance'] == instance['id'] and
                       r['engine'] == engine and r['status'] == 'ok'] if previous else []
                if len(old) > 1:
                    raise ValueError('Duplicate completed external result')
                if old:
                    cached = old[0]
                    worker_name = 'serena_retrieval_worker.py' if engine == 'serena_symbols' else 'cocoindex_retrieval_worker.py'
                    if (engine not in ('serena_symbols', 'cocoindex_semantic') or
                            any(cached.get(key) != row[key] for key in ('query_sha256', 'dataset_sha256', 'index_ref')) or
                            previous['implementation_sha256'].get(worker_name) not in
                            [report['implementation_sha256'][worker_name], *(compatible_worker_hashes or {}).get(worker_name, [])] or
                            (engine == 'cocoindex_semantic' and cached['embedding_settings']['model'] != embedding_model)):
                        raise ValueError('Completed external result is incompatible with current request')
                    checked = score(cached['candidates'], instance)
                    if checked['metrics'] != cached['metrics']:
                        raise ValueError('Completed external metrics do not reproduce')
                    row.update(cached, reused=True, reuse_report=str(resume_report),
                        reuse_report_sha256=hashlib.sha256(resume_report.read_bytes()).hexdigest(),
                        seconds_this_run=0)
                    report['records'].append(row)
                    save()
                    print('[Retrieval comparison] reuse '+engine+' '+instance['id'], flush=True)
                    continue
                if engine == 'cocoindex_semantic':
                    if not cocoindex_python or not cocoindex_python.is_file():
                        raise ModuleNotFoundError('Isolated CocoIndex interpreter not available')
                    directory = output/f'task-{number}'/'cocoindex'
                    directory.mkdir(parents=True)
                    worker_input, worker_output = directory/'query-only.json', directory/'result.json'
                    checkpoints = [r for r in previous['records'] if r['instance'] == instance['id']
                        and r['engine'] == engine and r.get('worker_result')
                        and r.get('query_sha256') == row['query_sha256']
                        and r.get('dataset_sha256') == row['dataset_sha256']] if previous else []
                    checkpoint = None
                    if checkpoints:
                        candidate = Path(checkpoints[-1]['worker_result']).resolve()
                        if candidate.is_file():
                            saved = json.loads(candidate.read_text(encoding='utf-8'))
                            if saved.get('daemon_cleanup_returncode') == 0 and saved.get('stage') in ('index', 'search'):
                                checkpoint = str(candidate.parent)
                    worker_input.write_text(json.dumps({'repo': instance['repo'], 'query': instance['query'],
                        'model_cache': str(cocoindex_cache.resolve()),
                        'resume_checkpoint': checkpoint,
                        'embedding_model': embedding_model, 'timeout': engine_timeout}), encoding='utf-8')
                    with (directory/'worker.log').open('w', encoding='utf-8') as log:
                        process = subprocess.run([str(cocoindex_python),
                            str(Path(__file__).with_name('cocoindex_retrieval_worker.py')),
                            '--input', str(worker_input.resolve()), '--output', str(worker_output.resolve())],
                            stdout=log, stderr=subprocess.STDOUT, timeout=engine_timeout+60)
                    if process.returncode or not worker_output.exists():
                        raise RuntimeError('CocoIndex worker did not finish; inspect worker.log')
                    measured = json.loads(worker_output.read_text(encoding='utf-8'))
                    row['worker_result'] = str(worker_output)
                    row['stage'] = measured['stage']
                    if measured.get('ipc_preflight'):
                        row['ipc_preflight'] = measured['ipc_preflight']
                    if measured['status'] == 'unavailable':
                        row['unavailable_type'] = measured.get('error_type', 'ModuleNotFoundError')
                        raise ModuleNotFoundError(measured['error'])
                    if measured['status'] != 'ok':
                        raise RuntimeError(measured.get('error', 'CocoIndex worker failed'))
                    rows, version = measured['candidates'], measured['version']
                    row['adapter'] = measured['adapter']
                    row['embedding_settings'] = measured['embedding_settings']
                    row['embedding_usage'] = measured['embedding_usage']
                elif engine == 'serena_symbols':
                    if not serena_python or not serena_python.is_file():
                        raise ModuleNotFoundError('Isolated Serena interpreter not available')
                    directory = output/f'task-{number}'
                    directory.mkdir()
                    worker_input, worker_output = directory/'query-only.json', directory/'serena-result.json'
                    worker_input.write_text(json.dumps({'repo': instance['repo'], 'query': instance['query'],
                        'state': str((output/'serena-state').resolve()), 'pyright_command': pyright_command,
                        'experience_store': str(Path(__file__).resolve().parents[1]/'.keel/experience/operations.sqlite')}), encoding='utf-8')
                    with (directory/'serena.log').open('w', encoding='utf-8') as log:
                        process = subprocess.run([str(serena_python), str(Path(__file__).with_name('serena_retrieval_worker.py')),
                            '--input', str(worker_input.resolve()), '--output', str(worker_output.resolve())],
                            stdout=log, stderr=subprocess.STDOUT, timeout=240)
                    if process.returncode or not worker_output.exists():
                        raise RuntimeError('Serena worker did not produce a result; inspect its log')
                    measured = json.loads(worker_output.read_text(encoding='utf-8'))
                    if measured['status'] != 'ok':
                        raise RuntimeError('Serena worker failed; inspect its result and log')
                    rows, version = measured['candidates'], measured['version']
                    row['adapter'] = measured['adapter']
                    row['worker_result'] = str(worker_output)
                    row['recovery'] = measured.get('recovery', [])
                    row['tool_calls'] = measured.get('tool_calls')
                else:
                    rows, version = rank_external(engine, documents, instance['query'])
                row.update(status='ok', version=version, **score(rows, instance))
            except ModuleNotFoundError as error:
                row.update(status='unavailable', error_type=row.get('unavailable_type', type(error).__name__), detail=str(error)[:200])
            except Exception as error:
                row.update(status='failed', error_type=type(error).__name__, detail=str(error)[:200])
            row['seconds_including_initialization'] = time.monotonic()-started
            report['records'].append(row)
            save()
            if fingerprint(Path(instance['repo'])) != before:
                raise ValueError('Source snapshot changed during external retrieval')
        # Preserve historical Compass results, clearly separated from new runs.
        for measurement in item['measurements']:
            runs = Path(measurement['sweep']).parent/'runs.jsonl'
            for saved in [json.loads(s) for s in runs.read_text(encoding='utf-8').splitlines() if s.strip()]:
                if saved['mode'] == 't1' and saved['status'] == 'passed' and saved['line_budget'] == 100:
                    old = saved['result']
                    report['records'].append({'instance': instance['id'], 'engine': 'compass_cached_'+measurement['ranking'],
                        'status': 'ok', 'metrics': old['metrics'], 'scope': 'Historical measured baseline, not rerun',
                        'source_runs_sha256': hashlib.sha256(runs.read_bytes()).hexdigest()})
        save()
    report['status'] = 'completed'
    save()
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--packages-dir', type=Path)
    parser.add_argument('--serena-python', type=Path)
    parser.add_argument('--pyright-command', nargs='+')
    parser.add_argument('--cocoindex-python', type=Path)
    parser.add_argument('--engines', nargs='+', choices=('sqlite_fts5', 'rank_bm25', 'bm25s',
                        'serena_symbols', 'cocoindex_semantic'))
    parser.add_argument('--embedding-model', default='Snowflake/snowflake-arctic-embed-xs')
    parser.add_argument('--engine-timeout', type=int, default=900)
    args = parser.parse_args()
    if args.packages_dir:
        sys.path.insert(0, str(args.packages_dir.resolve()))
    if args.engine_timeout < 30:
        parser.error('--engine-timeout must be at least 30 seconds')
    result = run(args.source, args.output.resolve(), args.serena_python, args.pyright_command,
        cocoindex_python=args.cocoindex_python, engines=args.engines, embedding_model=args.embedding_model,
        engine_timeout=args.engine_timeout)
    print(json.dumps({'summary': result['summary'], 'new_model_calls': 0}, indent=2))
