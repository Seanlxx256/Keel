import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from examples.package_httpx_transition import export
from tests.test_httpx_1588 import matrix
from examples import reproduce_httpx_1588 as reproduction
from keel.evaluation_protocol import file_hash
import hashlib


class PackageTests(unittest.TestCase):
    def test_export_excludes_curator_answers_and_binds_acceptance(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)/'source'
            source.mkdir()
            report = {'candidate': 'encode__httpx-1588', 'probe_passed': True,
                'executions': matrix(), 'probe_sha256': hashlib.sha256(reproduction.PROBE.encode()).hexdigest(),
                'runner_sha256': file_hash(Path(reproduction.__file__)),
                'selected_metadata': {'repository': 'encode/httpx', 'number': 1588,
                    'base_commit': '2d571046e15d3f4c4cbe5a68173cdf12e99cb3ca',
                    'gold_commit': 'd98e9e7ae7963a60ce8dc6a25cbe5f04c6438f4c',
                    'source_files_curator_only': ['SECRET_ANSWER'], 'body': 'SECRET_ANSWER'},
                'images': {'old': 'sha256:'+'a'*64, 'new': 'sha256:'+'b'*64},
                'collection_shortlist_sha256': 'c'*64, 'verified_range': {'base_inventory': {'httpx/a.py': 'd'*64}}}
            summary = source/'summary.json'
            summary.write_text(json.dumps(report))
            output = Path(directory)/'package'
            self.assertFalse(export(source, output)['executed'])
            task = (output/'task.json').read_text()
            self.assertNotIn('SECRET_ANSWER', task)
            self.assertNotIn(report['selected_metadata']['gold_commit'], task)
            manifest = json.loads((output/'manifest.json').read_text())
            self.assertEqual(manifest['files']['acceptance.py'], file_hash(output/'acceptance.py'))
            with self.assertRaises(FileExistsError):
                export(source, output)
            report['executions'].pop('base_old')
            summary.write_text(json.dumps(report))
            with self.assertRaises(ValueError):
                export(source, Path(directory)/'invalid')


if __name__ == '__main__':
    unittest.main()
