import unittest
from keel.probe_context import context_inventory


class ProbeContextTests(unittest.TestCase):
    def test_context_fields_and_local_callees_come_from_source(self):
        text='def helper(context=None):\n    return context.options.enabled, context.references.get("key")\n\ndef parse(text, context=None):\n    return helper(context)\n'
        rows=context_inventory('sample.py',text,['parse','helper'])['functions']
        self.assertEqual(rows[0]['local_callees'],['helper'])
        self.assertIn('context.options.enabled',rows[1]['parameter_attribute_accesses'])
        self.assertIn('context.references.get',rows[1]['parameter_attribute_accesses'])
        self.assertNotIn('enabled',rows[0]['parameters'])

    def test_conditional_access_is_not_claimed_mandatory(self):
        value=context_inventory('a.py','def target(context=None):\n    if context:\n        return context.value\n',['target'])
        self.assertIn('conditional',value['scope'])
        self.assertEqual(value['functions'][0]['parameter_attribute_accesses'],['context.value'])
        with self.assertRaises(ValueError):
            context_inventory('a.py','def target(): pass',['invented'])
