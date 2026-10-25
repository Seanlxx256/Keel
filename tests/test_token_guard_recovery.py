import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from keel.core import Budget, Limits, BudgetExceeded, InputCapacityExceeded, Ledger, Trace
from keel.context_budget import admission, admission_with_recovery, estimate_input, compact_json_payloads
from keel.proposals import _propose_once, proposal_request, source_evidence
from keel.models import Reply
from keel.workspace import Workspace


class TokenGuardRecoveryTests(unittest.TestCase):
    def policy(self, **changes):
        return {'model_context_tokens':50000,'max_input_tokens':20000,'safety_tokens':64,
                'max_request_bytes':60000,'recover_capacity':True,**changes}

    def test_next_request_reservation_is_not_actual_spend_and_metrics_are_retained(self):
        b=Budget(Limits(max_tokens=1000));b.tokens=100
        with self.assertRaises(BudgetExceeded) as caught:
            admission([{'role':'user','content':'x'*1000}],{},self.policy(),200,b)
        self.assertIsInstance(caught.exception,InputCapacityExceeded)
        metrics=caught.exception.context_metrics
        self.assertEqual(metrics['total_tokens_remaining'],900)
        self.assertIn('global_next_request_reservation',metrics['binding_constraints'])
        self.assertNotIn('global_tokens_spent',metrics['binding_constraints'])
        self.assertEqual(caught.exception.guard_incident['category'],'request_capacity')
        self.assertEqual(b.model_calls,0)

    def test_lossless_layout_can_recover_global_reservation_without_dropping_source(self):
        payload={'source':'    exact = " x "\r\n','rows':[{'n':n} for n in range(25)]}
        messages=[{'role':'user','content':json.dumps(payload,indent=3)}];original=copy.deepcopy(messages)
        policy=self.policy();packed=compact_json_payloads(messages)
        raw=estimate_input(messages,{},policy)['input_estimate'];small=estimate_input(packed,{},policy)['input_estimate']
        b=Budget(Limits(max_tokens=(raw+small)//2+64+100));events=[]
        admitted,metrics=admission_with_recovery(messages,{},policy,100,b,on_event=events.append)
        self.assertEqual(json.loads(admitted[0]['content']),payload)
        self.assertEqual(messages,original)
        self.assertLess(metrics['input_estimate'],raw)
        self.assertEqual(events[-1]['disposition'],'recovered')
        self.assertEqual(b.model_calls,0)
        self.assertEqual(b.tokens,0)
        self.assertEqual(metrics['output_reserved_tokens'],100)

    def test_required_evidence_not_truncated_and_failed_repacking_is_bounded(self):
        messages=[{'role':'user','content':json.dumps({'current_source':'x'*5000})}]
        original=copy.deepcopy(messages);repack=Mock(side_effect=lambda x:x);events=[]
        with self.assertRaises(BudgetExceeded):
            admission_with_recovery(messages,{},self.policy(max_input_tokens=300),200,
                                    Budget(Limits(max_tokens=20000)),repack=repack,on_event=events.append)
        self.assertEqual(messages,original)
        self.assertEqual(repack.call_count,1)
        self.assertEqual(events[-1]['disposition'],'checkpoint_stop')

    def test_actual_call_exhaustion_never_attempts_repacking(self):
        b=Budget(Limits(max_model_calls=1));b.model_calls=1;repack=Mock()
        with self.assertRaises(BudgetExceeded) as caught:
            admission_with_recovery([{'content':'small'}],{},self.policy(),100,b,repack=repack)
        repack.assert_not_called()
        self.assertIn('global_model_calls_spent',caught.exception.context_metrics['binding_constraints'])
        self.assertEqual(caught.exception.guard_incident['allowed_actions'],())

    def test_required_incident_checkpoint_failure_propagates(self):
        with self.assertRaisesRegex(OSError,'checkpoint'):
            admission_with_recovery([{'role':'user','content':json.dumps({'value':'x'*1000},indent=4)}],{},
                self.policy(max_input_tokens=100),100,Budget(Limits()),
                on_event=Mock(side_effect=OSError('checkpoint failed')))

    def test_production_proposal_reuses_duplicate_evidence_and_reaches_validated_write(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);text='VALUE = 1\n';(root/'app.py').write_bytes(text.encode())
            probe={'stdout':'result '*500,'stderr':'','returncode':0}
            goal='Update VALUE.\n'+json.dumps({'probe':probe,'execution':{
                'stdout':json.dumps(probe),'stderr':'','returncode':0,'timeout':False}})
            evidence=[source_evidence('app.py',text,['VALUE'])]
            policy=self.policy();settings={'max_context_bytes':50000,'max_output':1024,'proposal_context_policy':policy}
            messages,schema,_=proposal_request(goal,['app.py'],evidence,settings)
            raw=estimate_input(messages,schema,policy)['input_estimate']
            policy['max_input_tokens']=raw-1000
            with self.assertRaises(BudgetExceeded):admission(messages,schema,policy,1024,Budget(Limits(max_tokens=100000)))
            budget=Budget(Limits(max_tokens=100000,max_model_calls=1));ledger=Ledger(root/'ledger.sqlite')
            ws=Workspace(root,budget,ledger,Trace(root/'trace.jsonl'))
            owner=self
            class Model:
                calls=0
                def complete_json(self,messages,**kwargs):
                    self.calls+=1;payload=json.loads(messages[1]['content'])
                    owner.assertEqual(payload['evidence'],evidence)
                    owner.assertEqual(json.loads(payload['goal'].splitlines()[1])['probe'],probe)
                    owner.assertEqual(kwargs['max_output'],1024)
                    return Reply(json.dumps({'edits':[{'path':'app.py','old':text,'new':'VALUE = 2\n'}],
                                             'summary':'Update VALUE.'}),10)
            model=Model()
            try:
                _propose_once(model,ws,goal,['app.py'],evidence,settings)
                self.assertEqual(model.calls,1)
                self.assertEqual((root/'app.py').read_bytes(),b'VALUE = 2\n')
                self.assertEqual(budget.model_calls,1)
                self.assertEqual(budget.tokens,10)
                facts=ledger.statistics()['facts'];self.assertGreater(facts,0)
                records=[json.loads(line) for line in (root/'trace.jsonl').read_text(encoding='utf-8').splitlines()]
                self.assertTrue(any(r.get('disposition')=='recovered' for r in records))
            finally:ledger.close()

    def test_capacity_incident_reaches_existing_model_evidence_selection_route(self):
        from unittest.mock import MagicMock, patch
        from keel.recovery import RecoveryController
        b=Budget(Limits(max_tokens=1000))
        try:
            admission([{'role':'user','content':'x'*2000}],{},self.policy(),100,b)
        except InputCapacityExceeded as error:
            incident_error=error
        ws=MagicMock();controller=RecoveryController({'max_actions':6},ws)
        large=[{'path':'app.py','windows':[{'text':'large'}]}]
        small=[{'path':'app.py','windows':[{'text':'small'}]}]
        with patch('keel.proposals._propose_once',side_effect=[incident_error,'patch']), \
             patch('keel.repair.select_repair_evidence',return_value=small) as selection:
            self.assertEqual(controller.propose(object(),ws,'goal',['app.py'],large,{}),'patch')
            feedback=selection.call_args.args[4]
            self.assertEqual(feedback['capacity_guard']['code'],'token_admission_rejected')
            self.assertIn('global_next_request_reservation',feedback['capacity_guard']['details']['binding_constraints'])
