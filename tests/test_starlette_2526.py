import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from examples import reproduce_starlette_2526 as candidate
from examples.run_agent_baseline import prepare, real_task


def executions():
    versions = dict(package.split('==') for package in candidate.PACKAGES)
    return {phase: {'backend': 'docker', 'returncode': code, 'timeout': False,
        'stdout': json.dumps({'versions': versions, 'records': [
            {'case': case, 'passed': phase == 'gold', 'type': 'TypeError',
             'message': "Client.__init__() got an unexpected keyword argument 'app'"}
            for case in candidate.CASES]})}
        for phase, code in [('base', 1), ('gold', 0)]}


class NewCompatibilityTests(unittest.TestCase):
    def test_assessment_requires_all_cases_versions_and_specific_failure(self):
        self.assertTrue(candidate.assess(executions()))
        for mutation in ('missing', 'version', 'failure', 'duplicate', 'timeout', 'partial'):
            with self.subTest(mutation=mutation):
                runs = executions()
                payload = json.loads(runs['base']['stdout'])
                if mutation == 'missing':
                    payload['records'].pop()
                elif mutation == 'version':
                    payload['versions']['httpx'] = '0.27.0'
                elif mutation == 'failure':
                    payload['records'][0]['message'] = 'unrelated environment error'
                elif mutation == 'duplicate':
                    payload['records'][0]['case'] = 'cookie'
                elif mutation == 'timeout':
                    runs['gold']['timeout'] = True
                else:
                    gold = json.loads(runs['gold']['stdout'])
                    gold['records'][0]['passed'] = False
                    runs['gold']['stdout'] = json.dumps(gold)
                runs['base']['stdout'] = json.dumps(payload)
                self.assertFalse(candidate.assess(runs))

    def test_probe_syntax_and_goal_do_not_supply_reference_fix(self):
        compile(candidate.PROBE, 'probe', 'exec')
        self.assertNotIn(candidate.GOLD, candidate.GOAL)
        self.assertNotIn('app=self.app', candidate.GOAL)
        self.assertNotIn('Remove', candidate.GOAL)

    def test_new_case_exports_only_base_and_requires_matching_reproduction(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reproduction = root/'reproduction'
            reproduction.mkdir()
            base = root/'.keel/upgradebench-snapshots/kludex--starlette'/candidate.BASE
            (base/'starlette').mkdir(parents=True)
            raw_source = b'VERSION = 1\n'
            (base/'starlette/testclient.py').write_bytes(raw_source)
            evidence = {'candidate': 'kludex__starlette-2526', 'executions': executions(),
                'probe_sha256': hashlib.sha256(candidate.PROBE.encode()).hexdigest(),
                'image_id': 'sha256:'+'a'*64}
            path = reproduction/'summary.json'
            path.write_text(json.dumps(evidence), encoding='utf-8')
            with patch.object(candidate, 'verify_range', return_value={'starlette/testclient.py': 'hash'}) as verify:
                spec, image, _ = real_task(root, reproduction, '2526')
                manifest = prepare(root/'prepared', [spec], image, 'model', strategy='proposal')
                verify.assert_called_once()
                encoded = json.dumps(manifest)
                self.assertNotIn(candidate.GOLD, encoded)
                self.assertNotIn(candidate.BASE, encoded)
                self.assertEqual(spec['assessor'], candidate.assess)
                self.assertEqual(spec['queries'], ['class TestClient(', 'super().__init__('])
                self.assertEqual((root/'prepared/tasks/starlette-2526/template/starlette/testclient.py').read_bytes(), raw_source)
                broken = copy.deepcopy(evidence)
                broken['probe_sha256'] = 'wrong'
                path.write_text(json.dumps(broken), encoding='utf-8')
                with self.assertRaisesRegex(ValueError, 'probe mismatch'):
                    real_task(root, reproduction, '2526')

    def test_unexpected_gold_parent_or_file_change_is_rejected(self):
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base, gold = root/'base', root/'gold'
            for path in (base, gold):
                path.mkdir()
                (path/'testclient.py').write_text('old' if path == base else 'new')
            response = SimpleNamespace(stdout='parent '+'b'*40+'\n\nmessage')
            with patch.object(candidate, 'check_snapshot'), patch.object(candidate.subprocess, 'run', return_value=response):
                with self.assertRaisesRegex(ValueError, 'parent'):
                    candidate.verify_range(base, gold)
                response.stdout = 'parent '+candidate.BASE+'\n\nmessage'
                with self.assertRaisesRegex(ValueError, 'inventory'):
                    candidate.verify_range(base, gold)
