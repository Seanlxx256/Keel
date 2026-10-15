import unittest

from keel.transition_signal import extract
from keel.candidate_selection import shortlist, validate_policy
from test_candidate_selection import policy, row, KNOWN


class TransitionEvidenceTests(unittest.TestCase):
    def test_explicit_dependency_versions_are_extracted_with_bounded_source(self):
        for text in ('Support httpcore 1.0.0', 'Requires `httpcore==1.0`', 'Use httpcore[asyncio]>=1.0.0'):
            result = extract(text, '', 'httpcore')
            self.assertIsNotNone(result)
            self.assertFalse(result['verified_transition'])
            self.assertLessEqual(len(result['excerpt']), 240)
        result = extract('Update runtime', 'Support urllib3 version 2.0.0', 'urllib3')
        self.assertEqual(result['field'], 'body')
        self.assertEqual(result['mentioned_version'], '2.0.0')

    def test_generic_compatibility_and_unrelated_python_versions_are_not_evidence(self):
        for text in ('Windows compatibility', 'Remove compatibility shim for Python 3.6',
                     'httpcore supports Python 3.12', 'compatibility comment about urllib3'):
            self.assertIsNone(extract(text, '', 'httpcore'))

    def test_v3_requires_evidence_for_declared_dependency_and_keeps_rejections(self):
        config = {**policy(), 'schema_version': 3, 'query': 'dependency-name',
            'missing_commit_policy': 'record_exclusion_count_toward_limit',
            'dependencies': {'org/one': 'dep', 'org/two': 'dep'}}
        validate_policy(config, KNOWN)
        collections = {repo: {'status': 'completed', 'candidates': [row(repo, 1)]}
                       for repo in config['repositories']}
        result = shortlist(config, KNOWN, collections)
        self.assertFalse(result['selected'])
        self.assertTrue(all('no_dependency_version_evidence' in r['reasons'] for r in result['screened']))
        for state in collections.values():
            state['candidates'][0]['transition_signal'] = extract('Support dep 2.0', '', 'dep')
        result = shortlist(config, KNOWN, collections)
        self.assertEqual(len(result['selected']), 2)
        self.assertEqual(result['independent_tasks_ready'], 0)
