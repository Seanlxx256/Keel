import unittest

from keel.state import RoleStateMachine


class StateTests(unittest.TestCase):
    def machine(self):
        events = []
        class Trace:
            def emit(self, role, event, **data):
                events.append((role, event, data))
        self.elapsed = 0
        return RoleStateMachine(Trace(), clock=lambda: self.elapsed), events

    def test_success_requires_verification_and_audit_then_terminal_state(self):
        state, events = self.machine()
        state.enter("scout")
        with self.assertRaises(ValueError):
            state.enter("auditor")
        for role in ("planner", "implementer", "verifier", "auditor"):
            self.elapsed += 1
            state.enter(role)
        self.elapsed += 1
        state.finish("passed")
        self.assertEqual([r["role"] for r in state.history], ["scout", "planner", "implementer", "verifier", "auditor"])
        self.assertEqual([r["seconds"] for r in state.history], [1] * 5)
        with self.assertRaises(ValueError):
            state.enter("scout")
        self.assertEqual(events[-1][1], "state_machine_finished")

    def test_baseline_phase_resumes_scout_and_failure_closes_through_critic(self):
        state, _ = self.machine()
        state.enter("scout")
        state.enter("verifier", phase="baseline")
        with self.assertRaises(ValueError):
            state.enter("auditor")
        with self.assertRaises(ValueError):
            state.finish("passed")
        state.enter("scout")
        state.enter("critic", previous_status="failed")
        state.finish("failed")
        self.assertEqual(state.history[1]["phase"], "baseline")
        self.assertEqual(state.history[-2]["status"], "failed")
        self.assertEqual(state.history[-1]["role"], "critic")
