# Paired multi-repository evaluation preparation

The 2026-10-14 plan at
`.keel/swe-public/530fe11afe004575adf5c2f2ea3340ad/plan.json` freezes seed 42,
three repositories and three repetitions per policy/mode. Dataset revisions and
file hashes are recorded there before any checkout or model call.

| Repository | Instance | Base commit | Cached at planning |
| --- | --- | --- | --- |
| pallets/flask | pallets__flask-5014 | 7ee9ceb71e868944a46e1ff00b506772a53a4f1d | Yes |
| psf/requests | psf__requests-1724 | 1ba83c47ce7b177efe90d5f51f7760680f72eda0 | No |
| mwaskom/seaborn | mwaskom__seaborn-3069 | 54cab15bdacfaa05a88fbc5502a5b322d99f148e | No |

Snapshot existence in plan-only mode is not cleanliness or commit verification.
Actual execution still performs those checks. The planned experiment is 3 tasks,
2 ranking policies, 4 modes, and 3 repetitions: 72 retrieval runs, not 72 tasks.

The runner now supports multiple seeded instances per repository, paired policy
sweeps, fresh-index reuse, instance failure isolation, durable checkpoints and
paired-only quality summaries. Instance means exclude a task from a mode when
either policy is incomplete; all excluded IDs and per-mode denominators are
reported. Failed instances still make the overall process return exit code 1.

An attempt to fetch the pinned Requests snapshot failed in the agent execution
environment because its configured proxy at `127.0.0.1:9` refused the connection.
No Requests or Seaborn retrieval scores have been produced. The user shell can
run the complete preparation and experiment with:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\examples\run_swe_public.ps1 -Repositories 3 -CompareRankings -Repeats 3
```

This is development coverage, not a held-out test or an official benchmark result.
The default ranking remains RRF pending broader evidence.

## Runner verification

The offline execution at
`.keel/swe-public/0a0453ca5ee64619a8b6c9ad16d7e94b/` used one repetition to
exercise the batch pipeline. It reused the compatible Flask semantic index and
completed eight retrieval runs (two policies, four modes). Requests and Seaborn
were recorded as failed because their pinned snapshots were unavailable offline.
The batch continued, wrote all three instance checkpoints, and returned exit 1.
`comparison.json` reports exactly one paired instance per mode and lists the two
excluded IDs. This verifies pipeline behavior, not expanded retrieval coverage.
