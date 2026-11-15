"""Explicit, checksummed PostgreSQL schema migrations.

Migrations run inside the caller's PostgresUnitOfWork. They are serialized by a
transaction-scoped advisory lock and never run from repository construction.
"""
from dataclasses import dataclass
import hashlib
import json

from .governance import GovernanceUnavailable


@dataclass(frozen=True)
class SchemaMigration:
    version: int
    name: str
    statements: tuple[str, ...]


def migration_checksum(migration: SchemaMigration) -> str:
    raw=json.dumps({'version':migration.version,'name':migration.name,
                    'statements':list(migration.statements)},sort_keys=True,
                   separators=(',',':'),ensure_ascii=True).encode('ascii')
    return hashlib.sha256(raw).hexdigest()


def validate_migrations(migrations):
    migrations=tuple(migrations)
    if not migrations:
        raise ValueError('At least one schema migration is required')
    seen=set()
    for migration in migrations:
        if (not isinstance(migration,SchemaMigration) or type(migration.version) is not int
                or migration.version<1 or migration.version in seen
                or not isinstance(migration.name,str) or not migration.name.strip()
                or not isinstance(migration.statements,tuple) or not migration.statements
                or any(not isinstance(sql,str) or not sql.strip() for sql in migration.statements)):
            raise ValueError('Invalid PostgreSQL schema migration')
        seen.add(migration.version)
    if sorted(seen)!=list(range(1,len(seen)+1)):
        raise ValueError('PostgreSQL schema migration versions must be contiguous from 1')
    return tuple(sorted(migrations,key=lambda item:item.version))


def pending_migrations(migrations,rows):
    """Validate the recorded ledger and return only contiguous unapplied work."""
    migrations=validate_migrations(migrations)
    by_version={migration.version:migration for migration in migrations}
    prior={row['version']:row for row in rows}
    if len(prior)!=len(rows):
        raise GovernanceUnavailable('PostgreSQL schema migration ledger has duplicate versions')
    if any(version not in by_version for version in prior):
        raise GovernanceUnavailable('PostgreSQL schema is newer than this Keel build')
    pending=[]
    for migration in migrations:
        expected=migration_checksum(migration)
        row=prior.get(migration.version)
        if row is not None:
            if row['name']!=migration.name or row['checksum']!=expected:
                raise GovernanceUnavailable('Applied PostgreSQL migration differs from this Keel build')
            continue
        if any(version>migration.version for version in prior):
            raise GovernanceUnavailable('PostgreSQL schema migration ledger has a gap')
        pending.append(migration)
    return tuple(pending)


def apply_migrations(store,migrations):
    """Apply new migrations atomically; reject drift, gaps and newer schemas."""
    migrations=validate_migrations(migrations)
    applied=[]
    with store.transaction() as db:
        # A fixed application lock serializes first-time bootstrap as well as
        # later upgrades, before the migration ledger is queried.
        db.execute('SELECT pg_advisory_xact_lock(%s)',(731946208114,))
        db.execute('''CREATE TABLE IF NOT EXISTS public.keel_schema_migrations_v1 (
            version INTEGER PRIMARY KEY CHECK(version>0),
            name TEXT NOT NULL,
            checksum TEXT NOT NULL CHECK(checksum ~ '^[0-9a-f]{64}$'),
            applied_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp())''')
        rows=db.execute('SELECT version,name,checksum FROM public.keel_schema_migrations_v1 ORDER BY version').fetchall()
        for migration in pending_migrations(migrations,rows):
            expected=migration_checksum(migration)
            for statement in migration.statements:
                db.execute(statement)
            db.execute('''INSERT INTO public.keel_schema_migrations_v1(version,name,checksum)
                          VALUES(%s,%s,%s)''',(migration.version,migration.name,expected))
            applied.append(migration.version)
    return applied
