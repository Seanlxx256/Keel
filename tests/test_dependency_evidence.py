import json
from contextlib import ExitStack
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest

from keel.core import Budget, Ledger, Limits, PolicyDenied, Trace
from keel.dependency_evidence import SCAN, collect, validate_requests, referenced_calls, compact_contracts


class DependencyEvidenceTests(unittest.TestCase):
    def test_projection_preserves_public_contracts_and_declares_private_omissions(self):
        records = [{'symbol': symbol, 'signature': signature, 'signature_truncated': False}
            for symbol, signature in [('Pool.send', 'def Pool.send(self, *, extensions)'),
                ('Pool.__init__', 'def Pool.__init__(self)'), ('Pool._internal', 'def Pool._internal(self)')]]
        payload = {'distribution': 'fixture', 'version': '1', 'records': records,
            'inventory_sha256': 'a'*64, 'scope': 'Static only'}
        projected = compact_contracts([payload])[0]
        self.assertEqual(projected['signatures'], [r['signature'] for r in records[:2]])
        self.assertEqual(projected['private_records_omitted'], 1)
        records[0]['signature_truncated'] = True
        with self.assertRaises(ValueError):
            compact_contracts([payload])
    def test_api_requests_come_from_observed_import_calls_not_repair_hints(self):
        text = 'import fixture_api as api\nfrom fixture_api import Pool as P\nfrom other import NotOurs\nx=api.Pool()\ny=P()\nz=api.Stream()\nNotOurs()\nx.send()\n'
        self.assertEqual(referenced_calls(text, 'fixture_api'), ['Pool', 'Stream'])
        self.assertNotIn('send', referenced_calls(text, 'fixture_api'))
        with self.assertRaises(ValueError):
            referenced_calls(text, '../escape')

    def test_direct_methods_include_real_signatures_without_importing_package(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.fixture(root)
            (root/'fixture_api/thread.py').write_text(
                'class Pool:\n'
                '    def send(self, url, *, extensions=None):\n        raise RuntimeError("not executed")\n'
                '    async def receive(self, *, timeout=1):\n        raise RuntimeError("not executed")\n')
            request = {**self.request(), 'symbols': ['Pool'], 'include_methods': True}
            result = self.scan(root, request)
            self.assertEqual(result.returncode, 0, result.stderr)
            records = json.loads(result.stdout)['records']
            self.assertEqual([r['symbol'] for r in records], ['Pool', 'Pool.send', 'Pool.receive'])
            self.assertIn('extensions=None', records[1]['signature'])
            self.assertTrue(records[2]['signature'].startswith('async def'))
            self.assertTrue(all(len(r['source_sha256']) == 64 for r in records))
            result = self.scan(root, {**request, 'include_methods': False})
            self.assertEqual([r['symbol'] for r in json.loads(result.stdout)['records']], ['Pool'])
        with self.assertRaises(ValueError):
            validate_requests([{**self.request(), 'include_methods': 1}])

    def test_collector_charges_budget_archives_execution_and_checks_identity(self):
        with tempfile.TemporaryDirectory() as directory, ExitStack() as resources:
            root = Path(directory)
            ledger = Ledger(root/'ledger.sqlite')
            resources.callback(ledger.close)
            payload = {'distribution': 'evidence-fixture', 'version': '1.0', 'complete': True, 'records': []}
            def execute(command, path, timeout):
                self.assertEqual(command[:3], ['python', '-I', '-c'])
                self.assertLessEqual(timeout, 30)
                self.assertEqual(json.loads(command[-1]), self.request())
                return {'returncode': 0, 'timeout': False, 'stdout': json.dumps(payload), 'stderr': '', 'backend': 'docker'}
            workspace = SimpleNamespace(root=root, runner=SimpleNamespace(backend='docker', run=execute),
                budget=Budget(Limits()), ledger=ledger, trace=Trace(root/'trace.jsonl'))
            self.assertEqual(collect(workspace, [self.request()]), [payload])
            self.assertEqual(workspace.budget.tool_calls, 1)
            self.assertTrue((root/'dependency-evidence/0.json').is_file())
            payload['version'] = '2.0'
            with self.assertRaisesRegex(ValueError, 'identity'):
                collect(workspace, [self.request()])

    def request(self):
        return {'distribution': 'evidence-fixture', 'version': '1.0', 'symbols': ['portal']}

    def scan(self, root, request):
        program = 'import sys; sys.path.insert(0, sys.argv.pop(1));\n' + SCAN
        return subprocess.run([sys.executable, '-I', '-c', program, str(root), json.dumps(request)],
                              capture_output=True, text=True, timeout=10)

    def fixture(self, root):
        package = root/'fixture_api'
        package.mkdir()
        (package/'__init__.py').write_text('raise RuntimeError("Package must never be imported")\n')
        (package/'thread.py').write_text('def portal(backend="asyncio"):\n    """Start a portal."""\n    raise RuntimeError("Must not execute")\n')
        metadata = root/'evidence_fixture-1.0.dist-info'
        metadata.mkdir()
        (metadata/'METADATA').write_text('Metadata-Version: 2.1\nName: evidence-fixture\nVersion: 1.0\n')
        (metadata/'RECORD').write_text('fixture_api/__init__.py,,\nfixture_api/thread.py,,\n')

    def test_static_definition_lookup_does_not_import_or_execute_dependency(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.fixture(root)
            result = self.scan(root, self.request())
            self.assertEqual(result.returncode, 0, result.stderr)
            evidence = json.loads(result.stdout)
            self.assertTrue(evidence['complete'])
            self.assertEqual(evidence['version'], '1.0')
            self.assertEqual(evidence['files_scanned'], 2)
            self.assertEqual(evidence['records'][0]['module'], 'fixture_api.thread')
            self.assertEqual(evidence['records'][0]['doc_summary'], 'Start a portal.')
            self.assertIn('backend=', evidence['records'][0]['signature'])

    def test_wrong_version_missing_symbol_and_scan_cap_are_visible(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.fixture(root)
            result = self.scan(root, {**self.request(), 'version': '2.0'})
            self.assertNotEqual(result.returncode, 0)
            result = self.scan(root, {**self.request(), 'symbols': ['missing']})
            self.assertEqual(json.loads(result.stdout)['records'], [])
            (root/'fixture_api/thread.py').write_bytes(b'#' * 2_000_001)
            self.assertNotEqual(self.scan(root, self.request()).returncode, 0)

    def test_invalid_requests_and_host_fallback_are_rejected(self):
        for change in [{'distribution': '../escape'}, {'symbols': ['a.b']}, {'version': ''}]:
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_requests([{**self.request(), **change}])
        with self.assertRaises(PolicyDenied):
            collect(SimpleNamespace(runner=SimpleNamespace(backend='local')), [self.request()])
