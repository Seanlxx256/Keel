from contextlib import ExitStack
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import uuid

from keel.control_service import ControlService, make_server
from keel.core import BudgetExceeded, ModelError, PolicyDenied
from keel.governance import GovernedModel, GovernanceUnavailable
from keel.models import Reply
from keel.remote_governance import RemoteSession, validate_remote_config
from keel.runtime import run


TOOLS={'scout':['read_file','search_code'],'planner':['read_file'],
       'implementer':['read_file','replace']}


def worker(endpoint,task_id,mode):
    session=RemoteSession.begin({'endpoint':endpoint,'token_env':'KEEL_CONTROL_TEST_TOKEN','task_id':task_id,
        'timeout_seconds':2},'fixed-worker-input',10)
    try:
        request=session.reserve(40)
        if mode=='crash':os._exit(19)
        print(json.dumps({'status':'reserved','run_id':session.run_id,'request_id':request}),flush=True)
    except BudgetExceeded:
        print(json.dumps({'status':'denied','run_id':session.run_id}),flush=True)


class ControlServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.token_a='a'*48;self.token_b='b'*48
        self.env=patch.dict(os.environ,{'KEEL_CONTROL_A':self.token_a,'KEEL_CONTROL_B':self.token_b})
        self.env.start();self.addCleanup(self.env.stop)
        self.config={'path':str(self.root/'server/control.sqlite'),
            'scopes':{'scope-a':{'max_tokens':40000,'max_model_calls':20,'lease_seconds':1200,'denied_tools':['search_code']},
                      'scope-b':{'max_tokens':40000,'max_model_calls':20,'lease_seconds':1200}},
            'principals':[{'id':'worker-a','token_env':'KEEL_CONTROL_A','scope':'scope-a','task_id':'task-a','tools':TOOLS},
                          {'id':'worker-b','token_env':'KEEL_CONTROL_B','scope':'scope-b','task_id':'task-b','tools':TOOLS}]}
        self.service=ControlService(self.config)
        self.server=make_server(self.service)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.addCleanup(self.stop)
        self.endpoint='http://127.0.0.1:'+str(self.server.server_address[1])

    def stop(self):
        if self.thread.is_alive():self.server.shutdown();self.thread.join(timeout=5)
        self.server.server_close()

    def client(self,which='a'):
        return RemoteSession.begin({'endpoint':self.endpoint,'token_env':'KEEL_CONTROL_'+which.upper(),
            'task_id':'task-'+which,'timeout_seconds':.5},'frozen-input',30)

    def test_authenticated_client_server_owns_task_policy_and_storage(self):
        session=self.client()
        self.assertEqual(session.config['scope'],'scope-a')
        with self.assertRaises(PolicyDenied):session.tool_started('scout','search_code','forbidden-search')
        session.tool_started('scout','read_file','authorized-read')
        events=session.inspect()['events']
        self.assertIn('tool_denied',[e['kind'] for e in events])
        with self.service.store.transaction() as db:
            owner=db.execute('SELECT owner FROM governance_runs WHERE id=?',(session.run_id,)).fetchone()[0]
        self.assertNotIn(owner,json.dumps(events))
        self.assertNotIn('path',session.report())
        self.assertFalse(hasattr(session,'store'))

    def test_foreign_task_run_and_role_are_denied(self):
        a=self.client();b=self.client('b')
        with self.assertRaises(PolicyDenied):
            RemoteSession.begin({'endpoint':self.endpoint,'token_env':'KEEL_CONTROL_A','task_id':'task-b'},'input',30)
        own=b.run_id;b.run_id=a.run_id
        with self.assertRaises(PolicyDenied):b.report()
        b.run_id=own
        with self.assertRaises(PolicyDenied):a.tool_started('scout','replace','role-escalation')
        with self.assertRaises(ValueError):a._rpc('reserve',{'tokens':1,'request_id':'x','max_tokens':100000000})

    def test_bad_credential_is_denied_without_retry(self):
        with patch.dict(os.environ,{'KEEL_CONTROL_A':'wrong'*10}):
            with self.assertRaises(PolicyDenied):self.client()

    def test_untrusted_usage_report_cannot_release_quota(self):
        session=self.client();request=session.reserve(100)
        session.settle(request,0)
        report=session.report()
        self.assertEqual(report['reserved_or_unknown_tokens'],100)
        self.assertEqual(report['spent_tokens'],0)
        event=session.inspect()['events'][-1]
        self.assertEqual(event['kind'],'worker_usage_report')
        self.assertFalse(event['payload']['quota_released'])

    def test_trusted_accounting_requires_explicit_server_grant(self):
        self.service.principals['worker-a']['trusted_usage']=True
        session=self.client();request=session.reserve(100);session.settle(request,7)
        self.assertEqual(session.report()['spent_tokens'],7)
        self.assertEqual(session.report()['reserved_or_unknown_tokens'],0)

    def test_bad_json_is_recorded_without_claiming_independent_validation(self):
        class Provider:
            def complete(self,*args,**kwargs):return Reply('broken json',7)
        session=self.client()
        with self.assertRaises(ModelError):
            GovernedModel(Provider(),session).complete_json([],schema={'type':'object'},timeout=1,max_output=20)
        events=session.inspect()['events']
        self.assertTrue(any(e['kind']=='worker_observation' and e['payload']['kind']=='model_format_rejected' for e in events))
        self.assertGreater(session.report()['reserved_or_unknown_tokens'],0)

    def test_lost_response_reconciles_same_reservation_without_redispatch(self):
        session=self.client();original=session._send
        def lose_response(operation):
            original(operation)
            raise GovernanceUnavailable('simulated lost response after commit')
        with patch.object(session,'_send',side_effect=lose_response):
            with self.assertRaises(GovernanceUnavailable):session.reserve(100)
        self.assertIsNotNone(session.pending)
        with self.assertRaises(GovernanceUnavailable):session.reserve(100)
        response=session.reconcile_pending()
        self.assertIn('request_id',response)
        report=session.report()
        self.assertEqual(report['model_calls'],1)
        self.assertEqual(report['reserved_or_unknown_tokens'],100)

    def test_changed_parameters_reusing_operation_id_are_denied(self):
        session=self.client()
        operation={'operation_id':'fixed-operation','run_id':session.run_id,'action':'reserve',
                   'data':{'tokens':100,'request_id':'fixed-request'}}
        first=session._send(operation)
        self.assertEqual(first,session._send(operation))
        operation['data']['tokens']=101
        with self.assertRaises(PolicyDenied):session._send(operation)
        self.assertEqual(session.report()['model_calls'],1)

    def test_one_client_serializes_concurrent_operations_without_losing_pending_ids(self):
        session=self.client();outcomes=[]
        def reserve():
            try:outcomes.append(session.reserve(40))
            except BaseException as error:outcomes.append(error)
        threads=[threading.Thread(target=reserve) for _ in range(2)]
        for thread in threads:thread.start()
        for thread in threads:thread.join(timeout=5)
        self.assertTrue(all(not thread.is_alive() for thread in threads))
        self.assertEqual(len(outcomes),2)
        self.assertTrue(all(isinstance(value,str) for value in outcomes),outcomes)
        self.assertEqual(len(set(outcomes)),2)
        self.assertEqual(session.report()['model_calls'],2)

    def test_operation_and_response_rollback_together_on_storage_failure(self):
        session=self.client()
        with patch.object(self.service.store,'_event',side_effect=GovernanceUnavailable('disk full')):
            with self.assertRaises(GovernanceUnavailable):session.reserve(100)
        self.assertEqual(self.service.store.inspect(scope='scope-a')['scope']['calls'],0)
        session.reconcile_pending()
        self.assertEqual(session.report()['model_calls'],1)

    def test_service_outage_prevents_provider_call(self):
        class Provider:
            def complete(self,*args,**kwargs):raise AssertionError('provider must not run')
        session=self.client();self.stop()
        with self.assertRaises(GovernanceUnavailable):GovernedModel(Provider(),session).complete([],timeout=1,max_output=20)
        self.assertIsNotNone(session.pending)

    def test_worker_observation_cannot_impersonate_authoritative_event(self):
        session=self.client()
        with self.assertRaises(PolicyDenied):session.event('model_intent',{'reserved_tokens':0})
        session.event('phase_started',{'role':'scout'})
        event=session.inspect()['events'][-1]
        self.assertEqual(event['kind'],'worker_observation')
        self.assertIn('not independent',event['payload']['authority'])

    def test_restart_preserves_bindings_and_idempotency(self):
        session=self.client();request=session.reserve(100)
        self.stop()
        self.service=ControlService(self.config)
        self.server=make_server(self.service)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        session.location='http://127.0.0.1:'+str(self.server.server_address[1])
        session.settle(request,None)
        self.assertEqual(session.report()['reserved_or_unknown_tokens'],100)

    def test_expired_run_does_not_reissue_cached_permission(self):
        session=self.client()
        operation={'operation_id':'permission','run_id':session.run_id,'action':'tool_started',
                   'data':{'role':'scout','tool':'read_file','action_id':'read-1'}}
        self.assertTrue(session._send(operation)['authorized'])
        self.service.store.clock=lambda:time.time()+1300
        self.service.store.reconcile_expired()
        with self.assertRaises(PolicyDenied):session._send(operation)

    def test_real_runtime_uses_remote_control_without_database_path(self):
        repo=self.root/'repo';repo.mkdir();(repo/'app.py').write_text('VERSION = 1\n')
        config={'goal':'Upgrade','budget':{'max_wallclock':30},'governance':{'endpoint':self.endpoint,
            'token_env':'KEEL_CONTROL_A','task_id':'task-a','timeout_seconds':2},
            'acceptance':[[sys.executable,'-c','import app; assert app.VERSION == 2']],
            'work_items':[{'id':'upgrade','edits':[{'path':'app.py','old':'VERSION = 1','new':'VERSION = 2'}]}]}
        result=run(config,repo,self.root/'runtime')
        self.assertEqual(result['status'],'passed',result['failure'])
        self.assertEqual(result['governance']['transport'],'authenticated_control_service')
        self.assertNotIn(str(self.service.store.path),json.dumps(config))
        events=self.service.store.inspect(scope='scope-a',run_id=result['governance']['run_id'])['events']
        self.assertTrue(any(e['kind']=='worker_observation' and e['payload']['kind']=='verification_outcome' for e in events))

    def test_remote_agent_runtime_uses_model_and_tool_gate_together(self):
        from tests.test_agents import ScriptedModel,plan
        repo=self.root/'agent-repo';repo.mkdir();(repo/'app.py').write_text('VERSION = 1\n')
        model=ScriptedModel([{'final':{'files':['app.py'],'summary':'Upgrade constant'}},plan(),
            {'tool':'replace','arguments':{'path':'app.py','old':'VERSION = 1','new':'VERSION = 2'}},{'final':'Updated'}])
        config={'goal':'Upgrade','mode':'agent','budget':{'max_wallclock':30},
                'governance':{'endpoint':self.endpoint,'token_env':'KEEL_CONTROL_A','task_id':'task-a'},
                'acceptance':[[sys.executable,'-c','import app; assert app.VERSION == 2']]}
        result=run(config,repo,self.root/'agent-runtime',model=model)
        self.assertEqual(result['status'],'passed',result['failure'])
        self.assertEqual(result['governance']['model_calls'],4)
        self.assertEqual(result['governance']['spent_tokens'],0)
        self.assertGreater(result['governance']['reserved_or_unknown_tokens'],400)

    def test_real_worker_processes_compete_for_shared_quota_and_crash(self):
        self.stop()
        config=json.loads(json.dumps(self.config))
        config['scopes']['scope-a']['max_tokens']=70
        config['principals'][1]['scope']='scope-a'
        # New scope identity and fresh database preserve earlier policies.
        config['path']=str(self.root/'concurrency/control.sqlite')
        self.service=ControlService(config)
        self.server=make_server(self.service)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        endpoint='http://127.0.0.1:'+str(self.server.server_address[1])
        processes=[];paths=[];deadline=time.monotonic()+20
        with ExitStack() as stack:
            try:
                for i in range(2):
                    path=self.root/f'worker-{i}.log';paths.append(path)
                    stream=stack.enter_context(path.open('wb'))
                    env={**os.environ,'KEEL_CONTROL_TEST_TOKEN':self.token_a if i==0 else self.token_b}
                    processes.append(subprocess.Popen([sys.executable,'-c',
                        'import sys; from tests.test_control_service import worker; worker(*sys.argv[1:])',
                        endpoint,'task-a' if i==0 else 'task-b','normal'],env=env,stdout=stream,stderr=subprocess.STDOUT))
                for process in processes:self.assertEqual(process.wait(timeout=max(.1,deadline-time.monotonic())),0)
            finally:
                for process in processes:
                    if process.poll() is None:process.kill();process.wait(timeout=5)
        results=[json.loads(path.read_text()) for path in paths]
        self.assertEqual(sorted(r['status'] for r in results),['denied','reserved'])
        self.assertEqual(self.service.store.inspect(scope='scope-a')['scope']['held'],40)
        # Abrupt real process exit after its durable request, separate scope.
        env={**os.environ,'KEEL_CONTROL_TEST_TOKEN':self.token_a}
        # The first grant has insufficient remaining tokens: use a fresh service
        # scope for the crash, never increase the established quota in place.
        self.stop();config['path']=str(self.root/'crash/control.sqlite')
        self.service=ControlService(config)
        self.server=make_server(self.service)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        endpoint='http://127.0.0.1:'+str(self.server.server_address[1])
        result=subprocess.run([sys.executable,'-c',
            'import sys; from tests.test_control_service import worker; worker(*sys.argv[1:])',endpoint,'task-a','crash'],env=env,timeout=10)
        self.assertEqual(result.returncode,19)
        self.service.store.clock=lambda:time.time()+1300
        expired=self.service.store.reconcile_expired()
        self.assertEqual(len(expired),1)
        state=self.service.store.inspect(scope='scope-a',run_id=expired[0])
        self.assertEqual(state['run']['status'],'unreachable')
        self.assertEqual(state['scope']['held'],40)

    def test_transport_validation_and_secret_not_persisted(self):
        for config in [{'endpoint':'http://example.com','token_env':'KEY','task_id':'t'},
                       {'endpoint':self.endpoint,'token_env':'KEY','task_id':'t','max_tokens':100000}]:
            with self.assertRaises(ValueError):validate_remote_config(config)
        with self.assertRaises(ValueError):make_server(self.service,host='0.0.0.0')
        self.client().event('phase_started',{'role':'scout'})
        raw=self.service.store.path.read_bytes()
        self.assertNotIn(self.token_a.encode(),raw);self.assertNotIn(self.token_b.encode(),raw)


if __name__=='__main__':unittest.main()
