# Freeze before the next candidate cohort

The current optional localized proposal path includes size-aware bounded localization refinement, installed-contract support, explicit repair evidence acquisition, per-proposal validation retry when repair is enabled, and bounded verification feedback under the original budget. Native/LangGraph role orchestration is not replaced. These capabilities have fixture tests and development observations, not a proven aggregate success-rate gain.

Development exposure includes Starlette 1936/2526, Flask-WTF 565 and HTTPX 1588. The last entry was missing from the development registry and is now added, preventing HTTPX repositories from being incorrectly admitted to repository-disjoint evaluation. Earlier collections are preserved with their original registry hashes; do not bypass cache/replay checks after this registry correction.

The Flask-WTF single-arm diagnostic passed initially in three calls, 2626 tokens and 23.39 runtime seconds. It did not exercise validation recovery, and its missing paired arm is intentional. Freeze after recording this outcome rather than repeatedly tuning for a particular generation.

`examples/independent_candidate_policy_next.json` fixes four new collection repositories and their dependency-name searches, limits, seed and screening policy before collection. This policy change defines a new experiment, not a favorable reinterpretation of an older shortlist. Prepared policy/implementation hashes are saved before any network collection. Candidate status is metadata-only; no executable independent tasks are currently established by this cohort.

Next command, read-only GitHub metadata collection, no paid model calls:

```powershell
python examples/prepare_independent_candidates.py --policy examples/independent_candidate_policy_next.json --execute
```

After collection, retain the selected IDs and apply curator review and old-base-pass/new-base-fail/new-gold-pass environment gates. Do not run models on invalid environments, silently replace failed candidates, expose gold fixes to runtime inputs, or claim independent success before those gates. Any runtime change after the freeze must create a new version and be reported; if driven by new task outcomes, those tasks become development data. The local freeze records hashes, not tamper-proof timestamps or external model weights.
