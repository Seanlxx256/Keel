"""Role lifecycle with optional guarded recovery transitions from Critic."""
import time


class RoleStateMachine:
    TRANSITIONS = {
        "created": {"scout", "critic"},
        "scout": {"planner", "critic"},
        "planner": {"scout", "implementer", "critic"},
        "implementer": {"verifier", "critic"},
        "verifier": {"auditor", "critic"},
        "auditor": {"critic"},
        "critic": set(),
        "finished": set(),
    }

    def __init__(self, trace, clock=time.monotonic, *, allow_recovery=False):
        self.trace, self.clock = trace, clock
        self.state, self.phase = "created", "main"
        self.history = []
        self.started = None
        self.outcome = None
        self.allow_recovery = allow_recovery

    def enter(self, role, *, phase="main", previous_status="completed"):
        if not isinstance(role, str) or role not in self.TRANSITIONS or role in {"created", "finished"}:
            raise ValueError(f"Unknown execution role: {role}")
        if self.state == "finished":
            raise ValueError("Execution is already finished")
        if previous_status not in {"completed", "failed"}:
            raise ValueError("Role outcome must be completed or failed")
        if role == self.state and phase == self.phase:
            return
        baseline = (self.state == "scout" and role == "verifier" and phase == "baseline")
        resumed = (self.state == "verifier" and self.phase == "baseline" and role == "scout")
        if phase not in {"main", "baseline"} or (phase == "baseline" and not baseline) or (
                self.state == "verifier" and self.phase == "baseline" and role not in {"scout", "critic"}):
            raise ValueError("Invalid baseline verification transition")
        recovery = self.allow_recovery and self.state == 'critic' and role in {'scout', 'implementer'}
        if self.state == "finished" or not (baseline or resumed or recovery or role in self.TRANSITIONS[self.state]):
            raise ValueError(f"Invalid role transition: {self.state}/{self.phase} -> {role}/{phase}")
        self._close(previous_status)
        previous = self.state
        self.state, self.phase, self.started = role, phase, self.clock()
        self.trace.emit(role, "role_entered", previous=previous, phase=phase)

    def _close(self, status):
        if self.started is None:
            return
        row = {"role": self.state, "phase": self.phase, "status": status,
               "seconds": max(0, self.clock() - self.started)}
        self.history.append(row)
        self.trace.emit(self.state, "role_exited", **{key: value for key, value in row.items() if key != "role"})
        self.started = None

    def finish(self, outcome):
        if (outcome, self.state) not in {("passed", "auditor"), ("failed", "critic")}:
            raise ValueError(f"Cannot finish {outcome} from {self.state}")
        self._close("completed")
        self.state, self.outcome = "finished", outcome
        self.trace.emit("runtime", "state_machine_finished", outcome=outcome)

    def report(self):
        return {"state": self.state, "outcome": self.outcome, "history": list(self.history)}
