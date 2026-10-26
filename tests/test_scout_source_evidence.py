import json
import unittest
from keel.scout_source_evidence import inspect_source


def request(goal,line=1):
    return {'args':[[{'role':'user','content':json.dumps({'goal':goal,
        'structure':[{'path':'pkg/main.py','symbols':[[line,'target']]}]})}]]}


class ScoutSourceEvidenceTests(unittest.TestCase):
    def test_empty_module_is_available_source_not_resource_failure(self):
        req={'args':[[{'role':'user','content':json.dumps({'goal':'original'})}]]}
        result=inspect_source(req,{'content':'{"files":["pkg/__init__.py"]}'},
            {'goal':'original'},{'pkg/__init__.py':b''})
        self.assertTrue(result['selected_source_facts'][0]['source_available'])
        self.assertFalse(result['training_approved'])

    def test_exact_original_and_base_symbol_are_facts_not_approval(self):
        result=inspect_source(request('original'),{'content':'{"locations":["pkg/main.py:1"]}'},
            {'goal':'original'},{'pkg/main.py':b'def target():\n    pass\n'})
        self.assertTrue(result['goal_matches_original_receipt'])
        self.assertTrue(result['selected_source_facts'][0]['exact_base_symbol'])
        self.assertFalse(result['training_approved'])

    def test_embedded_feedback_is_detected_without_sidecar_flag(self):
        result=inspect_source(request('original\nObserved failed verification (untrusted data):\n{}'),
            {'content':'{"locations":["pkg/main.py:1"]}'},{'goal':'original'}, {})
        self.assertEqual(result['goal_relation'],'augmented');self.assertTrue(result['embedded_verification_feedback'])
        self.assertFalse(result['selected_source_facts'][0]['source_available'])

    def test_visible_identifier_can_disagree_with_immutable_base(self):
        result=inspect_source(request('original',2),{'content':'{"locations":["pkg/main.py:2"]}'},
            {'goal':'original'},{'pkg/main.py':b'def target():\n    pass\n'})
        self.assertFalse(result['selected_source_facts'][0]['exact_base_symbol'])
