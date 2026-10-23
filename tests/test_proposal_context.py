import copy
import json
import unittest
from unittest.mock import MagicMock, patch

from keel.proposals import compact_goal_evidence, proposal_request, ProposalCapacityExceeded, proposal_context_limits
from keel.core import InputCapacityExceeded, RecoveryStopped, BudgetExceeded
from keel.recovery import RecoveryController


class ProposalContextTests(unittest.TestCase):
    def test_headroom_never_bypasses_shared_budget_or_dispatches_on_denial(self):
        from keel.proposals import _propose_once
        model=MagicMock();ws=MagicMock()
        ws.budget.allow_model.side_effect=BudgetExceeded('Insufficient token budget')
        evidence=[{'path':'a.py','windows':[{'text':'x'*2000}]}]
        _,_,raw=proposal_request('task',['a.py'],evidence,{})
        soft=raw-100
        with self.assertRaisesRegex(BudgetExceeded,'Insufficient token'):
            _propose_once(model,ws,'task',['a.py'],evidence,
                          {'max_context_bytes':soft,'proposal_context_hard_bytes':soft+soft//10,'max_output':777})
        self.assertGreater(ws.budget.allow_model.call_args.args[0],soft)
        self.assertEqual(ws.budget.allow_model.call_args.args[1],777)
        model.complete_json.assert_not_called()

    def test_declared_headroom_admits_complete_request_but_never_beyond_hard_cap(self):
        ev=[{'path':'a.py','windows':[{'text':'x'*2000}]}]
        _,_,size=proposal_request('task',['a.py'],ev,{})
        soft=size-100
        messages,_,actual=proposal_request('task',['a.py'],ev,
            {'max_context_bytes':soft,'proposal_context_hard_bytes':soft+soft//10})
        self.assertGreater(actual,soft)
        self.assertEqual(json.loads(messages[1]['content'])['evidence'],ev)
        with self.assertRaises(ProposalCapacityExceeded):
            proposal_request('task',['a.py'],ev,{'max_context_bytes':soft-600,
                'proposal_context_hard_bytes':soft-600+(soft-600)//10})

    def test_invalid_headroom_rejected_including_booleans(self):
        for settings in ({'proposal_context_hard_bytes':5000},
                         {'max_context_bytes':1000,'proposal_context_hard_bytes':1101},
                         {'max_context_bytes':1000,'proposal_context_hard_bytes':999},
                         {'max_context_bytes':1000,'proposal_context_hard_bytes':True}):
            with self.subTest(settings=settings), self.assertRaises(ValueError):
                proposal_context_limits(settings)
        self.assertEqual(proposal_context_limits({'max_context_bytes':1000}),(1000,1000))

    def test_small_overflow_uses_lossless_payload_layout_before_reselection(self):
        ev=[{'path':'a.py','windows':[{'start_line':i,'end_line':i,'text':'    x = "keep spaces"\r\n'}
                                   for i in range(1,31)]}]
        messages,_,rawsize=proposal_request('Keep this task unchanged',['a.py'],ev,{})
        before=json.loads(messages[1]['content'])
        packed,_,size=proposal_request('Keep this task unchanged',['a.py'],ev,{'max_context_bytes':rawsize-75})
        self.assertLessEqual(size,rawsize-75)
        self.assertEqual(json.loads(packed[1]['content']),before)

    def test_fixed_context_overflow_does_not_pay_for_source_reselection(self):
        ws=MagicMock(); recovery=RecoveryController({'max_actions':6},ws)
        evidence=[{'path':'a.py','windows':[{'text':'x=1'}]}]
        with patch('keel.proposals._propose_once',side_effect=ProposalCapacityExceeded(5000,2000,3000)), \
             patch('keel.repair.select_repair_evidence') as select:
            with self.assertRaisesRegex(RecoveryStopped,'Fixed proposal context'):
                recovery.propose(object(),ws,'goal',['a.py'],evidence,{})
            select.assert_not_called()
            self.assertEqual(recovery.actions,[])

    def test_same_oversized_selection_stops_without_third_selection(self):
        ws=MagicMock(); recovery=RecoveryController({'max_actions':6},ws)
        evidence=[{'path':'a.py','windows':[{'text':'x=1'}]}]
        with patch('keel.proposals._propose_once',side_effect=ProposalCapacityExceeded(5000,2000,1000)), \
             patch('keel.repair.select_repair_evidence',return_value=copy.deepcopy(evidence)) as select:
            with self.assertRaisesRegex(RecoveryStopped,'same oversized evidence'):
                recovery.propose(object(),ws,'goal',['a.py'],evidence,{})
            self.assertEqual(select.call_count,1)
            self.assertEqual(len(recovery.actions),1)

    def test_changed_selection_can_proceed(self):
        ws=MagicMock(); recovery=RecoveryController({'max_actions':6},ws)
        evidence=[{'path':'a.py','windows':[{'text':'large'}]}]
        smaller=[{'path':'a.py','windows':[{'text':'small'}]}]
        with patch('keel.proposals._propose_once',side_effect=[ProposalCapacityExceeded(5000,2000,1000),'patch']) as propose, \
             patch('keel.repair.select_repair_evidence',return_value=smaller):
            self.assertEqual(recovery.propose(object(),ws,'goal',['a.py'],evidence,{}),'patch')
            self.assertEqual(propose.call_args.args[4],smaller)

    def test_capacity_measurements_distinguish_fixed_and_source_size(self):
        ev=[{'path':'a.py','windows':[{'text':'x'*5000}]}]
        with self.assertRaises(ProposalCapacityExceeded) as caught:
            proposal_request('goal',['a.py'],ev,{'max_context_bytes':4000})
        error=caught.exception
        self.assertLess(error.fixed_bytes,error.limit_bytes)
        self.assertGreater(error.input_bytes,error.limit_bytes)

    def test_overflow_compacts_duplicate_but_preserves_exact_source_and_child(self):
        probe={'returncode':0,'stdout':'failure result '*140,'stderr':'trace','timeout':False}
        row={'probe':probe,'execution':{'returncode':0,'timeout':False,'stderr':'','stdout':json.dumps(probe)}}
        goal='Task\nUntrusted execution:\n'+json.dumps({'executions':[row]})
        ev=[{'path':'a.py','windows':[{'text':'x = 1\r\n'}]}]
        original=copy.deepcopy(ev)
        _,_,rawsize=proposal_request(goal,['a.py'],ev,{})
        messages,_,size=proposal_request(goal,['a.py'],ev,{'max_context_bytes':rawsize-1500})
        self.assertLessEqual(size,rawsize-1500)
        payload=json.loads(messages[1]['content'])
        result=json.loads(payload['goal'].splitlines()[-1])['executions'][0]
        self.assertEqual(result['probe'],probe)
        self.assertEqual(payload['evidence'],original)
        self.assertEqual(ev,original)
        self.assertIn('stdout',row['execution'])

    def test_distinct_output_and_non_json_goal_preserved(self):
        value={'probe':{'stdout':'child'},'execution':{'stdout':'different','returncode':0}}
        goal='Natural task\n'+json.dumps(value)
        compacted=compact_goal_evidence(goal)
        self.assertEqual(compacted.splitlines()[0],'Natural task')
        self.assertEqual(json.loads(compacted.splitlines()[1]),value)

    def test_fitting_request_unchanged_and_oversized_source_still_rejected(self):
        goal='Task\n'+json.dumps({'important':'preserve text'})
        ev=[{'path':'a.py','windows':[{'text':'x'*5000}]}]
        messages,_,_=proposal_request(goal,['a.py'],ev,{'max_context_bytes':20000})
        self.assertEqual(json.loads(messages[1]['content'])['goal'],goal)
        with self.assertRaises(InputCapacityExceeded):
            proposal_request(goal,['a.py'],ev,{'max_context_bytes':2000})
