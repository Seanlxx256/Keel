"""Native PostgreSQL unit of work and operation receipts; not a full controller backend.

No SQLite SQL translation, automatic retry or provider/tool dispatch. Schema
initialization is an explicit administrator action against a dedicated database.
"""
from contextlib import contextmanager
import json
import os
import threading

from .core import PolicyDenied
from .governance import GovernanceUnavailable, encoded, reject_nonfinite
from .operation_store import validate_operation_request


class PostgresUnitOfWork:
    def __init__(self,*,dsn_env='KEEL_POSTGRES_DSN',connect_timeout=5,
                 statement_timeout_ms=5000,lock_timeout_ms=3000):
        if not isinstance(dsn_env,str) or not dsn_env or any(char in dsn_env for char in '=\0'):
            raise ValueError('Expected PostgreSQL DSN environment variable name')
        for value in (connect_timeout,statement_timeout_ms,lock_timeout_ms):
            if type(value) is not int or value<=0:raise ValueError('PostgreSQL timeouts must be positive integers')
        self.dsn_env=dsn_env;self.connect_timeout=connect_timeout
        self.statement_timeout_ms=statement_timeout_ms;self.lock_timeout_ms=lock_timeout_ms
        self.transaction_domain=object();self._local=threading.local()

    @staticmethod
    def _driver():
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError:
            raise GovernanceUnavailable('PostgreSQL optional dependency unavailable; install the postgres extra') from None
        return psycopg,dict_row

    @contextmanager
    def transaction(self):
        existing=getattr(self._local,'connection',None)
        if existing is not None:
            yield existing
            return
        driver,row_factory=self._driver()
        dsn=os.environ.get(self.dsn_env)
        if not dsn:raise GovernanceUnavailable('PostgreSQL DSN environment variable is not configured')
        connection=None;phase='connect'
        try:
            connection=driver.connect(dsn,autocommit=True,row_factory=row_factory,
                connect_timeout=self.connect_timeout,
                options=f'-c statement_timeout={self.statement_timeout_ms} -c lock_timeout={self.lock_timeout_ms}')
            phase='transaction'
            with connection.transaction():
                connection.execute('SET TRANSACTION ISOLATION LEVEL READ COMMITTED')
                self._local.connection=connection
                yield connection
        except driver.Error as error:
            failure=GovernanceUnavailable('PostgreSQL '+phase+' unavailable; no automatic retry')
            sqlstate=getattr(error,'sqlstate',None)
            failure.failure={'stage':phase,'error_type':type(error).__name__,
                'sqlstate':sqlstate if isinstance(sqlstate,str) and len(sqlstate)==5 and sqlstate.isalnum() else None,
                'automatic_retry':False,'outcome':'unconfirmed'}
            raise failure from None
        finally:
            self._local.connection=None
            if connection is not None:
                try:connection.close()
                except Exception:
                    raise GovernanceUnavailable('PostgreSQL connection cleanup unavailable; inspect outcome before retry') from None


class PostgresOperationStore:
    def __init__(self,store):self.store=store

    @property
    def transaction_domain(self):return self.store.transaction_domain

    def initialize_schema(self):
        """Explicit trusted migration; constructor never creates tables."""
        with self.store.transaction() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS public.keel_operation_receipts_v1 (
                principal TEXT NOT NULL, operation_id TEXT NOT NULL,
                request_hash TEXT NOT NULL, status TEXT NOT NULL,
                response TEXT, PRIMARY KEY(principal,operation_id),
                CHECK (status IN ('pending','complete')),
                CHECK ((status='pending' AND response IS NULL) OR (status='complete' AND response IS NOT NULL)))''')

    def execute(self,*,principal,operation_id,request_hash,prepare,apply,replay,record=True):
        validate_operation_request(principal,operation_id,request_hash,record)
        with self.store.transaction() as db:
            context=prepare(db)
            created=False
            if record:
                # The unique key serializes contenders even when no prior row
                # existed. A subsequent READ COMMITTED statement sees its result.
                inserted=db.execute('''INSERT INTO public.keel_operation_receipts_v1
                    (principal,operation_id,request_hash,status) VALUES(%s,%s,%s,'pending')
                    ON CONFLICT (principal,operation_id) DO NOTHING RETURNING operation_id''',
                    (principal,operation_id,request_hash)).fetchone()
                created=inserted is not None
            prior=db.execute('''SELECT request_hash,status,response FROM public.keel_operation_receipts_v1
                WHERE principal=%s AND operation_id=%s FOR UPDATE''',(principal,operation_id)).fetchone()
            if prior:
                if prior['request_hash']!=request_hash:raise PolicyDenied('Operation ID reused with different parameters')
                if created and prior['status']!='pending':raise GovernanceUnavailable('Unexpected PostgreSQL intent state')
                if not created:
                    if prior['status']!='complete':raise GovernanceUnavailable('PostgreSQL operation outcome unavailable; inspect original intent')
                    try:response=json.loads(prior['response'],parse_constant=reject_nonfinite)
                    except (ValueError,TypeError):raise GovernanceUnavailable('Invalid PostgreSQL operation receipt') from None
                    if not isinstance(response,dict):raise GovernanceUnavailable('Invalid PostgreSQL operation receipt shape')
                    return replay(db,context,response)
            elif record:
                raise GovernanceUnavailable('PostgreSQL intent row unavailable; no business dispatch')
            response=apply(db,context)
            if not isinstance(response,dict):raise ValueError('Operation response must be a JSON object')
            if record:
                changed=db.execute('''UPDATE public.keel_operation_receipts_v1 SET status='complete',response=%s
                    WHERE principal=%s AND operation_id=%s AND request_hash=%s''',
                    (encoded(response),principal,operation_id,request_hash)).rowcount
                if changed!=1:raise GovernanceUnavailable('PostgreSQL receipt publication unavailable')
            return response
