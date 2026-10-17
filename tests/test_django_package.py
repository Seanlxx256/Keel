import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from examples.package_django_transition import export
from examples import reproduce_django_13586 as reproduction
from examples.run_transition_task import load_package, baseline_matches
from keel.evaluation_protocol import file_hash
from tests import test_django_transition as fixtures


class DjangoPackageTests(unittest.TestCase):
    def test_model_task_excludes_gold_and_curator_hints(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root/'source'
            source.mkdir()
            report = {'candidate': 'django__django-13586', 'probe_passed': True,
                'executions': fixtures.DjangoTransitionTests().executions(),
                'probe_sha256': hashlib.sha256(reproduction.PROBE.encode()).hexdigest(),
                'runner_sha256': file_hash(Path(reproduction.__file__)),
                'selected_metadata': {'repository': 'django/django', 'number': 13586,
                    'base_commit': '0b4fe82c7405ba96f2eb25b954a8f498cc8364b3',
                    'gold_commit': 'e17ee4468875077b90b70bb6a589ebad7493f757', 'body': 'SECRET_GOLD_HINT'},
                'images': {'old': 'sha256:'+'a'*64, 'new': 'sha256:'+'b'*64},
                'collection_shortlist_sha256': 'c'*64, 'verified_range': {'base_inventory': {}}}
            (source/'summary.json').write_text(json.dumps(report), encoding='utf-8')
            export(source, root/'package')
            manifest, task = load_package(root/'package')
            self.assertEqual(task['id'], 'django-13586')
            self.assertNotIn('SECRET_GOLD_HINT', json.dumps(task))
            self.assertNotIn(report['selected_metadata']['gold_commit'], json.dumps(task))
            self.assertTrue(baseline_matches(report['executions']['base_new'], manifest['acceptance']))
            bad = dict(report['executions']['base_new'])
            payload = json.loads(bad['stdout'])
            payload['records'][0]['type'] = 'ImportError'
            bad['stdout'] = json.dumps(payload)
            self.assertFalse(baseline_matches(bad, manifest['acceptance']))
            with self.assertRaises(FileExistsError):
                export(source, root/'package')
