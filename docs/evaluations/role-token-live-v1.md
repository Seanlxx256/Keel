# Three-role strict token-counting live check

Prepared launcher: `.keel/repair-review/role-token-live-v1/run.ps1`.

This small integration check replays three exposed historical requests from Astropy full-repair-v4: first Critic, first Scout catalog selection, and Implementer proposal. It freezes their messages/schema, current runtime source snapshot, current model configuration and exact offline encoding. The v2 strict policy's capacity parameters are unchanged; only its encoding path points to the experiment's byte-identical local copy.

One shared budget: **3 model calls,45000tokens,180seconds**, with each provider call <=60seconds. Output allowances: Critic2048, Scout1024, Implementer4096. Calls are sequential and charged from the same Budget; no retries or per-role reset. Raw replies are saved before host validation. The runner checks Critic response structure, Scout membership in the frozen catalog and scoped edit structure. It does **not** apply edits, claim semantic diagnostic correctness, run Docker or score repair. Consequently `completed` means interface/strict-counting flow completed, not task success.

Required role/report/receipt artifacts survive failures. `--resume` reuses receipt-verified completed roles and carries usage/time; unfinished paid calls are refused. Missing credential preflight fails before creating a new results directory. Input/snapshot drift and independent request byte-ceiling violations stop before dispatch. The launcher refuses an existing output unless explicit resume is requested; it never changes historical runs.

Local validation:31relatedtests passed2.198s, covering shared three-call budget, no source writes, receipt reuse with no extra calls, invalid Scout selection stopping later calls, and credential failure before output creation. Actual frozen snapshot/asset hashes and PowerShell syntax verified.

Zero-provider preflight with the real installed tokenizer and saved historical responses completed all three role interfaces. Input estimates10111/13930/13839, each with1024safety; replayed old reported totalusage36661 fits the45000 budget. `offline-preflight.json` explicitly identifies this as historical usage replay, **not 36661 newly consumed tokens or three new API calls**. It validates runner mechanics; output variability, provider latency and current usage remain for the live check. Creator snapshot environment is not the live interpreter environment.

Next run:

```powershell
& D:\keel\.keel\repair-review\role-token-live-v1\run.ps1
```

Live results should show `offline_tiktoken` for all roles and compare estimates/safety against newly reported prompt usage. No policy promotion or new repair acceptance follows automatically.

## Observed live result (2026-10-25)

Verified plan identity, all frozen input hashes, three role receipts and the sum of provider usage. All calls reported `gpt-5.4-mini-2026-03-17` and used `offline_tiktoken`.

| Role | Estimated input | Reserved with safety | Actual prompt | Actual completion |
|---|---:|---:|---:|---:|
| Critic | 10111 | 11135 | 9494 | 689 |
| Scout | 13930 | 14954 | 13004 | 32 |
| Implementer | 13839 | 14863 | 11855 | 1395 |

Estimates exceeded actual prompt usage by approximately 6.5%, 7.1% and 16.7%, before the additional 1024-token safety reservation. No binding capacity constraint occurred. Total new usage: **36469 tokens, 3 calls, 32.031 seconds**, within the shared 45000-token/180-second budget.

This confirms live counting and role response interfaces for these frozen requests, not semantic diagnosis, patch applicability or repair success. No new API call was made during review. Next: a separately frozen bounded real repair using the strict policy, preserving acceptance and total-budget constraints.
