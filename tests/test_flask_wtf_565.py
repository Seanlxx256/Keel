import copy
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from examples import reproduce_flask_wtf_565 as candidate


def executions():
    return {phase: {'backend': 'docker', 'timeout': False, 'returncode': code,
        'stdout': json.dumps({'versions': dict(pin.split('==') for pin in candidate.PACKAGES),
            'records': [{'case': case, 'passed': phase == 'gold', 'type': 'ImportError',
                'message': "cannot import name 'url_encode' from 'werkzeug.urls'"}
                for case in candidate.CASES]})} for phase, code in [('base', 1), ('gold', 0)]}


class FlaskWtfReproductionTests(unittest.TestCase):
    def test_multifile_export_uses_base_only_and_checks_declared_change_scope(self):
        from examples.run_agent_baseline import real_task, prepare, changed_scope_passes
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reproduction = root/'reproduction'
            reproduction.mkdir()
            base_revision, gold_revision = 'a'*40, 'b'*40
            base = root/'.keel/upgradebench-snapshots/pallets-eco--flask-wtf'/base_revision
            names = ['src/flask_wtf/recaptcha/widgets.py', 'src/flask_wtf/recaptcha/validators.py']
            for name in names:
                path = base/name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('BASE_ONLY = 1\n')
            evidence = {'candidate': 'pallets-eco__flask-wtf-565', 'executions': executions(),
                'probe_sha256': hashlib.sha256(candidate.PROBE.encode()).hexdigest(),
                'base_commit': base_revision, 'gold_commit': gold_revision, 'image_id': 'sha256:'+'c'*64}
            (reproduction/'summary.json').write_text(json.dumps(evidence), encoding='utf-8')
            with patch.object(candidate, 'verify', return_value={'base_inventory': dict.fromkeys(names, 'hash')}):
                spec, image, _ = real_task(root, reproduction, 'flask-wtf-565')
            manifest = prepare(root/'export', [spec], image, 'model', strategy='proposal')
            task = manifest['tasks'][0]
            self.assertEqual(task['config']['proposal']['files'], names)
            self.assertNotIn(gold_revision, json.dumps(task))
            self.assertLess(task['context_preflight']['source_input_bytes'], 12000)
            self.assertTrue(changed_scope_passes(task, names))
            self.assertTrue(changed_scope_passes(task, names[:1]))
            self.assertFalse(changed_scope_passes(task, []))
            self.assertFalse(changed_scope_passes(task, names + ['tests/test_recaptcha.py']))
            self.assertEqual((root/'export/tasks/flask-wtf-565/template'/names[0]).read_text(), 'BASE_ONLY = 1\n')

    def test_assessment_rejects_missing_cases_versions_and_unrelated_failures(self):
        self.assertTrue(candidate.assess(executions()))
        for change in ('missing', 'version', 'unrelated', 'duplicate', 'partial'):
            with self.subTest(change=change):
                runs = executions()
                phase = 'gold' if change == 'partial' else 'base'
                data = json.loads(runs[phase]['stdout'])
                if change == 'missing':
                    data['records'].pop()
                elif change == 'version':
                    data['versions']['Flask'] = '2.3.0'
                elif change == 'unrelated':
                    data['records'][0]['message'] = 'missing an unrelated package'
                elif change == 'duplicate':
                    data['records'][0]['case'] = 'widget'
                else:
                    data['records'][0]['passed'] = False
                runs[phase]['stdout'] = json.dumps(data)
                self.assertFalse(candidate.assess(runs))

    def test_rejects_timeout_wrong_backend_and_zero_exit_base(self):
        for phase, field, value in [('base', 'returncode', 0), ('gold', 'timeout', True), ('gold', 'backend', 'local')]:
            runs = executions()
            runs[phase][field] = value
            self.assertFalse(candidate.assess(runs))
        compile(candidate.PROBE, 'curated-probe', 'exec')
        self.assertIn("sys.path.insert(0, '/workspace/src')", candidate.PROBE)

    def test_resolver_freezes_merge_first_parent_not_mutable_pr_base(self):
        pr = {'merged': True, 'merge_commit_sha': 'a'*40,
              'base': {'sha': 'c'*40, 'repo': {'full_name': candidate.REPOSITORY}}}
        commit = {'sha': 'a'*40, 'parents': [{'sha': 'b'*40}, {'sha': 'd'*40}]}
        seen = []
        def fetch(route):
            seen.append(route)
            return pr if '/pulls/' in route else commit
        self.assertEqual(candidate.resolve(fetch), ('b'*40, 'a'*40))
        self.assertEqual(len(seen), 2)
        pr['merged'] = False
        with self.assertRaises(ValueError):
            candidate.resolve(fetch)
        pr['merged'] = True
        commit['sha'] = 'e'*40
        with self.assertRaises(ValueError):
            candidate.resolve(fetch)

    def test_git_parent_and_exact_file_inventory_are_both_required(self):
        with tempfile.TemporaryDirectory() as directory:
            before, after = Path(directory)/'base', Path(directory)/'gold'
            for root in (before, after):
                root.mkdir()
                for name in candidate.CHANGED:
                    path = root/name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text('base' if root == before else 'gold')
            raw = SimpleNamespace(stdout='parent '+'a'*40+'\n\nmessage')
            with patch.object(candidate, 'check_snapshot'), patch.object(candidate.subprocess, 'run', return_value=raw):
                self.assertEqual(candidate.verify('a'*40, 'b'*40, before, after)['changed_files'], candidate.CHANGED)
                (after/'unexpected.py').write_text('unexpected')
                with self.assertRaisesRegex(ValueError, 'inventory'):
                    candidate.verify('a'*40, 'b'*40, before, after)
                raw.stdout = 'parent '+'c'*40+'\n\nmessage'
                with self.assertRaisesRegex(ValueError, 'first parent'):
                    candidate.verify('a'*40, 'b'*40, before, after)
