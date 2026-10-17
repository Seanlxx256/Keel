from pathlib import Path
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from examples.reproduce_flask_login_813 import verify_sources


class FlaskLoginRangeTests(unittest.TestCase):
    def verify(self, left, right, advertised):
        row = {'base_commit': 'a'*40, 'gold_commit': 'b'*40, 'curator_files': advertised}
        raw = SimpleNamespace(stdout='parent '+'a'*40+'\nparent '+'c'*40+'\n\nmessage')
        with patch('examples.reproduce_flask_login_813.check_snapshot'), \
             patch('examples.reproduce_flask_login_813.subprocess.run', return_value=raw), \
             patch('examples.reproduce_flask_login_813.inventory', side_effect=[left, right]):
            return verify_sources(row, Path('/base'), Path('/gold'))

    def test_verified_unchanged_advertised_path_is_recorded(self):
        result = self.verify({'src/flask_login/utils.py': 'old', 'release.txt': 'same'},
                             {'src/flask_login/utils.py': 'new', 'release.txt': 'same'},
                             ['src/flask_login/utils.py', 'release.txt'])
        self.assertEqual(result['pr_paths_unchanged_between_pins'], ['release.txt'])
        self.assertEqual(result['changed_files_curator_only'], ['src/flask_login/utils.py'])

    def test_unadvertised_change_or_missing_claimed_path_is_rejected(self):
        for left, right, advertised in [
            ({'x.py': 'old'}, {'x.py': 'new'}, ['other.py']),
            ({'src/flask_login/utils.py': 'old'}, {'src/flask_login/utils.py': 'new'},
             ['src/flask_login/utils.py', 'missing.txt'])]:
            with self.assertRaises(ValueError):
                self.verify(left, right, advertised)

    def test_metadata_only_delta_is_not_a_source_repair(self):
        with self.assertRaises(ValueError):
            self.verify({'release.txt': 'old'}, {'release.txt': 'new'}, ['release.txt'])
