# Supervision v1: preserved incomplete review

Plan: 837e45221859ccd5d6ac9a1fec48b45361d0d85a38010852ec4f20ada0e7c3da.
One new provider call, 3,745 tokens, 9.172 seconds. Initial diagnosis was replayed
without a provider call. No correction or final recheck occurred.

The reviewer returned verdict consistent but populated findings with three
supporting/no-conflict matches. The protocol reserves findings for contradictions.
It also named action as the field for a reason quotation and added quotation marks
not present in the cited diagnosis/evidence text. All three claim and evidence
substring checks fail. The host rejected the review as InvalidSelection. This is
not a character-limit or environment failure.

The content mostly verifies same test/call and accepts uncertainty, without
addressing whether the explanation of later steps conflicts with the earlier
observed failure. This does not demonstrate effective semantic supervision even
if the output-format mistakes were corrected. Consistent is a model judgment,
not independent task acceptance or evidence of no contradiction.

Developer changes clarify findings=[] for consistent/insufficient in both prompt
and schema description, enumerate available evidence IDs and explicitly require
raw exact substrings in the named field. Validation prioritizes the inconsistent
verdict/findings combination and traces its specific error. The review runner now
saves validation_error instead of only the exception class. No quotes are silently
stripped, fields reassigned or historical result upgraded to successful.

Offline checks and hashes are recorded in
.keel/repair-review/supervision-v1/offline-review.json. Original report and ledger
remain unchanged, no successful receipt issued, no new paid calls. Do not rerun
the frozen v1 launcher under changed implementation. Future work must distinguish
protocol reliability from genuine semantic review effectiveness and progress to
bounded execution evidence rather than repeating text-only trials indefinitely.
