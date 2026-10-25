import copy
import json
import unittest

from keel.diagnostic_inspection import request_view


class RequestViewTests(unittest.TestCase):
    def test_optional_knowledge_yields_capacity_to_current_observations(self):
        current={'kind':'execution','evidence_id':'E1','probe':{'stdout':'CURRENT_RESULT=7','stderr':'current failure'}}
        data={'observations':[current],'operational_knowledge':{'catalog_sha256':'a'*64,'cards':[{'guidance':'x'*3000}]}}
        before=copy.deepcopy(data)
        messages,size,changes=request_view(data,{},structured=True,limit=1500,compact=True)
        view=json.loads(messages[1]['content'])
        self.assertLessEqual(size,1500)
        self.assertEqual(view['observations'],[current])
        self.assertEqual(view['operational_knowledge']['status'],'omitted_for_request_capacity')
        self.assertEqual(data,before)
        self.assertIn('operational_knowledge',[row['omitted'] for row in changes])

    def test_source_echo_and_old_code_compact_without_losing_distinct_results(self):
        source='def example():\n    return '+repr('x'*250)+'\n'
        latest={'kind':'execution','evidence_id':'E2','code':'print("actual")',
                'probe':{'stdout':source+'\nACTUAL_RESULT=7','stderr':'actual error'}}
        data={'readable_paths':['a.py'],'observations':[
            {'kind':'source','evidence_id':'S1','path':'a.py','text':source},
            {'kind':'execution','evidence_id':'E1','code':'old '*1000,'probe':{'stdout':'OLD_RESULT=4'}},latest]}
        before=copy.deepcopy(data)
        messages,size,changes=request_view(data,{},structured=True,limit=2000,compact=True)
        view=json.loads(messages[1]['content'])
        self.assertLessEqual(size,2000)
        self.assertEqual(data,before)
        self.assertIn('ACTUAL_RESULT=7',view['observations'][-1]['probe']['stdout'])
        self.assertEqual(view['observations'][-1]['probe']['stderr'],'actual error')
        self.assertEqual(view['observations'][-1]['code'],latest['code'])
        self.assertEqual(view['observations'][1]['probe']['stdout'],'OLD_RESULT=4')
        self.assertTrue(view['observations'][1]['code_view']['omitted'])
        self.assertIn('exact_source_echo',[row['omitted'] for row in changes])

    def test_duplicate_wrapper_removed_without_changing_evidence(self):
        probe={'returncode':0,'stdout':'result '*600,'stderr':'','timeout':False}
        data={'observations':[{'kind':'execution','evidence_id':'E1','probe':probe,
              'execution':{'returncode':0,'timeout':False,'stderr':'','stdout':json.dumps(probe)}}]}
        before=copy.deepcopy(data)
        messages,size,changes=request_view(data,{},structured=True,limit=6000,compact=True)
        self.assertLessEqual(size,6000)
        self.assertEqual(data,before)
        self.assertEqual(json.loads(messages[1]['content'])['observations'][0]['probe'],probe)
        self.assertEqual(changes[0]['omitted'],'duplicate_execution_wrapper')

    def test_distinct_transport_output_never_discarded(self):
        data={'observations':[{'kind':'execution','evidence_id':'E1','probe':{'stdout':'child'},
                              'execution':{'stdout':'different '*1000,'returncode':0}}]}
        messages,size,changes=request_view(data,{},structured=True,limit=1000,compact=True)
        self.assertGreater(size,1000)
        self.assertFalse(changes)
        self.assertEqual(json.loads(messages[1]['content']),data)

    def test_old_source_explicitly_omitted_latest_execution_preserved(self):
        data={'readable_paths':['a.py'],'observations':[
            {'kind':'source','evidence_id':'S1','path':'a.py','text':'x'*5000},
            {'kind':'execution','evidence_id':'E1','probe':{'stdout':'important'}}]}
        messages,size,changes=request_view(data,{},structured=True,limit=2000,compact=True)
        view=json.loads(messages[1]['content'])
        self.assertLessEqual(size,2000)
        self.assertTrue(view['observations'][0]['text_view']['omitted'])
        self.assertEqual(view['observations'][1],data['observations'][1])
        self.assertIn('text',data['observations'][0])

    def test_fitting_request_and_other_stages_unchanged(self):
        data={'observations':[]}
        _,_,changes=request_view(data,{},structured=False,limit=10000,compact=True)
        self.assertFalse(changes)
        _,size,changes=request_view({'observations':[{'text':'x'*5000}]},{},structured=True,limit=100,compact=False)
        self.assertFalse(changes)
        self.assertGreater(size,100)

    def test_crlf_source_echo_can_be_deduplicated_without_dropping_results(self):
        text='def sample():\r\n    return '+repr('x'*220)+'\r\n'
        data={'readable_paths':['a.py'],'observations':[
            {'kind':'source','evidence_id':'S1','path':'a.py','text':text},
            {'kind':'execution','evidence_id':'E1','probe':{'stdout':text.replace('\r\n','\n')+'RESULT=3'}}]}
        messages,_,changes=request_view(data,{},structured=True,limit=700,compact=True)
        output=json.loads(messages[1]['content'])['observations'][-1]['probe']['stdout']
        self.assertIn('RESULT=3',output)
        self.assertIn('CRLF/LF-equivalent',output)
        self.assertIn('exact_source_echo',[r['omitted'] for r in changes])
