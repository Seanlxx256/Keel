from pathlib import Path
import tempfile
import unittest
from keel.core import BudgetExceeded
from keel.proposals import located_source_evidence, proposal_request


class LocatedEvidenceTests(unittest.TestCase):
    def test_duplicate_names_are_disambiguated_and_decorator_is_preserved(self):
        text = '# preamble\n'*45+'class A:\n    @property\n    def value(self):\n        return "FIRST"\n'+'# gap\n'*20+'class B:\n    def value(self):\n        return "SECOND"\n'
        lines = text.splitlines(keepends=True)
        position = next(i for i, line in enumerate(lines, 1) if 'def value' in line)
        evidence = located_source_evidence('a.py', text, [position])
        rendered = ''.join(w['text'] for w in evidence['windows'])
        self.assertIn('@property', rendered)
        self.assertIn('FIRST', rendered)
        self.assertNotIn('SECOND', rendered)
        for w in evidence['windows']:
            self.assertEqual(w['text'], ''.join(lines[w['start_line']-1:w['end_line']]))
        with self.assertRaises(ValueError):
            located_source_evidence('a.py', text, [position+1])
        with self.assertRaises(ValueError):
            located_source_evidence('a.py', text, [True])

    def test_complete_large_function_is_rejected_by_cap_not_truncated(self):
        text = '# preamble\n'*45+'def large():\n'+'    # padding\n'*2000+'    return "TAIL"\n'
        evidence = located_source_evidence('a.py', text, [46])
        self.assertIn('TAIL', ''.join(w['text'] for w in evidence['windows']))
        with self.assertRaises(BudgetExceeded):
            proposal_request('Repair', ['a.py'], [evidence], {'max_context_bytes': 12000})
