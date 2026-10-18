# Development checkpoints

User preference: whenever a new stable, verified increment is reached, proactively
state that it is ready for a Git commit and provide a concrete `git commit -m "..."`
command. Do not commit automatically. Describe the actual scope and evidence;
do not label mocked tests, development reruns, or partial integration as stronger
results than they establish. Report material remaining failures separately.

A checkpoint should have a reviewable change and relevant validation, with limitations
stated. For example, a real Compass stdio response archived in the Keel ledger is a
tool-integration checkpoint, not proof of end-to-end repair quality or HTTP interoperability.
