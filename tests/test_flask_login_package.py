import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from examples.package_flask_login_issue import export
from examples import reproduce_flask_login_issue5279 as reproduction
from examples.run_transition_task import load_package, baseline_matches
from keel.evaluation_protocol import file_hash
from tests import test_flask_login_transition as fixtures


class FlaskLoginPackageTests(unittest.TestCase):
    def test_package_isolates_model_task_and_checks_exact_baseline(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root/'source'
            source.mkdir()
            report = {'candidate': 'maxcountryman__flask-login-issue5279-range', 'probe_passed': True,
                'executions': fixtures.FlaskLoginTransitionTests().matrix(),
                'probe_sha256': hashlib.sha256(reproduction.PROBE.encode()).hexdigest(),
                'runner_sha256': file_hash(Path(reproduction.__file__)),
                'selected_metadata': {'repository': 'maxcountryman/flask-login',
                    'base_commit': reproduction.BASE, 'gold_commit': reproduction.GOLD, 'reason': 'SECRET_GOLD_HINT'},
                'images': {'old': 'sha256:'+'a'*64, 'new': 'sha256:'+'b'*64},
                'history_sha256': 'c'*64, 'comparison_receipts_sha256': 'd'*64,
                'verified_range': {'base_inventory': {'src/flask_login/utils.py': 'e'*64}}}
            (source/'summary.json').write_text(json.dumps(report), encoding='utf-8')
            export(source, root/'package')
            manifest, task = load_package(root/'package')
            self.assertEqual(task['source_scope'], 'src/flask_login/**/*.py')
            self.assertNotIn('SECRET_GOLD_HINT', json.dumps(task))
            self.assertNotIn(reproduction.GOLD, json.dumps(task))
            self.assertEqual(manifest['acceptance']['cases'], reproduction.CASES)
            self.assertTrue(baseline_matches(report['executions']['base_new'], manifest['acceptance']))
            bad = dict(report['executions']['base_new'])
            payload = json.loads(bad['stdout'])
            payload['records'][0]['message'] = 'unrelated ImportError'
            bad['stdout'] = json.dumps(payload)
            self.assertFalse(baseline_matches(bad, manifest['acceptance']))
            with self.assertRaises(FileExistsError):
                export(source, root/'package')
