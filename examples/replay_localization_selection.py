"""Check a saved model file selection against current request formatting, without inference."""
import argparse
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from keel.localization import selection_request, symbol_structure, ANCHOR_INSTRUCTION
from examples.run_starlette_upgrade_task import inventory


def replay(trial):
    trial = trial.resolve()
    prepared = json.loads((trial/'prepared.json').read_text(encoding='utf-8'))
    if inventory(trial/'repo') != prepared['source']:
        raise ValueError('Replay requires unchanged prepared source')
    ledger = trial/'run/ledger.sqlite'
    with closing(sqlite3.connect(ledger.as_uri()+'?mode=ro', uri=True)) as connection:
        rows = connection.execute("SELECT payload FROM facts WHERE role='scout' AND summary='Untrusted localization file-selection'").fetchall()
    if len(rows) != 1:
        raise ValueError('Exactly one saved file-selection response required')
    selection = json.loads(json.loads(rows[0][0]))
    files = selection['files']
    if not isinstance(files, list) or not files or len(files) != len(set(files)):
        raise ValueError('Invalid saved selection')
    structure = []
    for name in files:
        if name not in prepared['source']:
            raise ValueError('Selection not in frozen inventory')
        path = (trial/'repo'/name).resolve()
        if not path.is_relative_to((trial/'repo').resolve()):
            raise ValueError('Selection escapes source')
        structure.append(symbol_structure(name, path.read_bytes().decode('utf-8')))
    config = prepared['config']
    # Unbounded size computation only; no provider or budget object exists here.
    _, _, size = selection_request(config['goal'], {'max_context_bytes': sys.maxsize},
        stage='anchor-selection', data={'structure': structure}, keys=('locations',), instruction=ANCHOR_INSTRUCTION)
    cap = config['agent']['max_context_bytes']
    return {'trial': str(trial), 'selected_files': files, 'definition_count': sum(len(r['symbols']) for r in structure),
        'request_bytes': size, 'cap_bytes': cap, 'fits': size <= cap, 'new_model_calls': 0,
        'prepared_sha256': hashlib.sha256((trial/'prepared.json').read_bytes()).hexdigest(),
        'saved_selection_sha256': hashlib.sha256(rows[0][0].encode()).hexdigest(),
        'limitations': 'Formatting/capacity replay of an observed development selection; no new model output, repair context or task success.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--trial', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = replay(args.trial)
    with args.output.open('x', encoding='utf-8') as stream:
        json.dump(report, stream, indent=2)
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
