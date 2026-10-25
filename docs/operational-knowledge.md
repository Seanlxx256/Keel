# Runtime operational knowledge

Keel can opt in to a shared SQLite catalog of reviewed operational advice.
This is runtime retrieval, unlike the developer learning journal, which Keel
does not automatically read. It does not train the model or edit runtime code.

## Lifecycle and applicability

`keel.operational_knowledge.OperationalKnowledge` reuses the existing
`ExperienceStore` connection and episode recording implementation. Cards have
an ID, increasing revision, exact applicability tags, bounded guidance and
checks, evidence file hashes, and implementation compatibility hashes.

New cards are `candidate` and cannot be retrieved. An operator reviews the
evidence before calling `promote`; promotion checks file identity, **not the
truth of a claim**. Verified cards can be deprecated. A newer candidate or
deprecated revision suppresses the older verified revision rather than
silently falling back. Changed evidence or implementation excludes the card.

Matching requires all supplied dimensions (stage, tool, exception type,
host platform); values within one dimension are alternatives. Host platform
does not imply the container platform. There is no vector database or paid
retrieval call. At most three whole cards enter a bounded advice view. Optional
advice is dropped before current evidence when a request exceeds its capacity.

The initial hooks are verification feedback to Critic and the diagnostic probe
loop. This does not cover every role, environment controller, or failure.
Advice is historical support: it cannot supply fresh acceptance evidence,
grant a tool, expand a budget, authorize writes, or select an executable fix.
Never store task solution patches or reference answers in operational cards.

## Configuration

The database must be outside the candidate workspace. For example, save this
as a local config JSON (use the catalog hash returned by `inspect`):

```json
{"path":"D:/keel/.keel/operational-knowledge-v1.sqlite","catalog_sha256":"<64-character catalog hash>"}
```

Pass it to `examples/run_swebench_task.py` using
`--operational-knowledge-config <config.json>`, or set `operational_knowledge`
in a runtime/review plan. The feature is disabled when omitted. Frozen trials
must bind the config, catalog hash, implementation, and evidence inputs. Do
not retrofit old experiment receipts. Episode writes do not change the catalog
hash; card changes invalidate its configured snapshot.

Management commands (each is one shell command):

```powershell
python examples/manage_operational_knowledge.py --store D:/keel/.keel/knowledge.sqlite register --card D:/keel/.keel/card.json
python examples/manage_operational_knowledge.py --store D:/keel/.keel/knowledge.sqlite promote --id candidate-parent-namespace --revision 1
python examples/manage_operational_knowledge.py --store D:/keel/.keel/knowledge.sqlite inspect
python examples/manage_operational_knowledge.py --store D:/keel/.keel/knowledge.sqlite deprecate --id candidate-parent-namespace --revision 1
python examples/manage_operational_knowledge.py --store D:/keel/.keel/knowledge.sqlite import-episodes --source D:/keel/.keel/experiment/knowledge.sqlite
```

## What accumulates automatically

Runtime records typed failure features, matched card identities, catalog hash
and the final outcome in shared episodes. It deliberately does not copy raw
logs, credentials, source or model prose into that database. A successful run
is correlation, not proof the advice caused success; episodes never promote a
card automatically. Creating and reviewing general lessons remains an explicit
development step in this first version.

An isolated experiment store can be migrated explicitly with `import-episodes`.
The source is opened read-only; a bounded batch is validated before one atomic
destination transaction. Only typed retrieval/outcome records are accepted;
unknown payload fields are discarded. Content fingerprints make repeated imports
idempotent. Cards are never imported or promoted by episode migration, and the
destination catalog hash stays unchanged. Importing records does not itself make
them model-visible advice. A developer must separately register/review a lesson.
After adding or changing cards, issue a new configuration with the new catalog
hash; retain old configs and trial artifacts instead of silently upgrading them.

Local ledger and trace record retrievals; reports expose match counts and
storage errors. A matched card may later be omitted for request capacity, so
the actual model request is the evidence of delivery. Optional knowledge store
failures yield unavailable advice; required local checkpoint/result failures
still propagate. Retrieval has bounded inventory and cooperative file-check
deadlines, under the existing outer runtime watchdog.

## Validation boundary

`tests/test_operational_knowledge.py` exercises lifecycle, hash invalidation,
scope, capacity, optional-store failure, required-ledger failure, workspace
write isolation and a scripted end-to-end repair loop. The latter verifies
that advice reaches Critic without an extra model call. It is not a real-model
success-rate evaluation. The first seed lesson references the actual old/new
Docker import controls; those establish a loader mechanism, not Sphinx repair
acceptance or a causal benefit from memory retrieval. Next evaluate a frozen
knowledge-on/off diagnostic comparison, preserving both outcomes and costs.
