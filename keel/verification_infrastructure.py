"""Keep unavailable verification separate from evidence that source tests failed."""
import json
import subprocess
import time

from .core import BudgetExceeded, PolicyDenied, digest


class EnvironmentBlocked(OSError):
    """Acceptance could not establish a test result; do not request a code repair."""


def infrastructure_failures(verification):
    failures = []
    for entry in verification:
        if entry.get('returncode') == 0:
            continue
        try:
            payload = json.loads(entry.get('stdout', ''))
        except (ValueError, TypeError):
            continue
        if not isinstance(payload, dict):
            continue
        # Only the structured verifier protocol is interpreted; arbitrary stderr
        # and nonzero return codes are not evidence of infrastructure failure.
        if (payload.get('official_resolved') is None and
                (payload.get('failure_kind') in {'grading_error', 'grading_timeout', 'infrastructure_error'}
                 or payload.get('grading_status') in {'grading_error', 'infrastructure_error'})):
            failures.append(payload)
    return failures


def verify_available(workspace, commands, *, phase, retries=0, attempts):
    snapshot = workspace.snapshot()
    for number in range(retries + 1):
        workspace.budget.check()
        verification = workspace.verify(commands, phase=phase if number == 0 else f'{phase}-infrastructure-{number}')
        if workspace.snapshot() != snapshot:
            raise PolicyDenied('Acceptance changed the workspace during infrastructure-guarded verification')
        failures = infrastructure_failures(verification)
        if not failures:
            return verification
        record = {'phase': phase, 'attempt': number, 'candidate_sha256': digest(snapshot),
                  'verification': verification, 'classification': 'environment_unavailable',
                  'scope': 'Same candidate retry; no code edits, model calls or host configuration changes'}
        attempts.append(record)
        fact = workspace.ledger.add('failed_attempt', 'verifier', 'Verification infrastructure unavailable', record)
        workspace.trace.emit('verifier', 'infrastructure_unavailable', fact_id=fact, attempt=number)
        if number == retries:
            raise EnvironmentBlocked('Verification infrastructure unavailable; preserved candidate and failure artifacts')
        if workspace.budget.remaining <= 2:
            raise BudgetExceeded('Insufficient wall-clock budget for infrastructure retry')
        workspace.trace.emit('verifier', 'infrastructure_retry_wait', seconds=2)
        time.sleep(2)


def docker_health(*, timeout=8):
    """Read the selected Docker server; never start, reset or reconfigure it."""
    try:
        result = subprocess.run(['docker', 'info', '--format', '{{json .ServerVersion}}'],
                                capture_output=True, text=True, timeout=timeout)
        try:
            version = json.loads(result.stdout.strip())
        except ValueError:
            version = None
        ready = result.returncode == 0 and isinstance(version, str) and bool(version.strip())
        return {'ready': ready, 'server_version': version if ready else None,
                'returncode': result.returncode, 'diagnostic': result.stderr[-1200:]}
    except (OSError, subprocess.TimeoutExpired) as error:
        return {'ready': False, 'error_type': type(error).__name__}
