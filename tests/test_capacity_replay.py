import json
import tempfile
import unittest
from pathlib import Path
from keel.capacity_replay import measure_request,replay


class CapacityReplayTests(unittest.TestCase):
    def request(self):
        probe={'stdout':'observed value'*50,'stderr':'','returncode':0}
        goal='Keep task.\n'+json.dumps({'probe':probe,'execution':{'stdout':json.dumps(probe),
              'stderr':'','returncode':0,'timeout':False}})
        payload={'goal':goal,'evidence':[{'path':'a.py','text':'    x = "keep"\r\n'}],
                 'allowed_files':['a.py'],'current_failure':'assertion failed'}
        return [{'role':'system','content':'Do not change policy.'},
                {'role':'user','content':json.dumps(payload,indent=3)}]

    def test_measurement_does_not_mutate_evidence_or_claim_provider_exactness(self):
        messages=self.request();before=json.dumps(messages)
        result=measure_request(messages,{'required':['edits']})
        self.assertTrue(result['non_goal_payload_unchanged'])
        self.assertGreater(result['saved_estimated_units'],0)
        self.assertFalse(result['provider_exact'])
        self.assertEqual(json.dumps(messages),before)

    def test_transcript_pairing_preserves_source_and_records_actual_usage_without_dispatch(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);path=root/'transcript.jsonl'
            rows=[{'args':[self.request()],'kwargs':{'schema':{'required':['edits']},'max_output':1024}},
                  {'event':'response','tokens':150,'metadata':{'prompt_tokens':100}},
                  {'args':[self.request()],'kwargs':{'schema':{'required':['locations']}}}]
            path.write_text('\n'.join(json.dumps(row) for row in rows),encoding='utf-8');raw=path.read_bytes()
            result=replay([path],root/'result')
            self.assertEqual(result['requests'],1)
            self.assertEqual(result['provider_calls'],0)
            self.assertEqual(result['records'][0]['observed_input_tokens'],100)
            self.assertEqual(path.read_bytes(),raw)
            self.assertTrue((root/'result'/'receipt.json').exists())
            with self.assertRaises(FileExistsError):replay([path],root/'result')

    def test_unsupported_requests_are_not_quality_failures(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);path=root/'input.jsonl';path.write_text('{}',encoding='utf-8')
            result=replay([path],root/'result')
            self.assertEqual(result['status'],'no_supported_requests')
