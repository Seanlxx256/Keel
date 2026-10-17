import json
import unittest

from keel.recovery import bounded_verification
from keel.verification_feedback import failure_feedback


class VerificationFeedbackTests(unittest.TestCase):
    def test_failure_survives_many_passing_tests_and_recovery_boundary(self):
        log = ('___ test_first ___\nassert actual == expected\nE   AssertionError: first detail\n'
               '___ test_second ___\ncall()\nE   ValueError: second detail\n'
               '=== short test summary info ===\n' + 'test_other PASSED\n'*2000)
        status = {'FAIL_TO_PASS': {'success': ['ok']*2000, 'failure': ['first']},
                  'PASS_TO_PASS': {'success': ['other']*2000, 'failure': ['second']}}
        # Official pytest logs may color both section delimiters and error prefixes.
        log = '\n'.join('\x1b[31m'+line+'\x1b[0m' for line in log.splitlines())
        feedback = failure_feedback(status, log)
        feedback.update(failure_kind='test_failure', official_resolved=False)
        result = bounded_verification([{'stdout': json.dumps(feedback), 'metadata': None}])[0]
        text = json.dumps(result)
        self.assertIn('first detail', text)
        self.assertIn('second detail', text)
        self.assertEqual(result['feedback']['test_counts']['FAIL_TO_PASS']['success'], 2000)
        self.assertNotIn('stdout_tail', result)
        self.assertLess(len(text), 6000)

    def test_limits_are_explicit_and_plain_logs_still_work(self):
        feedback = failure_feedback({'FAIL_TO_PASS': {'failure': [str(i) for i in range(20)]}}, '')
        self.assertEqual(len(feedback['failed_tests']), 10)
        self.assertEqual(feedback['omitted_failed_tests'], 10)
        result = bounded_verification([{'stdout': 'plain error', 'metadata': None}])[0]
        self.assertEqual(result['stdout_tail'], 'plain error')

    def test_grading_timeout_remains_distinct_from_test_failure(self):
        result = bounded_verification([{'stdout': json.dumps({'failure_kind': 'grading_timeout',
            'official_resolved': None, 'error': 'TimeoutExpired'}), 'returncode': 2}])[0]
        self.assertEqual(result['feedback']['failure_kind'], 'grading_timeout')
        self.assertIsNone(result['feedback']['official_resolved'])
