import unittest
from keel.repair_reporting import summarize


class RepairReportingTests(unittest.TestCase):
    def row(self, task, arm, passed=False, **kwargs):
        return dict(task_id=task, repair_attempts=arm, passed=passed, status='completed', executed=True, **kwargs)

    def test_pre_verification_failure_stays_in_denominator(self):
        records = [self.row('a', 0, True), self.row('a', 2, verification_rounds=0),
                   self.row('b', 0), self.row('b', 2)]
        result = summarize({'records': records})
        self.assertEqual(result['paired_completed_tasks'], 2)
        self.assertEqual(result['paired_success_rate'], {'0': .5, '2': 0})
        self.assertEqual(result['outcome_counts']['disabled_only'], 1)

    def test_unpaired_environment_errors_are_explicitly_excluded(self):
        bad = self.row('a', 2)
        bad.update(status='environment_error', executed=False)
        result = summarize({'records': [self.row('a', 0, True), bad, self.row('b', 0)]})
        self.assertEqual(result['paired_completed_tasks'], 0)
        self.assertIsNone(result['enabled_minus_disabled_rate'])
        self.assertEqual(len(result['excluded_tasks']), 2)

    def test_export_preserves_source_and_refuses_overwrite(self):
        import tempfile
        import json
        from pathlib import Path
        from examples.summarize_repair_comparison import export
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root/'results.json'
            source.write_text(json.dumps({'records': [self.row('a', 0), self.row('a', 2)]}))
            before = source.read_bytes()
            result = export(source, root/'summary')
            self.assertEqual(source.read_bytes(), before)
            self.assertTrue(result['source_sha256'])
            self.assertTrue((root/'summary/summary.md').exists())
            with self.assertRaises(FileExistsError):
                export(source, root/'summary')

    def test_repetitions_and_fake_success_are_rejected(self):
        with self.assertRaises(ValueError):
            summarize({'records': [self.row('a', 0), self.row('a', 0)]})
        bad = self.row('a', 0, True)
        bad['executed'] = False
        with self.assertRaises(ValueError):
            summarize({'records': [bad]})
