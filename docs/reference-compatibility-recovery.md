# Evidence-gated reference compatibility recovery

`recover-reference` now handles an observed SCM provider collision together with
declared installed dependency conflicts. It is a reference-environment controller,
not an Agent source repair or a claim of general environment learning.

The controller verifies the frozen task, reference prediction and failed grading,
binds the evidence and existing policy files, then inspects the retained image.
SCM removal still requires the existing independent provider calls and proof that
the conflicting provider has no dependents. Inspection never restores a missing
image automatically.

For import failures, a fixed network-disabled program inventories installed
versions and active dependency requirements. When at most three noneditable
consumers have declared conflicts, a separate read-only container uses the
[pip dry-run report](https://pip.pypa.io/en/stable/cli/pip_install/) to resolve
compatible consumer releases while constraining other installed versions.
Only binary distributions are considered. A maximum of three resolver rounds
share 150 seconds; newly introduced dependencies are excluded so the resolver
can backtrack without broadening the modification scope.

The host accepts only exact consumer pins from this bounded set. Provider anchors,
editable project distributions, pip/build tools and pytest/pluggy cannot be
replaced. Missing dependencies, metadata that does not explain the import failure,
resolver unavailability or broad changes produce an unresolved result, not a guess.

The policy is reapplied after repository and evaluation-time installations inside
the harness. Live guards recheck provider versions, editable status, exact applied
pins, unchanged other versions and absence of newly introduced dependency
conflicts. The project source, test commands, reference patch, labels and warning
policy remain unchanged. Official reference acceptance is the success condition;
metadata reconciliation alone is insufficient.

Policy receipts bind the exact JSON and propagate it to later Agent verification
and final grading. Cache identity hashes the complete final recipe, including the
repair program, before reuse. Changed policies may require a new image build;
inspection reuse does not promise that a new grading recipe will skip APT.

Run actions use owned, bounded containers with no host mount or injected API key.
Only the resolver needs networking. Reports preserve observations and candidate
actions before grading, keep old failures, reserve grading time and disclose
reconstructed conditions. Exact version pins are not a complete environment lock.

Future batches can opt in during preparation with `--recover-compatibility`.
This arm automatically handles failed graded references and can follow an enabled
network-recovery arm. It cannot stack with the older packaging overlay arm.
Existing frozen plans are unchanged. A successful recovered reference is handed
to the Agent; failed references never become zero-quality Agent results.

Validation includes generic fictional distributions, automatic observation-to-
resolution-to-grading and batch handoff, live guard execution with controlled
metadata, cache invalidation, image drift and receipt mutation. These checks do
not certify real Docker recovery or broad autonomous repair success.

### Failure-linked selection correction (2026-10-24)
The first live inventory found nine constraints involving eight consumers, most
unrelated to the observed failures. Selecting the entire inventory incorrectly
hit the three-consumer guard before resolution. The controller now joins actual
site-package traceback module paths with importlib.metadata's module/distribution
mapping, intersects these distributions with declared conflicts, and excludes
providers already handled by a separately verified action. It records selected
and untouched baseline conflicts in dependency-selection.json. Shared provider
identity alone does not authorize changing its other consumers. Frame membership
is evidence of relevance, not proof of causality; fresh acceptance remains required.
Classic editable distributions located under /testbed are also protected when
older installers do not write direct_url.json. Reports distinguish planned actions
from submission and reference verification, so an interrupted plan is not recorded
as an already executed uninstall. No consumer limit increase or case-specific pin.
