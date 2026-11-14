import json
from contextlib import ExitStack
import subprocess
import time
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

from keel.core import Budget, BudgetExceeded, Ledger, Limits, ModelError, PolicyDenied, Trace
from keel.governance import ControlStore, GovernedModel, GovernanceUnavailable, govern_model, validate_config
from keel.gateway import ToolGateway
from keel.models import Reply
from keel.runtime import run
from keel.workspace import Workspace


def reserve_worker(path, number):
    try:
        store=ControlStore(path)
        config={'path':path,'scope':'parallel','max_tokens':100,'max_model_calls':10}
        session=store.begin(config,'worker-'+str(number),'frozen-input')
        session.reserve(40)
        print('reserved',flush=True)
    except BudgetExceeded:
        print('denied',flush=True)
    except BaseException as error:
        print(type(error).__name__+': '+str(error),flush=True)


class GovernanceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.repo=self.root/'repo';self.repo.mkdir()
        (self.repo/'app.py').write_text('VERSION = 1\n',encoding='utf-8')
        self.config={'path':str(self.root/'control.sqlite'),'scope':'tenant/budget-1',
                     'max_tokens':20000,'max_model_calls':20}
        self.store=ControlStore(self.config['path'])

    def session(self, name='run-1', **changes):
        return self.store.begin({**self.config,**changes},name,'input-hash')

    def test_reservation_settlement_reopen_and_duplicate_id(self):
        s=self.session()
        request=s.reserve(100,request_id='provider-request')
        s.settle(request,30)
        s.settle(request,30)
        self.assertEqual(s.report()['spent_tokens'],30)
        self.assertEqual(s.report()['reserved_or_unknown_tokens'],0)
        with self.assertRaises(PolicyDenied):s.settle(request,31)
        with self.assertRaises(PolicyDenied):s.reserve(100,request_id=request)
        reopened=ControlStore(self.config['path'])
        self.assertEqual([e['kind'] for e in reopened.events('run-1')],['run_started','model_intent','model_outcome'])

    def test_unknown_usage_remains_reserved_and_can_be_reconciled(self):
        s=self.session(max_tokens=100)
        request=s.reserve(80)
        s.settle(request,None,outcome='connection_reset')
        with self.assertRaises(BudgetExceeded):s.reserve(21)
        s.settle(request,20,outcome='provider_usage_reconciled')
        self.assertEqual(s.report()['spent_tokens'],20)
        self.assertEqual(s.report()['reserved_or_unknown_tokens'],0)

    def test_process_crash_preserves_unknown_work_on_reopen(self):
        code='''import os,sys
from keel.governance import ControlStore
cfg={'path':sys.argv[1],'scope':'crashed','max_tokens':100,'max_model_calls':2,'lease_seconds':10}
s=ControlStore(sys.argv[1],clock=lambda:100).begin(cfg,'crashed-run','frozen-input')
s.reserve(80,request_id='request-before-crash')
os._exit(19)
'''
        result=subprocess.run([sys.executable,'-c',code,str(self.store.path)],timeout=10)
        self.assertEqual(result.returncode,19)
        reopened=ControlStore(self.store.path,clock=lambda:111)
        self.assertEqual(reopened.reconcile_expired(),['crashed-run'])
        snapshot=reopened.inspect(scope='crashed',run_id='crashed-run')
        self.assertEqual(snapshot['run']['status'],'unreachable')
        self.assertEqual(snapshot['scope']['held'],80)
        self.assertEqual(snapshot['scope']['calls'],1)
        self.assertEqual(snapshot['events'][-1]['kind'],'lease_expired')

    def test_readonly_inspector_paginates_and_rejects_foreign_scope(self):
        from examples.inspect_governance import inspect
        self.session().event('observed',{'fact':'reference only'})
        result=inspect(self.store.path,scope=self.config['scope'],run_id='run-1',limit=1)
        self.assertEqual(len(result['events']),1)
        next_page=inspect(self.store.path,scope=self.config['scope'],run_id='run-1',after=result['next_after'])
        self.assertEqual(next_page['events'][0]['kind'],'observed')
        self.session('other-run',scope='other')
        with self.assertRaises(PolicyDenied):inspect(self.store.path,scope='other',run_id='run-1')

    def test_limits_and_policy_cannot_be_reset_by_second_worker(self):
        s=self.session(max_tokens=100,max_model_calls=1)
        s.settle(s.reserve(20),5)
        second=self.session('run-2',max_tokens=100,max_model_calls=1)
        with self.assertRaises(BudgetExceeded):second.reserve(1)
        with self.assertRaises(PolicyDenied):self.session('run-3',max_tokens=200)
        with self.assertRaises(PolicyDenied):self.session('run-4',denied_tools=['search_code'])

    def test_expired_lease_blocks_old_writer_without_replay_or_budget_release(self):
        clock=[100.0];self.store=ControlStore(self.config['path'],clock=lambda:clock[0])
        s=self.session(lease_seconds=10)
        request=s.reserve(80)
        clock[0]=111.0
        self.assertEqual(self.store.reconcile_expired(),['run-1'])
        self.assertEqual(s.report()['status'],'unreachable')
        self.assertEqual(s.report()['reserved_or_unknown_tokens'],80)
        with self.assertRaises(PolicyDenied):s.event('write_intent',{})
        with self.assertRaises(PolicyDenied):s.finish('passed')
        s.settle(request,15)  # Late provider accounting, not execution permission.
        self.assertEqual(s.report()['spent_tokens'],15)
        self.assertEqual(s.report()['status'],'unreachable')

    def test_model_wrapper_no_retry_on_unknown_transport(self):
        class Provider:
            calls=0
            def complete(self,*args,**kwargs):
                self.calls+=1
                raise ModelError('transport unavailable')
        provider=Provider();s=self.session();model=GovernedModel(provider,s)
        with self.assertRaises(ModelError):model.complete([],timeout=2,max_output=20)
        self.assertEqual(provider.calls,1)
        self.assertGreater(s.report()['reserved_or_unknown_tokens'],0)

    def test_transport_retry_must_reserve_again_before_provider_dispatch(self):
        from keel.campaign_reporting import FrozenModel
        from keel.core import ModelTransportError
        class Provider:
            calls=0
            def complete(self,*args,**kwargs):
                self.calls+=1
                raise ModelTransportError('connection reset')
        provider=Provider();s=self.session(max_model_calls=1)
        frozen=FrozenModel(provider,lambda:None,transport_retries=1)
        budget=Budget(Limits(max_tokens=20000));budget.allow_model(100,20)
        frozen.bind_budget(budget)
        model=govern_model(frozen,s)
        with patch('keel.model_transport.time.sleep'):
            with self.assertRaises(BudgetExceeded):model.complete([],timeout=10,max_output=20)
        self.assertEqual(provider.calls,1)
        self.assertEqual(s.report()['model_calls'],1)
        self.assertGreater(s.report()['reserved_or_unknown_tokens'],0)

    def test_invalid_json_keeps_cost_and_records_rejection(self):
        class Provider:
            def complete(self,*args,**kwargs):return Reply('not json',7)
        s=self.session();model=GovernedModel(Provider(),s)
        with self.assertRaises(ModelError) as failure:
            model.complete_json([],schema={'type':'object'},timeout=2,max_output=20)
        self.assertEqual(failure.exception.tokens,7)
        self.assertEqual(s.report()['spent_tokens'],7)
        self.assertIn('model_format_rejected',[r['kind'] for r in self.store.events('run-1')])

    def test_required_audit_failure_prevents_provider_call(self):
        class Provider:
            def complete(self,*args,**kwargs):raise AssertionError('must not dispatch')
        s=self.session()
        with patch.object(s,'reserve',side_effect=sqlite3.OperationalError('disk full')):
            with self.assertRaises(sqlite3.OperationalError):
                GovernedModel(Provider(),s).complete([],timeout=2,max_output=20)

    def workspace(self, denied):
        ledger=Ledger(self.root/'ledger.sqlite');self.addCleanup(ledger.close)
        ws=Workspace(self.repo,Budget(Limits()),ledger,Trace(self.root/'trace.jsonl'))
        ws.governance=self.session(denied_tools=denied)
        return ws

    def test_forbidden_search_never_reaches_tool_implementation(self):
        ws=self.workspace(['search_code'])
        with patch.object(ws,'search',side_effect=AssertionError('must not search')):
            with self.assertRaises(PolicyDenied):ToolGateway('scout',ws).call('search_code',{'query':'VERSION'})
        self.assertEqual(self.store.events('run-1')[-1]['kind'],'tool_denied')

    def test_host_edit_also_obeys_policy_without_gateway(self):
        ws=self.workspace(['replace'])
        with self.assertRaises(PolicyDenied):ws.replace('app.py','VERSION = 1','VERSION = 2')
        self.assertEqual((self.repo/'app.py').read_text(),'VERSION = 1\n')

    def test_explicit_host_search_cannot_bypass_denial(self):
        ws=self.workspace(['search_code'])
        with self.assertRaises(PolicyDenied):ws.search('VERSION')

    def test_audit_failure_prevents_gateway_tool_call(self):
        ws=self.workspace([])
        with patch.object(ws.governance,'tool_started',side_effect=OSError('required audit unavailable')):
            with patch.object(ws,'read',side_effect=AssertionError('must not read')):
                with self.assertRaises(OSError):ToolGateway('scout',ws).call('read_file',{'path':'app.py'})

    def test_runtime_explicit_writes_and_verification_are_persisted(self):
        config={'goal':'Upgrade version','governance':self.config,
                'acceptance':[[sys.executable,'-c','import app; assert app.VERSION == 2']],
                'work_items':[{'id':'upgrade','edits':[{'path':'app.py','old':'VERSION = 1','new':'VERSION = 2'}]}]}
        result=run(config,self.repo,self.repo/'.keel'/'run')
        self.assertEqual(result['status'],'passed')
        self.assertEqual(result['governance']['status'],'passed')
        kinds=[e['kind'] for e in self.store.events(result['governance']['run_id'])]
        for name in ['write_intent','write_completed','verification_intent','verification_outcome','run_finished']:
            self.assertIn(name,kinds)

    def test_runtime_model_and_gateway_use_same_control_session(self):
        from tests.test_agents import ScriptedModel,plan
        model=ScriptedModel([{'final':{'files':['app.py'],'summary':'Version is old'}},plan(),
            {'tool':'replace','arguments':{'path':'app.py','old':'VERSION = 1','new':'VERSION = 2'}},{'final':'Updated'}])
        config={'goal':'Upgrade','mode':'agent','governance':self.config,
                'acceptance':[[sys.executable,'-c','import app; assert app.VERSION == 2']]}
        result=run(config,self.repo,self.repo/'.keel'/'agent',model=model)
        self.assertEqual(result['status'],'passed',result['failure'])
        self.assertEqual(result['governance']['model_calls'],4)
        self.assertEqual(result['governance']['spent_tokens'],400)
        kinds=[e['kind'] for e in self.store.events(result['governance']['run_id'])]
        self.assertIn('model_intent',kinds);self.assertIn('tool_intent',kinds)

    def test_database_cannot_be_in_agent_repository(self):
        config={'goal':'Inspect','governance':{**self.config,'path':str(self.repo/'control.sqlite')},
                'acceptance':[[sys.executable,'-c','pass']]}
        with self.assertRaises(ValueError):run(config,self.repo,self.repo/'.keel'/'unsafe')

    def test_required_final_record_failure_cannot_report_pass(self):
        from keel.governance import Session
        config={'goal':'Inspect','governance':self.config,'acceptance':[[sys.executable,'-c','pass']]}
        with patch.object(Session,'finish',side_effect=GovernanceUnavailable('control store unavailable')):
            result=run(config,self.repo,self.repo/'.keel'/'lost-control')
        self.assertEqual(result['status'],'failed')
        self.assertEqual(result['failure']['category'],'governance_unavailable')
        self.assertEqual(json.loads((self.repo/'.keel/lost-control/result.json').read_text())['status'],'failed')

    def test_parallel_processes_cannot_overreserve(self):
        # Real concurrent OS processes; files avoid dependence on Windows named
        # pipe permissions required by multiprocessing.Queue in restricted hosts.
        workers=[];paths=[];deadline=time.monotonic()+20
        with ExitStack() as stack:
            try:
                for number in range(6):
                    path=self.root/f'worker-{number}.log';paths.append(path)
                    stream=stack.enter_context(path.open('wb'))
                    workers.append(subprocess.Popen([sys.executable,'-c',
                        'import sys; from tests.test_governance import reserve_worker; reserve_worker(sys.argv[1],int(sys.argv[2]))',
                        str(self.store.path),str(number)],stdout=stream,stderr=subprocess.STDOUT))
                for worker in workers:
                    self.assertEqual(worker.wait(timeout=max(.1,deadline-time.monotonic())),0)
            finally:
                for worker in workers:
                    if worker.poll() is None:worker.kill();worker.wait(timeout=5)
        outcomes=[path.read_text().strip() for path in paths]
        self.assertEqual(outcomes.count('reserved'),2,outcomes)
        self.assertEqual(outcomes.count('denied'),4,outcomes)

    def test_config_rejects_unknown_fields_and_bad_limits(self):
        for change in [{'max_tokens':True},{'lease_seconds':float('inf')},{'denied_tools':'search_code'},{'remote_url':'http://example'}]:
            with self.assertRaises(ValueError):validate_config({**self.config,**change})


if __name__=='__main__':unittest.main()
