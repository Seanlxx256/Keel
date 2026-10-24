# Process timeouts and inherited output

The live reference-network-v1 run stopped producing output while Docker unpacked a FROM layer. Its inner600second timeout did not hand control back before the1800second watchdog. The exact original blocking stack was not captured.

A real fixture reproduces the failure class against the archived old runner: a parent spawns a descendant inheriting stdout. Inner timeout2seconds still exceeds the outer12second fixture deadline. The patched Windows runner returns in about3.156seconds and the descendant heartbeat stops. This verifies local execution containment, not Docker image health or daemon-side build cancellation.

`run_harness` now redirects child stdout/stderr directly to a binary log file and polls that regular file for console progress. It has no output-reader thread whose buffered pipe lock can block close. Full output remains in the log; bounded console forwarding is recorded separately. Probe callers suppress raw output echo and retain existing diagnostic redaction.

On Windows, `keel.process_job` creates a kill-on-close Job Object. A trusted bootstrap assigns itself using the inherited job handle before spawning the actual command, then closes its inherited copy. This avoids a race with virtual-environment launcher redirection. The controller terminates the job on completion/timeout and bounds root reaping. The outer watchdog uses the same containment, including nested harness jobs. If assignment fails the tool is not launched; errors stay in the log. No host settings or administrator action is requested. [Microsoft Job Objects documentation](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects) describes default child membership and kill-on-close behavior.

On POSIX the runner creates a new session and signals that isolated process group. Explicitly detached processes and Docker daemon work remain outside any claim of verified cleanup. Timeout means the command deadline plus bounded local cleanup, not an exact zero-overhead return instant.

`harness-process.json` records terminal status, root result, cleanup mechanism and signal outcome. `descendants_verified` remains false in production metadata; real fixture heartbeat checks establish only the processes exercised in that test. Required process receipts still fail loudly, with cleanup attempted even if initial receipt writing fails.

Tests use a separately supervised worker so regression cannot hang the whole suite. They cover inherited output on normal parent exit, timeout, real outer watchdog descendants, and Windows nested jobs. Fixture cooperation is used only as an after-assertion safety backstop, never to satisfy termination checks. The first taskkill-only local attempt failed because taskkill was denied and a venv redirector outlived its killed launcher; this failure led to owned-job containment rather than relaxed assertions.

Next live check is examples/check_docker_runtime.py: no model, Docker info/identity checks, FROM plus Python print with --network=none,60second build deadline and150second outer guard. Its unique generated image tag is the only cleanup target. It does not run APT or certify reference recovery.
