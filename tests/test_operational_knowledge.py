from contextlib import closing
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

from keel.core import Budget,Limits,Ledger,Trace
from keel.evaluation_protocol import file_hash
from keel.models import Reply
from keel.operational_knowledge import OperationalKnowledge,RuntimeKnowledge,attach,context,failure_features
from keel.workspace import Workspace


class OperationalKnowledgeTests(unittest.TestCase):
    def test_typed_policy_rejection_does_not_require_error_suffix(self):
        from keel.core import PolicyDenied
        self.assertIn('PolicyDenied',failure_features('diagnostic','diagnostic_probe',{'error_type':'PolicyDenied'})['error_type'])
        self.assertIn('PolicyDenied',failure_features('diagnostic','diagnostic_probe',PolicyDenied('not allowed'))['error_type'])

    def test_explicit_episode_migration_is_idempotent_and_never_imports_cards(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source,card=self.prepared(root)
            source.record('run','fingerprint','operational_retrieval','observed',
                {'features':failure_features('diagnostic','candidate_imports',ImportError('x')),
                 'cards':[[card['id'],1]],'catalog_sha256':source.catalog_hash(),'raw_log':'DO NOT COPY'})
            target=OperationalKnowledge(root/'shared.sqlite');before=target.catalog_hash()
            value=target.import_episodes(source.path)
            self.assertEqual(value['imported'],1);self.assertEqual(target.latest(),[])
            self.assertEqual(target.catalog_hash(),before)
            self.assertEqual(target.import_episodes(source.path)['duplicates'],1)
            with target.connect() as db:
                rows=db.execute('SELECT evidence FROM attempts').fetchall()
            self.assertEqual(len(rows),1);self.assertNotIn('DO NOT COPY',str(rows))

    def test_malformed_episode_batch_is_rejected_before_any_import(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=OperationalKnowledge(root/'source.sqlite')
            source.record('run','signature','runtime_outcome','failed',{'cards':[]})
            source.record('run','signature','operational_retrieval','observed',{'cards':[],'features':'raw prose'})
            target=OperationalKnowledge(root/'target.sqlite')
            with self.assertRaises(ValueError):target.import_episodes(source.path)
            with target.connect() as db:self.assertEqual(db.execute('SELECT count(*) FROM attempts').fetchone()[0],0)

    def test_diagnostic_request_retrieves_matching_failure_advice(self):
        from keel.diagnostic_probe import investigate
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            store,card=self.prepared(root,match={'stage':['diagnostic'],'tool':['candidate_imports'],'error_type':['ImportError']})
            repo=root/'repo';repo.mkdir();(repo/'failure.txt').write_text('ImportError: missing parent')
            owner=self
            class Model:
                def complete_json(self,messages,**kwargs):
                    data=json.loads(messages[1]['content'])
                    owner.assertEqual(data['operational_knowledge']['cards'][0]['id'],card['id'])
                    return Reply(json.dumps({'action':'answer','path':'','query':'','code':'','start_line':0,'end_line':0,
                        'reason':'Historical failure needs a fresh check','conclusion':'unknown',
                        'answer':'Current cause not established','evidence_ids':['source-0']}),20)
            with closing(Ledger(root/'ledger.sqlite')) as ledger:
                ws=Workspace(repo,Budget(Limits()),ledger,Trace(root/'trace.jsonl'))
                attach(ws,{'path':str(root/'knowledge.sqlite')},'diagnostic')
                result=investigate(Model(),ws,'Investigate imports','Which provider failed?',
                    [{'path':'failure.txt','text':'ImportError: missing parent'}],{},candidate_imports=True,max_model_calls=1)
                self.assertEqual(ws.budget.model_calls,1)
                self.assertEqual(result['assessment']['conclusion'],'unknown')

    def test_store_cannot_write_inside_candidate_workspace(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);repo=root/'repo';repo.mkdir()
            with closing(Ledger(root/'ledger.sqlite')) as ledger:
                ws=Workspace(repo,Budget(Limits()),ledger,Trace(root/'trace.jsonl'))
                with self.assertRaisesRegex(ValueError,'outside'):
                    attach(ws,{'path':str(repo/'knowledge.sqlite')},'run')
            self.assertFalse((repo/'knowledge.sqlite').exists())

    def card(self,root,**overrides):
        proof=root/'proof.json';implementation=root/'tool.py'
        proof.write_bytes(b'{"controlled_validation":true}\n');implementation.write_bytes(b'VERSION=1\n')
        return {'id':'inspect-context','revision':1,'scope':'operational',
            'match':{'stage':['verification'],'error_type':['AssertionError']},
            'guidance':'Use current observations; historical advice does not establish the cause.',
            'checks':['Run fresh acceptance after changing source.'],
            'evidence':[{'path':str(proof),'sha256':file_hash(proof)}],
            'compatibility':[{'path':str(implementation),'sha256':file_hash(implementation)}],**overrides}

    def prepared(self,root,**overrides):
        store=OperationalKnowledge(root/'knowledge.sqlite');card=self.card(root,**overrides)
        store.register(card);store.promote(card['id'],card['revision'])
        return store,card

    def test_candidates_require_review_and_deprecation_does_not_fall_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);store=OperationalKnowledge(root/'knowledge.sqlite');card=self.card(root)
            query=failure_features('verification','verification',AssertionError('failed'))
            store.register(card);self.assertEqual(store.retrieve(query)['cards'],[])
            store.promote(card['id'],1);self.assertEqual(len(store.retrieve(query)['cards']),1)
            next_card={**card,'revision':2};store.register(next_card)
            self.assertEqual(store.retrieve(query)['cards'],[])
            store.promote(card['id'],2);store.deprecate(card['id'],2)
            self.assertEqual(store.retrieve(query)['cards'],[])
            with self.assertRaises(ValueError):store.register(card)

    def test_exact_applicability_and_stale_evidence_are_excluded(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);store,card=self.prepared(root)
            self.assertFalse(store.retrieve(failure_features('diagnostic','verification',AssertionError('x')))['cards'])
            self.assertFalse(store.retrieve(failure_features('verification','verification',ImportError('x')))['cards'])
            Path(card['compatibility'][0]['path']).write_bytes(b'VERSION=2\n')
            result=store.retrieve(failure_features('verification','verification',AssertionError('x')))
            self.assertFalse(result['cards']);self.assertEqual(result['excluded'][0]['reason'],'evidence_or_implementation_changed')

    def test_promotion_checks_actual_proof_and_runtime_hashes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);store=OperationalKnowledge(root/'knowledge.sqlite');card=self.card(root);store.register(card)
            Path(card['evidence'][0]['path']).write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError,'changed'):store.promote(card['id'],1)

    def test_retrieval_capacity_omits_whole_cards_without_truncating_advice(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);store,card=self.prepared(root,guidance='x'*800)
            result=store.retrieve(failure_features('verification','verification',AssertionError('x')),max_bytes=256)
            self.assertEqual(result['cards'],[])
            self.assertEqual(result['excluded'][0]['reason'],'request_capacity')

    def test_attempts_accumulate_without_promoting_or_changing_catalog(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);store,card=self.prepared(root);identity=store.catalog_hash()
            repo=root/'repo';repo.mkdir()
            with closing(Ledger(root/'ledger.sqlite')) as ledger:
                ws=Workspace(repo,Budget(Limits()),ledger,Trace(root/'trace.jsonl'))
                attach(ws,{'path':str(root/'knowledge.sqlite'),'catalog_sha256':identity},'run-one')
                value=context(ws,'verification','verification',AssertionError('secret not persisted'))
                self.assertEqual(value['cards'][0]['id'],card['id'])
                ws.operational_knowledge.finish('failed')
            self.assertEqual(store.catalog_hash(),identity)
            with store.connect() as db:rows=db.execute('SELECT action,outcome,evidence FROM attempts').fetchall()
            self.assertEqual(len(rows),2);self.assertNotIn('secret not persisted',str(rows))
            self.assertEqual(store.latest()[0][2],'verified')

    def test_catalog_changes_and_storage_errors_do_not_inject_new_advice(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);store,card=self.prepared(root)
            repo=root/'repo';repo.mkdir()
            with closing(Ledger(root/'ledger.sqlite')) as ledger:
                ws=Workspace(repo,Budget(Limits()),ledger,Trace(root/'trace.jsonl'))
                attach(ws,{'path':str(root/'knowledge.sqlite')},'run')
                store.deprecate(card['id'],1)
                value=context(ws,'verification','verification',AssertionError('x'))
                self.assertEqual(value['status'],'unavailable');self.assertEqual(value['cards'],[])
                with patch.object(ledger,'add',side_effect=OSError('required checkpoint failed')):
                    with self.assertRaises(OSError):context(ws,'verification','verification',AssertionError('x'))

    def test_unavailable_optional_store_does_not_disable_local_result_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);repo=root/'repo';repo.mkdir()
            with patch('keel.operational_knowledge.OperationalKnowledge',side_effect=sqlite3.OperationalError('locked')):
                memory=RuntimeKnowledge({'path':str(root/'store.sqlite')},'run')
            with closing(Ledger(root/'ledger.sqlite')) as ledger:
                ws=Workspace(repo,Budget(Limits()),ledger,Trace(root/'trace.jsonl'));ws.operational_knowledge=memory
                self.assertEqual(context(ws,'verification','verification',[])['status'],'unavailable')
                self.assertTrue(ledger.summaries())

    def test_runtime_recovery_injects_reviewed_advice_without_extra_model_calls(self):
        from keel.runtime import run
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);store,card=self.prepared(root);repo=root/'repo';repo.mkdir()
            (repo/'app.py').write_bytes(b'def value():\n    return 1\n')
            critic={'action':'repair',**{key:'unknown; verify against current observations' for key in
                ('reason','hypothesis','evidence','next_check','previous_attempt_assessment')}}
            replies=[{'files':['app.py']},{'locations':['app.py:1']},
                     {'summary':'first candidate','edits':[{'path':'app.py','old':'return 1','new':'return 3'}]},
                     critic,{'summary':'correct candidate','edits':[{'path':'app.py','old':'return 3','new':'return 2'}]}]
            owner=self
            class Model:
                calls=0
                def complete_json(self,messages,**kwargs):
                    self.calls+=1
                    if self.calls==4:
                        payload=json.loads(messages[1]['content'])
                        owner.assertEqual(payload['operational_knowledge']['cards'][0]['id'],card['id'])
                    return Reply(json.dumps(replies[self.calls-1]),20)
            config={'mode':'localized-proposal','goal':'Return two','agent':{'max_context_bytes':24000,'max_output':1024},
                    'budget':{'max_model_calls':5,'max_tokens':100000,'max_tool_calls':80,'max_wallclock':30},
                    'recovery':{'strategy':'adaptive','max_actions':4,'write_roots':['.']},
                    'verification_repair_attempts':1,'operational_knowledge':{'path':str(root/'knowledge.sqlite'),'catalog_sha256':store.catalog_hash()},
                    'acceptance':[[sys.executable,'-B','-c','import app; assert app.value()==2, "wrong result"']]}
            model=Model();result=run(config,repo,root/'run',model=model)
            self.assertEqual(result['status'],'passed');self.assertEqual(model.calls,5)
            self.assertEqual(result['operational_knowledge']['matched_cards'],[{'id':card['id'],'revision':1}])
            self.assertEqual(result['budget']['model_calls'],5)
