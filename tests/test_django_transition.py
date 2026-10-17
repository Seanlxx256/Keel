import copy
import json
import unittest
from examples.reproduce_django_13586 import assess, COMMON, TARGETS, PROBE, CASES


class DjangoTransitionTests(unittest.TestCase):
    def executions(self):
        result = {}
        for phase, version, passing in [('base_old', 'old', True), ('base_new', 'new', False), ('gold_new', 'new', True)]:
            versions = dict(pin.split('==') for pin in COMMON)
            versions['asgiref'] = TARGETS[version]
            record = {'case': CASES[0], 'passed': passing}
            if not passing:
                record.update(type='BrokenBarrierError', message='')
            result[phase] = {'backend': 'docker', 'returncode': 0 if passing else 1, 'timeout': False,
                             'stdout': json.dumps({'versions': versions, 'records': [record]})}
        return result

    def test_requires_all_three_cells_and_exact_failure(self):
        executions = self.executions()
        self.assertTrue(assess(executions))
        del executions['base_old']
        self.assertFalse(assess(executions))
        executions = self.executions()
        payload = json.loads(executions['base_new']['stdout'])
        payload['records'][0]['type'] = 'ImportError'
        executions['base_new']['stdout'] = json.dumps(payload)
        self.assertFalse(assess(executions))

    def test_timeout_wrong_versions_and_empty_cases_fail(self):
        for mode in ('timeout', 'version', 'empty'):
            executions = self.executions()
            if mode == 'timeout':
                executions['gold_new']['timeout'] = True
            else:
                payload = json.loads(executions['gold_new']['stdout'])
                if mode == 'version':
                    payload['versions']['asgiref'] = 'wrong'
                else:
                    payload['records'] = []
                executions['gold_new']['stdout'] = json.dumps(payload)
            self.assertFalse(assess(executions))

    def test_probe_compiles_and_keeps_callback_observations(self):
        compile(PROBE, 'probe', 'exec')
        self.assertIn('threading.Barrier', PROBE)
        self.assertNotIn('thread_sensitive=', PROBE)
        self.assertIn("[b'one', b'two']", PROBE)
