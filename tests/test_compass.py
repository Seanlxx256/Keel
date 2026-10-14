import importlib.util
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import textwrap
import tempfile
import unittest
from unittest.mock import patch

from compass.graph import link_files
from compass.index import RepositoryIndex, build_index, git_ref
from compass.parsing import PythonParser
from compass.vectors import HashEmbedder, OllamaEmbedder, checked_vectors


class ParserTests(unittest.TestCase):
    def test_decorated_async_nested_and_unicode_ranges(self):
        raw = ('# 中文 header\n@decorate\nasync def outer(x: str):\n'
               '    """Handle Unicode identifiers."""\n    def inner():\n        return "你好"\n'
               '    return inner()\n\nclass Worker:\n    def run(self):\n        return outer("x")\n').encode()
        parsed = PythonParser("python-ast").parse("src/pkg/module.py", raw)
        symbols = {symbol.qualname: symbol for symbol in parsed.symbols}
        self.assertEqual(set(symbols), {"outer", "outer.inner", "Worker", "Worker.run"})
        self.assertEqual(symbols["outer"].module, "pkg.module")
        self.assertTrue(symbols["outer"].code.startswith("@decorate\nasync def"))
        self.assertEqual(symbols["outer"].start_line, 2)
        self.assertIn('return "你好"', symbols["outer.inner"].code)
        self.assertEqual(symbols["outer.inner"].parent_id, symbols["outer"].id)
        self.assertEqual(symbols["Worker.run"].kind, "method")
        self.assertEqual(symbols["outer"].docstring, "Handle Unicode identifiers.")
        self.assertNotIn('return inner()', symbols["outer"].embed_text)

    def test_static_alias_relative_and_receiver_edges(self):
        parser = PythonParser("python-ast")
        helper = parser.parse("pkg/helpers.py", b"def helper(value):\n    return value + 1\n")
        source = parser.parse("pkg/main.py", b"from .helpers import helper as h\nimport pkg.helpers as util\n"
                              b"def outer(value):\n    def inner():\n        return h(value)\n    return inner()\n"
                              b"class Worker:\n    def first(self):\n        return self.second()\n"
                              b"    def second(self):\n        return util.helper(1)\n"
                              b"def parameter(h):\n    return h(1)\n"
                              b"def dynamic(obj):\n    return obj.helper(1)\n")
        calls, imports = link_files([helper, source])
        target_by_id = {symbol.id: symbol.qualname for file in [helper, source] for symbol in file.symbols}
        resolved = [(call["target_text"], target_by_id.get(call["target_id"])) for call in calls]
        self.assertIn(("h", "helper"), resolved)
        self.assertIn(("inner", "outer.inner"), resolved)
        self.assertIn(("self.second", "Worker.second"), resolved)
        self.assertIn(("util.helper", "helper"), resolved)
        self.assertIn(("h", None), resolved)
        self.assertIn(("obj.helper", None), resolved)
        self.assertEqual(imports[0]["resolved_module"], "pkg.helpers")

    def test_rebound_import_is_not_linked(self):
        parser = PythonParser("python-ast")
        files = [parser.parse("helpers.py", b"def work(): pass\n"), parser.parse("main.py", b"from helpers import work\n"
                 b"def caller(work):\n    return work()\n")]
        calls, _ = link_files(files)
        self.assertIsNone(calls[0]["target_id"])

    @unittest.skipUnless(importlib.util.find_spec("tree_sitter") and importlib.util.find_spec("tree_sitter_python"),
                         "Optional tree-sitter packages are not installed")
    def test_real_tree_sitter_ranges_match_stdlib_backend(self):
        raw = b"@decorator\nasync def outer(x):\n    def inner():\n        return x\n    return inner()\n"
        expected = PythonParser("python-ast").parse("pkg/main.py", raw)
        actual = PythonParser("tree-sitter").parse("pkg/main.py", raw)
        self.assertEqual(actual, expected)
        # Native faults must fail an isolated child rather than terminate the test runner.
        # A large class exercises GC and offsets far beyond its declaration line.
        script = textwrap.dedent('''
            import gc
            from compass.parsing import PythonParser
            gc.set_threshold(25, 5, 5)
            source = '# Unicode: \\u4f60\\u597d\\nclass Large:\\n    """' + ('padding ' * 5000) + '"""\\n'
            for number in range(180):
                source += f'    @decorate\\n    def method_{number}(self, value):\\n        """Read a value."""\\n        return value + {number}\\n'
            raw = source.encode()
            expected = PythonParser('python-ast').parse('large.py', raw)
            parser = PythonParser('tree-sitter')
            for _ in range(5):
                actual = parser.parse('large.py', raw)
                assert actual == expected
                gc.collect()
            print('Large native-parser/GC regression passed')
        ''')
        completed = subprocess.run([sys.executable, "-X", "faulthandler", "-c", script],
                                   cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=60)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)


class IndexTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "helpers.py").write_bytes(b'def calculate_total(value):\n    """Calculate invoice totals."""\n    return value + 1\n')
        (self.root / "main.py").write_bytes(b"from helpers import calculate_total as total\n"
                                            b"def run():\n    return total(3)\n")

    def build(self, **kwargs):
        return build_index(self.root, parser="python-ast", **kwargs)

    def test_git_head_retries_exit_128_but_does_not_accept_persistent_failure(self):
        (self.root / ".git").mkdir()
        failed = subprocess.CompletedProcess([], 128, b"", b"not enough memory for initialization")
        valid = subprocess.CompletedProcess([], 0, b"a" * 40 + b"\n", b"")
        with patch("compass.index.subprocess.run", side_effect=[failed, valid]) as process:
            self.assertEqual(git_ref(self.root), "a" * 40)
            self.assertEqual(process.call_count, 2)
        with patch("compass.index.subprocess.run", return_value=failed):
            with self.assertRaisesRegex(ValueError, "not enough memory"):
                git_ref(self.root)

    def test_persistent_symbols_graph_and_readonly_database(self):
        stats = self.build()
        self.assertEqual(stats["symbols"], 2)
        self.assertEqual(stats["resolved_calls"], 1)
        with RepositoryIndex(self.root) as index:
            result = index.find_symbol("calculate_total")
            self.assertEqual(result["results"][0]["path"], "helpers.py")
            self.assertFalse(result["stale"])
            context = index.context("main.py", 3)
            self.assertEqual(context["neighbors"][0]["name"], "calculate_total")
            self.assertEqual(context["outgoing"][0]["resolution"], "import")
            reverse = index.context("helpers.py", 2)
            self.assertEqual(reverse["incoming"][0]["path"], "main.py")
            with self.assertRaises(sqlite3.OperationalError):
                index.db.execute("DELETE FROM symbols")

    def test_hash_vector_smoke_search_is_persistent(self):
        self.build(vector_store="sqlite", embedder=HashEmbedder())
        with RepositoryIndex(self.root) as index:
            result = index.search_vector("calculate invoice totals", limit=1)
            self.assertEqual(result["results"][0]["name"], "calculate_total")
            self.assertEqual(result["embedding"]["provider"], "hash")
            self.assertIsNone(result["confidence"])

    def test_add_edit_delete_each_marks_index_stale(self):
        self.build()
        for operation in ("edit", "add", "delete"):
            with self.subTest(operation=operation):
                if operation == "edit":
                    (self.root / "main.py").write_text("def changed(): pass\n")
                elif operation == "add":
                    (self.root / "new.py").write_text("pass\n")
                else:
                    (self.root / "new.py").unlink()
                with RepositoryIndex(self.root) as index:
                    self.assertTrue(index.stale)
                    with self.assertRaisesRegex(ValueError, "stale"):
                        index.find_symbol("run")
                self.build()

    def test_failed_generation_preserves_published_index(self):
        first = self.build()

        class Broken:
            spec = {"provider": "hash", "dimensions": 128}
            def embed(self, texts):
                raise ValueError("provider failed")
        with self.assertRaisesRegex(ValueError, "provider failed"):
            self.build(vector_store="sqlite", embedder=Broken())
        with RepositoryIndex(self.root) as index:
            self.assertEqual(index.metadata["generation"], first["generation"])

    def test_git_head_change_marks_index_stale_even_when_sources_match(self):
        with patch("compass.index.git_ref", return_value="a" * 40) as head:
            self.build()
            head.return_value = "b" * 40
            with RepositoryIndex(self.root) as index:
                self.assertTrue(index.stale)
                with self.assertRaisesRegex(ValueError, "stale"):
                    index.find_symbol("run")

    def test_source_change_during_build_is_not_published(self):
        self.build()
        original = (self.root / ".compass" / "current.json").read_bytes()
        root = self.root

        class Mutating(HashEmbedder):
            def embed(self, texts):
                (root / "main.py").write_text("def new_function(): pass\n")
                return super().embed(texts)
        with self.assertRaisesRegex(ValueError, "changed during indexing"):
            self.build(vector_store="sqlite", embedder=Mutating())
        self.assertEqual((self.root / ".compass" / "current.json").read_bytes(), original)

    def test_parse_error_is_reported_without_pretending_complete(self):
        (self.root / "broken.py").write_bytes(b"def broken(:\n")
        stats = self.build()
        self.assertFalse(stats["complete"])
        self.assertEqual(stats["diagnostics"][0]["path"], "broken.py")
        with RepositoryIndex(self.root) as index:
            self.assertFalse(index.find_symbol("run")["complete"])

    def test_ignored_directories_do_not_change_fingerprint(self):
        self.build()
        for name in (".keel", ".venv-deps", "node_modules"):
            directory = self.root / name
            directory.mkdir()
            (directory / "generated.py").write_text("def ignored(): pass\n")
        with RepositoryIndex(self.root) as index:
            self.assertFalse(index.stale)
            self.assertEqual(index.find_symbol("ignored")["results"], [])

    def test_duplicate_names_return_both_and_input_is_parameterized(self):
        (self.root / "other.py").write_bytes(b"def run(): pass\n")
        self.build()
        with RepositoryIndex(self.root) as index:
            self.assertEqual(len(index.find_symbol("run")["results"]), 2)
            self.assertEqual(index.find_symbol("' OR 1=1 --")["results"], [])

    def test_empty_repository_supports_empty_vector_search(self):
        (self.root / "main.py").unlink()
        (self.root / "helpers.py").unlink()
        self.build(vector_store="sqlite", embedder=HashEmbedder())
        with RepositoryIndex(self.root) as index:
            self.assertEqual(index.search_vector("anything")["results"], [])

    @unittest.skipUnless(importlib.util.find_spec("lancedb"), "Optional LanceDB package is not installed")
    def test_real_lancedb_roundtrip(self):
        self.build(vector_store="lancedb", embedder=HashEmbedder())
        with RepositoryIndex(self.root) as index:
            result = index.search_vector("calculate invoice totals", limit=1)
            self.assertEqual(result["results"][0]["name"], "calculate_total")


class EmbeddingTests(unittest.TestCase):
    def test_hash_vectors_are_stable_and_normalized(self):
        first = HashEmbedder().embed(["calculateTotal invoice"])[0]
        second = HashEmbedder().embed(["calculateTotal invoice"])[0]
        self.assertEqual(first, second)
        self.assertAlmostEqual(sum(value * value for value in first), 1)

    def test_invalid_dimensions_nan_and_empty_vectors_are_rejected(self):
        for vectors in ([[1, 2], [1]], [[float("nan")]], [[]], [[0, 0]]):
            with self.subTest(vectors=vectors), self.assertRaises(ValueError):
                checked_vectors(vectors, len(vectors))

    def test_ollama_batch_contract_without_network(self):
        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self, size): return b'{"embeddings": [[1, 0], [0, 1]]}'
        with patch("compass.vectors.urllib.request.urlopen", return_value=Response()) as request:
            embedder = OllamaEmbedder("embedding-model", num_batch=32)
            result = embedder.embed(["one", "two"])
        self.assertEqual(result, [[1, 0], [0, 1]])
        payload = json.loads(request.call_args.args[0].data)
        self.assertEqual(payload["input"], ["one", "two"])
        self.assertFalse(payload["truncate"])
        self.assertEqual(payload["options"], {"num_batch": 32})
        from compass.vectors import embedder_from_spec
        self.assertEqual(embedder_from_spec(embedder.spec).num_batch, 32)


if __name__ == "__main__":
    unittest.main()
