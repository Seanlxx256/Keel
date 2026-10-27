# Approved intermediate checkpoint archive

User authorized the proposed archival on2026-10-27. Scope: step1 through167 of
the two completed numbered_end/id_free_end cells in scout-representation-comparison-v1.
Keep finalstep168, training receipts, evaluation reports and all other experiments
in their original locations. Intermediate checkpoints remain restorable from E.

Actual source preflight verified334directories/2338files,2347107942bytes
(approximately2.19GiB), including checkpoint-file hashes against the completed
training receipts. Manifest, identity and preflight are in
`.keel/storage-audit-20261027-archive-v1/`. Destination:
`E:\KeelArchive\scout-representation-comparison-v1\intermediate-checkpoints-20261027.zip`.

The current assistant session is writable only under D:\keel, so it cannot write
this E destination. No production checkpoint has been removed and no E archive
has been created by the assistant. Execute locally:

```powershell
& D:\keel\.keel\storage-audit-20261027-archive-v1\run.ps1
```

Shared implementation `keel.checkpoint_archive` writes a separate partial ZIP,
embeds the complete manifest, decompresses and SHA256-checks every member,
rechecks source/final/receipt identity, then commits the archive. Only afterward
does it unlink manifest-listed files and remove their empty intermediate folders.
No recursive shell deletion, Docker operation or whole-root migration is used.
Path escape/reparse checks constrain cleanup to the authorized workspace roots.

If interrupted after archive completion, rerun the same script: it validates and
reuses the archive, verifies remaining source files, and continues cleanup.
An invalid incomplete ZIP is preserved for inspection, not silently overwritten.
All result/error state remains in archive-record/report.json (the configured
record directory here is storage-audit-20261027-archive-v1).

Example restore to the exact original checkpoint path:

```powershell
& D:\keel\.keel\harness-v3\Scripts\python.exe D:\keel\examples\archive_intermediate_checkpoints.py --record D:\keel\.keel\storage-audit-20261027-archive-v1 --restore-directory .keel/finetuning/scout-representation-comparison-v1/results/numbered_end/training-run/training/step-24
```

Restoring an archived checkpoint is required before evaluating that intermediate
step again. Final-step evaluations retain their original paths and files. The
archive is not optimizer resume certification or a new model score.

Five synthetic safety/recovery tests passed67.403seconds; an additional fast
deadline-validation regression passed afterward. Tests cover source corruption,
verification failure before deletion, interrupted cleanup recovery, actual ZIP
restoration/final preservation, and path escapes. They are distinct from the
actual2.19GiB source preflight; real E archival remains operator-executed.

## Completed operator execution and independent postcheck

The operator ran the script successfully in131.906seconds. All334selected
directories were removed only after archive verification. The archive is
2167199075bytes; source content2347107942bytes. Archive SHA256:
`23467d48417c2dfd5488be71b239409cfa1b244bd4f5c30dba3117a684d60beb`.

Independent postcheck rehashed the E archive and local manifest, verified all
334directories absent and every final checkpoint file/training receipt intact.
D now has5.79GiB free; E57.43GiB. Evidence: archive record `report.json` and
`postcheck.json`. This supersedes the earlier pending-execution status. The
original operation verified every decompressed member; the independent postcheck
verified the whole-container hash, not a second full restoration. Windows commit
headroom and training stability are separate and have not been revalidated.
