"""Tenant aggregate admission over authoritative scope counters, SQLite only."""
from .core import BudgetExceeded, PolicyDenied


def configure(store, policies, principals):
    from .tenancy import bounded_id
    if policies is None:policies={}
    if not isinstance(policies,dict):raise ValueError('tenants must be a policy object')
    for tenant,policy in policies.items():
        bounded_id(tenant)
        if (not isinstance(policy,dict) or set(policy)!={'max_tokens','max_model_calls'}
                or any(type(value) is not int or value<=0 for value in policy.values())):
            raise ValueError('Tenant quota requires positive integer max_tokens and max_model_calls')
    with store.transaction() as db:
        for principal in principals:
            tenant=principal.get('tenant_id')
            if tenant is None:continue
            old=db.execute('SELECT 1 FROM governance_tenant_limits WHERE tenant_id=?',(tenant,)).fetchone()
            if (policies or old) and tenant not in policies:
                raise PolicyDenied('Explicit tenant requires configured aggregate quota; existing limits cannot be removed')
        for tenant,policy in policies.items():
            row=db.execute('SELECT max_tokens,max_calls FROM governance_tenant_limits WHERE tenant_id=?',(tenant,)).fetchone()
            expected=(policy['max_tokens'],policy['max_model_calls'])
            if row and tuple(row)!=expected:raise PolicyDenied('Existing tenant quota changed; explicit policy migration required')
            if not row:db.execute('INSERT INTO governance_tenant_limits VALUES(?,?,?)',(tenant,*expected))
    return {tenant:dict(policy) for tenant,policy in policies.items()}


def report(db, scope):
    row=db.execute('''SELECT limits.tenant_id,limits.max_tokens,limits.max_calls
        FROM control_namespace_bindings binding JOIN governance_tenant_limits limits
        ON limits.tenant_id=binding.namespace_id
        WHERE binding.resource_kind='scope' AND binding.resource_id=? AND binding.namespace_kind='tenant' ''',
        (scope,)).fetchone()
    if row is None:return None
    usage=db.execute('''SELECT COALESCE(SUM(scopes.spent),0),COALESCE(SUM(scopes.held),0),COALESCE(SUM(scopes.calls),0)
        FROM governance_scopes scopes JOIN control_namespace_bindings binding ON scopes.scope=binding.resource_id
        WHERE binding.resource_kind='scope' AND binding.namespace_kind='tenant' AND binding.namespace_id=?''',
        (row['tenant_id'],)).fetchone()
    return {'tenant_id':row['tenant_id'],'max_tokens':row['max_tokens'],'max_model_calls':row['max_calls'],
            'spent_tokens':usage[0],'reserved_or_unknown_tokens':usage[1],'model_calls':usage[2]}


def check_reservation(db, scope, tokens):
    # Caller holds the same write transaction as scope reserve/receipt publication.
    # No separate tenant counter to drift, and no mutation before a quota rejection.
    usage=report(db,scope)
    if usage and (usage['spent_tokens']+usage['reserved_or_unknown_tokens']+tokens>usage['max_tokens']
                  or usage['model_calls']>=usage['max_model_calls']):
        raise BudgetExceeded('Tenant aggregate token or model-call budget exhausted')
