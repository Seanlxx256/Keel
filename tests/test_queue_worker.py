"""Worker-host admission and failure contracts; no live Docker or provider."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from keel.queue_worker import child_environment, execute, load_task


class QueueWorkerTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root=Path(temp.name);self.repo=self.root/'repo';self.repo.mkdir()
        self.task=self.root/'task.json'
        self.config={'execution':{'backend':'docker','image':'sha256:'+'a'*64},
                     'mode':'explicit','budget':{'max_wallclock':60}}
        self.write_task()
        self.remote={'endpoint':'http://127.0.0.1:8788','task_id':'task','token_env':'QUEUE_WORKER_TOKEN'}

    def write_task(self):
        self.task.write_text(json.dumps(self.config),encoding='utf-8')
        self.digest=hashlib.sha256(self.task.read_bytes()).hexdigest()

    def test_hash_drift_and_local_backend_rejected(self):
        with self.assertRaises(ValueError):load_task(self.task,'0'*64,self.repo)
        self.config['execution']['backend']='local';self.write_task()
        with self.assertRaises(ValueError):load_task(self.task,self.digest,self.repo)

    def test_embedded_governance_cannot_override_worker_host(self):
        self.config['governance']={'endpoint':'http://other'};self.write_task()
        with self.assertRaises(ValueError):load_task(self.task,self.digest,self.repo)

    def test_child_environment_does_not_inherit_unapproved_secrets(self):
        with patch.dict(os.environ,{'QUEUE_WORKER_TOKEN':'allowed','CONTROLLER_SECRET':'denied','MODEL_KEY':'optional'}):
            env=child_environment(self.remote,['MODEL_KEY'])
        self.assertEqual(env['QUEUE_WORKER_TOKEN'],'allowed')
        self.assertEqual(env['MODEL_KEY'],'optional')
        self.assertNotIn('CONTROLLER_SECRET',env)

    def execute(self,output=None):
        return execute(remote=self.remote,task_path=self.task,task_sha256=self.digest,repo=self.repo,
                       output=output or self.root/'output',state_root=self.root/'state',max_seconds=60)

    def test_wrong_payload_never_starts_runtime_or_marks_task_complete(self):
        session=Mock(run_id='run')
        session.claim_task.return_value={'dispatch_allowed':True,'task':{'id':'item','fence':1,'payload':{'shell':'bad'}}}
        session.finish.return_value={'status':'failed'}
        with patch('keel.queue_worker.RemoteSession.begin',return_value=session):
            with patch('keel.queue_worker.subprocess.Popen') as launch:
                result=self.execute()
        self.assertEqual(result['status'],'unresolved');launch.assert_not_called()
        session.start_task.assert_not_called();session.finish_task.assert_not_called()

    def test_idle_worker_closes_session_without_dispatch(self):
        session=Mock(run_id='run');session.claim_task.return_value={'task':None}
        session.finish.return_value={'status':'passed'}
        with patch('keel.queue_worker.RemoteSession.begin',return_value=session):
            result=self.execute()
        self.assertEqual(result['status'],'idle')
        session.finish.assert_called_once_with('passed')

    def test_evidence_inside_repository_is_rejected(self):
        with self.assertRaises(ValueError):self.execute(self.repo/'output')


if __name__=='__main__':unittest.main()
