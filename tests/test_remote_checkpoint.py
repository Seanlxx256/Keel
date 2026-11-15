"""Recovery contracts; no Docker or provider calls."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from keel.governance import GovernanceUnavailable
from keel.remote_governance import RemoteSession


class RemoteCheckpointTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'client.json'
        self.config={'endpoint':'http://127.0.0.1:8788','task_id':'task-a',
                     'token_env':'KEEL_CHECKPOINT_TEST_TOKEN','state_path':str(self.path)}
        env=patch.dict(os.environ,{'KEEL_CHECKPOINT_TEST_TOKEN':'secret-'*8})
        env.start();self.addCleanup(env.stop)

    def begin(self):
        with patch.object(RemoteSession,'_send',return_value={
                'run_id':'run-a','scope':'scope-a','lease_seconds':900}):
            return RemoteSession.begin(self.config,'input',30)

    def test_pending_intent_survives_loss_and_exact_rpc_is_reconciled(self):
        session=self.begin()
        with patch.object(session,'_send',side_effect=GovernanceUnavailable('lost')):
            with self.assertRaises(GovernanceUnavailable):session.reserve(20)
        pending=json.loads(self.path.read_text())['pending']
        restored=RemoteSession.recover(self.config)
        with patch.object(restored,'_send',return_value={'request_id':'request-a'}) as send:
            restored.reconcile_pending()
            self.assertEqual(send.call_args.args[0],pending)
        self.assertIsNone(json.loads(self.path.read_text())['pending'])
        with self.assertRaises(GovernanceUnavailable):restored.reserve(20)
        with self.assertRaises(GovernanceUnavailable):restored.tool_started('scout','read_file','a')

    def test_begin_loss_is_recoverable_without_starting_another_run(self):
        with patch.object(RemoteSession,'_send',side_effect=GovernanceUnavailable('lost')):
            with self.assertRaises(GovernanceUnavailable):RemoteSession.begin(self.config,'input',30)
        restored=RemoteSession.recover(self.config)
        with patch.object(restored,'_send',return_value={
                'run_id':'run-a','scope':'scope-a','lease_seconds':900}):
            restored.reconcile_pending()
        self.assertEqual(json.loads(self.path.read_text())['run_id'],'run-a')

    def test_existing_state_is_not_overwritten_and_secret_is_not_saved(self):
        self.begin();original=self.path.read_bytes()
        with self.assertRaises(FileExistsError):self.begin()
        self.assertEqual(self.path.read_bytes(),original)
        self.assertNotIn(os.environ[self.config['token_env']],original.decode())

    def test_identity_change_rejected_before_network(self):
        self.begin()
        with self.assertRaises(ValueError):
            RemoteSession.recover(dict(self.config,task_id='other'))

    def test_required_checkpoint_failure_prevents_dispatch(self):
        session=self.begin()
        with patch('compass.progress.atomic_json',side_effect=OSError('disk full')):
            with patch.object(session,'_send') as send:
                with self.assertRaises(GovernanceUnavailable):session.reserve(20)
                send.assert_not_called()
        with self.assertRaises(GovernanceUnavailable):session.inspect()


if __name__=='__main__':unittest.main()
