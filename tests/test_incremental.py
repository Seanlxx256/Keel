from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from compass.index import RepositoryIndex, build_index, update_index
from compass.parsing import PythonParser
from compass.service import CompassService
from compass.vectors import HashEmbedder
from keel.core import Budget, Ledger, Limits, Trace
from keel.workspace import Workspace


class CountingEmbedder(HashEmbedder):
    def __init__(self):
        super().__init__()
        self.inputs = []

    def embed(self, texts):
        self.inputs.extend(texts)
        return super().embed(texts)


class IncrementalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "api.py").write_bytes(b"def fetch(value):\n    return value\n")
        (self.root / "worker.py").write_bytes(b"from api import fetch\ndef run(value):\n    return fetch(value)\n")
        (self.root / "other.py").write_bytes(b"def noop():\n    return None\n")
        self.initial = build_index(self.root, parser="python-ast", vector_store="sqlite", embedder=HashEmbedder())

    def test_noop_retains_generation_without_parsing_or_embedding(self):
        model = CountingEmbedder()
        with patch.object(PythonParser, "parse", side_effect=AssertionError("No parse expected")):
            result = update_index(self.root, embedder=model)
        self.assertEqual(result["generation"], self.initial["generation"])
        self.assertEqual(result["update"]["mode"], "noop")
        self.assertEqual(model.inputs, [])

    def test_body_only_change_parses_one_file_and_reuses_all_vectors(self):
        (self.root / "api.py").write_bytes(b"def fetch(value):\n    return value + 1\n")
        model = CountingEmbedder()
        original = PythonParser.parse
        parsed = []
        def tracked(parser, name, raw):
            parsed.append(name)
            return original(parser, name, raw)
        with patch.object(PythonParser, "parse", tracked):
            result = update_index(self.root, embedder=model)
        self.assertEqual(parsed, ["api.py"])
        self.assertEqual(result["update"]["reused_files"], 2)
        self.assertEqual(result["update"]["reused_vectors"], 3)
        self.assertEqual(model.inputs, [])
        with RepositoryIndex(self.root) as index:
            self.assertIn("value + 1", index.find_symbol("fetch")["results"][0]["code"])

    def test_signature_change_invalidates_caller_embedding_in_unchanged_file(self):
        (self.root / "api.py").write_bytes(b"def fetch(value, retries=1):\n    return value\n")
        model = CountingEmbedder()
        result = update_index(self.root, embedder=model)
        self.assertEqual(result["update"]["parsed_files"], 1)
        self.assertEqual(result["update"]["embedded_symbols"], 2)
        self.assertEqual(result["update"]["reused_vectors"], 1)
        self.assertEqual(set(result["update"]["invalidated_symbols"]), {"api.fetch", "worker.run"})
        self.assertTrue(any("worker.run" in text and "retries=1" in text for text in model.inputs))

    def test_deletion_removes_symbols_vectors_and_relinks_old_callers(self):
        (self.root / "api.py").unlink()
        result = update_index(self.root)
        self.assertEqual(result["update"]["deleted_files"], ["api.py"])
        with RepositoryIndex(self.root) as index:
            self.assertEqual(index.find_symbol("fetch")["results"], [])
            edge = index.context("worker.py", 3)["outgoing"][0]
            self.assertIsNone(edge["target_id"])
            self.assertEqual(index.db.execute("SELECT count(*) FROM vectors").fetchone()[0], 2)

    def test_new_symbol_resolves_previously_unresolved_call_without_reparsing_caller(self):
        (self.root / "api.py").unlink()
        update_index(self.root)
        (self.root / "api.py").write_bytes(b"def fetch(value):\n    return value\n")
        result = update_index(self.root)
        self.assertEqual(result["update"]["parsed_files"], 1)
        with RepositoryIndex(self.root) as index:
            self.assertIsNotNone(index.context("worker.py", 3)["outgoing"][0]["target_id"])

    def test_embedding_failure_preserves_previous_manifest(self):
        (self.root / "api.py").write_bytes(b"def fetch(value, retries=1):\n    return value\n")
        class Broken(HashEmbedder):
            def embed(self, texts):
                raise ValueError("embedding failed")
        with self.assertRaisesRegex(ValueError, "embedding failed"):
            update_index(self.root, embedder=Broken())
        with RepositoryIndex(self.root) as index:
            self.assertEqual(index.metadata["generation"], self.initial["generation"])
            self.assertTrue(index.stale)

    def test_incremental_matches_clean_full_build(self):
        (self.root / "api.py").write_bytes(b"def fetch(value, retries=1):\n    return value\n")
        update_index(self.root)
        with RepositoryIndex(self.root) as index:
            incremental_symbols = [dict(row) for row in index.db.execute("SELECT * FROM symbols ORDER BY id")]
            incremental_edges = [dict(row) for row in index.db.execute("SELECT * FROM calls ORDER BY id")]
            incremental_vectors = [dict(row) for row in index.db.execute("SELECT * FROM vectors ORDER BY id")]
        build_index(self.root, parser="python-ast", vector_store="sqlite", embedder=HashEmbedder())
        with RepositoryIndex(self.root) as index:
            self.assertEqual(incremental_symbols, [dict(row) for row in index.db.execute("SELECT * FROM symbols ORDER BY id")])
            self.assertEqual(incremental_edges, [dict(row) for row in index.db.execute("SELECT * FROM calls ORDER BY id")])
            self.assertEqual(incremental_vectors, [dict(row) for row in index.db.execute("SELECT * FROM vectors ORDER BY id")])

    def test_cache_keeps_raw_dependency_text_without_accumulating_suffixes(self):
        for version in (1, 2):
            (self.root / "api.py").write_bytes(f"def fetch(value, retries={version}):\n    return value\n".encode())
            update_index(self.root)
        with RepositoryIndex(self.root) as index:
            text = index.find_symbol("run")["results"][0]["embed_text"]
            self.assertEqual(text.count("Calls:"), 1)
            self.assertIn("retries=2", text)
            self.assertNotIn("retries=1", text)

    def test_service_auto_update_and_default_fail_closed(self):
        (self.root / "api.py").write_bytes(b"def fetch(value):\n    return value + 1\n")
        with self.assertRaisesRegex(ValueError, "stale"):
            CompassService(self.root).call("find_symbol", {"name": "fetch"})
        result = CompassService(self.root, auto_update=True).call("find_symbol", {"name": "fetch"})
        self.assertIn("value + 1", result["results"][0]["code"])
        self.assertEqual(result["index_updates"][0]["update"]["mode"], "incremental")

    def test_keel_auto_update_after_edit_records_index_generation(self):
        output = self.root / ".keel" / "test"
        output.mkdir(parents=True)
        ledger = Ledger(output / "ledger.sqlite")
        self.addCleanup(ledger.close)
        workspace = Workspace(self.root, Budget(Limits()), ledger, Trace(output / "trace.jsonl"),
                              retrieval={"provider": "compass", "auto_update": True})
        workspace.replace("api.py", "return value", "return value + 1")
        result = workspace.find_symbol("fetch")
        self.assertIn("value + 1", result["results"][0]["code"])
        self.assertTrue(any(fact["summary"] == "index_updated" for fact in ledger.summaries()))


if __name__ == "__main__":
    unittest.main()
