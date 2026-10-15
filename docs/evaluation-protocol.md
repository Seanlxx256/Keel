# Development versus independent evaluation

## Current evidence

The three curated real tasks are development diagnostics, permanently recorded
in `examples/evaluation_development_registry.json`:

| Task | Observed outcome | Why not independent |
| --- | --- | --- |
| Starlette #1936 | Proposal passed; tool loop failed | Repeated protocol, evidence and model diagnostics |
| Starlette #2526 | Proposal passed after context preparation correction | Task-specific anchors revised; patch inspected |
| Flask-WTF #565 | Initial acceptance failure; follow-up invalid patch | Feedback and function-window policy revised after inspection |

These observations are useful engineering evidence, not an unbiased estimate
of repair quality. Synthetic controls also remain development-only. The current
agent baseline runner always emits `evaluation_split: development` and
`heldout_eligible: false`; real task preparation requires registry membership.
There is no CLI switch that relabels these runs independent. Existing historical
artifacts are not rewritten: apply the registry when interpreting them.

No independent test set or independent result exists yet. Freeze tooling is
infrastructure, not additional task coverage or evidence of runtime benefit.
The next preparation step is [policy-bound candidate discovery](independent-candidates.md),
which fixes a repository pool, bounded search and outcome-blind ranking before
requesting metadata. A shortlist is not an executable independent task set.

## Rules for the next experiment

1. Finish runtime/prompt development first. Do not keep paying for ad hoc reruns
   of these cases to estimate success rate.
2. Select other repositories using a rule fixed before model outcomes. The
   protocol excludes entire development repositories and their recorded aliases,
   not just the three PR IDs. Record all screened candidates and exclusion reasons.
3. Prepare task inputs with a uniform localization policy, independent acceptance,
   reproducible environment and predeclared budgets. Inspect gold only for
   curator reproduction; never insert it or its replacement hints into model input.
4. Freeze inputs, model/settings and implementation before first inference. Do
   not tune anchors, prompts, acceptance or budgets based on evaluation failures.
5. Keep every planned first attempt, including environment and runtime failures.
   Report retry-assisted outcomes separately and include their cumulative costs.
6. If a failure is inspected to guide a change, register it as development and
   invalidate that evaluation freeze. A fresh independent evaluation needs new
   uninspected tasks; do not silently drop the failure and recompute the mean.

Curator validity work before inference is still human assistance. Record whether
files were operator-localized; do not compare it as autonomous retrieval. A
simple proposal and a tool-loop configuration require separate frozen settings
and matched task inputs. Changing several factors is a workflow comparison,
not an isolated component ablation.

## Local freeze and verification

Create a plan with this structure, using real paths to complete frozen task
packages and credential-free execution settings. This is a schema example,
not an available task or a ready-to-run benchmark:

```json
{
  "operator_declared_unseen": true,
  "settings_file": ".keel/new-evaluation/settings.json",
  "tasks": [
    {
      "id": "candidate-identifier",
      "repository": "another-owner/another-repository",
      "pr": 123,
      "task_file": ".keel/new-evaluation/candidate.json"
    }
  ]
}
```

Task packages must bind all actual source/environment/acceptance inputs, not
just a mutable path to them. Settings must contain model identity, strategy,
budgets, context and localization policy. This tool hashes declared files; it
does not recursively discover references inside arbitrary JSON or certify that
the supplied task/settings schema is complete. Never put API key values there.

```powershell
python examples/freeze_evaluation.py --plan .keel/new-evaluation/plan.json --output .keel/new-evaluation/frozen.json
python examples/freeze_evaluation.py --verify .keel/new-evaluation/frozen.json
```

Output must not already exist. Empty plans, development IDs/repositories,
duplicate PR aliases and escaping paths are rejected. The freeze hashes task
packages, settings, registry, Python source/file sets under keel/compass/examples/
adapters and pyproject.toml. Execution is not performed. Changes invalidate
verification instead of silently creating a new comparison.

A future independent runner must attach the exact `protocol_sha256`,
`settings_sha256` and `implementation_sha256`, plus `evaluation_split: independent`
and `prepared_only: false`. Each terminal record must carry its task ID,
`task_sha256`, `attempt: 1`, status, executed and passed booleans. Missing planned
tasks, repeats, invalid pass states and diagnostic reports fail validation:

```powershell
python examples/freeze_evaluation.py --verify .keel/new-evaluation/frozen.json --results .keel/new-evaluation/results.json
```

Do not manually relabel current diagnostic output to satisfy this envelope.
There is no independent execution adapter wired yet. Result verification checks
declared consistency, not Docker execution authenticity, acceptance correctness,
human exposure or statistical independence. Local timestamps/digests are not a
trusted remote preregistration service. API model weights and arbitrary external
dependencies are not pinned by local source hashes. An operator declaration of
unseen tasks is an explicit claim, not something the tool can infer or prove.

Five protocol tests cover development repository aliases, source/task/settings
drift, changed file sets, duplicate/missing results, retries, malformed outcomes,
path escapes, empty plans and manifest tampering. No live-model gain is claimed.
