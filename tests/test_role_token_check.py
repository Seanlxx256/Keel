import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from keel.role_token_check import execute
from keel.models import Reply
from keel.core import ModelError
from keel.recovery import CRITIC_QUESTIONS


class RoleTokenCheckTests(unittest.TestCase):
    def fixture(self,root):
        policy={'model_context_tokens':10000,'max_input_tokens':5000,'safety_tokens':64,'max_request_bytes':30000,
                'local_tokenizer':'fixture','require_local_tokenizer':True}
        schemas=[{'required':['action',*CRITIC_QUESTIONS]},
                 {'required':['files'],'properties':{'files':{'items':{'enum':['app.py']}}}},
                 {'required':['edits','summary'],'properties':{'edits':{'items':{'properties':{'path':{'enum':['app.py']}}}}}}]
        requests=[{'role':role,'messages':[{'role':'user','content':'frozen'}],'schema':schema,'max_output':1024}
                  for role,schema in zip(('critic','scout','implementer'),schemas)]
        for name,data in [('policy',policy),('requests',requests),('model',{})]:
            (root/(name+'.json')).write_text(json.dumps(data),encoding='utf-8')
        plan={'snapshot':str(root/'snapshot'),'policy':str(root/'policy.json'),'requests':str(root/'requests.json'),
              'model_config':str(root/'model.json'),'output':str(root/'results'),
              'frozen_files':{str(root/(name+'.json')):hashlib.sha256((root/(name+'.json')).read_bytes()).hexdigest()
                              for name in ('policy','requests','model')}}
        path=root/'plan.json';path.write_text(json.dumps(plan),encoding='utf-8')
        path.with_suffix('.sha256').write_text(hashlib.sha256(path.read_bytes()).hexdigest(),encoding='utf-8')
        return path
    def model(self,bad=False):
        class Model:
            calls=0
            def complete_json(self,messages,**kwargs):
                self.calls+=1
                required=kwargs['schema']['required']
                if 'action' in required:value={'action':'replan',**{k:'unknown' for k in CRITIC_QUESTIONS}}
                elif 'files' in required:value={'files':['outside.py' if bad else 'app.py']}
                else:value={'summary':'update','edits':[{'path':'app.py','old':'x=1','new':'x=2'}]}
                return Reply(json.dumps(value),20,{'prompt_tokens':10})
        return Model()
    def patches(self):
        return patch('keel.context_budget.estimate_input',return_value={'input_estimate':10,'estimator':'fixture','provider_exact':False})
    def test_shared_budget_receipts_resume_and_no_source_write(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);plan=self.fixture(root);(root/'app.py').write_text('x=1',encoding='utf-8');model=self.model()
            with patch('keel.role_token_check.verify_snapshot'),patch('keel.role_token_check.estimate_input'),self.patches():
                result=execute(plan,model=model)
                execute(plan,model=model,resume=True)
            self.assertEqual(model.calls,3)
            self.assertEqual(result['budget']['model_calls'],3)
            self.assertEqual(result['budget']['tokens'],60)
            self.assertEqual((root/'app.py').read_text(encoding='utf-8'),'x=1')
    def test_failed_role_not_retried_and_later_role_not_dispatched(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);plan=self.fixture(root);model=self.model(bad=True)
            with patch('keel.role_token_check.verify_snapshot'),patch('keel.role_token_check.estimate_input'),self.patches():
                with self.assertRaises(ValueError):execute(plan,model=model)
                with self.assertRaisesRegex(ValueError,'Unfinished'):execute(plan,model=model,resume=True)
            self.assertEqual(model.calls,2)
            self.assertFalse((root/'results'/'implementer.json').exists())
    def test_credentials_fail_before_creating_output(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);plan=self.fixture(root);model=self.model()
            model.check_credentials=lambda:(_ for _ in ()).throw(ModelError('Missing key'))
            with patch('keel.role_token_check.verify_snapshot'),patch('keel.role_token_check.estimate_input'),self.assertRaises(ModelError):
                execute(plan,model=model)
            self.assertFalse((root/'results').exists())
