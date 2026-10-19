import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from keel.experience import ExperienceStore, RecoverySession, environment


class ExperienceTests(unittest.TestCase):
    def test_publish_entrypoint_reuses_experience_across_tasks(self):
        from compass.progress import atomic_json
        with tempfile.TemporaryDirectory() as directory:
            store = ExperienceStore(Path(directory)/'experience.sqlite')
            original = Path.replace
            for task in ['index-task-a', 'index-task-b']:
                session = RecoverySession(task=task, store=store, max_actions=1)
                calls = []
                def replace(source, target):
                    calls.append(target)
                    if len(calls) == 1:
                        raise PermissionError('controlled target sharing conflict')
                    return original(source, target)
                with patch.object(Path, 'replace', replace):
                    atomic_json(Path(directory)/(task+'.json'), {'task': task}, delay=0, recovery=session)
                self.assertEqual(len(calls), 2)
                if task.endswith('b'):
                    self.assertIn('retry_replace_v1', next(e['actions'] for e in session.events if e['event'] == 'retrieved'))

    def test_environment_change_and_probe_rejection_prevent_reuse(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ExperienceStore(Path(directory)/'experience.sqlite')
            session = RecoverySession(task='other', store=store, max_actions=1)
            with self.assertRaises(PermissionError):
                session.run(lambda: (_ for _ in ()).throw(PermissionError()), stage='publish',
                    facts=environment(dependency='2'), classify=lambda error: 'permission',
                    actions={'retry': {'categories': ['permission'],
                        'probe': lambda error: {'applicable': False, 'check': 'persistent_parent_denial'},
                        'apply': lambda remaining: self.fail('inapplicable action executed')}},
                    verify=lambda value: True)
            self.assertEqual(session.used_actions, 0)

    def test_another_task_retrieves_only_verified_applicable_experience(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ExperienceStore(Path(directory)/'experience.sqlite')
            for task in ['first-task', 'another-task']:
                session = RecoverySession(task=task, store=store, max_actions=1)
                state = {'ready': False}
                def operation():
                    if not state['ready']:
                        raise ConnectionError('transient')
                    return [1, 2]
                result = session.run(operation, stage='query', facts=environment(version='1'),
                    classify=lambda error: 'connection', actions={'reconnect_v1': {
                        'categories': ['connection'],
                        'probe': lambda error: {'applicable': True, 'check': 'service_probe'},
                        'apply': lambda remaining: state.update(ready=True)}},
                    verify=lambda result: result == [1, 2])
                self.assertEqual(result, [1, 2])
                retrieved = [e['actions'] for e in session.events if e['event'] == 'retrieved']
                self.assertEqual(retrieved, [[]] if task == 'first-task' else [['reconnect_v1']])

    def test_failed_verification_never_promoted_and_unknown_is_bounded(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ExperienceStore(Path(directory)/'experience.sqlite')
            session = RecoverySession(task='bad', store=store, max_actions=1)
            with self.assertRaises(ValueError):
                session.run(lambda: [], stage='query', facts=environment(),
                    classify=lambda error: 'invalid', actions={'retry': {
                        'categories': ['invalid'], 'probe': lambda error: {'applicable': True},
                        'apply': lambda remaining: None}}, verify=lambda value: False)
            with store.connect() as db:
                self.assertEqual(db.execute('SELECT count(*) FROM attempts WHERE outcome="verified"').fetchone()[0], 0)
                self.assertEqual(db.execute('SELECT count(*) FROM attempts WHERE outcome="failed"').fetchone()[0], 1)
            calls = []
            session = RecoverySession(task='unknown', max_actions=2,
                diagnose=lambda observation, remaining: calls.append(observation) or 'unregistered_command')
            with self.assertRaises(RuntimeError):
                session.run(lambda: (_ for _ in ()).throw(RuntimeError()), stage='unknown',
                    facts=environment(), classify=lambda error: 'unseen', actions={}, verify=lambda value: True)
            self.assertEqual(len(calls), 1)
