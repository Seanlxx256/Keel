import concurrent.futures
import copy
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from keel.control_service import ControlService
from keel.core import PolicyDenied
from keel.models import Reply


class TenantQuotaTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        env=patch.dict(os.environ,{'KEEL_QUOTA_A':'a'*48,'KEEL_QUOTA_B':'b'*48})
        env.start();self.addCleanup(env.stop)
        self.config={'path':str(Path(temp.name)/'control.sqlite'),
            'tenants':{'team':{'max_tokens':100,'max_model_calls':10}},
            'scopes':{scope:{'max_tokens':1000,'max_model_calls':20,'lease_seconds':300} for scope in ('pool-a','pool-b')},
            'principals':[{'id':who,'tenant_id':'team','token_env':'KEEL_QUOTA_'+who.upper(),
                'scope':'pool-'+who,'task_id':'task-'+who,'trusted_usage':True,'tools':{}} for who in ('a','b')]}
        self.counter=0

    def begin(self,service,who='a'):
        self.counter+=1
        return service.operate(who,{'operation_id':'begin-'+str(self.counter),'action':'begin',
            'data':{'task_id':'task-'+who,'identity':'fixture','wallclock_seconds':30}})['result']['run_id']

    def rpc(self,service,who,run,action,data):
        self.counter+=1
        if action=='settle':data={**data,'outcome':'fixture_accounting'}
        result=service.operate(who,{'operation_id':'op-'+str(self.counter),'action':action,'run_id':run,'data':data})
        if action=='settle':self.assertTrue(result['ok'],result)
        return result

    def reserve(self,service,who,run,tokens):
        return self.rpc(service,who,run,'reserve',{'tokens':tokens,'request_id':'request-'+str(self.counter+1)})

    def report(self,service,who,run):
        return self.rpc(service,who,run,'report',{})['result']

    def test_other_scope_cannot_bypass_aggregate_and_denial_has_no_partial_counters(self):
        service=ControlService(self.config);a=self.begin(service);b=self.begin(service,'b')
        self.assertTrue(self.reserve(service,'a',a,80)['ok'])
        denied=self.reserve(service,'b',b,30)
        self.assertEqual(denied['error_type'],'BudgetExceeded')
        report=self.report(service,'b',b)
        self.assertEqual(report['reserved_or_unknown_tokens'],0);self.assertEqual(report['model_calls'],0)
        self.assertEqual(report['tenant_budget']['reserved_or_unknown_tokens'],80)

    def test_unknown_holds_budget_and_late_known_usage_releases_only_reservation(self):
        service=ControlService(self.config);a=self.begin(service);b=self.begin(service,'b')
        request=self.reserve(service,'a',a,80)['result']['request_id']
        self.rpc(service,'a',a,'settle',{'request_id':request,'actual':None})
        self.assertFalse(self.reserve(service,'b',b,21)['ok'])
        self.rpc(service,'a',a,'settle',{'request_id':request,'actual':20})
        self.assertTrue(self.reserve(service,'b',b,80)['ok'])
        tenant=self.report(service,'b',b)['tenant_budget']
        self.assertEqual((tenant['spent_tokens'],tenant['reserved_or_unknown_tokens']),(20,80))

    def test_aggregate_call_cap_crosses_scopes_even_if_usage_is_zero(self):
        self.config['tenants']['team']['max_model_calls']=1
        service=ControlService(self.config);a=self.begin(service);b=self.begin(service,'b')
        request=self.reserve(service,'a',a,1)['result']['request_id']
        self.rpc(service,'a',a,'settle',{'request_id':request,'actual':0})
        self.assertFalse(self.reserve(service,'b',b,1)['ok'])

    def test_scope_limit_still_applies_without_mutating_aggregate(self):
        self.config['scopes']['pool-a']['max_tokens']=10
        service=ControlService(self.config);a=self.begin(service)
        self.assertFalse(self.reserve(service,'a',a,11)['ok'])
        self.assertEqual(self.report(service,'a',a)['tenant_budget']['model_calls'],0)

    def test_restart_preserves_usage_and_does_not_reset_limits(self):
        service=ControlService(self.config);a=self.begin(service)
        self.reserve(service,'a',a,80)
        restarted=ControlService(self.config);b=self.begin(restarted,'b')
        self.assertFalse(self.reserve(restarted,'b',b,21)['ok'])
        changed=copy.deepcopy(self.config);changed['tenants']['team']['max_tokens']=200
        with self.assertRaises(PolicyDenied):ControlService(changed)
        omitted=copy.deepcopy(self.config);omitted.pop('tenants')
        with self.assertRaises(PolicyDenied):ControlService(omitted)

    def test_oversized_actual_usage_is_recorded_and_blocks_future_admission(self):
        service=ControlService(self.config);a=self.begin(service);b=self.begin(service,'b')
        request=self.reserve(service,'a',a,10)['result']['request_id']
        self.rpc(service,'a',a,'settle',{'request_id':request,'actual':120})
        self.assertEqual(self.report(service,'a',a)['tenant_budget']['spent_tokens'],120)
        self.assertFalse(self.reserve(service,'b',b,1)['ok'])

    def test_enable_policy_counts_preexisting_bound_scope_usage(self):
        previous=copy.deepcopy(self.config);previous.pop('tenants')
        service=ControlService(previous);a=self.begin(service);self.reserve(service,'a',a,80)
        upgraded=ControlService(self.config);b=self.begin(upgraded,'b')
        self.assertFalse(self.reserve(upgraded,'b',b,21)['ok'])

    def test_concurrent_scope_requests_share_one_atomic_admission_limit(self):
        service=ControlService(self.config)
        runs=[(who,self.begin(service,who)) for who in ['a','b']*4]
        def invoke(index):
            who,run=runs[index]
            return service.operate(who,{'operation_id':'parallel-'+str(index),'action':'reserve','run_id':run,
                'data':{'tokens':40,'request_id':'parallel-request-'+str(index)}})
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:results=list(pool.map(invoke,range(8)))
        self.assertEqual(sum(value['ok'] for value in results),2)
        tenant=self.report(service,'a',runs[0][1])['tenant_budget']
        self.assertEqual((tenant['reserved_or_unknown_tokens'],tenant['model_calls']),(80,2))

    def test_untrusted_settlement_cannot_release_tenant_budget(self):
        self.config['principals'][0]['trusted_usage']=False
        service=ControlService(self.config);a=self.begin(service);b=self.begin(service,'b')
        request=self.reserve(service,'a',a,80)['result']['request_id']
        self.rpc(service,'a',a,'settle',{'request_id':request,'actual':0})
        self.assertFalse(self.reserve(service,'b',b,21)['ok'])

    def test_other_tenant_has_independent_aggregate(self):
        self.config['principals'][1]['tenant_id']='other-team'
        self.config['tenants']['other-team']={'max_tokens':100,'max_model_calls':10}
        service=ControlService(self.config);a=self.begin(service);b=self.begin(service,'b')
        self.assertTrue(self.reserve(service,'a',a,80)['ok'])
        self.assertTrue(self.reserve(service,'b',b,80)['ok'])
        self.assertEqual(self.report(service,'a',a)['tenant_budget']['reserved_or_unknown_tokens'],80)
        self.assertEqual(self.report(service,'b',b)['tenant_budget']['reserved_or_unknown_tokens'],80)

    def test_expired_run_does_not_release_aggregate_reservation(self):
        clock=[0]
        service=ControlService(self.config,clock=lambda:clock[0]);a=self.begin(service)
        self.reserve(service,'a',a,80);clock[0]=400
        service.store.reconcile_expired()
        report=self.report(service,'a',a)
        self.assertEqual(report['status'],'unreachable')
        self.assertEqual(report['tenant_budget']['reserved_or_unknown_tokens'],80)

    def test_model_proxy_checks_tenant_cap_before_second_provider_dispatch(self):
        self.config['tenants']['team']={'max_tokens':1000,'max_model_calls':1}
        self.config['model_proxy']={'models':{'repair':{'provider':'ollama','name':'fixture'}},'max_output':100}
        for principal in self.config['principals']:principal.update(models=['repair'],require_model_proxy=True)
        provider=Mock();provider.complete.return_value=Reply('fixture',7)
        with patch('keel.models.from_config',return_value=provider):service=ControlService(self.config)
        a=self.begin(service);b=self.begin(service,'b')
        data={'alias':'repair','messages':[{'role':'user','content':'fixture'}],'schema':None,'max_output':16,'timeout':2}
        self.assertTrue(self.rpc(service,'a',a,'model_complete',data)['ok'])
        denied=self.rpc(service,'b',b,'model_complete',data)
        self.assertEqual(denied['error_type'],'BudgetExceeded');provider.complete.assert_called_once()

    def test_invalid_tenant_policy_is_not_accepted(self):
        for policy in ({'max_tokens':True,'max_model_calls':1},{'max_tokens':100},
                       {'max_tokens':100,'max_model_calls':0}):
            with self.subTest(policy=policy):
                self.config['tenants']['team']=policy
                with self.assertRaises(ValueError):ControlService(self.config)
