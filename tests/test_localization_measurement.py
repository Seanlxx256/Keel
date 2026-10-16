from pathlib import Path
import tempfile
import unittest
from examples.measure_localization import measure


class MeasurementTests(unittest.TestCase):
    def test_preflight_fits_and_blocks_without_network_or_source_mutation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root/'repo'
            repo.mkdir()
            (repo/'a.py').write_bytes(b'def value():\n    return 1\n')
            fitting = measure(repo, root/'fit')
            self.assertEqual(fitting['status'], 'request_fits')
            self.assertEqual(fitting['new_model_calls'], 0)
            self.assertEqual(fitting['last_structure_files'], 0)
            self.assertTrue(fitting['source_unchanged'])
            blocked = measure(repo, root/'blocked', cap=20)
            self.assertEqual(blocked['status'], 'budget_blocked')
            self.assertTrue(blocked['source_unchanged'])
            tool_blocked = measure(repo, root/'tool-blocked', tools=1)
            self.assertEqual(tool_blocked['status'], 'request_fits')
            self.assertEqual(tool_blocked['new_model_calls'], 0)
