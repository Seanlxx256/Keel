# Controller tenant identity bindings

Implemented: explicit tenant identity on trusted principal grants, durable
namespace ownership and remote context propagation. SQLite remains the only
backend. This is metadata/authorization governance, not full SaaS isolation,
sandbox isolation, a service database adapter or distributed scheduling.

## Identity model

- `tenant_id`: administrator-owned organization/group identity. Optional for
  compatibility; a task request cannot choose or override it.
- `id`: globally unique authenticated principal, such as a worker identity.
  Multiple principals can belong to one tenant. This is not end-user login,
  organization roles, invitations or a complete revocation workflow.
- `scope`: budget/policy pool. Principals in one tenant may explicitly share it;
  different tenants cannot. Optional [tenant aggregate quotas](tenant-quotas.md)
  constrain the total across scopes without replacing their own limits.
- `task_id`: globally unique task/resource binding. Explicit tenants cannot
  share one task ID. Different task IDs could still point at overlapping physical
  repositories if configured by an administrator; physical isolation is separate.

Administrator configuration example, not an untrusted task payload:

```json
{
  "path": "D:/KeelControl/control.sqlite",
  "scopes": {
    "blue-budget": {"max_tokens": 100000, "max_model_calls": 20, "lease_seconds": 900}
  },
  "principals": [
    {"id": "blue-worker-1", "tenant_id": "team-blue", "token_env": "KEEL_BLUE_1_TOKEN",
     "scope": "blue-budget", "task_id": "blue-task-1", "tools": {}},
    {"id": "blue-worker-2", "tenant_id": "team-blue", "token_env": "KEEL_BLUE_2_TOKEN",
     "scope": "blue-budget", "task_id": "blue-task-2", "tools": {}}
  ]
}
```

Configure distinct credentials in the trusted service environment according to
the existing token policy. This example grants no runtime tools. Begin returns
the server-assigned tenant context, retained by RemoteSession/checkpoints.
Context is not a credential. Full grant hashes include an explicit tenant field;
cross-principal run access remains denied.

## Persistent ownership and legacy behavior

`keel/tenancy.py` atomically registers principal, scope and task ownership in
`control_namespace_bindings`. Explicit and legacy namespaces have different
kinds: matching text cannot merge them. Old grants without `tenant_id` retain
their scope-based behavior and existing shared-task configurations. Legacy begin
responses/grant dictionaries are unchanged. This compatibility mode is not a
retroactive guarantee of explicit tenant isolation.

Restarting with edited JSON cannot reassign existing ownership. Removing a
principal does not release its task/scope to another tenant. Old unlabelled
receipts, runs or budget state cannot automatically acquire a new owner; startup
requires an explicit migration. New members can join a used scope already owned
by their tenant. No automated ownership migration/deletion command exists yet.
Such migration must account for history, active runs, unknown effects and backing
artifacts. Do not delete binding rows to bypass the checks.

## Validation and limits

Twelve `tests/test_tenancy.py` contracts cover cross-tenant scope/task collisions,
same operation IDs across principals, shared-scope accounting, restart/removed
member ownership, old-data migration refusal, caller spoofing, legacy shared
tasks, new membership and real loopback HTTP context propagation.
The combined 15-module group passed 144 tests without skips in 61.077s; watchdog
70.047s. Frozen evidence: `.keel/production-reuse/tenancy-v1/`.

No Docker, paid provider, PostgreSQL, cluster or production load test was run.
Remaining work includes quota policy migration/reset workflows, repository/artifact
authorization, ownership migration tooling, storage adapters and compute/network isolation.
Operation receipts still use globally unique `(principal, operation_id)` keys.
Untrusted agents must not receive the trusted database or controller credentials;
direct database access is not protected by this application-level tenant model.
