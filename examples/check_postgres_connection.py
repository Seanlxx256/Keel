"""Read-only PostgreSQL connection/transaction check; no migrations or model calls."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from compass.progress import atomic_json
from keel.governance import GovernanceUnavailable
from keel.postgres_store import PostgresUnitOfWork


def execute(output,*,dsn_env='KEEL_POSTGRES_DSN'):
    store=PostgresUnitOfWork(dsn_env=dsn_env)
    output=Path(output);output.mkdir(parents=True,exist_ok=False)
    report={'status':'running','model_calls':0,'migrations':0,
            'driver_available':importlib.util.find_spec('psycopg') is not None,
            'dsn_configured':bool(os.environ.get(dsn_env)),
            'scope':'Read-only connection/transaction check, not persistence backend certification'}
    atomic_json(output/'report.json',report)
    print('[PostgreSQL] read-only connection check; no migration',flush=True)
    if not report['driver_available'] or not report['dsn_configured']:
        report['status']='unavailable'
    else:
        try:
            with store.transaction() as db:
                db.execute('SET TRANSACTION READ ONLY')
                row=db.execute("SELECT current_setting('server_version') AS server_version, 1 AS check_value").fetchone()
            report.update(status='passed',server_version=row['server_version'],check_value=row['check_value'])
        except GovernanceUnavailable as error:
            report.update(status='unavailable',failure=getattr(error,'failure',{'error_type':type(error).__name__}))
    atomic_json(output/'report.json',report)
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--dsn-env',default='KEEL_POSTGRES_DSN')
    args=parser.parse_args();result=execute(args.output,dsn_env=args.dsn_env)
    print(json.dumps(result),flush=True)
    sys.exit(0 if result['status']=='passed' else 1)
