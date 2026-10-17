# Candidate collection: add/remove operation pairs

Collection `.keel/independent-candidates/dfacdf461e8b47189c533075e83911ac` stopped at aiohttp PR 9576. Saved PR metadata declares 12 changed files. Its first file page contains 13 records but 12 unique paths: `CHANGES/9305.breaking.rst` occurs as both removed and added, with different blob SHAs. These are not identical duplicate responses. The previous validator incorrectly required record count and unique path count both to equal changed_files.

The collector now accepts exactly two records for one path only when their statuses are added and removed. It retains raw receipts, records the operation pair on collected candidates and requires unique path count to equal the declared count. Other duplicates, missing paths, malformed records and count mismatches still fail. This validates the metadata inventory only, not the semantics of the change or benchmark eligibility.

Offline validation of the actual saved page yields 12 unique paths from 13 operation records, without network or model calls. The original incomplete collection remains unchanged. The amendment changes collector behavior, so ordinary resume hash checks must not be silently bypassed. The explicit option below permits a new collection reusing verified old responses while retaining original/current collector hashes; policy, registry and selector hashes must match. It does not authorize arbitrary selector or policy changes.

```powershell
python examples/prepare_independent_candidates.py --policy examples/independent_candidate_policy_next.json --resume-from .keel/independent-candidates/dfacdf461e8b47189c533075e83911ac --file-listing-amendment
```

This fetches missing GitHub routes only and makes no paid model calls. It may still fail on another invalid response; do not suppress that failure. The earlier implementation freeze predates this collector amendment; record the amendment separately and create a new full freeze before task execution. No runtime repair logic was changed by this amendment.
