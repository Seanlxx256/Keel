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
        config = {**self.config, "agent": {"max_work_items": 1}}
        items = plan()["final"]
        items.append({"id": "extra", "description": "Another item", "files": ["app.py"]})
        result, _ = self.execute([self.impact(), {"final": items}], config)
        self.assertEqual(result["failure"]["category"], "model_error")
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
        self.assertEqual(model.schemas[0]["required"], ["final"])
        self.assertEqual(model.schemas[0]["properties"]["final"]["required"], ["summary", "files"])

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
