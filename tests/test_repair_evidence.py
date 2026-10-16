import json
from types import SimpleNamespace
import unittest

from keel.repair import repair_evidence


class RepairEvidenceTests(unittest.TestCase):
    def test_traceback_focus_excludes_large_outer_callers_and_stale_locations(self):
        source = 'def caller():\n' + '    x = 1\n'*3000 + '    return helper()\n\ndef helper():\n    return 2\n'
        files = {'outer.py': source, 'inner.py': 'def send():\n    return helper()\ndef helper():\n    raise ValueError("bad")\n'}
        reads = []
        def read(name, **kwargs):
            reads.append(name)
            return {'value': files[name]}
        workspace = SimpleNamespace(read=read, ledger=SimpleNamespace(add=lambda *a: None))
        trace = 'File "/workspace/outer.py", line 2\nFile "/workspace/inner.py", line 2\nFile "/workspace/inner.py", line 4\n'
        verification = [{'stdout': json.dumps({'records': [{'passed': False, 'message': 'bad', 'traceback': trace}]} )}]
        scope = {'files': list(files), 'locations': {'outer.py': [1], 'inner.py': [1]}}
        evidence, feedback = repair_evidence(workspace, scope, verification)
        self.assertEqual(reads, ['inner.py'])
        self.assertEqual(evidence[0]['omitted_declared_files'], ['outer.py'])
        self.assertIn('raise ValueError', evidence[0]['windows'][0]['text'])
        self.assertLess(len(json.dumps(evidence)), 1500)
        self.assertEqual(feedback[0]['message'], 'bad')

    def test_external_frames_never_expand_declared_scope(self):
        workspace = SimpleNamespace(read=lambda name, **kw: {'value': 'def f():\n    return 1\n'},
                                    ledger=SimpleNamespace(add=lambda *a: None))
        evidence, _ = repair_evidence(workspace, {'files': ['allowed.py'], 'locations': {'allowed.py': [1]}},
            [{'stdout': json.dumps({'records': [{'traceback': 'File "/workspace/secret.py", line 1'}]})}])
        self.assertEqual([e['path'] for e in evidence], ['allowed.py'])
