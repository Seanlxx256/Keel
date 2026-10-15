import copy
import json
import unittest

from examples.reproduce_starlette_1936 import PACKAGES, assess


def executions():
    versions = dict(package.split('==') for package in PACKAGES)
    base = [{'case': case, 'passed': False, 'type': 'AttributeError',
             'message': "module 'anyio' has no attribute 'start_blocking_portal'"}
            for case in ['request', 'lifespan']]
    gold = [{'case': case, 'passed': True} for case in ['request', 'lifespan']]
    return {phase: {'backend': 'docker', 'returncode': code, 'timeout': False,
                    'stdout': json.dumps({'records': rows, 'versions': versions})}
            for phase, rows, code in [('base', base, 1), ('gold', gold, 0)]}


class ReproductionTests(unittest.TestCase):
    def test_requires_specific_base_failure_and_gold_pass_in_identical_environment(self):
        self.assertTrue(assess(executions()))
        for phase, field, value in [('base', 'returncode', 0), ('gold', 'returncode', 1),
                                    ('gold', 'timeout', True), ('base', 'backend', 'local'),
                                    ('base', 'stdout', 'installation failed')]:
            with self.subTest(phase=phase, field=field):
                runs = executions()
                runs[phase][field] = value
                self.assertFalse(assess(runs))

    def test_missing_cases_wrong_versions_and_unrelated_failures_are_not_success(self):
        for change in ['missing_case', 'wrong_version', 'unrelated_failure', 'partial_gold']:
            runs = copy.deepcopy(executions())
            phase = 'gold' if change == 'partial_gold' else 'base'
            data = json.loads(runs[phase]['stdout'])
            if change == 'missing_case':
                data['records'].pop()
            elif change == 'wrong_version':
                data['versions']['anyio'] = '3.0.0'
            elif change == 'unrelated_failure':
                data['records'][0]['message'] = 'unrelated attribute missing'
            else:
                data['records'][0]['passed'] = False
            runs[phase]['stdout'] = json.dumps(data)
            with self.subTest(change=change):
                self.assertFalse(assess(runs))
