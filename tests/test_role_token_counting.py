import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from keel.context_budget import estimate_input,offline_encoding
from keel.core import Budget,Limits,Ledger,Trace,PolicyDenied
from keel.workspace import Workspace
from keel.models import Reply
from keel.localization import select
from keel.recovery import RecoveryController,CRITIC_QUESTIONS
from keel.tokenizer_setup import export_encoding


class RoleTokenCountingTests(unittest.TestCase):
    def setUp(self):offline_encoding.cache_clear()
    def tearDown(self):offline_encoding.cache_clear()
    def policy(self,root):
        path=root/'encoding.json';path.write_text(json.dumps({'name':'fixture','pat_str':'.','mergeable_ranks':{},'special_tokens':{}}),encoding='utf-8')
        return {'model_context_tokens':10000,'max_input_tokens':4000,'safety_tokens':64,'max_request_bytes':50000,
                'local_tokenizer':str(path),'local_tokenizer_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
                'require_local_tokenizer':True,'recover_capacity':True}
    def tokenizer(self):return SimpleNamespace(Encoding=lambda **kwargs:SimpleNamespace(encode=lambda text,**options:list(range(12))))

    def test_required_missing_or_changed_encoding_never_silently_falls_back(self):
        with tempfile.TemporaryDirectory() as temp:
            policy=self.policy(Path(temp));policy['local_tokenizer_sha256']='0'*64
            with self.assertRaisesRegex(PolicyDenied,'Required offline tokenizer'):
                estimate_input([],{},policy)
            policy=self.policy(Path(temp))
            with patch.dict(sys.modules,{'tiktoken':None}),self.assertRaises(PolicyDenied):
                estimate_input([],{},policy)

    def test_encoding_construction_cached_but_changed_bytes_rechecked(self):
        with tempfile.TemporaryDirectory() as temp:
            policy=self.policy(Path(temp));calls=[]
            def factory(**kwargs):calls.append(kwargs);return SimpleNamespace(encode=lambda text,**opts:[1]*12)
            with patch.dict(sys.modules,{'tiktoken':SimpleNamespace(Encoding=factory)}):
                estimate_input([],{},policy);estimate_input([{'content':'new'}],{},policy)
                self.assertEqual(len(calls),1)
                Path(policy['local_tokenizer']).write_bytes(b'changed')
                with self.assertRaises(PolicyDenied):estimate_input([],{},policy)

    def test_scout_and_critic_share_actual_policy_and_budget_and_record_usage(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);policy=self.policy(root);ledger=Ledger(root/'ledger.sqlite')
            budget=Budget(Limits(max_tokens=1500,max_model_calls=2));ws=Workspace(root,budget,ledger,Trace(root/'trace.jsonl'))
            settings={'max_context_bytes':18000,'max_output':200,'critic_max_output':200,'proposal_context_policy':policy}
            class Model:
                calls=0
                def complete_json(self,messages,**kwargs):
                    self.calls+=1
                    required=kwargs['schema']['required']
                    value={'files':['app.py']} if required==['files'] else {'action':'replan',**{key:'unknown' for key in CRITIC_QUESTIONS}}
                    return Reply(json.dumps(value),20,{'prompt_tokens':12})
            model=Model()
            try:
                with patch.dict(sys.modules,{'tiktoken':self.tokenizer()}):
                    selected=select(model,ws,'goal',settings,stage='files',data={'paths':['app.py']},keys=('files',),instruction='Select files.')
                    decision=RecoveryController({'max_actions':2},ws).decide(model,'goal',[],[],settings)
                self.assertEqual(selected['files'],['app.py']);self.assertEqual(decision['action'],'replan')
                self.assertEqual(budget.model_calls,2);self.assertEqual(budget.tokens,40)
                rows=[json.loads(line) for line in (root/'trace.jsonl').read_text(encoding='utf-8').splitlines()]
                admitted=[r for r in rows if r['event']=='role_token_admitted']
                self.assertEqual({r['role'] for r in admitted},{'scout','critic'})
                self.assertTrue(all(r['estimator']=='offline_tiktoken' for r in admitted))
                self.assertEqual(len([r for r in rows if r['event']=='role_token_estimate_observed']),2)
            finally:ledger.close()

    def test_explicit_export_preserves_limits_and_generates_strict_hash_bound_policy(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);base={k:v for k,v in self.policy(root).items() if k not in ('local_tokenizer','local_tokenizer_sha256','require_local_tokenizer')}
            (root/'base.json').write_text(json.dumps(base),encoding='utf-8')
            (root/'model.json').write_text(json.dumps({'name':'fixture-model','api_key_env':'SECRET_NOT_READ'}),encoding='utf-8')
            encoder=SimpleNamespace(name='fixture',_pat_str='.',_mergeable_ranks={},_special_tokens={})
            fake=self.tokenizer();fake.encoding_for_model=lambda name:encoder
            with patch.dict(sys.modules,{'tiktoken':fake}),patch('keel.tokenizer_setup.importlib.metadata.version',return_value='fixture'):
                export_encoding(root/'model.json',root/'base.json',root)
                from keel.tokenizer_setup import verify_export
                self.assertEqual(verify_export(root)['estimator'],'offline_tiktoken')
            policy=json.loads((root/'policy.json').read_text(encoding='utf-8'))
            for key,value in base.items():self.assertEqual(policy[key],value)
            self.assertTrue(policy['require_local_tokenizer'])
            self.assertEqual(json.loads((root/'export.json').read_text(encoding='utf-8'))['provider_calls'],0)

    def test_preparation_stages_are_bounded_and_model_api_is_not_used(self):
        from keel.tokenizer_setup import prepare
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'model.json').write_text('{"name":"fixture"}',encoding='utf-8')
            (root/'base.json').write_text('{}',encoding='utf-8');calls=[]
            def run(runner,command,cwd,timeout):
                calls.append((command,timeout))
                return {'returncode':0,'timeout':False,'stdout':'ok','stderr':''}
            with patch('keel.tokenizer_setup.CommandRunner.run',new=run), \
                 patch('keel.tokenizer_setup.verify_export',return_value={'estimator':'offline_tiktoken'}):
                report=prepare(root/'model.json',root/'base.json',root/'output',install=True,
                               transcripts=[root/'model.json'])
            self.assertEqual([r['stage'] for r in report['stages']],['install','export','calibration'])
            self.assertTrue(all(0<seconds<=120 for _,seconds in calls))
            self.assertEqual(report['provider_calls'],0)
            self.assertEqual(calls[0][0][1:3],['-m','pip'])
            with self.assertRaises(FileExistsError):prepare(root/'model.json',root/'base.json',root/'output')

    def test_scout_tool_loop_also_uses_configured_tokenizer(self):
        from keel.agents import AgentSession
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'app.py').write_text('VALUE = 1\n',encoding='utf-8')
            policy=self.policy(root);ledger=Ledger(root/'ledger.sqlite')
            ws=Workspace(root,Budget(Limits(max_tokens=1500,max_model_calls=2)),ledger,Trace(root/'trace.jsonl'))
            class Model:
                calls=0
                def complete_json(self,*args,**kwargs):
                    self.calls+=1
                    value={'tool':'read_file','arguments':{'path':'app.py'}} if self.calls==1 else {'final':{'summary':'Observed','files':['app.py']}}
                    return Reply(json.dumps(value),20,{'prompt_tokens':12})
            try:
                with patch.dict(sys.modules,{'tiktoken':self.tokenizer()}):
                    session=AgentSession('scout',Model(),ws,max_steps=2,max_output=200,
                                         proposal_context_policy=policy,max_context_bytes=18000)
                    session.execute({'goal':'Inspect app.py'},'A source summary')
                self.assertEqual(ws.budget.model_calls,2)
                self.assertEqual(ws.budget.tokens,40)
            finally:ledger.close()

    def test_parent_process_log_does_not_overwrite_export_receipt(self):
        from keel.tokenizer_setup import prepare
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);base={k:v for k,v in self.policy(root).items() if k not in ('local_tokenizer','local_tokenizer_sha256','require_local_tokenizer')}
            model_path=root/'model.json';model_path.write_text('{"name":"fixture"}',encoding='utf-8')
            base_path=root/'base.json';base_path.write_text(json.dumps(base),encoding='utf-8')
            encoder=SimpleNamespace(name='fixture',_pat_str='.',_mergeable_ranks={},_special_tokens={})
            fake=self.tokenizer();fake.encoding_for_model=lambda name:encoder
            def run(runner,command,cwd,timeout):
                export_encoding(model_path,base_path,cwd)
                return {'returncode':0,'timeout':False,'stdout':'','stderr':''}
            with patch.dict(sys.modules,{'tiktoken':fake}),patch('keel.tokenizer_setup.importlib.metadata.version',return_value='fixture'), \
                 patch('keel.tokenizer_setup.CommandRunner.run',new=run):
                result=prepare(model_path,base_path,root/'result')
            self.assertEqual(result['status'],'completed')
            metadata=json.loads((root/'result'/'export.json').read_text(encoding='utf-8'))
            process=json.loads((root/'result'/'export-process.json').read_text(encoding='utf-8'))
            self.assertIn('tokenizer_sha256',metadata)
            self.assertEqual(process['returncode'],0)

    def test_recovery_preserves_hashed_assets_and_does_not_resolve_or_download_encoding(self):
        from keel.tokenizer_setup import recover_encoding,verify_export
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);old=root/'old';old.mkdir();new=root/'new';new.mkdir()
            base={k:v for k,v in self.policy(root).items() if k not in ('local_tokenizer','local_tokenizer_sha256','require_local_tokenizer')}
            model_path=root/'model.json';model_path.write_text('{"name":"fixture"}',encoding='utf-8')
            base_path=root/'base.json';base_path.write_text(json.dumps(base),encoding='utf-8')
            encoder=SimpleNamespace(name='fixture',_pat_str='.',_mergeable_ranks={},_special_tokens={})
            fake=self.tokenizer();fake.encoding_for_model=lambda name:encoder
            with patch.dict(sys.modules,{'tiktoken':fake}),patch('keel.tokenizer_setup.importlib.metadata.version',return_value='fixture'):
                export_encoding(model_path,base_path,old)
            (old/'export.json').write_text('{"returncode":0}',encoding='utf-8')
            (old/'report.json').write_text(json.dumps({'stages':[{'stage':'export','returncode':0,'timeout':False}],
                'input_hashes':{str(p.resolve()):hashlib.sha256(p.read_bytes()).hexdigest() for p in (model_path,base_path)}}),encoding='utf-8')
            before={p.name:p.read_bytes() for p in old.iterdir()}
            fake.encoding_for_model=lambda name:(_ for _ in ()).throw(AssertionError('network-capable resolver called'))
            mapping=SimpleNamespace(encoding_name_for_model=lambda name:'fixture')
            with patch.dict(sys.modules,{'tiktoken':fake,'tiktoken.model':mapping}), \
                 patch('keel.tokenizer_setup.importlib.metadata.version',return_value='fixture'):
                recover_encoding(model_path,base_path,old,new)
                self.assertEqual(verify_export(new)['estimator'],'offline_tiktoken')
                self.assertEqual(before,{p.name:p.read_bytes() for p in old.iterdir()})
                self.assertEqual((old/'tokenizer.json').read_bytes(),(new/'tokenizer.json').read_bytes())
                model_path.write_text('{"name":"changed"}',encoding='utf-8')
                another=root/'another';another.mkdir()
                with self.assertRaisesRegex(ValueError,'input drift'):
                    recover_encoding(model_path,base_path,old,another)
