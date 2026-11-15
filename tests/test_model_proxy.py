"""Controller model proxy contracts. Providers are fixtures, never paid calls."""
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from keel.control_service import ControlService
from keel.core import ModelError, PolicyDenied
from keel.governance import GovernanceUnavailable, govern_model
from keel.model_proxy import ProxyModel
from keel.models import Reply, from_config
from keel.remote_governance import RemoteSession


class ModelProxyTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.config={'path':str(Path(temp.name)/'control.sqlite'),
            'scopes':{'scope':{'max_tokens':10000,'max_model_calls':10,'lease_seconds':900}},
            'principals':[{'id':'worker','task_id':'task','scope':'scope','token_env':'KEEL_PROXY_TEST',
                           'tools':{},'models':['repair']}],
            'model_proxy':{'models':{'repair':{'provider':'ollama','name':'fixture'}},'max_output':1000}}
        self.provider=Mock();self.provider.complete.return_value=Reply('answer',7)
        self.provider.complete_json.return_value=Reply('{"ok":true}',9)
        env=patch.dict(os.environ,{'KEEL_PROXY_TEST':'t'*48});env.start();self.addCleanup(env.stop)
        factory=patch('keel.models.from_config',return_value=self.provider)
        with factory:self.service=ControlService(self.config)
        self.run_id=self.service.operate('worker',{'operation_id':'begin','action':'begin',
            'data':{'task_id':'task','identity':'input','wallclock_seconds':100}})['result']['run_id']

    def request(self,operation_id='call'):
        return {'operation_id':operation_id,'action':'model_complete','run_id':self.run_id,
                'data':{'alias':'repair','messages':[{'role':'user','content':'hello'}],
                        'schema':None,'max_output':100,'timeout':10}}

    def report(self):
        return self.service.operate('worker',{'operation_id':'report','action':'report','run_id':self.run_id,'data':{}})['result']

    def test_completed_duplicate_returns_same_result_without_second_provider_call(self):
        first=self.service.operate('worker',self.request())
        self.assertEqual(first,self.service.operate('worker',self.request()))
        self.provider.complete.assert_called_once()
        self.assertEqual(self.report()['spent_tokens'],7)
        self.assertEqual(self.report()['model_calls'],1)

    def test_reused_id_changed_prompt_is_denied(self):
        self.service.operate('worker',self.request());changed=self.request()
        changed['data']['messages'][0]['content']='different'
        with self.assertRaises(PolicyDenied):self.service.operate('worker',changed)
        self.provider.complete.assert_called_once()

    def test_unknown_inflight_never_replays_after_crash_boundary(self):
        class SimulatedProcessLoss(BaseException):pass
        self.provider.complete.side_effect=SimulatedProcessLoss()
        with self.assertRaises(SimulatedProcessLoss):self.service.operate('worker',self.request())
        with self.assertRaises(GovernanceUnavailable):self.service.operate('worker',self.request())
        self.provider.complete.assert_called_once()
        self.assertGreater(self.report()['reserved_or_unknown_tokens'],0)

    def test_provider_error_is_cached_and_sensitive_message_not_relayed(self):
        self.provider.complete.side_effect=ModelError('secret-value-do-not-relay',tokens=4)
        result=self.service.operate('worker',self.request())
        self.assertFalse(result['ok']);self.assertNotIn('secret-value',json.dumps(result))
        self.assertEqual(result,self.service.operate('worker',self.request()))
        self.assertEqual(self.report()['spent_tokens'],4)

    def test_alias_scope_rejected_before_provider(self):
        request=self.request();request['data']['alias']='ungranted'
        with self.assertRaises(PolicyDenied):self.service.operate('worker',request)
        self.provider.complete.assert_not_called()

    def test_provider_executes_outside_database_transaction(self):
        def reply(*args,**kwargs):
            self.assertIsNone(getattr(self.service.store._transactions,'connection',None))
            return Reply('answer',7)
        self.provider.complete.side_effect=reply
        self.assertTrue(self.service.operate('worker',self.request())['ok'])

    def test_bad_json_retains_actual_usage_and_is_not_retried(self):
        self.provider.complete_json.return_value=Reply('invalid json',9)
        request=self.request();request['data']['schema']={'type':'object'}
        self.assertFalse(self.service.operate('worker',request)['ok'])
        self.assertEqual(self.report()['spent_tokens'],9)
        self.provider.complete_json.assert_called_once()

    def test_missing_usage_does_not_release_reservation(self):
        self.provider.complete.return_value=Reply('answer',None)
        self.assertFalse(self.service.operate('worker',self.request())['ok'])
        self.assertGreater(self.report()['reserved_or_unknown_tokens'],0)

    def test_proxy_requires_remote_binding_and_does_not_double_reserve(self):
        proxy=from_config({'provider':'control-proxy','alias':'repair'})
        with self.assertRaises(PolicyDenied):proxy.complete([],timeout=1,max_output=10)
        remote=RemoteSession({'endpoint':'http://127.0.0.1:8788','token_env':'KEEL_PROXY_TEST','task_id':'task'})
        remote.run_id=self.run_id
        self.assertIs(govern_model(proxy,remote),proxy)
        with patch.object(remote,'_send',return_value={'content':'answer','tokens':7,'metadata':{}}):
            with patch.object(remote,'reserve') as reserve:
                self.assertEqual(proxy.complete([{'role':'user','content':'hi'}],timeout=1,max_output=10).tokens,7)
                reserve.assert_not_called()

    def test_server_policy_change_invalidates_existing_model_grant(self):
        changed=copy.deepcopy(self.config);changed['model_proxy']['max_output']=999
        with patch('keel.models.from_config',return_value=self.provider):second=ControlService(changed)
        with self.assertRaises(PolicyDenied):second.operate('worker',self.request())

    def test_proxy_only_principal_cannot_reserve_direct_calls_or_settle_usage(self):
        config=copy.deepcopy(self.config);config['principals'][0]['require_model_proxy']=True
        with patch('keel.models.from_config',return_value=self.provider):service=ControlService(config)
        run_id=service.operate('worker',{'operation_id':'new-begin','action':'begin',
            'data':{'task_id':'task','identity':'input','wallclock_seconds':100}})['result']['run_id']
        for action,data in [('reserve',{'tokens':100,'request_id':'direct'}),
                            ('settle',{'request_id':'direct','actual':0,'outcome':'completed'})]:
            response=service.operate('worker',{'operation_id':action,'action':action,'run_id':run_id,'data':data})
            self.assertFalse(response['ok'])
            self.assertEqual(response['error_type'],'PolicyDenied')


if __name__=='__main__':unittest.main()
