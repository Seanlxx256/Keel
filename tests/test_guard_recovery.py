import json
import tempfile
import time
import unittest
from pathlib import Path
from examples.evaluate_diagnosis import trial,FAMILIES
from keel.core import Budget, Limits, BudgetExceeded
from keel.models import Reply
from keel.guard_recovery import canonicalize_candidate_names,GuardViolation
from keel.outer_improvement import execute


def action(ids, kind='probe', probe='decode_spaced', conclusion='undetermined'):
    return {'action':kind,'probe_id':probe,'predicted_A':True,'predicted_B':False,
            'conclusion':conclusion,'evidence_ids':ids,'reason':'Distinguish causes using observed evidence.'}


class GuardRecoveryTests(unittest.TestCase):
    def test_host_names_preserve_guidance_and_display_names_without_path_authority(self):
        original={'candidates':[{'id':'../../'+'x'*100,'guidance':'Unchanged guidance.'}]}
        mapped,event=canonicalize_candidate_names(original)
        self.assertNotIn('/',mapped[0]['id'])
        self.assertEqual(mapped[0]['guidance'],original['candidates'][0]['guidance'])
        self.assertEqual(event['details']['mapping'][0]['display_name'],original['candidates'][0]['id'])
        self.assertEqual(canonicalize_candidate_names(original)[0],mapped)
        for bad in ({'candidates':[],'tools':[]},
                    {'candidates':[{'id':'x','guidance':'ok','limits':{}}]},
                    {'candidates':[{'id':'x','guidance':'ok'}]*2}):
            with self.assertRaises(GuardViolation):canonicalize_candidate_names(bad)

    def test_unknown_reference_reasons_again_executes_and_passes_in_original_three_turns(self):
        owner=self
        class Model:
            calls=0
            def complete_json(self,messages,**kwargs):
                self.calls+=1
                if self.calls==1:value=action(['invented'])
                elif self.calls==2:
                    guard=json.loads(messages[-1]['content'])['guard']
                    owner.assertEqual(guard['code'],'unknown_observation_reference')
                    owner.assertEqual(guard['details']['available_observation_ids'],[])
                    owner.assertNotIn('oracle',json.dumps(guard))
                    value=action([])
                else:value=action(['observation-1'],'conclude','','B')
                return Reply(json.dumps(value),10)
        with tempfile.TemporaryDirectory() as temp:
            budget=Budget(Limits(max_model_calls=3,max_tokens=16000,max_tool_calls=6,max_wallclock=60))
            result=trial(Model(),FAMILIES['reader'],'B','baseline',Path(temp)/'arm',time.monotonic()+60,
                         recover_guards=True,budget=budget)
            self.assertTrue(result['score']['passed'])
            self.assertEqual(result['budget']['model_calls'],3)
            self.assertEqual(result['budget']['tool_calls'],2)
            self.assertEqual(len(result['guard_events']),1)

    def test_repeated_bad_reference_stops_and_disallowed_tool_cannot_use_recovery(self):
        class Model:
            def __init__(self,probe):self.probe=probe
            def complete_json(self,*args,**kwargs):return Reply(json.dumps(action(['invented'],probe=self.probe)),10)
        with tempfile.TemporaryDirectory() as temp:
            for probe,calls in [('decode_spaced',2),('__import__("os")',1)]:
                result=trial(Model(probe),FAMILIES['reader'],'B','baseline',Path(temp)/str(calls),
                             time.monotonic()+60,recover_guards=True)
                self.assertFalse(result['score']['passed'])
                self.assertEqual(result['budget']['model_calls'],calls)
                self.assertEqual(result['budget']['tool_calls'],0)

    def test_recovery_never_raises_shared_call_limit(self):
        class Model:
            def complete_json(self,*args,**kwargs):return Reply(json.dumps(action(['invented'])),10)
        with tempfile.TemporaryDirectory() as temp:
            b=Budget(Limits(max_model_calls=1,max_tokens=16000,max_tool_calls=6,max_wallclock=60))
            result=trial(Model(),FAMILIES['reader'],'B','baseline',Path(temp)/'arm',time.monotonic()+60,
                         recover_guards=True,budget=b)
            self.assertEqual(result['budget']['model_calls'],1)
            self.assertEqual(result['guard_events'][0]['disposition'],'checkpoint_stop')

    def test_outer_actual_long_name_reaches_downstream_and_resumes_without_model(self):
        class Model:
            calls=0
            def complete_json(self,messages,**kwargs):
                self.calls+=1
                if 'Propose at most' in messages[0]['content']:
                    return Reply(json.dumps({'candidates':[{'id':'x'*100,'guidance':'General advice.'}]}),10)
                return Reply(json.dumps(action([],'conclude','','undetermined')),10)
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'run';model=Model()
            result=execute(model,root,config_hash='fixed',max_seconds=120,recover_guards=True)
            self.assertEqual(result['status'],'completed')
            self.assertEqual(model.calls,9)
            names=json.loads((root/'candidate-identities.json').read_text(encoding='utf-8'))
            self.assertEqual(names['incident']['details']['mapping'][0]['display_name'],'x'*100)
            execute(model,root,config_hash='fixed',max_seconds=120,recover_guards=True,resume=True)
            self.assertEqual(model.calls,9)
