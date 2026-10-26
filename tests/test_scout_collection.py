import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from contextlib import contextmanager
from unittest.mock import patch

from keel.core import Budget,Ledger,Limits,Trace,ModelError,ModelCompletionError,PolicyDenied
from keel.models import Reply
from keel.workspace import Workspace
from keel.scout_collection import SourceBoundModel,task_inputs,collect
from keel.scout_data_audit import _digest
from keel.scout_tokenizer import file_hash


class FakeTeacher:
    def __init__(self):self.calls=0
    def complete_json(self,messages,*,schema,timeout,max_output):
        self.calls+=1;data=json.loads(messages[-1]['content'])
        if 'files' in schema['properties']:value={'files':[data['paths'][0]]}
        else:
            first=data['structure'][0];value={'locations':[first['path']+':'+str(first['symbols'][0][0])]}
        return Reply(json.dumps(value),20)


class ScoutCollectionTests(unittest.TestCase):
    @contextmanager
    def temporary_directory(self):
        # Register directory cleanup first so later SQLite cleanups run before it
        # on Windows, where deleting an open database is forbidden.
        yield self.enterContext(tempfile.TemporaryDirectory())

    def setup_workspace(self,root):
        repo=root/'repo';repo.mkdir();(repo/'code.py').write_text('def first():\n    return 1\n')
        ledger=Ledger(root/'ledger.sqlite');self.addCleanup(ledger.close)
        return Workspace(repo,Budget(Limits()),ledger,Trace(root/'trace.jsonl'))

    def request(self):
        return [{'role':'system','content':'Select source only'},
                {'role':'user','content':json.dumps({'goal':'original issue','paths':['code.py']})}]

    def schema(self):return {'type':'object','properties':{'files':{'type':'array','items':{'type':'string'}}}}

    def test_actual_catalog_bytes_and_request_are_saved_without_changing_response(self):
        with self.temporary_directory() as tmp:
            root=Path(tmp);workspace=self.setup_workspace(root);teacher=FakeTeacher()
            model=SourceBoundModel(teacher,workspace,root/'capture',{'instance_id':'demo__demo-1'})
            reply=model.complete_json(self.request(),schema=self.schema(),timeout=10,max_output=512)
            self.assertEqual(json.loads(reply.content),{'files':['code.py']});self.assertEqual(teacher.calls,1)
            call=root/'capture/call-0001';binding=json.loads((call/'source-binding.json').read_text())
            source=binding['catalog_sources']['code.py'];self.assertEqual(Path(source['object']).read_bytes(),(workspace.root/'code.py').read_bytes())
            self.assertEqual(source['sha256'],hashlib.sha256(Path(source['object']).read_bytes()).hexdigest())
            events=[json.loads(line) for line in (root/'capture/model-transcript.jsonl').read_text().splitlines()]
            self.assertEqual([e['event'] for e in events],['request','response'])
            self.assertEqual(events[0]['args'][0],self.request());self.assertEqual(events[1]['content'],reply.content)
            self.assertFalse(binding['training_approved']);self.assertTrue(json.loads((call/'result.json').read_text())['source_stable'])

    def test_response_survives_source_drift_and_provider_error_is_not_logged_as_answer(self):
        with self.temporary_directory() as tmp:
            root=Path(tmp);workspace=self.setup_workspace(root)
            teacher=FakeTeacher();original=teacher.complete_json
            def mutate(*args,**kwargs):
                reply=original(*args,**kwargs);(workspace.root/'code.py').write_text('changed');return reply
            teacher.complete_json=mutate;model=SourceBoundModel(teacher,workspace,root/'capture',{})
            with self.assertRaisesRegex(ModelError,'Source changed'):model.complete_json(self.request(),schema=self.schema(),timeout=10,max_output=512)
            events=[json.loads(line) for line in (root/'capture/model-transcript.jsonl').read_text().splitlines()]
            self.assertEqual(events[-1]['event'],'response')
            self.assertFalse(json.loads((root/'capture/call-0001/result.json').read_text())['source_stable'])

    def test_checkpoint_failure_and_escaping_catalog_never_dispatch_provider(self):
        with self.temporary_directory() as tmp:
            root=Path(tmp);workspace=self.setup_workspace(root);teacher=FakeTeacher()
            model=SourceBoundModel(teacher,workspace,root/'capture',{})
            with patch('keel.scout_collection.atomic_json',side_effect=OSError('disk unavailable')):
                with self.assertRaises(OSError):model.complete_json(self.request(),schema=self.schema(),timeout=10,max_output=512)
            self.assertEqual(teacher.calls,0)
            messages=self.request();messages[-1]['content']=json.dumps({'paths':['../outside.py']})
            with self.assertRaises(PolicyDenied):model.complete_json(messages,schema=self.schema(),timeout=10,max_output=512)
            self.assertEqual(teacher.calls,0)

    def test_incomplete_paid_completion_keeps_partial_text_and_usage(self):
        with self.temporary_directory() as tmp:
            root=Path(tmp);workspace=self.setup_workspace(root);teacher=FakeTeacher()
            def incomplete(*args,**kwargs):
                raise ModelCompletionError('incomplete',tokens=17,diagnostics={'finish_reason':'length'},content='{"files":[')
            teacher.complete_json=incomplete;model=SourceBoundModel(teacher,workspace,root/'capture',{})
            with self.assertRaises(ModelCompletionError):model.complete_json(self.request(),schema=self.schema(),timeout=10,max_output=512)
            event=json.loads((root/'capture/model-transcript.jsonl').read_text().splitlines()[-1])
            self.assertEqual(event['event'],'error');self.assertEqual(event['partial_content'],'{"files":[')
            self.assertEqual(event['tokens'],17)

    def plan_fixture(self,root):
        workspace=self.setup_workspace(root)
        task={'instance_id':'demo__demo-1','repo':'demo/demo','base_commit':'a'*40,'problem_statement':'Original issue'}
        solver=root/'solver-task.json';solver.write_text(json.dumps(task))
        reservation=root/'reservation.json';reservation.write_text(json.dumps({'assignments':{'tasks':{
            'other__other-1':{'partition':'transfer_review'}}}}))
        exported=root/'export.json';exported.write_text(json.dumps({'samples':[]}))
        model_config=root/'model.json';model_config.write_text('{}')
        plan={'reservation':str(reservation),'training_export':str(exported),'model_config':str(model_config),
            'tasks':[{'solver_task':str(solver),'source_repository':str(workspace.root)}],
            'inputs':{str(p.resolve()):file_hash(p) for p in (solver,reservation,exported,model_config)},
            'budget':{'max_wallclock':60,'max_model_calls':6,'max_tokens':100000,'max_tool_calls':20},
            'settings':{'max_context_bytes':12000,'max_output':1024}}
        path=root/'plan.json';path.write_text(json.dumps(plan));prepared=root/'prepared';prepared.mkdir()
        (prepared/'preparation.json').write_text(json.dumps({'status':'prepared','plan_sha256':file_hash(path),
            'items':[{'task':task,'repo':str(workspace.root),'tree_sha256':_digest(workspace.snapshot())}]}))
        return plan,path,prepared

    def test_scout_only_collection_uses_shared_localization_and_never_approves_labels(self):
        with self.temporary_directory() as tmp:
            root=Path(tmp);_,path,prepared=self.plan_fixture(root);teacher=FakeTeacher()
            result=collect(path,prepared,root/'result',model=teacher)
            self.assertEqual(result['status'],'collected_pending_review');self.assertEqual(teacher.calls,2)
            self.assertEqual(result['budget']['model_calls'],2);self.assertEqual(result['training_approved'],0)
            self.assertEqual(result['tasks'][0]['selection']['locations'],{'code.py':[1]})
            self.assertFalse((root/'result/changes.patch').exists())

    def test_missing_credentials_before_output_and_reserved_task_before_dispatch(self):
        with self.temporary_directory() as tmp:
            root=Path(tmp);plan,path,prepared=self.plan_fixture(root);teacher=FakeTeacher()
            teacher.check_credentials=lambda:(_ for _ in ()).throw(ModelError('Missing credential'))
            with self.assertRaisesRegex(ModelError,'Missing'):collect(path,prepared,root/'result',model=teacher)
            self.assertFalse((root/'result').exists());self.assertEqual(teacher.calls,0)
            reservation=Path(plan['reservation']);reservation.write_text(json.dumps({'assignments':{'tasks':{
                'demo__demo-99':{'partition':'transfer_review'}}}}))
            with self.assertRaisesRegex(ValueError,'reserved repository'):task_inputs(plan)

    def test_explicit_resume_reuses_completed_calls_and_rejects_evidence_drift(self):
        with self.temporary_directory() as tmp:
            root=Path(tmp);_,path,prepared=self.plan_fixture(root);teacher=FakeTeacher()
            collect(path,prepared,root/'first',model=teacher)
            self.assertEqual(teacher.calls,2)
            # Reusing a wholly completed collection needs no new provider/key.
            teacher.check_credentials=lambda:(_ for _ in ()).throw(ModelError('Missing credential'))
            reused=collect(path,prepared,root/'second',model=teacher,resume_from=root/'first')
            self.assertEqual(teacher.calls,2);self.assertEqual(reused['budget']['model_calls'],0)
            self.assertEqual(reused['tasks'][0]['new_provider_calls'],0)
            transcript=root/'first/demo__demo-1/capture/model-transcript.jsonl'
            transcript.write_text('changed')
            with self.assertRaisesRegex(ValueError,'evidence changed'):
                collect(path,prepared,root/'third',model=teacher,resume_from=root/'first')
            self.assertFalse((root/'third').exists())
