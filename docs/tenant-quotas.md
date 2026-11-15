# Tenant aggregate token and call budgets

Implemented on the current SQLite control plane. This is a cumulative admission
budget, not a CPU/memory scheduler, request-rate limit, recurring billing period
or authoritative provider bill. There is no automatic time-based reset or quota
change/migration command.

## Configuration

An optional controller-level policy augments explicit principal tenant bindings:

```json
"tenants": {
  "team-blue": {"max_tokens": 1000000, "max_model_calls": 100}
}
```

This fragment belongs in the trusted service configuration alongside `scopes`
and `principals`, not in a worker request. If tenant policies are supplied, each
configured explicit-tenant principal must have a matching policy. Legacy grants
without `tenant_id` retain their original behavior. Explicit identities without
a tenant quota remain supported when no tenant policy was previously established.

Every model reservation must pass both its scope budget and its tenant aggregate
budget. For example, two scopes each allowing 1000 tokens do not allow spending
2000 if their tenant cap is 1200. Sharing one tenant does not merge scopes' own
permissions or remove their local budget limits.

## Atomicity and accounting

`tenant_quotas.check_reservation` derives aggregate `spent`, `held` and `calls`
from all persistent scopes owned by the tenant. It executes under the same SQLite
write transaction as the scope reservation, request receipt and audit intent.
Tenant admission is checked before counter mutations. Scope rejection does not
increase an independent tenant counter because no such counter is maintained.
This ordering also matters when the controller catches a budget rejection and
commits its error response in the surrounding transaction.

Scope ownership persists even after a member is removed, so historical counters
do not disappear from the total. Enabling a tenant cap includes existing usage
in already-owned scopes, without resetting it. Established tenant caps cannot
be removed or changed merely by editing configuration. The relevant tenant
policy is included in the run's grant fingerprint.

Unknown usage keeps its reservation, including after run expiry. A trusted late
settlement converts reserved tokens to actual spent tokens; repeated settlement
retains existing idempotency behavior. Untrusted worker accounting cannot release
quota. Known actual usage above the reservation is still recorded, even if that
exceeds the cap: the cap blocks future admission, not historical truth. Model-call
counts are cumulative and are not refunded when a reply uses zero tokens.

Both manual authorized reservation and the controller model proxy use this path.
The proxy cannot call the provider before aggregate admission. The quota cannot
promise an absolute external billing ceiling because estimates may be exceeded
or external outcomes remain unknown.

## Inspection and limitations

Run reports add `tenant_budget` only when a tenant aggregate policy applies:
tenant ID, max tokens/calls, aggregate spent, reserved-or-unknown and calls.
These are shared tenant totals; scope-local report fields retain their meaning.
Legacy reports without a tenant policy retain their original shape.

SQLite's write transaction currently provides serialization on one database.
This is not proof of correctness on several hosts or another database backend.
Aggregation cost grows with scopes; production load/lock-wait measurements and
server-database transaction design remain outstanding. Do not deploy multiple
hosts sharing an SQLite file and call this distributed quota enforcement.

Contracts: `tests/test_tenant_quotas.py` covers cross-scope/cross-tenant budgets,
concurrent admission, no partial mutation on rejection, persistent history,
unknown and late usage, call caps, restart policy checks, scope caps, untrusted
settlement, lease expiry, policy validation and model-proxy pre-dispatch checks.
All provider calls in these tests are mocks, not paid requests.

Validation on 2026-11-15: 13 new contracts passed, then the frozen 19-module
compatibility group passed all 182 tests without skips (72.112s unittest,
80.063s watchdog). Reports, original console, plan and source archive are
retained in `.keel/production-reuse/tenant-quotas-v1/`. Declared input bytes were
unchanged. This does not replace full CI, server-database or multi-node testing.
