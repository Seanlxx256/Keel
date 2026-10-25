import unittest
from keel.verification_context import failure_test_context, executed_test_patch_context


class VerificationContextTests(unittest.TestCase):
    def test_archived_test_patch_is_read_without_executing_shell(self):
        raw=b"echo unrelated\ngit apply -v - <<'END'\ndiff --git a/tests/test_app.py b/tests/test_app.py\n--- a/tests/test_app.py\n+++ b/tests/test_app.py\n@@ -1,1 +1,3 @@\n+def test_case():\n+    assert value == expected\nEND\nraise anything\n"
        value=executed_test_patch_context(raw,'tests/test_app.py::test_case')
        self.assertIn('+    assert value == expected',value['text'])
        self.assertNotIn('raise anything',value['text'])
        with self.assertRaises(ValueError):
            executed_test_patch_context(raw,'tests/test_else.py::test_case')

    def test_observed_assertion_is_retained_and_labelled_partial(self):
        raw=b"    def test_case(app):\n        value = call()\n>       assert value == 'expected'\n\ntests/test_app.py:12: \n    def assert_helper():\n        pass\n"
        value=failure_test_context(raw,'tests/test_app.py::test_case')
        self.assertIn("assert value == 'expected'",value['text'])
        self.assertNotIn('assert_helper',value['text'])
        self.assertEqual(value['failure_line'],12)
        self.assertFalse(value['complete_test_body'])

    def test_ansi_is_removed_but_unrelated_test_is_not_used(self):
        raw=b"    def test_other():\n        pass\ntests/test_app.py:1:\n    def \x1b[32mtest_case\x1b[0m():\n>       assert False\ntests/test_app.py:9:\n"
        value=failure_test_context(raw,'tests/test_app.py::test_case[param]')
        self.assertNotIn('test_other',value['text'])
        self.assertNotIn('\x1b',value['text'])

    def test_missing_or_oversized_context_fails_instead_of_inventing_source(self):
        with self.assertRaises(ValueError):
            failure_test_context(b'no body here','tests/test_app.py::test_case')
        with self.assertRaisesRegex(ValueError,'limit'):
            failure_test_context(b'    def test_case():\n        assert False\ntests/test_app.py:2:\n','tests/test_app.py::test_case',max_bytes=8)
