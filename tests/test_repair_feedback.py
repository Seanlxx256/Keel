import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from examples.repair_feedback import with_feedback


class RepairFeedbackTests(unittest.TestCase):
    def fixture(self, root):
        source = b'VERSION = 1\n'
        model = {'provider': 'openai-compatible', 'name': 'model'}
        gold = {'records': [{'case': 'import', 'passed': True}], 'versions': {'fixture': '1'}}
        spec = {'id': 'task', 'goal': 'Upgrade fixture', 'targets': ['app.py'],
            'files': {'app.py': source}, 'acceptance': 'fixed acceptance',
            'reference_execution': {'stdout': json.dumps(gold)}}
        config = {'goal': spec['goal'], 'model': model, 'execution': {'backend': 'docker', 'image': 'image'},
            'acceptance': [['python', '-c', spec['acceptance']]], 'proposal': {'files': ['app.py']}}
        manifest = {'strategy': 'proposal', 'tasks': [{'id': 'task', 'config': config,
            'source_sha256': {'app.py': hashlib.sha256(source).hexdigest()}}]}
        failure = {'category': 'verification_failed'}
        report = {'strategy': 'proposal', 'prepared_only': False, 'records': [{'id': 'task',
            'status': 'completed', 'executed': True, 'passed': False, 'failure': failure,
            'changed_files': ['app.py'], 'budget': {'model_calls': 1, 'tokens': 100}}]}
        execution = {'backend': 'docker', 'timeout': False, 'returncode': 1,
            'stdout': json.dumps({'records': [{'case': 'import', 'passed': False,
                'type': 'ImportError', 'message': 'missing old API'}], 'versions': {'fixture': '1'}})}
        runtime = {'status': 'failed', 'failure': failure, 'verification': [execution]}
        run = root/'runs/task/run'
        run.mkdir(parents=True)
        (root/'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
        (root/'results.json').write_text(json.dumps(report), encoding='utf-8')
        (run/'result.json').write_text(json.dumps(runtime), encoding='utf-8')
        (run/'changes.patch').write_text('--- a/app.py\n+++ b/app.py\n', encoding='utf-8')
        return spec, model

    def test_followup_preserves_original_source_and_links_previous_cost(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            spec, model = self.fixture(root)
            augmented, provenance = with_feedback(spec, 'image', root, model)
            self.assertEqual(augmented['files'], spec['files'])
            self.assertEqual(spec['goal'], 'Upgrade fixture')
            self.assertIn('missing old API', augmented['goal'])
            self.assertIn('ORIGINAL base', augmented['goal'])
            self.assertEqual(provenance['attempt'], 2)
            self.assertEqual(provenance['previous_budget']['tokens'], 100)

    def test_recursive_feedback_changed_model_and_source_are_rejected(self):
        for mutation in ('recursive', 'model', 'source'):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                spec, model = self.fixture(root)
                if mutation == 'recursive':
                    path = root/'manifest.json'
                    manifest = json.loads(path.read_text())
                    manifest['feedback_from'] = {'attempt': 2}
                    path.write_text(json.dumps(manifest))
                elif mutation == 'model':
                    model = {**model, 'name': 'changed'}
                else:
                    spec['files']['app.py'] = b'changed source'
                with self.assertRaises(ValueError):
                    with_feedback(spec, 'image', root, model)

    def test_timeout_and_changed_case_identity_are_not_repair_evidence(self):
        for mutation in ('timeout', 'cases', 'versions', 'oversized'):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                spec, model = self.fixture(root)
                path = root/'runs/task/run/result.json'
                runtime = json.loads(path.read_text())
                if mutation == 'timeout':
                    runtime['verification'][0]['timeout'] = True
                elif mutation == 'oversized':
                    (path.parent/'changes.patch').write_text('x'*4001)
                else:
                    data = json.loads(runtime['verification'][0]['stdout'])
                    if mutation == 'cases':
                        data['records'][0]['case'] = 'another test'
                    else:
                        data['versions']['fixture'] = '2'
                    runtime['verification'][0]['stdout'] = json.dumps(data)
                path.write_text(json.dumps(runtime))
                with self.assertRaises(ValueError):
                    with_feedback(spec, 'image', root, model)
