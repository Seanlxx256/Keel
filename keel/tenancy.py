"""Persistent controller identity ownership; not OS or database row isolation."""
from .core import PolicyDenied


def bounded_id(value):
    if not isinstance(value,str) or not value.strip() or len(value)>256:
        raise ValueError('Expected nonempty tenant identifier of at most 256 characters')
    return value


class TenantRegistry:
    def __init__(self, store):
        self.store=store

    def bind(self, principals):
        """Atomically bind configured identities; never silently reassign data.

        Legacy mode preserves old shared-task configurations. It is deliberately
        distinct from explicit tenant mode and cannot be upgraded by editing JSON.
        """
        with self.store.transaction() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS control_namespace_bindings (
                resource_kind TEXT NOT NULL, resource_id TEXT NOT NULL,
                namespace_kind TEXT NOT NULL, namespace_id TEXT NOT NULL,
                PRIMARY KEY(resource_kind,resource_id))''')
            for principal in principals:
                explicit='tenant_id' in principal
                namespace=('tenant',bounded_id(principal['tenant_id'])) if explicit else ('legacy_scope',principal['scope'])
                bindings=[('principal',principal['id'],namespace),('scope',principal['scope'],namespace),
                          ('task',principal['task_id'],namespace if explicit else ('legacy_task','compatibility'))]
                if explicit:
                    # Existing unlabelled state cannot gain a new owner retrospectively.
                    registered=db.execute("SELECT 1 FROM control_namespace_bindings WHERE resource_kind='principal' AND resource_id=?",
                                          (principal['id'],)).fetchone()
                    if not registered:
                        old_principal=db.execute('SELECT 1 FROM remote_operations WHERE principal=? LIMIT 1',(principal['id'],)).fetchone()
                        old_run=db.execute('SELECT 1 FROM remote_run_bindings WHERE principal=? OR task_id=? LIMIT 1',
                                           (principal['id'],principal['task_id'])).fetchone()
                        old_scope=db.execute('SELECT 1 FROM governance_scopes WHERE scope=?',(principal['scope'],)).fetchone()
                        # A scope already bound to this tenant is safe for a new member.
                        scope_owner=db.execute("SELECT namespace_kind,namespace_id FROM control_namespace_bindings WHERE resource_kind='scope' AND resource_id=?",
                                               (principal['scope'],)).fetchone()
                        task_owner=db.execute("SELECT namespace_kind,namespace_id FROM control_namespace_bindings WHERE resource_kind='task' AND resource_id=?",
                                              (principal['task_id'],)).fetchone()
                        if old_principal or (old_scope and (not scope_owner or tuple(scope_owner)!=namespace)) or (
                                old_run and (not task_owner or tuple(task_owner)!=namespace)):
                            raise PolicyDenied('Unlabelled controller state requires explicit tenant migration; no automatic reassignment')
                for kind,resource,owner in bindings:
                    row=db.execute('SELECT namespace_kind,namespace_id FROM control_namespace_bindings WHERE resource_kind=? AND resource_id=?',
                                   (kind,resource)).fetchone()
                    if row:
                        if tuple(row)!=owner:raise PolicyDenied('Controller identity already belongs to another namespace; migration required')
                    else:
                        db.execute('INSERT INTO control_namespace_bindings VALUES(?,?,?,?)',(kind,resource,*owner))
