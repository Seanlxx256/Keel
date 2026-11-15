"""Ownership and shutdown contracts; Docker calls are fixtures only."""
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

from keel.container_receipts import ContainerRegistry, TrackedCommandRunner, inspect_known, owned_container
from keel.execution_broker import ExecutionBroker
from keel.governance import ControlStore, GovernanceUnavailable


class ContainerReceiptTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.store=ControlStore(Path(temp.name)/'control.sqlite')
        self.registry=ContainerRegistry(self.store,'owner')
        self.name='keel-'+'a'*32
        self.labels=self.registry.register('job',self.name,'sha256:'+'b'*64,'/repo','/reports')
        self.expected={'image':'sha256:'+'b'*64,'root':'/repo','reports':'/reports','labels':self.labels}
        self.inspect={'Id':'c'*64,'Name':'/'+self.name,'Image':self.expected['image'],'Labels':self.labels,
            'Mounts':[{'Type':'bind','Source':'/repo','Destination':'/workspace','RW':False},
                      {'Type':'bind','Source':'/reports','Destination':'/keel-reports','RW':True}]}

    def test_owned_container_requires_labels_image_and_mount_identity(self):
        self.assertTrue(owned_container(self.inspect,self.name,self.expected))
        for field,value in [('Image','different'),('Labels',{}),('Mounts',[])]:
            altered={**self.inspect,field:value}
            self.assertFalse(owned_container(altered,self.name,self.expected))

    def test_cleanup_uses_inspected_full_id_never_name(self):
        rows=[Mock(returncode=0,stdout=json.dumps(self.inspect).encode()),Mock(returncode=0,stdout=b''),
              Mock(returncode=0,stdout=b'')]
        with patch('keel.container_receipts.subprocess.run',side_effect=rows) as call:
            result=inspect_known(self.name,self.expected,remove=True,deadline=time.monotonic()+5)
        self.assertTrue(result['confirmed_absent'])
        self.assertEqual(call.call_args_list[1].args[0],['docker','rm','--force','c'*64])

    def test_wrong_identity_is_not_removed(self):
        wrong={**self.inspect,'Labels':{}}
        with patch('keel.container_receipts.subprocess.run',return_value=Mock(returncode=0,stdout=json.dumps(wrong).encode())) as call:
            result=inspect_known(self.name,self.expected,remove=True,deadline=time.monotonic()+5)
        self.assertEqual(result['status'],'identity_mismatch');self.assertEqual(call.call_count,1)

    def test_daemon_failure_is_not_absence(self):
        with patch('keel.container_receipts.subprocess.run',return_value=Mock(returncode=1,stdout=b'')):
            result=inspect_known(self.name,self.expected,deadline=time.monotonic()+5)
        self.assertFalse(result['confirmed_absent'])

    def test_launch_is_registered_before_command_dispatch_and_labels_are_added(self):
        runner=TrackedCommandRunner({'backend':'docker','image':'sha256:'+'b'*64},self.registry,'job',threading.Event())
        command=runner.docker_command(['python','-V'],Path('/repo'),Path('/reports'),'keel-'+'d'*32)
        self.assertIn('--label',command)
        with self.store.transaction() as db:
            self.assertIsNotNone(db.execute('SELECT * FROM broker_containers WHERE name=?',('keel-'+'d'*32,)).fetchone())

    def test_stopped_executor_cannot_prepare_a_container(self):
        stopped=threading.Event();stopped.set()
        runner=TrackedCommandRunner({'backend':'docker','image':'sha256:'+'b'*64},self.registry,'job',stopped)
        with self.assertRaises(GovernanceUnavailable):runner.docker_command(['python'],Path('/repo'),None,'keel-'+'d'*32)

    def test_shutdown_with_live_thread_is_not_certified_stopped(self):
        broker=object.__new__(ExecutionBroker)
        broker.owner='owner';broker.stopping=threading.Event();broker.lock=threading.Lock()
        broker.service=Mock(store=self.store);broker.containers=Mock()
        broker.containers.inspect_job.return_value={'confirmed_absent':True}
        thread=Mock();thread.is_alive.return_value=True
        broker.threads={'job':thread}
        result=broker.shutdown(timeout=.01)
        self.assertEqual(result['status'],'cleanup_unconfirmed')
        self.assertTrue(broker.stopping.is_set())


if __name__=='__main__':unittest.main()
