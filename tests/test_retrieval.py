import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from compass.evaluation import evaluate, file_metrics, load_queries
from compass.index import RepositoryIndex, build_index
from compass.retrieval import Retriever, Routing, routing_from_dict
from compass.vectors import HashEmbedder
from keel.core import Budget, BudgetExceeded, Ledger, Limits, Trace
from keel.models import Reply
from keel.runtime import run
from keel.workspace import Workspace


class Scripted:
    def __init__(self, actions):
        self.actions, self.calls = iter(actions), []

    def complete(self, messages, **kwargs):
        self.calls.append(copy.deepcopy(messages))
        return Reply(json.dumps(next(self.actions)), 20)


class RetrievalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "storage.py").write_bytes(b'def save_order(payload):\n    """Persist purchase record."""\n    return payload\n')
        (self.root / "service.py").write_bytes(b'from storage import save_order\ndef submit_order(payload):\n'
                                               b'    """Submit checkout."""\n    return save_order(payload)\n')
        (self.root / "ui.py").write_bytes(b'from service import submit_order\ndef handle_click(payload):\n'
                                          b'    """Checkout button."""\n    return submit_order(payload)\n')
        build_index(self.root, parser="python-ast", vector_store="sqlite", embedder=HashEmbedder())
        self.index = RepositoryIndex(self.root)
        self.addCleanup(self.index.close)
        self.save_id = self.index.find_symbol("save_order")["results"][0]["id"]
        self.submit_id = self.index.find_symbol("submit_order")["results"][0]["id"]

    def relaxed(self, **kwargs):
        return Routing(**{"min_relevance": 0, "min_overlap": 0, "max_entropy": 1, "max_files": 1000, **kwargs})

    def test_t0_unique_symbol_bypasses_vector_and_model(self):
        model = Scripted([])
        with patch.object(self.index, "search_vector", side_effect=AssertionError("expensive path reached")):
            result = Retriever(self.index, model=model).retrieve("save_order")
        self.assertEqual(result["tier"], "T0")
        self.assertEqual(result["results"][0]["id"], self.save_id)
        self.assertEqual(result["usage"]["model_calls"], 0)
        self.assertEqual(model.calls, [])

    def test_t0_exact_path_and_missing_symbol(self):
        retriever = Retriever(self.index)
        self.assertEqual(retriever.retrieve("storage.py")["tier"], "T0")
        self.assertEqual(retriever.retrieve("missing", mode="t0")["results"], [])

    def test_t1_bm25_and_vector_fuse_with_provenance(self):
        result = Retriever(self.index, routing=self.relaxed()).retrieve("persist purchase record")
        self.assertEqual(result["tier"], "T1")
        self.assertEqual(result["results"][0]["id"], self.save_id)
        self.assertEqual(set(result["results"][0]["channels"]), {"bm25", "vector"})
        self.assertEqual(result["routing"]["upgrade_reasons"], [])
        self.assertIsNone(result["confidence"])

    def test_wide_file_span_defers_upgrade_without_model(self):
        result = Retriever(self.index, routing=self.relaxed(max_files=1)).retrieve("checkout purchase")
        self.assertIn("wide_file_span", result["routing"]["upgrade_reasons"])
        self.assertEqual(result["routing"]["mode_status"], "model_unconfigured")
        self.assertEqual(result["tier"], "T1")

    def test_adaptive_gate_enters_t2_only_after_t1_evidence(self):
        model = Scripted([{"final": [self.save_id]}])
        result = Retriever(self.index, model=model, routing=self.relaxed(max_files=1)).retrieve("purchase checkout")
        self.assertEqual(result["tier"], "T2")
        self.assertEqual([step["tier"] for step in result["routing"]["trace"]], ["T0", "T1", "T2"])
        self.assertIn("wide_file_span", result["routing"]["upgrade_reasons"])
        self.assertEqual(result["usage"]["model_calls"], 1)

    def test_ambiguous_symbol_routes_to_t1_and_qualified_name_stays_t0(self):
        (self.root / "other.py").write_bytes(b"def save_order(value):\n    return value\n")
        build_index(self.root, parser="python-ast", vector_store="sqlite", embedder=HashEmbedder())
        with RepositoryIndex(self.root) as index:
            retriever = Retriever(index, routing=self.relaxed())
            self.assertEqual(retriever.retrieve("save_order")["tier"], "T1")
            self.assertEqual(retriever.retrieve("storage.save_order")["tier"], "T0")

    def test_t2_graph_expansion_read_and_final_selection(self):
        model = Scripted([{"expand": [self.save_id]}, {"read": self.submit_id}, {"final": [self.submit_id]}])
        events = []
        result = Retriever(self.index, model=model, routing=self.relaxed(candidates=1),
                           record=lambda event, data: events.append((event, data))).retrieve("persist purchase record", mode="t2")
        self.assertEqual(result["tier"], "T2")
        self.assertEqual(result["results"][0]["id"], self.submit_id)
        self.assertIn("graph", result["results"][0]["channels"])
        self.assertEqual(result["routing"]["mode_status"], "completed")
        self.assertEqual(result["usage"]["model_calls"], 3)
        self.assertEqual(result["usage"]["tokens"], 60)
        self.assertTrue(any(event == "retrieval_model_reply" for event, _ in events))

    def test_query_expansion_preserves_original_error_and_api_anchors(self):
        model = Scripted([{"query": "checkout"}, {"final": [self.save_id]}])
        events = []
        Retriever(self.index, model=model, routing=self.relaxed(), record=lambda event, data: events.append((event, data))).retrieve(
            "purchase save_order", mode="t2")
        queries = [data["query"] for event, data in events if event == "retrieval_gate"]
        self.assertEqual(queries[1], "purchase save_order\ncheckout")

    def test_unknown_model_ids_are_rejected_before_access(self):
        model = Scripted([{"read": "invented-id"}, {"final": [self.save_id]}])
        result = Retriever(self.index, model=model).retrieve("persist purchase", mode="t2")
        self.assertEqual(result["routing"]["trace"][1]["action"], "invalid")
        self.assertEqual(result["results"][0]["id"], self.save_id)

    def test_t2_turn_and_node_limits_are_explicit(self):
        model = Scripted([{"read": self.save_id}])
        result = Retriever(self.index, model=model, routing=self.relaxed(max_steps=1, max_nodes=1)).retrieve(
            "persist purchase", mode="t2")
        self.assertEqual(result["routing"]["mode_status"], "step_limit")
        self.assertEqual(len(result["results"]), 1)

    def test_model_and_tool_budget_exhaustion_stop_retrieval(self):
        model = Scripted([{"read": self.save_id}])
        with self.assertRaises(BudgetExceeded):
            Retriever(self.index, model=model, budget=Budget(Limits(max_model_calls=1))).retrieve("persist purchase", mode="t2")
        with self.assertRaises(BudgetExceeded):
            Retriever(self.index, budget=Budget(Limits(max_tool_calls=1))).retrieve("persist purchase", mode="t1")

    def test_bm25_only_index_is_labeled(self):
        build_index(self.root, parser="python-ast")
        with RepositoryIndex(self.root) as index:
            result = Retriever(index, routing=self.relaxed()).retrieve("persist purchase", mode="t1")
            self.assertFalse(result["signals"]["vector_available"])
            self.assertEqual(result["routing"]["trace"][0]["channels"], ["bm25"])

    def test_invalid_routing_settings_rejected(self):
        for settings in ({"min_overlap": float("nan")}, {"unknown": 1}, {"max_nodes": 0}):
            with self.subTest(settings=settings), self.assertRaises(ValueError):
                routing_from_dict(settings)

    def test_keel_compass_search_uses_shared_budget_and_trace(self):
        output = self.root / ".keel" / "test"
        output.mkdir(parents=True)
        ledger = Ledger(output / "ledger.sqlite")
        self.addCleanup(ledger.close)
        budget = Budget(Limits())
        workspace = Workspace(self.root, budget, ledger, Trace(output / "trace.jsonl"),
                              retrieval={"provider": "compass"})
        result = workspace.search("save_order")
        self.assertEqual(result["tier"], "T0")
        self.assertEqual(result["matches"][0]["file"], "storage.py")
        self.assertEqual(budget.tool_calls, 1)
        self.assertTrue(any(f["summary"] == "retrieval_finished" for f in ledger.summaries()))
        self.assertEqual(workspace.find_symbol("save_order")["results"][0]["id"], self.save_id)
        self.assertTrue(workspace.get_context("storage.py", 2)["incoming"])
        workspace.replace("storage.py", "return payload", "return dict(payload)")
        with self.assertRaisesRegex(ValueError, "stale"):
            workspace.search("save_order")

    def test_full_keel_run_with_compass_queries(self):
        config = {"goal": "Wrap payload in a dictionary", "retrieval": {"provider": "compass"},
                  "queries": ["persist purchase"], "work_items": [{"id": "wrap", "edits": [
                      {"path": "storage.py", "old": "return payload", "new": "return dict(payload)"}]}],
                  "acceptance": [[sys.executable, "-c", "from storage import save_order; assert save_order({'id': 1}) == {'id': 1}"]]}
        result = run(config, self.root, self.root / ".keel" / "run")
        self.assertEqual(result["status"], "passed")
        self.assertTrue(any(f["summary"] == "retrieval_gate" for f in result["facts"]))

    def test_evaluation_records_modes_costs_and_source_without_benchmark_claims(self):
        queries = [{"id": "purchase", "query": "persist purchase record", "relevant_files": ["storage.py"], "source": "synthetic-test"}]
        result = evaluate(self.index, queries, modes=["t0", "t1", "adaptive"], routing=self.relaxed())
        self.assertEqual(result["summary"]["t0"]["mean_recall"], 0)
        self.assertEqual(result["summary"]["t1"]["mean_recall"], 1)
        self.assertEqual(result["mean_recall_regret_to_evaluated_modes"], 0)
        self.assertFalse(result["public_benchmark_verified"])

    def test_file_metrics_do_not_count_duplicate_symbol_hits_twice(self):
        metrics = file_metrics([{"path": "storage.py"}, {"path": "storage.py"}, {"path": "ui.py"}],
                               ["storage.py", "service.py"], 3)
        self.assertEqual(metrics["recall"], 0.5)
        self.assertLess(metrics["ndcg"], 1)

    def test_jsonl_loader_rejects_duplicate_ids(self):
        path = self.root / "queries.jsonl"
        entry = {"id": "one", "query": "purchase", "relevant_files": ["storage.py"]}
        path.write_text(json.dumps(entry) + "\n" + json.dumps(entry), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "unique"):
            load_queries(path)


if __name__ == "__main__":
    unittest.main()
