# Repository transfer during candidate collection

Collection `.keel/independent-candidates/701028027c4c491f82989a3eff172ffc` encountered GitHub metadata resolving encode/uvicorn to kludex/uvicorn. The miner followed that resolution, while the fixed policy and shortlist still used the requested repository identity. Appending the first candidate before validating its repository poisoned the in-memory checkpoint, causing both callback saving and final saving to raise a mismatch error. Raw responses and hash receipts remain saved by the GitHub client.

The collection wrapper now records the resolved identity from the actual `/repos/<planned>` metadata response. Candidate identities must match that verified resolution before entering state. Transferred candidates retain the original planned identity for this cohort's sampling consistency, with explicit resolved_repository and repository_resolution_route provenance. No arbitrary candidate repository is accepted. Resolutions into registered development repositories or a repository already resolved by another planned entry fail. This is wrapper behavior; the selector and policy are unchanged.

Resume replays hash-verified cached API responses into a new directory and requests missing routes only. It does not reuse a partially written candidate array or overwrite the failed collection. Existing resume permits explicit runner changes and records old/current runner hashes; collector, selector, registry and policy checks remain in force.

```powershell
python examples/prepare_independent_candidates.py --policy examples/independent_candidate_policy_recovery_v2.json --resume-from .keel/independent-candidates/701028027c4c491f82989a3eff172ffc
```

No paid model calls. Three new integration tests cover a verified transfer, an unrelated candidate rejection with a durable failed checkpoint, and a transfer into a development repository. Twenty existing selector/miner tests also passed. This correction is collection plumbing, not task reproduction or repair success.
