import json
import unittest

from keel.recovery import bounded_verification
from keel.verification_feedback import failure_feedback


class VerificationFeedbackTests(unittest.TestCase):
    def test_outer_call_frame_survives_internal_exception_tail_and_passing_noise(self):
        log = ('___ TestConversion.test_roundtrip ___\n'
               '    def test_roundtrip(self):\n'
               '        item = make_item()\n'
               '>       item.save("initial.bin")\n'
               '\nchecks/test_conversion.py:42:\n'
               '_ _ _ _ _ _ _ _\n'
               'library/store.py:15: in save\n    validate(value)\n'
               '>       raise ValueError("bad token")\n'
               'E       ValueError: bad token\nlibrary/validate.py:90: ValueError\n'
               '=== short test summary info ===\n'+'PASSED unrelated\n'*1000)
        feedback = failure_feedback({'PASS_TO_PASS': {'failure': ['checks/test_conversion.py::TestConversion::test_roundtrip']}}, log)
        origin = feedback['failure_locations'][0]
        self.assertEqual(origin['source_path'], 'checks/test_conversion.py')
        self.assertEqual(origin['line'], 42)
        self.assertEqual(origin['statement'], 'item.save("initial.bin")')
        self.assertEqual(origin['status'], 'observed')
        self.assertIn('bad token', feedback['failure_excerpts'][0])
        feedback['failure_kind'] = 'test_failure'
        bounded = bounded_verification([{'stdout': json.dumps(feedback)}])[0]['feedback']
        self.assertEqual(bounded['failure_locations'][0], origin)

    def test_two_failure_blocks_keep_separate_call_sites_and_missing_frames_are_unknown(self):
        log = ('___ test_initial ___\n>       initial_write()\nchecks/test_initial.py:7:\n'
               'E   ValueError: initial\n'
               '___ test_rewrite ___\n>       rewrite(warn=True)\nchecks/test_rewrite.py:91:\n'
               'E   ValueError: later\n')
        feedback = failure_feedback({}, '\x1b[31m'+log+'\x1b[0m')
        self.assertEqual([r['line'] for r in feedback['failure_locations']], [7, 91])
        unknown = failure_feedback({}, 'Traceback (most recent call last):\nValueError: missing caller')
        self.assertEqual(unknown['failure_locations'][0]['status'], 'not_established')
        self.assertIsNone(unknown['failure_locations'][0]['line'])

    def test_call_context_and_block_counts_have_explicit_omissions(self):
        block = '___ test_large ___\n    '+('x'*1500)+'\n>       run()\nchecks/test_large.py:5:\nE   ValueError: bad\n'
        feedback = failure_feedback({}, block*6)
        self.assertEqual(len(feedback['failure_locations']), 4)
        self.assertEqual(feedback['omitted_failure_locations'], 2)
        self.assertLessEqual(len(feedback['failure_locations'][0]['context']), 800)
        self.assertGreater(feedback['failure_locations'][0]['omitted_context_characters'], 0)

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
