import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from keel.core import ModelError
from keel.models import OllamaModel, Reply
from keel.runtime import run


class ScriptedModel:
    def __init__(self, actions):
        self.actions = iter(actions)
        self.calls = []

    def complete(self, messages, **kwargs):
        self.calls.append(copy.deepcopy(messages))
        action = next(self.actions)
        return Reply(action if isinstance(action, str) else json.dumps(action), 100)


def plan(files=None):
    return {"final": [{"id": "upgrade", "description": "Upgrade VERSION to 2",
                       "depends_on": [], "files": files or ["app.py"]}]}


class AgentTests(unittest.TestCase):
    def test_required_change_returns_feedback_then_accepts_real_edit(self):
        result, model = self.execute([
            self.impact(), plan(),
            {'tool': 'read_file', 'arguments': {'path': 'app.py'}},
            {'final': 'I will inspect and edit next'},
            {'tool': 'replace', 'arguments': {'path': 'app.py', 'old': 'VERSION = 1', 'new': 'VERSION = 2'}},
            {'final': 'Updated'}], config={**self.config,
                'agent': {'max_steps': 4, 'require_change': True}})
        self.assertEqual(result['status'], 'passed')
        feedback = json.loads(model.calls[4][-1]['content'])
        self.assertFalse(feedback['ok'])
        self.assertIn('nonempty net source change', feedback['error'])
        self.assertEqual(result['budget']['model_calls'], 6)

    def test_edit_then_revert_cannot_satisfy_required_change(self):
        result, _ = self.execute([
            self.impact(), plan(),
            {'tool': 'replace', 'arguments': {'path': 'app.py', 'old': 'VERSION = 1', 'new': 'VERSION = 2'}},
            {'tool': 'replace', 'arguments': {'path': 'app.py', 'old': 'VERSION = 2', 'new': 'VERSION = 1'}},
            {'final': 'Done'}], config={**self.config, 'agent': {'max_steps': 3, 'require_change': True}})
        self.assertEqual(result['failure']['category'], 'budget_exhausted')
        self.assertEqual(result['failure']['stage'], 'implementer')
        self.assertEqual(result['verification'], [])
        self.assertEqual((self.repo/'app.py').read_text(), 'VERSION = 1\n')

    def test_no_change_task_remains_valid_when_change_not_required(self):
        config = {**self.config, 'goal': 'Inspect current version',
            'acceptance': [[sys.executable, '-c', 'import app; assert app.VERSION == 1']],
            'agent': {'require_change': False}}
        result, _ = self.execute([self.impact(), plan(), {'final': 'No source changes needed'}], config=config)
        self.assertEqual(result['status'], 'passed')

    def test_oversized_read_continuation_then_edit_reaches_verifier(self):
        (self.repo/'app.py').write_bytes(('# padding\n'*90+'VERSION = 1\n').encode())
        result, model = self.execute([
            {'tool': 'search_code', 'arguments': {'query': 'VERSION'}}, self.impact(), plan(),
            {'tool': 'read_lines', 'arguments': {'path': 'app.py', 'start_line': 1, 'end_line': 220}},
            {'tool': 'read_page', 'arguments': {'path': 'app.py', 'start_line': 81}},
            {'tool': 'replace', 'arguments': {'path': 'app.py', 'old': 'VERSION = 1', 'new': 'VERSION = 2'}},
            {'final': 'Updated'}], config={**self.config,
                'agent': {'require_evidence': True, 'max_steps': 4}})
        self.assertEqual(result['status'], 'passed')
        first = json.loads(model.calls[4][-1]['content'])['result']
        self.assertTrue(first['truncated'])
        self.assertEqual(first['next_line'], 81)
        second = json.loads(model.calls[5][-1]['content'])['result']
        self.assertIn('VERSION = 1', second['text'])
        self.assertIsNone(second['next_line'])
        self.assertEqual(result['verification'][0]['returncode'], 0)

    def test_planner_item_limit_feedback_recovers_within_same_budget(self):
        too_many = {'final': [
            {'id': 'inspect', 'description': 'Inspect source', 'files': ['app.py']},
            {'id': 'change', 'description': 'Implement upgrade', 'files': ['app.py']}]}
        result, model = self.execute([
            {'tool': 'read_file', 'arguments': {'path': 'app.py'}}, self.impact(),
            too_many, plan(),
            {'tool': 'read_file', 'arguments': {'path': 'app.py'}},
            {'tool': 'replace', 'arguments': {'path': 'app.py', 'old': 'VERSION = 1', 'new': 'VERSION = 2'}},
            {'final': 'Updated'}], config={**self.config,
                'agent': {'require_evidence': True, 'max_steps': 3, 'max_work_items': 1}})
        self.assertEqual(result['status'], 'passed')
        feedback = json.loads(model.calls[3][-1]['content'])
        self.assertFalse(feedback['ok'])
        self.assertIn('1..1 work items', feedback['error'])
        self.assertEqual(result['budget']['model_calls'], 7)
        self.assertEqual(len(result['work_items']), 1)

    def test_bare_scout_after_observation_wraps_without_an_extra_model_call(self):
        result, model = self.execute([
            {'tool': 'read_file', 'arguments': {'path': 'app.py'}},
            {'summary': 'Version needs updating', 'files': ['app.py']}, plan(),
            {'tool': 'read_file', 'arguments': {'path': 'app.py'}},
            {'tool': 'replace', 'arguments': {'path': 'app.py', 'old': 'VERSION = 1', 'new': 'VERSION = 2'}},
            {'final': 'Changed version'}], config={**self.config,
                'agent': {'require_evidence': True, 'max_steps': 3}})
        self.assertEqual(result['status'], 'passed')
        self.assertEqual(len(model.calls), 6)
        events = [json.loads(line) for line in (self.repo/'.keel/run/trace.jsonl').read_text().splitlines()]
        normalized = [e for e in events if e['event'] == 'action_envelope_normalized']
        self.assertEqual(len(normalized), 1)
        self.assertEqual(normalized[0]['rule'], 'scout-final-wrapper-v1')
        self.assertEqual((self.repo/'app.py').read_text(), 'VERSION = 2\n')

    def test_envelope_normalization_is_exact_and_role_evidence_gated(self):
        from keel.agents import normalize_scout_envelope
        valid = {'summary': 'Observed source', 'files': ['app.py']}
        for value, role, ready in [
            (valid, 'scout', False), (valid, 'implementer', True),
            (valid, 'planner', True), ({**valid, 'tool': 'replace'}, 'scout', True),
            ({'summary': 'Missing files'}, 'scout', True),
            ({'summary': 1, 'files': ['app.py']}, 'scout', True),
            ({'summary': 'Wrong types', 'files': [1]}, 'scout', True)]:
            with self.subTest(value=value, role=role, ready=ready):
                self.assertEqual(normalize_scout_envelope(value, role=role, ready=ready), (value, False))

    def test_bare_scout_output_is_rejected_then_recovers_through_real_evidence(self):
        result, model = self.execute([
            {'summary': 'Uninspected guess', 'files': ['app.py']},
            {'tool': 'read_lines', 'arguments': {'path': 'app.py', 'start_line': 1, 'end_line': 1}},
            self.impact(), plan(),
            {'tool': 'read_file', 'arguments': {'path': 'app.py'}},
            {'tool': 'replace', 'arguments': {'path': 'app.py', 'old': 'VERSION = 1', 'new': 'VERSION = 2'}},
            {'final': 'Changed version'}], config={**self.config,
                'agent': {'require_evidence': True, 'max_steps': 5}})
        self.assertEqual(result['status'], 'passed')
        self.assertIn('Always wrap it as', model.calls[0][0]['content'])
        feedback = json.loads(model.calls[1][-1]['content'])
        self.assertFalse(feedback['ok'])
        self.assertIn('Repository evidence must be inspected', feedback['error'])
        self.assertIn('{"final": VALUE}', feedback['error'])
        self.assertEqual((self.repo/'app.py').read_text(), 'VERSION = 2\n')

    def test_last_turn_allows_tool_and_exhaustion_does_not_claim_completion(self):
        schemas = []
        class StructuredModel(ScriptedModel):
            def complete_json(self, messages, *, schema, **kwargs):
                schemas.append(schema)
                return self.complete(messages, **kwargs)
        model = StructuredModel([{'tool': 'read_file', 'arguments': {'path': 'app.py'}}])
        config = {**self.config, 'agent': {'max_steps': 1}}
        result = run(config, self.repo, self.repo/'.keel/run', model=model)
        self.assertIn('"read_file"', json.dumps(schemas[0]))
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['failure']['category'], 'budget_exhausted')
        self.assertEqual(result['failure']['stage'], 'scout')
        self.assertEqual(result['verification'], [])

    def test_repeated_unchanged_read_switches_schema_and_edit_restores_it(self):
        actions = [{'tool': 'read_file', 'arguments': {'path': 'app.py'}}, self.impact(), plan(),
            {'tool': 'read_file', 'arguments': {'path': 'app.py'}},
            {'tool': 'read_file', 'arguments': {'path': 'app.py'}},
            {'tool': 'read_lines', 'arguments': {'path': 'app.py', 'start_line': 1, 'end_line': 1}},
            {'tool': 'replace', 'arguments': {'path': 'app.py', 'old': 'VERSION = 1', 'new': 'VERSION = 2'}},
            {'tool': 'read_file', 'arguments': {'path': 'app.py'}}, {'final': 'Updated version'}]
        schemas = []
        class StructuredModel(ScriptedModel):
            def complete_json(self, messages, *, schema, **kwargs):
                schemas.append(schema)
                return self.complete(messages, **kwargs)
        model = StructuredModel(actions)
        result = run(self.config, self.repo, self.repo/'.keel/run', model=model)
        self.assertEqual(result['status'], 'passed')
        self.assertNotIn('"read_file"', json.dumps(schemas[5]))
        self.assertIn('"read_lines"', json.dumps(schemas[5]))
        self.assertIn('"read_file"', json.dumps(schemas[7]))
        events = [json.loads(line) for line in (self.repo/'.keel/run/trace.jsonl').read_text().splitlines()]
        switches = [event for event in events if event['event'] == 'tool_strategy_changed']
        self.assertEqual(len(switches), 2)
        self.assertEqual(switches[0]['reason'], 'unchanged_repeated_read')
        self.assertEqual(switches[1]['reason'], 'source_edited')
        self.assertEqual((self.repo/'app.py').read_text(), 'VERSION = 2\n')

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name)
        (self.repo / "app.py").write_text("VERSION = 1\n")
        self.config = {"mode": "agent", "goal": "Upgrade VERSION to 2", "budget": {"max_tokens": 100000},
                       "acceptance": [[sys.executable, "-c", "import app; assert app.VERSION == 2"]]}

    def execute(self, actions, config=None):
        model = ScriptedModel(actions)
        result = run(config or self.config, self.repo, self.repo / ".keel" / "run", model=model)
        return result, model

    def impact(self):
        return {"final": {"summary": "Change version constant", "files": ["app.py"]}}

    def test_model_driven_run_and_context_isolation(self):
        result, model = self.execute([
            {"tool": "search_code", "arguments": {"query": "VERSION"}},
            self.impact(), plan(),
            {"tool": "read_file", "arguments": {"path": "app.py"}},
            {"tool": "replace", "arguments": {"path": "app.py", "old": "VERSION = 1", "new": "VERSION = 2"}},
            {"final": "Updated VERSION"},
        ])
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["budget"]["model_calls"], 6)
        self.assertEqual(result["budget"]["tokens"], 600)
        spans = json.loads(Path(result["telemetry"]["path"]).read_text())["resourceSpans"][0]["scopeSpans"][0]["spans"]
        self.assertEqual(sum(span["name"] == "keel.model" for span in spans), 6)
        self.assertEqual(sum(span["name"] == "keel.tool" for span in spans), 3)
        self.assertEqual(sum(span["name"] == "keel.verification" for span in spans), 1)
        self.assertTrue(all("endTimeUnixNano" in span for span in spans))
        self.assertEqual(len(model.calls[2]), 2)  # Planner gets impact, not Scout history.
        self.assertEqual(len(model.calls[3]), 2)  # Implementer starts fresh.
        self.assertNotIn('"fact_id"', model.calls[2][1]["content"])

    def test_opt_in_handoff_filters_files_and_preserves_fresh_histories(self):
        (self.repo / "private.py").write_text("SECRET = 9\n")
        config = {**self.config, "context_handoff": True}
        result, model = self.execute([
            {"tool": "read_file", "arguments": {"path": "app.py"}},
            {"tool": "read_file", "arguments": {"path": "private.py"}},
            self.impact(), plan(),
            {"tool": "replace", "arguments": {"path": "app.py", "old": "VERSION = 1", "new": "VERSION = 2"}},
            {"final": "Updated version"},
        ], config)
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["memory"]["handed_off_facts"], 2)
        planner = json.loads(model.calls[3][1]["content"])
        implementer = json.loads(model.calls[4][1]["content"])
        self.assertEqual(len(planner["evidence"]), 1)
        self.assertEqual(len(implementer["evidence"]), 1)
        self.assertEqual(implementer["evidence"][0]["path"], "app.py")
        self.assertNotEqual(planner["evidence"][0]["fact_id"], implementer["evidence"][0]["fact_id"])
        self.assertNotIn("SECRET", model.calls[3][1]["content"])
        self.assertEqual(len(model.calls[4]), 2)

    def test_handoff_drops_evidence_changed_by_previous_work_item(self):
        items = plan()["final"]
        items.append({"id": "review", "description": "Review changed source", "files": ["app.py"],
                      "depends_on": ["upgrade"]})
        result, model = self.execute([
            {"tool": "read_file", "arguments": {"path": "app.py"}}, self.impact(), {"final": items},
            {"tool": "replace", "arguments": {"path": "app.py", "old": "VERSION = 1", "new": "VERSION = 2"}},
            {"final": "Updated version"}, {"final": "Reviewed"},
        ], {**self.config, "context_handoff": True})
        self.assertEqual(result["status"], "passed")
        self.assertEqual(json.loads(model.calls[5][1]["content"])["evidence"], [])

    def test_inherited_evidence_cannot_satisfy_local_observation_gate(self):
        result, model = self.execute([
            {"tool": "read_file", "arguments": {"path": "app.py"}}, self.impact(), plan(),
            {"final": "Already updated"},
            {"tool": "read_file", "arguments": {"path": "app.py"}},
            {"tool": "replace", "arguments": {"path": "app.py", "old": "VERSION = 1", "new": "VERSION = 2"}},
            {"final": "Updated version"},
        ], {**self.config, "context_handoff": True, "agent": {"require_evidence": True}})
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["memory"]["handed_off_facts"], 2)
        self.assertTrue(any(f["kind"] == "failed_attempt" and f["role"] == "implementer"
                            for f in result["facts"]))
        self.assertIn("in this session", model.calls[4][-1]["content"])

    def test_readonly_role_cannot_write(self):
        result, _ = self.execute([{"tool": "replace", "arguments": {
            "path": "app.py", "old": "1", "new": "2"}}])
        self.assertEqual(result["failure"]["category"], "policy_denied")
        self.assertEqual((self.repo / "app.py").read_text(), "VERSION = 1\n")

    def test_implementer_cannot_write_undeclared_file(self):
        (self.repo / "other.py").write_text("VALUE = 1\n")
        result, _ = self.execute([self.impact(), plan(), {"tool": "replace", "arguments": {
            "path": "other.py", "old": "1", "new": "2"}}])
        self.assertEqual(result["failure"]["category"], "policy_denied")

    def test_protected_model_plan_rejected(self):
        result, _ = self.execute([self.impact(), plan(["tests/check.py"])])
        self.assertEqual(result["failure"]["category"], "policy_denied")

    def test_invalid_json_can_recover_and_is_recorded(self):
        result, _ = self.execute(["not json", self.impact(), plan(), {"final": "No edit"}])
        self.assertEqual(result["failure"]["category"], "verification_failed")
        self.assertTrue(any(f["kind"] == "failed_attempt" and f["role"] == "scout" for f in result["facts"]))

    def test_model_claim_cannot_bypass_verification(self):
        result, _ = self.execute([self.impact(), plan(), {"final": "All tests pass!"}])
        self.assertEqual(result["failure"]["category"], "verification_failed")

    def test_role_cannot_recall_another_roles_fact(self):
        result, _ = self.execute([self.impact(), {"tool": "recall", "arguments": {"fact_id": 1}}])
        self.assertEqual(result["failure"]["category"], "policy_denied")

    def test_token_preflight_prevents_request(self):
        config = {**self.config, "budget": {"max_tokens": 1}}
        result, model = self.execute([], config)
        self.assertEqual(result["failure"]["category"], "budget_exhausted")
        self.assertEqual(model.calls, [])

    def test_role_turn_limit(self):
        config = {**self.config, "agent": {"max_steps": 1}}
        result, _ = self.execute([{"tool": "list_files", "arguments": {}}], config)
        self.assertEqual(result["failure"]["category"], "budget_exhausted")

    def test_model_call_limit(self):
        config = {**self.config, "budget": {"max_model_calls": 1}}
        result, model = self.execute([self.impact()], config)
        self.assertEqual(result["failure"]["category"], "budget_exhausted")
        self.assertEqual(len(model.calls), 1)

    def test_http_adapter_contract_without_network(self):
        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self, size):
                return json.dumps({"done": True, "message": {"content": '{"final": "ok"}'},
                                   "prompt_eval_count": 10, "eval_count": 5}).encode()
        with patch("keel.models.urllib.request.urlopen", return_value=Response()) as request:
            reply = OllamaModel("local-model").complete([{"role": "user", "content": "test"}],
                                                        timeout=2, max_output=100)
        body = json.loads(request.call_args.args[0].data)
        self.assertFalse(body["stream"])
        self.assertEqual(body["format"], "json")
        self.assertEqual(body["options"]["num_predict"], 100)
        self.assertEqual(reply.tokens, 15)
        schema = {"type": "object", "properties": {"final": {"type": "array"}}, "required": ["final"]}
        with patch("keel.models.urllib.request.urlopen", return_value=Response()) as request:
            OllamaModel("local-model", num_ctx=8192).complete_json([], schema=schema, timeout=2, max_output=100)
        self.assertEqual(json.loads(request.call_args.args[0].data)["format"], schema)
        self.assertEqual(json.loads(request.call_args.args[0].data)["options"]["num_ctx"], 8192)
        self.assertEqual(json.loads(request.call_args.args[0].data)["options"]["num_batch"], 32)
        self.assertEqual(json.loads(request.call_args.args[0].data)["keep_alive"], 0)

    def test_plan_item_cap_is_enforced_before_implementation(self):
        config = {**self.config, "agent": {"max_work_items": 1, "max_steps": 1}}
        items = plan()["final"]
        items.append({"id": "extra", "description": "Another item", "files": ["app.py"]})
        result, _ = self.execute([self.impact(), {"final": items}], config)
        self.assertEqual(result["failure"]["category"], "budget_exhausted")
        self.assertEqual(result["failure"]["stage"], "planner")
        self.assertEqual(result['verification'], [])
        self.assertEqual((self.repo / "app.py").read_text(), "VERSION = 1\n")

    def test_evidence_gate_rejects_early_final_and_recovers(self):
        config = {**self.config, "agent": {"require_evidence": True}}
        result, _ = self.execute([
            self.impact(),
            {"tool": "read_file", "arguments": {"path": "app.py"}},
            self.impact(), plan(),
            {"tool": "read_file", "arguments": {"path": "app.py"}},
            {"tool": "replace", "arguments": {"path": "app.py", "old": "VERSION = 1", "new": "VERSION = 2"}},
            {"final": "Changed version"},
        ], config)
        self.assertEqual(result["status"], "passed")
        self.assertTrue(any(f["kind"] == "failed_attempt" and f["role"] == "scout" for f in result["facts"]))

    def test_structured_role_contracts_and_final_turn(self):
        from keel.agents import AgentSession
        from keel.core import Budget, Ledger, Limits, Trace
        from keel.workspace import Workspace
        class StructuredModel:
            def __init__(self):
                self.schemas = []
            def complete_json(self, messages, *, schema, **kwargs):
                self.schemas.append(schema)
                return Reply(json.dumps({"final": {"summary": "Inspect app", "files": ["app.py"]}}), 10)
        ledger = Ledger(self.repo / "ledger.sqlite")
        self.addCleanup(ledger.close)
        workspace = Workspace(self.repo, Budget(Limits(max_tokens=100000)), ledger,
                              Trace(self.repo / "trace.jsonl"))
        model = StructuredModel()
        value = AgentSession("scout", model, workspace, max_steps=1).execute({}, "impact")
        self.assertEqual(value["files"], ["app.py"])
        final_branch = model.schemas[0]['oneOf'][1]
        self.assertEqual(final_branch['required'], ['final'])
        self.assertEqual(final_branch['properties']['final']['required'], ['summary', 'files'])
        self.assertIn('"read_file"', json.dumps(model.schemas[0]['oneOf'][0]))

    def test_cpu_configuration_reaches_ollama_request(self):
        from keel.models import from_config
        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self, size):
                return json.dumps({"done": True, "message": {"content": "{}"},
                                   "prompt_eval_count": 1, "eval_count": 1}).encode()
        model = from_config({"name": "keel-chat", "num_ctx": 8192, "num_gpu": 0})
        with patch("keel.models.urllib.request.urlopen", return_value=Response()) as request:
            model.complete([], timeout=1, max_output=32)
        self.assertEqual(json.loads(request.call_args.args[0].data)["options"]["num_gpu"], 0)
        for value in [-1, True, "0"]:
            with self.assertRaises(ValueError):
                OllamaModel("keel-chat", num_gpu=value)

    def test_transport_error_is_reported_without_credentials(self):
        from urllib.error import URLError
        with patch("keel.models.urllib.request.urlopen", side_effect=URLError("secret")):
            with self.assertRaises(ModelError) as caught:
                OllamaModel("local-model").complete([], timeout=1, max_output=100)
        self.assertNotIn("secret", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
