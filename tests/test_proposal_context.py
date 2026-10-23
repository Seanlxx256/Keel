import copy
import json
import unittest

from keel.proposals import compact_goal_evidence, proposal_request
from keel.core import InputCapacityExceeded


class ProposalContextTests(unittest.TestCase):
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
