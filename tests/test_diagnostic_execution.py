import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from keel.models import Reply
from keel.runtime import run
from keel.diagnostic_execution import validate_probe_config


class DiagnosticExecutionTests(unittest.TestCase):
    def trial(self, *, blocked=False, unknown=False, calls=12):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        root=Path(temp.name);(root/'module.py').write_text('def value():\n    return 1\n')
        probe={'execution':{'backend':'docker','image':'sha256:'+'b'*64},
               'python':'/python','max_model_calls':3}
        config={'mode':'localized-proposal','goal':'Return 2',
                'recovery':{'strategy':'adaptive','max_actions':6,'write_roots':['.']},
                'agent':{'max_context_bytes':24000,'max_output':1024},
                'budget':{'max_model_calls':calls,'max_tokens':200000},
                'diagnostic_execution':probe,
                'continuation_context':{'verification':[{'returncode':1,'timeout':False,
                    'stdout':'AssertionError: expected 2','stderr':''}],
                    'changes':{'controlled_comparisons':{'scope':'Historical contrast','observations':[{'label':'baseline','status':'passed'}]}},'provenance':{}},
                'acceptance':[[sys.executable,'-c','pass']]}
        decision={'action':'replan','reason':'Inspect','hypothesis':'Wrong return',
                  'evidence':'Observed failure','next_check':'Observe value()',
                  'previous_attempt_assessment':'No current execution'}
        def action(kind, data):
            return {'action':kind,'path':'','query':'','start_line':0,'end_line':0,
                    'code':'import module; print(module.value())' if kind=='probe' else '',
                    'reason':'Compare actual value with expected','conclusion':'unknown' if kind!='answer' or unknown else 'supported',
                    'answer':'Observed executor failure' if blocked and kind=='blocked' else 'Observed current value',
                    'evidence_ids':[data['observations'][-1]['evidence_id']]}
        class Model:
            def __init__(self):self.messages=[]
            def complete_json(inner,messages,**kwargs):
                inner.messages.append(messages);i=len(inner.messages)
                data=json.loads(messages[1]['content'])
                value=(decision if i==1 else {'files':['module.py']} if i==2 else
                       {'locations':['module.py:1']} if i==3 else
                       action('probe',data) if i==4 else action('blocked' if blocked else 'answer',data) if i==5 else
                       {'summary':'Change observed return value','edits':[{'path':'module.py','old':'return 1','new':'return 2'}]})
                return Reply(json.dumps(value),10)
        row={'kind':'execution','outcome':'executor_failed' if blocked else 'completed',
             'execution':{'returncode':1 if blocked else 0,'timeout':False},
             'probe':{'returncode':0,'timeout':False,'stdout':'CURRENT_VALUE=1','stderr':''}}
        model=Model()
        with patch('keel.diagnostic_probe.run_probe',return_value=row) as executor, \
                patch('keel.workspace.Workspace.verify',return_value=[{'returncode':0,'timeout':False,'stdout':'','stderr':''}]):
            result=run(config,root,root/'.keel/run',model=model)
        return root,result,model,executor

    def test_real_runtime_handoff_executes_before_patch_and_delivers_raw_result(self):
        root,result,model,executor=self.trial()
        self.assertEqual(result['status'],'passed',result.get('failure'))
        self.assertEqual(executor.call_count,1)
        self.assertEqual(result['budget']['model_calls'],6)
        self.assertIn('CURRENT_VALUE=1',model.messages[-1][1]['content'])
        self.assertIn('Historical contrast',model.messages[0][1]['content'])
        self.assertIn('Historical contrast',model.messages[3][1]['content'])
        self.assertIn('Historical contrast',model.messages[-1][1]['content'])
        self.assertIn('return 2',(root/'module.py').read_text())
        self.assertEqual(executor.call_args.kwargs['candidate_paths'],['module.py'])

    def test_executor_failure_stops_without_patch(self):
        root,result,model,_=self.trial(blocked=True)
        self.assertEqual(result['status'],'failed')
        self.assertEqual(result['failure']['category'],'environment_blocked')
        self.assertEqual(len(model.messages),5)
        self.assertIn('return 1',(root/'module.py').read_text())

    def test_unresolved_interpretation_does_not_force_patch(self):
        root,result,model,_=self.trial(unknown=True)
        self.assertEqual(result['status'],'failed')
        self.assertIn('unresolved after execution',result['failure']['message'])
        self.assertEqual(len(model.messages),5)
        self.assertIn('return 1',(root/'module.py').read_text())

    def test_bridge_uses_global_call_budget_without_reset(self):
        root,result,model,_=self.trial(calls=4)
        self.assertEqual(result['failure']['category'],'budget_exhausted')
        self.assertEqual(len(model.messages),4)
        self.assertIn('return 1',(root/'module.py').read_text())

    def test_host_execution_or_mutable_image_is_not_allowed(self):
        for execution in ({'backend':'local'},{'backend':'docker','image':'latest'}):
            with self.assertRaises(ValueError):
                validate_probe_config({'execution':execution,'python':'/python','max_model_calls':3})
