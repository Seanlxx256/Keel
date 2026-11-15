import copy
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from keel.control_service import ControlService, make_server
from keel.core import PolicyDenied
from keel.governance import ControlStore
from keel.remote_governance import RemoteSession


class TenancyTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root=Path(temp.name)
        env=patch.dict(os.environ,{'KEEL_TENANT_A':'a'*48,'KEEL_TENANT_B':'b'*48})
        env.start();self.addCleanup(env.stop)
        self.config={'path':str(self.root/'control.sqlite'),
            'scopes':{scope:{'max_tokens':100,'max_model_calls':10,'lease_seconds':300} for scope in ('budget-a','budget-b')},
            'principals':[{'id':'alice','tenant_id':'team-a','token_env':'KEEL_TENANT_A','scope':'budget-a','task_id':'task-a','tools':{}},
                          {'id':'bob','tenant_id':'team-b','token_env':'KEEL_TENANT_B','scope':'budget-b','task_id':'task-b','tools':{}}]}

    def begin(self,service,principal='alice',task='task-a',operation='same-id'):
        return service.operate(principal,{'operation_id':operation,'action':'begin',
            'data':{'task_id':task,'identity':'fixture','wallclock_seconds':30}})['result']

    def test_explicit_tenants_same_operation_id_are_separate(self):
        service=ControlService(self.config)
        a=self.begin(service);b=self.begin(service,'bob','task-b')
        self.assertNotEqual(a['run_id'],b['run_id'])
        self.assertEqual(a['tenant_id'],'team-a');self.assertEqual(b['tenant_id'],'team-b')
        with self.assertRaises(PolicyDenied):service.operate('bob',{'operation_id':'foreign','action':'report','run_id':a['run_id'],'data':{}})

    def test_different_tenants_cannot_share_budget_scope(self):
        self.config['principals'][1]['scope']='budget-a'
        with self.assertRaises(PolicyDenied):ControlService(self.config)

    def test_different_tenants_cannot_share_task_binding(self):
        self.config['principals'][1]['task_id']='task-a'
        with self.assertRaises(PolicyDenied):ControlService(self.config)

    def test_same_tenant_members_share_existing_budget_without_reset(self):
        self.config['principals'][1].update(tenant_id='team-a',scope='budget-a')
        service=ControlService(self.config)
        a=self.begin(service);b=self.begin(service,'bob','task-b')
        first=service.operate('alice',{'operation_id':'reserve','action':'reserve','run_id':a['run_id'],'data':{'tokens':80,'request_id':'request-a'}})
        second=service.operate('bob',{'operation_id':'reserve','action':'reserve','run_id':b['run_id'],'data':{'tokens':21,'request_id':'request-b'}})
        self.assertTrue(first['ok']);self.assertEqual(second['error_type'],'BudgetExceeded')

    def test_restart_cannot_reassign_principal_tenant(self):
        ControlService(self.config)
        self.config['principals'][0]['tenant_id']='other-team'
        with self.assertRaises(PolicyDenied):ControlService(self.config)

    def test_removed_member_does_not_release_task_ownership(self):
        ControlService(self.config)
        self.config['principals']=self.config['principals'][1:]
        self.config['principals'][0]['task_id']='task-a'
        with self.assertRaises(PolicyDenied):ControlService(self.config)

    def test_legacy_mode_compatible_but_not_silently_promoted(self):
        legacy=copy.deepcopy(self.config)
        for principal in legacy['principals']:principal.pop('tenant_id')
        service=ControlService(legacy)
        self.assertNotIn('tenant_id',self.begin(service))
        with self.assertRaises(PolicyDenied):ControlService(self.config)

    def test_pre_registry_unlabelled_budget_requires_migration(self):
        store=ControlStore(self.config['path'])
        store.begin({'path':self.config['path'],'scope':'budget-a','max_tokens':100,'max_model_calls':10},'old-run','old-input')
        with self.assertRaises(PolicyDenied):ControlService(self.config)

    def test_caller_cannot_choose_tenant_in_begin_payload(self):
        service=ControlService(self.config)
        response=service.operate('alice',{'operation_id':'spoof','action':'begin','data':{'task_id':'task-a',
            'identity':'fixture','wallclock_seconds':30,'tenant_id':'team-b'}})
        self.assertFalse(response['ok']);self.assertEqual(response['error_type'],'ValueError')

    def test_legacy_shared_task_configuration_remains_compatible(self):
        for principal in self.config['principals']:principal.pop('tenant_id')
        self.config['principals'][1]['task_id']='task-a'
        service=ControlService(self.config)
        self.assertNotEqual(self.begin(service)['run_id'],self.begin(service,'bob','task-a')['run_id'])

    def test_new_member_can_join_used_scope_of_same_explicit_tenant(self):
        original=copy.deepcopy(self.config);original['principals']=original['principals'][:1]
        self.begin(ControlService(original))
        self.config['principals'][1].update(tenant_id='team-a',scope='budget-a')
        result=self.begin(ControlService(self.config),'bob','task-b')
        self.assertEqual(result['tenant_id'],'team-a')

    def test_remote_session_keeps_authenticated_tenant_context(self):
        service=ControlService(self.config);server=make_server(service)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            remote=RemoteSession.begin({'endpoint':'http://127.0.0.1:'+str(server.server_address[1]),
                'token_env':'KEEL_TENANT_A','task_id':'task-a','timeout_seconds':2},'fixture',30)
            self.assertEqual(remote.config['tenant_id'],'team-a')
        finally:
            server.shutdown();thread.join(timeout=3);server.server_close()
