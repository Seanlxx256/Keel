from pathlib import Path
import tempfile
import unittest
from examples.measure_localized_contexts import inspect


class ContextMeasurementTests(unittest.TestCase):
    def test_large_function_is_reported_not_hidden_and_tests_are_excluded(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            text = 'def small():\n    return 1\n\ndef large():\n'+'    # padding\n'*2000+'    return 2\n'
            (root/'a.py').write_bytes(text.encode())
            (root/'test_secret.py').write_bytes(b'def hidden(): pass\n')
            report = inspect(root)
            self.assertTrue(report['source_unchanged'])
            self.assertEqual([r['path'] for r in report['files']], ['a.py'])
            anchors = {a['query']: a for a in report['files'][0]['anchors']}
            self.assertTrue(anchors['small']['fits'])
            self.assertFalse(anchors['large']['fits'])
            self.assertEqual(report['new_model_calls'], 0)
