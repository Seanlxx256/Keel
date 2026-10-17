import json
from pathlib import Path
import unittest
from examples.mine_upgradebench import unique_file_paths


class FileOperationTests(unittest.TestCase):
    def test_added_removed_pair_is_one_path_with_provenance(self):
        rows = [{'filename': 'a.py', 'status': 'removed', 'sha': 'old'},
                {'filename': 'a.py', 'status': 'added', 'sha': 'new'}, {'filename': 'b.py'}]
        paths, operations = unique_file_paths(rows, 2)
        self.assertEqual(paths, ['a.py', 'b.py'])
        self.assertEqual(operations, [{'path': 'a.py', 'statuses': ['added', 'removed']}])
        self.assertEqual(len(rows), 3)

    def test_other_duplicates_and_missing_files_still_fail(self):
        for rows, count in [([{'filename': 'a', 'status': 'modified'}]*2, 1),
                            ([{'filename': 'a', 'status': 'added'}]*2, 1),
                            ([{'filename': 'a'}], 2), ([{'filename': ''}], 1)]:
            with self.assertRaises(ValueError):
                unique_file_paths(rows, count)
