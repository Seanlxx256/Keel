import json
from pathlib import Path
import sys
import tempfile
import unittest
from keel.models import Reply
from keel.runtime import run


class DiagnosticInspectionTests(unittest.TestCase):
    def trial(self, *, forged=False, insufficient=False, limit=6):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        root=Path(temp.name);(root/'module.py').write_bytes(b'def value():\n    return 1\n')
        (root/'tests').mkdir();(root/'tests/test_value.py').write_bytes(b'assert True\n')
        config={'mode':'localized-proposal','goal':'Return 2','require_diagnostic_inspection':True,
                'recovery':{'strategy':'adaptive','max_actions':6,'write_roots':['.']},
                'budget':{'max_model_calls':limit},'verification_repair_attempts':0,
                'continuation_context':{'verification':[{'returncode':1,'stdout':json.dumps({
                    'failed_tests':[{'test':'tests/test_value.py::test_value'}]})}],
                    'changes':{},'provenance':{}},
                'acceptance':[[sys.executable,'-B','-c','import module; assert module.value()==2']]}
        owner=self
        class Model:
            calls=0
            def complete_json(self,messages,**kwargs):
                self.calls+=1
                if self.calls==1:
                    value={'action':'replan','reason':'Inspect return path','hypothesis':'Wrong return',
                           'evidence':'Saved assertion failed','next_check':'Read current value function',
                           'previous_attempt_assessment':'Saved edit is incomplete'}
                elif self.calls==2:value={'files':['module.py']}
                elif self.calls==3:value={'locations':['module.py:1']}
                elif self.calls==4:
                    data=json.loads(messages[1]['content'])
                    owner.assertIn('tests/test_value.py',data['readable_paths'])
                    value={'checks':[{'path':'module.py','start_line':1,'end_line':2},
                                     {'path':'tests/test_value.py','start_line':1,'end_line':1}]}
                elif self.calls==5:
                    data=json.loads(messages[1]['content'])
                    owner.assertIn('return 1',str(data['observations']))
                    ids=[r['fact_id'] for r in data['observations']]
                    value={'outcome':'insufficient' if insufficient else 'supported',
                           'evidence_ids':[999999] if forged else ids,
                           'assessment':'Current source returns 1','next_step':'Correct the return value','checks':[]}
                else:
                    owner.assertIn('Fresh diagnostic inspection',str(messages))
                    owner.assertEqual((root/'module.py').read_bytes(),b'def value():\n    return 1\n')
                    value={'summary':'Change value','edits':[{'path':'module.py','old':'return 1','new':'return 2'}]}
                return Reply(json.dumps(value),10)
        model=Model();result=run(config,root,root/'.keel/run',model=model)
        return root,result,model

    def test_actual_read_evidence_precedes_proposal_and_uses_shared_budget(self):
        root,result,model=self.trial()
        self.assertEqual(result['status'],'passed',result.get('failure'))
        self.assertEqual(result['budget']['model_calls'],6)
        self.assertEqual(len(result['diagnostic_inspections']),1)
        self.assertEqual(result['audit']['changed_files'],['module.py'])
        self.assertEqual((root/'tests/test_value.py').read_bytes(),b'assert True\n')

    def test_fabricated_fact_citation_prevents_edits(self):
        root,result,model=self.trial(forged=True)
        self.assertEqual(result['failure']['category'],'model_error')
        self.assertEqual(model.calls,5)
        self.assertIn('return 1',(root/'module.py').read_text())

    def test_insufficient_evidence_stops_without_claiming_a_check_succeeded(self):
        root,result,model=self.trial(insufficient=True)
        self.assertEqual(result['failure']['category'],'recovery_stopped')
        self.assertEqual(model.calls,5)
        self.assertIn('return 1',(root/'module.py').read_text())

    def test_inspection_cannot_reset_model_budget_for_the_patch(self):
        root,result,model=self.trial(limit=5)
        self.assertEqual(result['failure']['category'],'budget_exhausted')
        self.assertEqual(model.calls,5)
        self.assertIn('return 1',(root/'module.py').read_text())


class AdaptiveInspectionPagingTests(unittest.TestCase):
    def setup_workspace(self, calls=10):
        from keel.workspace import Workspace
        from keel.core import Budget, Limits, Ledger, Trace
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        root=Path(temp.name)
        (root/'module.py').write_bytes(('VALUE = 1\n'+'# source\n'*84+'# target\n').encode())
        ledger=Ledger(root/'ledger.sqlite');self.addCleanup(ledger.close)
        ws=Workspace(root,Budget(Limits(max_model_calls=calls)),ledger,Trace(root/'trace.jsonl'))
        return ws

    def model(self,owner,mode):
        class Model:
            calls=0
            def complete_json(self,messages,**kwargs):
                self.calls+=1
                data=json.loads(messages[1]['content'])
                if self.calls==1:
                    end=86 if mode!='repeat' else 2
                    value={'checks':[{'path':'module.py','start_line':1,'end_line':end}]}
                else:
                    ids=[row['fact_id'] for row in data['observations']]
                    keep=self.calls==2 or mode in {'repeat','escape'}
                    checks=([{'path':'module.py','start_line':1,'end_line':2}] if mode=='repeat' else
                            [{'path':'../outside.py','start_line':1,'end_line':2}] if mode=='escape' else [])
                    value={'outcome':'continue' if keep else 'supported','evidence_ids':ids,
                           'assessment':'Need the remaining source to assess the hypothesis' if keep else 'Observed target source',
                           'next_step':'Inspect next source range' if keep else 'Use observed source',
                           'checks':checks if keep else []}
                    if self.calls==2 and mode=='pages':
                        owner.assertEqual(data['progress'][0]['read_end'],80)
                        owner.assertEqual(data['progress'][0]['remaining_lines'],6)
                        owner.assertEqual(data['pending_ranges'][0]['start_line'],81)
                    if self.calls==3 and mode=='pages':
                        owner.assertIn('# target',str(data['observations']))
                        owner.assertEqual(data['progress'][0]['remaining_lines'],0)
                return Reply(json.dumps(value),10)
        return Model()

    def inspect(self,ws,model):
        from keel.diagnostic_inspection import inspect_diagnosis
        return inspect_diagnosis(model,ws,'Inspect value',{'next_check':'Read target source'},[],
                                ['module.py'],{'max_context_bytes':24000})

    def test_86_lines_are_two_pages_with_model_visible_progress(self):
        ws=self.setup_workspace();model=self.model(self,'pages')
        result=self.inspect(ws,model)
        self.assertEqual(model.calls,3)
        self.assertEqual([row['read_end'] for row in result['progress']],[80,86])
        self.assertEqual(result['assessment']['outcome'],'supported')

    def test_repeated_ranges_do_not_create_progress_or_repeat_reads(self):
        from keel.core import RecoveryStopped
        ws=self.setup_workspace();model=self.model(self,'repeat')
        with self.assertRaisesRegex(RecoveryStopped,'without new source'):
            self.inspect(ws,model)
        self.assertEqual(model.calls,4)
        self.assertEqual(len([row for row in ws.ledger.summaries() if row['summary']=='read_lines evidence']),1)

    def test_continuation_remains_inside_global_budget(self):
        from keel.core import BudgetExceeded
        ws=self.setup_workspace(calls=2);model=self.model(self,'pages')
        with self.assertRaises(BudgetExceeded):self.inspect(ws,model)
        self.assertEqual(model.calls,2)
        self.assertEqual(ws.budget.report()['model_calls'],2)

    def test_continuation_cannot_expand_readable_paths(self):
        from keel.core import ModelError
        ws=self.setup_workspace();model=self.model(self,'escape')
        with self.assertRaisesRegex(ModelError,'outside supplied paths'):
            self.inspect(ws,model)
        self.assertEqual(model.calls,2)


class DiagnosticSearchNavigationTests(unittest.TestCase):
    setup_workspace = AdaptiveInspectionPagingTests.setup_workspace

    def inspect(self,ws,model,verification=None):
        from keel.diagnostic_inspection import inspect_diagnosis
        return inspect_diagnosis(model,ws,'Inspect behavior',{'next_check':'Locate the observed failing test and inspect implementation'},
                                verification or [],['module.py'],{'max_context_bytes':24000})

    def test_failed_symbol_is_located_before_model_guesses_line_numbers(self):
        ws=self.setup_workspace();(ws.root/'tests').mkdir()
        (ws.root/'tests/test_feature.py').write_bytes(('# padding\n'*2000+'def test_behavior():\n    assert True\n').encode())
        owner=self
        class Model:
            calls=0
            def complete_json(self,messages,**kwargs):
                self.calls+=1;data=json.loads(messages[1]['content'])
                if self.calls==1:
                    owner.assertEqual(data['target_locations'][0]['definition_lines'],[2001])
                    value={'checks':[{'path':'tests/test_feature.py','start_line':2001,'end_line':2002}]}
                else:
                    owner.assertIn('def test_behavior',str(data['observations']))
                    value={'outcome':'supported','evidence_ids':[data['observations'][0]['fact_id']],
                           'assessment':'Located the actual failed definition','next_step':'Use the observed behavior','checks':[]}
                return Reply(json.dumps(value),10)
        model=Model()
        self.inspect(ws,model,[{'stdout':json.dumps({'failed_tests':[{'test':'tests/test_feature.py::test_behavior'}]})}])
        self.assertEqual(model.calls,2)
        rows=[r for r in ws.ledger.summaries() if r['summary']=='read_lines evidence']
        self.assertEqual(len(rows),1)
        self.assertEqual(ws.ledger.recall(rows[0]['fact_id'])['start_line'],2001)

    def test_model_can_search_then_read_only_the_hit(self):
        ws=self.setup_workspace();owner=self
        class Model:
            calls=0
            def complete_json(self,messages,**kwargs):
                self.calls+=1;data=json.loads(messages[1]['content'])
                if self.calls==1:value={'checks':[{'path':'module.py','query':'# target'}]}
                elif self.calls==2:
                    owner.assertEqual(data['observations'][0]['matches'][0]['line'],86)
                    value={'outcome':'continue','evidence_ids':[data['observations'][0]['fact_id']],
                           'assessment':'Search located the requested source','next_step':'Read the matched line',
                           'checks':[{'path':'module.py','start_line':86,'end_line':86}]}
                else:
                    value={'outcome':'supported','evidence_ids':[data['observations'][0]['fact_id']],
                           'assessment':'Observed target source','next_step':'Use the inspected source','checks':[]}
                return Reply(json.dumps(value),10)
        result=self.inspect(ws,Model())
        self.assertEqual(result['evidence'][0]['start_line'],86)

    def test_new_lines_do_not_justify_scanning_past_an_unresolved_known_target(self):
        from keel.core import RecoveryStopped
        ws=self.setup_workspace();(ws.root/'tests').mkdir()
        (ws.root/'tests/test_feature.py').write_bytes(('# padding\n'*2000+'def test_behavior():\n    assert True\n').encode())
        class Model:
            calls=0
            def complete_json(self,messages,**kwargs):
                self.calls+=1;data=json.loads(messages[1]['content'])
                start=1 if self.calls==1 else 81 if self.calls==2 else 161
                checks=[{'path':'tests/test_feature.py','start_line':start,'end_line':start+79}]
                value=({'checks':checks} if self.calls==1 else {'outcome':'continue','checks':checks,
                       'evidence_ids':[data['observations'][0]['fact_id']],
                       'assessment':'Still missing the same test','next_step':'Scan further'})
                return Reply(json.dumps(value),10)
        model=Model()
        with self.assertRaisesRegex(RecoveryStopped,'strategy stalled'):
            self.inspect(ws,model,[{'stdout':json.dumps({'failed_tests':[{'test':'tests/test_feature.py::test_behavior'}]})}])
        self.assertEqual(model.calls,3)

    def test_scoped_search_excludes_other_files_and_enforces_metadata_policy(self):
        from keel.gateway import ToolGateway
        from keel.core import PolicyDenied
        ws=self.setup_workspace();(ws.root/'other.py').write_bytes(b'# target elsewhere\n')
        gateway=ToolGateway('scout',ws)
        result=gateway.call('search_code',{'query':'target','paths':['module.py']})
        matches=ws.ledger.recall(result['fact_id'])['matches']
        self.assertEqual({m['file'] for m in matches},{'module.py'})
        with self.assertRaises(PolicyDenied):gateway.call('search_code',{'query':'target','paths':['.git/config']})

    def test_search_hit_alone_cannot_claim_completed_source_inspection(self):
        from keel.core import RecoveryStopped
        ws=self.setup_workspace()
        class Model:
            calls=0
            def complete_json(self,messages,**kwargs):
                self.calls+=1;data=json.loads(messages[1]['content'])
                value=({'checks':[{'path':'module.py','query':'# target'}]} if self.calls==1 else
                       {'outcome':'supported','evidence_ids':[data['observations'][0]['fact_id']],
                        'assessment':'Search hit is enough','next_step':'Edit now','checks':[]})
                return Reply(json.dumps(value),10)
        with self.assertRaisesRegex(RecoveryStopped,'no cited source window'):
            self.inspect(ws,Model())


class DiagnosticEvidenceRetentionTests(unittest.TestCase):
    setup_workspace = AdaptiveInspectionPagingTests.setup_workspace
    inspect = DiagnosticSearchNavigationTests.inspect

    def test_read_search_replay_retains_source_without_new_reads_or_progress(self):
        ws=self.setup_workspace();owner=self
        class Model:
            calls=0
            source_id=None
            def complete_json(self,messages,**kwargs):
                self.calls+=1;data=json.loads(messages[1]['content'])
                if self.calls==1:
                    value={'checks':[{'path':'module.py','start_line':1,'end_line':2}]}
                else:
                    source=[r for r in data['observations'] if r.get('kind')!='search']
                    owner.assertIn('VALUE = 1',source[0]['text'])
                    if self.source_id is None:self.source_id=source[0]['fact_id']
                    owner.assertEqual(source[0]['fact_id'],self.source_id)
                    if self.calls==2:
                        checks=[{'path':'module.py','query':'target'}]
                    elif self.calls==3:
                        owner.assertTrue(any(r.get('kind')=='search' for r in data['observations']))
                        checks=[{'path':'module.py','start_line':1,'end_line':2}]
                    else:
                        owner.assertEqual(data['new_lines'],0)
                        owner.assertEqual(data['no_progress_rounds'],1)
                        owner.assertEqual(data['progress'][0]['status'],'already_observed')
                        owner.assertIn(self.source_id,data['progress'][0]['replayed_fact_ids'])
                        checks=[]
                    value={'outcome':'continue' if checks else 'supported','evidence_ids':[self.source_id],
                           'assessment':'Actual source body remains available','next_step':'Inspect context' if checks else 'Use source',
                           'checks':checks}
                return Reply(json.dumps(value),10)
        result=self.inspect(ws,Model())
        self.assertEqual(result['assessment']['outcome'],'supported')
        self.assertEqual(len([r for r in ws.ledger.summaries() if r['summary']=='read_lines evidence']),1)
        self.assertEqual(len([r for r in ws.ledger.summaries() if r['summary']=='search_code evidence']),1)

    def test_bounded_retention_explicitly_lists_omitted_bodies_and_can_recall_old_range(self):
        from keel.diagnostic_inspection import inspection_observations
        evidence=[{'fact_id':i+1,'path':'module.py','start_line':i*80+1,'end_line':i*80+80,
                   'text':f'page {i}','source_sha256':'a'*64} for i in range(5)]
        shown,omitted=inspection_observations(evidence,[],[{'path':'module.py','start_line':82,'end_line':90}],None)
        self.assertLessEqual(len(shown),3)
        self.assertEqual(shown[0]['fact_id'],2)
        self.assertEqual({r['fact_id'] for r in shown}|set(omitted),{1,2,3,4,5})

    def test_stale_cached_source_is_not_replayed_after_file_changes(self):
        from keel.core import ModelError
        ws=self.setup_workspace()
        class Model:
            calls=0
            def complete_json(self,messages,**kwargs):
                self.calls+=1;data=json.loads(messages[1]['content'])
                if self.calls==1:value={'checks':[{'path':'module.py','start_line':1,'end_line':2}]}
                else:
                    (ws.root/'module.py').write_bytes(b'VALUE = 99\n')
                    value={'outcome':'continue','evidence_ids':[data['observations'][0]['fact_id']],
                           'assessment':'Request same source','next_step':'Read again',
                           'checks':[{'path':'module.py','start_line':1,'end_line':2}]}
                return Reply(json.dumps(value),10)
        with self.assertRaisesRegex(ModelError,'source changed'):
            self.inspect(ws,Model())
