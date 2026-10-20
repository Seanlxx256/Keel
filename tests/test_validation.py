import importlib.util
from unittest.mock import patch
import unittest

from compass.validation import validate_components


class ValidationTests(unittest.TestCase):
    def test_nested_sdk_failure_reports_the_leaf_contract_error(self):
        error = ExceptionGroup('TaskGroup', [ExceptionGroup('inner', [ValueError('SDK tool discovery differs')])])
        def fail(root):
            raise error
        with patch('compass.validation.util.find_spec', return_value=object()), \
             patch('compass.validation.metadata.version', return_value='test'), \
             patch.dict('compass.validation.PROBES', {'mcp_sdk': fail}):
            report = validate_components(['mcp_sdk'])
        self.assertEqual(report['checks'][0]['causes'], ['ValueError: SDK tool discovery differs'])
        self.assertFalse(report['all_passed'])
    def test_missing_dependencies_are_unavailable_not_passed(self):
        with patch("compass.validation.util.find_spec", return_value=None):
            report = validate_components()
        self.assertFalse(report["all_passed"])
        self.assertEqual([check["status"] for check in report["checks"]], ["unavailable"] * 3)

    def test_probe_failure_is_preserved(self):
        with patch("compass.validation.util.find_spec", return_value=object()), \
             patch("compass.validation.metadata.version", return_value="test"), \
             patch.dict("compass.validation.PROBES", {"tree_sitter": lambda root: (_ for _ in ()).throw(ValueError("broken integration"))}):
            report = validate_components(["tree_sitter"])
        self.assertEqual(report["checks"][0]["status"], "failed")
        self.assertIn("broken integration", report["checks"][0]["error"])
        self.assertFalse(report["all_passed"])

    @unittest.skipUnless(importlib.util.find_spec("mcp"), "Official MCP SDK is not installed")
    def test_real_official_sdk_interoperability(self):
        report = validate_components(["mcp_sdk"])
        self.assertTrue(report["all_passed"], report)


if __name__ == "__main__":
    unittest.main()
