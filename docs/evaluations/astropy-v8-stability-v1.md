# Astropy v8 prospective stability repeats

Prepared two new runs using the exact accepted full-repair-v8 runtime snapshot, GPT-5.4 config, strict tokenizer policy, saved source, reference and diagnostic/comparison evidence. Only output locations differ in command arguments; identity comparison checked this offline. The original observed success is archived separately and excluded from the two-run prospective denominator.

Launcher: `.keel/repair-exploration/astropy-v8-stability-v1/run.ps1`. Each run retains the same 20-call/180000-token budget, 1200-second total deadline (300-second final-grade reserve), 1260-second containment. Aggregate ceilings: 40 calls, 360000 tokens, 42 minutes containment. Samples run sequentially; failure remains in denominator and does not trigger replacement. Reinvoking the launcher skips already attempted receipted samples; interrupted or orphaned outputs require inspection.

Archived accepted trial/transcript/prediction/patch/trace/official receipts and tests with hashes. Launch preflight checks protocol, seed plan, source snapshot, all input hashes and copied acceptance artifacts before credentials and dispatch. Existing bounded runner, process containment and stability summary pattern reused; no repair/runtime logic changed.

Both actual frozen CLI plan-only checks passed with zero model and Docker calls; PowerShell parsing passed. Initial summary correctly shows 0/2 because neither repeat is dispatched, not two failed repairs. Live repeat outcomes remain pending. Do not infer broad reliability or generalization from this one exposed case.

## Live outcome (2026-10-25)

Both predeclared repeats passed runtime and fresh official grading: **2/2**. Each has 1 target and 174 preservation tests passing, no failures, and one runtime verification round. Verified unchanged source snapshot, seed plan, all frozen inputs, accepted archive hashes and each per-instance grading receipt. Distinct official run IDs: `keel-9258081b306c451cacfe5bb0c1dcbb83`, `keel-eb8efaf5fe984004b46fbcfe9e7d1cca`. Their deterministic per-instance result bytes share SHA `28193db849ef7ec132ecd498baa6f58b98a14840f44a740f6db649e9b6449b62`; equal result bytes alone do not establish independent execution, while separate run artifacts identify the runs.

| Repeat | Model calls | Tokens | Tool calls | Whole trial seconds |
|---|---:|---:|---:|---:|
| 1 | 8 | 93753 | 17 | 339.188 |
| 2 | 8 | 89375 | 13 | 320.594 |

Aggregate new cost:16calls183128tokens30tools659.782s of summed trial time; watchdog elapsed350.078+330.063=680.141s. Initial v8 success remains separate; descriptively all three observed runs passed. This supports repeatability under this frozen exposed continuation, not a precise population success rate, tokenizer-only causality or held-out task transfer. No additional paid run or Docker action during review. Next investigate newline export quality without changing preserved accepted artifacts, then evaluate transfer on a fresh case.
