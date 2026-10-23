import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from keel.context_budget import validate_policy, estimate_input, admission, calibration_report
from keel.core import Budget, Limits, BudgetExceeded, InputCapacityExceeded
from keel.proposals import proposal_request


class ContextBudgetTests(unittest.TestCase):
    def test_calibration_does_not_mix_models_or_mutate_policy(self):
        events=[{'event':'proposal_token_estimate_observed','model':model,'estimator':'test',
                 'estimated_input_tokens':100,'actual_input_tokens':actual,'reserved_input_tokens':110,
                 'policy_sha256':'p'} for model,actual in [('a',120),('a',80),('b',200)]]
        report=calibration_report(events)
        self.assertEqual(len(report['groups']),2)
        self.assertEqual(report['groups'][0]['samples'],2)
        self.assertEqual(report['groups'][0]['maximum_underestimate_tokens'],20)
        self.assertEqual(report['groups'][0]['under_reserved_samples'],1)

    def policy(self,**changes):
        return {'model_context_tokens':10000,'max_input_tokens':6000,
                'safety_tokens':128,'max_request_bytes':20000,**changes}

    def budget(self,**limits):
        return Budget(Limits(max_tokens=limits.get('tokens',20000)))

    def test_reserves_output_safety_and_remaining_budget(self):
        budget=self.budget(tokens=1000);budget.tokens=200
        result=admission([{'role':'user','content':'short'}],{},self.policy(),100,budget)
        self.assertEqual(result['effective_input_limit_tokens'],700)
        self.assertEqual(result['reserved_input_tokens'],result['input_estimate']+128)
        self.assertEqual(budget.model_calls,0)
        self.assertFalse(result['provider_exact'])

    def test_global_depletion_not_recoverable_input_error(self):
        with self.assertRaises(BudgetExceeded) as caught:
            admission([{'content':'x'*1000}],{},self.policy(),500,self.budget(tokens=1000))
        self.assertNotIsInstance(caught.exception,InputCapacityExceeded)

    def test_context_and_per_call_caps_independent(self):
        for p in [self.policy(model_context_tokens=500),self.policy(max_input_tokens=100)]:
            with self.subTest(p=p),self.assertRaises(InputCapacityExceeded):
                admission([{'content':'x'*400}],{},p,200,self.budget())

    def test_missing_local_tokenizer_is_visible_fallback(self):
        result=estimate_input([],{},self.policy(local_tokenizer='not-a-real-encoding-file.json'))
        self.assertEqual(result['estimator'],'utf8_bytes_conservative')
        self.assertIn('fallback_reason',result)

    def test_offline_tokenizer_does_not_need_model_resolver_or_network(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'encoding.json'
            path.write_text(json.dumps({'name':'test','pat_str':'.','mergeable_ranks':{},'special_tokens':{}}))
            factory=lambda **kwargs:SimpleNamespace(encode=lambda text,**options:list(range(12)))
            with patch.dict(sys.modules,{'tiktoken':SimpleNamespace(Encoding=factory)}):
                result=estimate_input([],{},self.policy(local_tokenizer=str(path)))
            self.assertEqual(result['input_estimate'],12)
            self.assertEqual(result['estimator'],'offline_tiktoken')
            self.assertFalse(result['provider_exact'])

    def test_byte_ceiling_independent_of_soft_ratio_and_token_window(self):
        settings={'max_context_bytes':2000,'proposal_context_policy':self.policy(max_request_bytes=20000)}
        ev=[{'path':'a.py','windows':[{'text':'x'*4000}]}]
        msg,_,size=proposal_request('task',['a.py'],ev,settings)
        self.assertGreater(size,2200)
        self.assertEqual(json.loads(msg[1]['content'])['evidence'],ev)
        with self.assertRaises(InputCapacityExceeded):
            proposal_request('task',['a.py'],ev,{**settings,'proposal_context_policy':self.policy(max_request_bytes=3000)})

    def test_invalid_policies_do_not_silently_expand_limits(self):
        for p in [self.policy(model_context_tokens=True),self.policy(safety_tokens=10000),
                  self.policy(max_input_tokens=0),{**self.policy(),'mystery':1}]:
            with self.subTest(p=p),self.assertRaises(ValueError):validate_policy(p)
        with self.assertRaises(ValueError):
            proposal_request('task',['a.py'],[{'path':'a.py'}],{'max_context_bytes':1000,
                'proposal_context_hard_bytes':1100,'proposal_context_policy':self.policy()})
