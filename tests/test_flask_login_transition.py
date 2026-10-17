import json
import unittest
from pathlib import Path
from examples.reproduce_flask_login_813 import assess, diagnose, COMMON, TARGETS, CASES, PROBE, selected_candidate


class FlaskLoginTransitionTests(unittest.TestCase):
    def test_same_preexisting_failure_is_not_relabelled_as_upgrade_regression(self):
        executions = self.matrix()
        records = [{'case': case, 'passed': case != 'login_query',
                    **({'type': 'AssertionError', 'message': ''} if case == 'login_query' else {})} for case in CASES]
        for phase in ('base_old', 'base_new'):
            payload = json.loads(executions[phase]['stdout'])
            payload['records'] = records
            executions[phase]['stdout'] = json.dumps(payload)
            executions[phase]['returncode'] = 1
        self.assertFalse(assess(executions))
        result = diagnose(executions)
        self.assertEqual(result['category'], 'same_failure_under_old_and_new_dependency')
        self.assertFalse(result['transition_established'])

    def matrix(self):
        executions = {}
        for phase, dependency, passing in [('base_old', 'old', True), ('base_new', 'new', False), ('gold_new', 'new', True)]:
            versions = dict(pin.split('==') for pin in COMMON)
            versions['Werkzeug'] = TARGETS[dependency]
            records = [{'case': case, 'passed': passing, **({} if passing else {
                'type': 'ImportError', 'message': "cannot import name 'url_decode' from 'werkzeug.urls'"})} for case in CASES]
            executions[phase] = {'backend': 'docker', 'timeout': False, 'returncode': 0 if passing else 1,
                                 'stdout': json.dumps({'records': records, 'versions': versions})}
        return executions

    def test_exact_three_cells_and_all_cases_are_required(self):
        executions = self.matrix()
        self.assertTrue(assess(executions))
        del executions['base_old']
        self.assertFalse(assess(executions))
        executions = self.matrix()
        payload = json.loads(executions['gold_new']['stdout'])
        payload['records'].pop()
        executions['gold_new']['stdout'] = json.dumps(payload)
        self.assertFalse(assess(executions))

    def test_unrelated_import_failure_timeout_or_version_mismatch_is_not_success(self):
        for mode in ('type', 'version', 'timeout'):
            executions = self.matrix()
            if mode == 'timeout':
                executions['gold_new']['timeout'] = True
            else:
                payload = json.loads(executions['base_new']['stdout'])
                if mode == 'type':
                    payload['records'][0]['message'] = 'unrelated import failure'
                else:
                    payload['versions']['Werkzeug'] = 'wrong'
                executions['base_new']['stdout'] = json.dumps(payload)
            self.assertFalse(assess(executions))

    def test_probe_compiles_and_covers_url_cookie_and_session_behavior(self):
        compile(PROBE, 'probe', 'exec')
        self.assertEqual(len(CASES), 5)
        self.assertIn("decode_cookie(encoded + 'tampered') is None", PROBE)
        self.assertIn("client.get('/private').data == b'alice'", PROBE)
        self.assertIn("'tag': ['a', 'b']", PROBE)
