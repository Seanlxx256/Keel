from contextlib import closing
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from keel.core import Budget, BudgetExceeded, Ledger, Limits, PolicyDenied, RecoveryStopped, Trace
from keel.diagnostic_probe import investigate, run_probe, BOOTSTRAP, probe_outcome
from keel.execution import CommandRunner
from keel.models import Reply
from keel.workspace import Workspace


class ProbeTests(unittest.TestCase):
    def test_unavailable_probe_is_removed_from_schema_and_corrected_without_execution(self):
        owner=self
        with tempfile.TemporaryDirectory() as temp, closing(Ledger(Path(temp)/'facts.sqlite')) as ledger:
            root=Path(temp)/'repo';root.mkdir();ws=self.fixture(root,ledger)
            class Model:
                calls=0
                def complete_json(self,messages,**kwargs):
                    self.calls+=1;data=json.loads(messages[1]['content'])
                    owner.assertEqual('probe' in kwargs['schema']['properties']['action']['enum'],data['probe_available'])
                    if self.calls==3:
                        owner.assertIn('NOT executed',data['observations'][-1]['text'])
                        value=owner.action('answer');value['evidence_ids']=data['current_question_execution_ids']
                        return Reply(json.dumps(value),10)
                    value=owner.action();value['code']=f'print({self.calls})'
                    return Reply(json.dumps(value),10)
            with patch('keel.diagnostic_probe.run_probe',return_value={'kind':'execution','outcome':'completed'}) as probe:
                result=investigate(Model(),ws,'Inspect','Question',[],{},
                    execution={'backend':'docker','image':'image'},python='/python',require_probe=True,max_model_calls=3)
            self.assertEqual(probe.call_count,1)
            self.assertEqual(ws.budget.model_calls,3)
            self.assertEqual(result['closure']['state'],'diagnosis_ready')

    def test_candidate_receipt_needs_matching_module_hash(self):
        from keel.diagnostic_probe import candidate_execution
        manifest={'sample':{'sha256':'expected'}}
        value={'module':'sample','function':'run','line':1,'sha256':'wrong'}
        observation={'probe':{'stderr':'__KEEL_CANDIDATE_CALLS__'+json.dumps([value])}}
        self.assertEqual(candidate_execution(observation,manifest)['state'],'not_observed')
        value['sha256']='expected'
        observation['probe']['stderr']='__KEEL_CANDIDATE_CALLS__'+json.dumps([value])
        self.assertEqual(candidate_execution(observation,manifest)['state'],'observed')

    def test_surrogate_probe_cannot_close_and_can_correct_to_candidate_call(self):
        owner=self
        with tempfile.TemporaryDirectory() as temp, closing(Ledger(Path(temp)/'facts.sqlite')) as ledger:
            root=Path(temp)/'repo';root.mkdir();ws=self.fixture(root,ledger)
            class Model:
                calls=0
                def complete_json(self,messages,**kwargs):
                    self.calls+=1;data=json.loads(messages[1]['content'])
                    value=owner.action('answer' if self.calls==3 else 'probe')
                    if self.calls==2:
                        owner.assertEqual(data['current_question_execution_ids'],[])
                        owner.assertTrue(data['failed_probe_correction_available'])
                    if self.calls<3:value['code']=f'print({self.calls})'
                    else:value['evidence_ids']=data['current_question_execution_ids']
                    return Reply(json.dumps(value),10)
            observations=[{'kind':'execution','outcome':'completed','candidate_execution':{'state':'not_observed'}},
                          {'kind':'execution','outcome':'completed','candidate_execution':{'state':'observed','calls':[{'function':'actual'}]}}]
            with patch('keel.diagnostic_probe.run_probe',side_effect=observations) as probe:
                result=investigate(Model(),ws,'Inspect','Question',[{'path':'sample.py','text':'value=1'}],{},
                    execution={'backend':'docker','image':'image'},python='/python',require_probe=True,
                    candidate_imports=True,correct_failed_probe=True,require_candidate_execution=True)
            self.assertEqual(probe.call_count,2)
            self.assertEqual(result['closure']['state'],'diagnosis_ready')
            self.assertEqual(ws.budget.model_calls,3)

    def test_citation_correction_reuses_execution_without_repeating_probe(self):
        owner=self
        with tempfile.TemporaryDirectory() as temp, closing(Ledger(Path(temp)/'facts.sqlite')) as ledger:
            root=Path(temp)/'repo';root.mkdir();ws=self.fixture(root,ledger)
            class Model:
                calls=0
                def complete_json(self,messages,**kwargs):
                    self.calls+=1;data=json.loads(messages[1]['content'])
                    owner.assertEqual(kwargs['schema']['properties']['evidence_ids']['items']['enum'],
                                      data['available_evidence_ids'])
                    value=owner.action('probe' if self.calls==1 else 'answer')
                    if self.calls==2:value['evidence_ids']=['evidence-2','observation-1']
                    if self.calls==3:
                        owner.assertFalse(data['probe_available'])
                        owner.assertIn('do not repeat',data['observations'][-1]['text'])
                        value['evidence_ids']=data['current_question_execution_ids']
                    return Reply(json.dumps(value),10)
            with patch('keel.diagnostic_probe.run_probe',return_value={'kind':'execution','outcome':'completed'}) as executor:
                result=investigate(Model(),ws,'Inspect','Question',[{'path':'sample.py','text':'value=1'}],{},
                    execution={'backend':'docker','image':'image'},python='/python',require_probe=True,max_model_calls=3)
                self.assertEqual(executor.call_count,1)
                self.assertEqual(ws.budget.model_calls,3)
                self.assertEqual(result['closure']['state'],'diagnosis_ready')

    def test_repeated_unknown_citation_stops_without_execution(self):
        owner=self
        with tempfile.TemporaryDirectory() as temp, closing(Ledger(Path(temp)/'facts.sqlite')) as ledger:
            root=Path(temp)/'repo';root.mkdir();ws=self.fixture(root,ledger)
            class Model:
                def complete_json(self,*args,**kwargs):
                    value=owner.action('answer');value['evidence_ids']=['invented-id']
                    return Reply(json.dumps(value),10)
            with patch('keel.diagnostic_probe.run_probe') as executor:
                with self.assertRaisesRegex(RecoveryStopped,'Repeated unknown'):
                    investigate(Model(),ws,'Inspect','Question',[],{},
                        execution={'backend':'docker','image':'image'},python='/python',require_probe=True)
                executor.assert_not_called()
                self.assertEqual(ws.budget.model_calls,2)

    def test_required_continuation_cannot_finish_using_only_historical_execution(self):
        owner = self
        with tempfile.TemporaryDirectory() as temp, closing(Ledger(Path(temp)/'facts.sqlite')) as ledger:
            root = Path(temp)/'repo'; root.mkdir(); ws = self.fixture(root, ledger)
            class Model:
                calls = 0
                def complete_json(self, messages, **kwargs):
                    self.calls += 1; data = json.loads(messages[1]['content'])
                    value = owner.action('probe' if self.calls == 2 else 'answer')
                    value['evidence_ids'] = ['prior-execution-0']
                    if self.calls == 1:
                        from keel.decision_guidance import DECISION_QUESTIONS
                        owner.assertEqual(data['decision_questions'], DECISION_QUESTIONS)
                        owner.assertNotIn('answer', kwargs['schema']['properties']['action']['enum'])
                        owner.assertEqual(data['current_question_execution_ids'], [])
                    if self.calls == 2: value['code'] = 'print(2)'
                    if self.calls == 3: value['evidence_ids'] = data['current_question_execution_ids']
                    return Reply(json.dumps(value), 10)
            with patch('keel.diagnostic_probe.run_probe', return_value={'kind':'execution','outcome':'completed'}) as run:
                report = investigate(Model(), ws, 'New question', 'Inspect', [], {},
                    execution={'backend':'docker','image':'image'}, python='/python', require_probe=True,
                    continue_successful_probe=True,
                    prior_probe_observations=[{'kind':'execution','outcome':'completed','code':'print(1)'}])
                self.assertEqual(run.call_count, 1)
                self.assertEqual(report['new_probe_attempts'], 1)
                self.assertEqual(ws.budget.model_calls, 3)

    def test_required_answer_must_cite_fresh_execution_not_just_source(self):
        owner = self
        with tempfile.TemporaryDirectory() as temp, closing(Ledger(Path(temp)/'facts.sqlite')) as ledger:
            root = Path(temp)/'repo'; root.mkdir(); ws = self.fixture(root, ledger)
            class Model:
                calls = 0
                def complete_json(self, messages, **kwargs):
                    self.calls += 1; data = json.loads(messages[1]['content'])
                    value = owner.action('probe' if self.calls == 1 else 'answer')
                    value['evidence_ids'] = (data['current_question_execution_ids']
                                             if self.calls == 3 else ['source-0'])
                    return Reply(json.dumps(value), 10)
            with patch('keel.diagnostic_probe.run_probe', return_value={'kind':'execution','outcome':'completed'}) as run:
                investigate(Model(), ws, 'Inspect', 'Question', [{'path':'sample.py','text':'value=1'}], {},
                    execution={'backend':'docker','image':'image'}, python='/python', require_probe=True)
                self.assertEqual(run.call_count, 1)
                self.assertEqual(ws.budget.model_calls, 3)

    def test_incompatible_historical_probe_is_rejected_before_model_dispatch(self):
        from examples.review_saved_diagnosis import execute
        from keel.evaluation_protocol import file_hash
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=root/'source.py';source.write_bytes(b'value=1\n')
            image='sha256:'+'b'*64
            plan={'mode':'diagnostic_probe_pair','arms':['probe'],'probe_policy':'required',
                  'probe_image':image,'probe_python':'/python','scope':'Fixture',
                  'diagnosis':{'action':'replan','reason':'Inspect','hypothesis':'Value', 'evidence':'Source',
                               'next_check':'Inspect','previous_attempt_assessment':'Not checked'},
                  'source_files':{'sample.py':str(source)},'frozen_files':{str(source):file_hash(source)},
                  'prior_probe_image_id':image,
                  'prior_probe_observations':[{'candidate_manifest':{'sample':{'sha256':'wrong'}}}]}
            p=root/'plan.json';p.write_text(json.dumps(plan));p.with_suffix('.sha256').write_text(file_hash(p))
            class Inspected:
                returncode=0;stdout=image
            with patch('examples.review_saved_diagnosis.subprocess.run',return_value=Inspected()):
                with self.assertRaisesRegex(ValueError,'source mismatch'):
                    execute(p,root/'out',model=object())

    def test_successful_probe_can_drive_one_cited_followup_inside_existing_budget(self):
        owner=self
        with tempfile.TemporaryDirectory() as temp, closing(Ledger(Path(temp)/'facts.sqlite')) as ledger:
            root=Path(temp)/'repo';root.mkdir();ws=self.fixture(root,ledger)
            class Model:
                calls=0
                def complete_json(self,messages,**kwargs):
                    self.calls+=1;data=json.loads(messages[1]['content'])
                    value=owner.action('answer' if self.calls==3 else 'probe')
                    if self.calls==2:owner.assertTrue(data['successful_probe_followup_available'])
                    if self.calls>1:value['evidence_ids']=[data['observations'][-1]['evidence_id']]
                    if value['action']=='probe':value['code']=f'print({self.calls})'
                    return Reply(json.dumps(value),10)
            with patch('keel.diagnostic_probe.run_probe',return_value={'kind':'execution','outcome':'completed'}) as run:
                report=investigate(Model(),ws,'Inspect','Question',[{'path':'sample.py','text':'value=1'}],{},
                    execution={'backend':'docker','image':'image'},python='/python',continue_successful_probe=True)
                self.assertEqual(run.call_count,2);self.assertEqual(ws.budget.model_calls,3)
                self.assertEqual(report['new_probe_attempts'],2)

    def test_prior_receipted_observation_avoids_repeating_completed_probe(self):
        owner=self
        with tempfile.TemporaryDirectory() as temp, closing(Ledger(Path(temp)/'facts.sqlite')) as ledger:
            root=Path(temp)/'repo';root.mkdir();ws=self.fixture(root,ledger)
            class Model:
                calls=0
                def complete_json(self,messages,**kwargs):
                    self.calls+=1;data=json.loads(messages[1]['content'])
                    value=owner.action('probe' if self.calls==1 else 'answer')
                    value['evidence_ids']=[data['observations'][-1]['evidence_id']]
                    value['code']='print(2)' if self.calls==1 else ''
                    return Reply(json.dumps(value),10)
            with patch('keel.diagnostic_probe.run_probe',return_value={'kind':'execution','outcome':'completed'}) as run:
                report=investigate(Model(),ws,'Inspect','Question',[{'path':'sample.py','text':'value=1'}],{},
                    execution={'backend':'docker','image':'image'},python='/python',continue_successful_probe=True,
                    prior_probe_observations=[{'kind':'execution','outcome':'completed','code':'print(1)','probe':{'stdout':'1'}}])
                self.assertEqual(run.call_count,1);self.assertEqual(ws.budget.model_calls,2)
                self.assertEqual(report['prior_probe_attempts'],1);self.assertEqual(report['new_probe_attempts'],1)

    def test_successful_followup_must_reference_prior_execution(self):
        owner=self
        with tempfile.TemporaryDirectory() as temp, closing(Ledger(Path(temp)/'facts.sqlite')) as ledger:
            root=Path(temp)/'repo';root.mkdir();ws=self.fixture(root,ledger)
            class Model:
                def complete_json(self,*args,**kwargs):return Reply(json.dumps(owner.action()),10)
            with patch('keel.diagnostic_probe.run_probe') as run:
                with self.assertRaisesRegex(ValueError,'cite the preceding'):
                    investigate(Model(),ws,'Inspect','Question',[],{},execution={'backend':'docker','image':'image'},
                        python='/python',continue_successful_probe=True,
                        prior_probe_observations=[{'kind':'execution','outcome':'completed','code':'old'}])
                run.assert_not_called()

    def test_child_error_is_not_hidden_by_successful_wrapper(self):
        self.assertEqual(probe_outcome({'execution':{'returncode':0,'timeout':False},
                                      'probe':{'returncode':1,'timeout':False}}),'script_failed')
        self.assertEqual(probe_outcome({'execution':{'returncode':1,'timeout':False}}),'executor_failed')

    def correction(self, *, second_fails=False, limit=3):
        owner=self
        with tempfile.TemporaryDirectory() as temp, closing(Ledger(Path(temp)/'facts.sqlite')) as ledger:
            root=Path(temp)/'repo';root.mkdir();ws=self.fixture(root,ledger);ws.budget.limits.max_model_calls=limit
            class Model:
                calls=0
                def complete_json(self,messages,**kwargs):
                    self.calls+=1;data=json.loads(messages[1]['content'])
                    if self.calls==2:owner.assertTrue(data['failed_probe_correction_available'])
                    value=owner.action('answer' if self.calls==3 and not second_fails else 'probe')
                    if value['action']=='probe':value['code']=f'print({self.calls})'
                    else:value['evidence_ids']=[data['observations'][-1]['evidence_id']]
                    return Reply(json.dumps(value),10)
            rows=[{'kind':'execution','outcome':'script_failed'},
                  {'kind':'execution','outcome':'script_failed' if second_fails else 'completed'}]
            model=Model();error=None;report=None
            with patch('keel.diagnostic_probe.run_probe',side_effect=rows) as run:
                try:report=investigate(model,ws,'Inspect','Question',[{'path':'sample.py','text':'value=1'}],{},
                    execution={'backend':'docker','image':'image'},python='/python',require_probe=True,
                    candidate_imports=True,correct_failed_probe=True)
                except (PolicyDenied,BudgetExceeded) as exc:error=exc
                return report,error,run.call_count,ws.budget.model_calls

    def test_failed_child_allows_one_different_probe_without_resetting_budget(self):
        report,error,runs,calls=self.correction()
        self.assertIsNone(error);self.assertEqual(runs,2);self.assertEqual(calls,3)
        self.assertEqual(report['probe_attempts'],2)

    def test_second_failed_probe_cannot_get_a_third_execution(self):
        report,error,runs,calls=self.correction(second_fails=True)
        self.assertIsInstance(error,BudgetExceeded);self.assertEqual(runs,2);self.assertEqual(calls,3)

    def test_failed_probe_correction_does_not_reset_model_call_limit(self):
        report,error,runs,calls=self.correction(limit=2)
        self.assertIsInstance(error,BudgetExceeded);self.assertEqual(runs,2);self.assertEqual(calls,2)

    def test_english_query_without_code_gets_bounded_correction_without_execution(self):
        owner=self
        with tempfile.TemporaryDirectory() as temp, closing(Ledger(Path(temp)/'facts.sqlite')) as ledger:
            root=Path(temp)/'repo';root.mkdir();ws=self.fixture(root,ledger)
            class Model:
                calls=0
                def complete_json(self,messages,**kwargs):
                    self.calls+=1;data=json.loads(messages[1]['content'])
                    value=owner.action('answer' if self.calls==3 else 'probe')
                    if self.calls==1:value.update(code='',query='Please run an experiment')
                    if self.calls==3:value['evidence_ids']=[data['observations'][-1]['evidence_id']]
                    return Reply(json.dumps(value),10)
            model=Model()
            with patch('keel.diagnostic_probe.run_probe',return_value={'kind':'execution','probe':{'stdout':'1'}}) as run:
                report=investigate(model,ws,'Inspect','Question',[{'path':'sample.py','text':'value=1'}],{},
                    execution={'backend':'docker','image':'image'},python='/python',require_probe=True)
                self.assertEqual(run.call_count,1);self.assertEqual(model.calls,3)
                self.assertTrue(report['probe_used'])

    def test_repeated_empty_code_stops_without_starting_container(self):
        owner=self
        with tempfile.TemporaryDirectory() as temp, closing(Ledger(Path(temp)/'facts.sqlite')) as ledger:
            root=Path(temp)/'repo';root.mkdir();ws=self.fixture(root,ledger)
            class Model:
                def complete_json(self,*args,**kwargs):
                    value=owner.action();value.update(code='',query='Run a test')
                    return Reply(json.dumps(value),10)
            with patch('keel.diagnostic_probe.run_probe') as run:
                with self.assertRaisesRegex(RecoveryStopped,'Repeated'):
                    investigate(Model(),ws,'Inspect','Question',[{'path':'sample.py','text':'value=1'}],{},
                        execution={'backend':'docker','image':'image'},python='/python',require_probe=True)
                run.assert_not_called()

    def test_required_policy_rejects_early_answer_then_allows_probe_and_answer(self):
        owner=self
        with tempfile.TemporaryDirectory() as temp, closing(Ledger(Path(temp)/'facts.sqlite')) as ledger:
            root=Path(temp)/'repo';root.mkdir();ws=self.fixture(root,ledger)
            class Model:
                calls=0
                def complete_json(self,messages,**kwargs):
                    self.calls+=1;data=json.loads(messages[1]['content'])
                    value=owner.action('probe' if self.calls==2 else 'answer')
                    if self.calls==1:value['evidence_ids']=['source-0']
                    if self.calls==3:value['evidence_ids']=[data['observations'][-1]['evidence_id']]
                    return Reply(json.dumps(value),10)
            model=Model()
            with patch('keel.diagnostic_probe.run_probe',return_value={'kind':'execution','probe':{'stdout':'1'}}) as run:
                report=investigate(model,ws,'Inspect','Question',[{'path':'sample.py','text':'value=1'}],{},
                    execution={'backend':'docker','image':'image'},python='/python',require_probe=True)
                self.assertEqual(model.calls,3);self.assertEqual(run.call_count,1)
                self.assertTrue(report['probe_used']);self.assertFalse(report['execution_blocked'])

    def test_required_policy_rejects_unsupported_blocker_without_execution(self):
        owner=self
        with tempfile.TemporaryDirectory() as temp, closing(Ledger(Path(temp)/'facts.sqlite')) as ledger:
            root=Path(temp)/'repo';root.mkdir();ws=self.fixture(root,ledger)
            class Model:
                def complete_json(self,*args,**kwargs):
                    value=owner.action('blocked');value.update(answer='Required binary extension is absent from the supplied environment',
                                                               evidence_ids=['source-0'])
                    return Reply(json.dumps(value),10)
            with patch('keel.diagnostic_probe.run_probe') as run:
                with self.assertRaisesRegex(RecoveryStopped,'unsupported blocker'):
                    investigate(Model(),ws,'Inspect','Question',[{'path':'sample.py','text':'value=1'}],{},
                        execution={'backend':'docker','image':'image'},python='/python',require_probe=True)
                run.assert_not_called()

    def test_missing_evidence_blocker_is_redirected_to_execution(self):
        owner=self
        with tempfile.TemporaryDirectory() as temp, closing(Ledger(Path(temp)/'facts.sqlite')) as ledger:
            root=Path(temp)/'repo';root.mkdir();ws=self.fixture(root,ledger)
            class Model:
                calls=0
                def complete_json(self,messages,**kwargs):
                    self.calls+=1;data=json.loads(messages[1]['content'])
                    value=owner.action(['blocked','probe','answer'][self.calls-1])
                    value['evidence_ids']=['source-0'] if self.calls<3 else data['current_question_execution_ids']
                    if self.calls==1:value['answer']='The observation has not been collected'
                    if self.calls==2:owner.assertIn('collection task',data['observations'][-1]['text'])
                    return Reply(json.dumps(value),10)
            with patch('keel.diagnostic_probe.run_probe',return_value={'kind':'execution','outcome':'completed'}) as run:
                report=investigate(Model(),ws,'Inspect','Question',[{'path':'sample.py','text':'value=1'}],{},
                    execution={'backend':'docker','image':'image'},python='/python',require_probe=True)
                self.assertEqual(run.call_count,1)
                self.assertEqual(report['closure']['state'],'diagnosis_ready')

    def test_observed_executor_failure_can_end_as_verified_blocker(self):
        owner=self
        with tempfile.TemporaryDirectory() as temp, closing(Ledger(Path(temp)/'facts.sqlite')) as ledger:
            root=Path(temp)/'repo';root.mkdir();ws=self.fixture(root,ledger)
            class Model:
                calls=0
                def complete_json(self,messages,**kwargs):
                    self.calls+=1;data=json.loads(messages[1]['content'])
                    value=owner.action('probe' if self.calls==1 else 'blocked')
                    if self.calls==2:value['answer']='The executor returned a failure; cause remains unknown'
                    value['evidence_ids']=['source-0'] if self.calls==1 else data['verified_execution_obstacle_ids']
                    return Reply(json.dumps(value),10)
            row={'kind':'execution','outcome':'executor_failed','execution':{'returncode':1,'timeout':False}}
            with patch('keel.diagnostic_probe.run_probe',return_value=row):
                report=investigate(Model(),ws,'Inspect','Question',[{'path':'sample.py','text':'value=1'}],{},
                    execution={'backend':'docker','image':'image'},python='/python',require_probe=True)
                self.assertEqual(report['closure']['state'],'blocked_verified')

    def test_required_policy_does_not_loop_on_repeated_early_answers(self):
        owner=self
        with tempfile.TemporaryDirectory() as temp, closing(Ledger(Path(temp)/'facts.sqlite')) as ledger:
            root=Path(temp)/'repo';root.mkdir();ws=self.fixture(root,ledger)
            class Model:
                calls=0
                def complete_json(self,*args,**kwargs):
                    self.calls+=1;value=owner.action('answer');value['evidence_ids']=['source-0']
                    return Reply(json.dumps(value),10)
            model=Model()
            with self.assertRaisesRegex(RecoveryStopped,'Repeated final answer'):
                investigate(model,ws,'Inspect','Question',[{'path':'sample.py','text':'value=1'}],{},
                    execution={'backend':'docker','image':'image'},python='/python',require_probe=True)
            self.assertEqual(model.calls,2)

    def test_paired_runner_preserves_arm_receipts_and_does_not_apply_edits(self):
        from examples.review_saved_diagnosis import execute
        from keel.evaluation_protocol import file_hash
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=root/'source.py';source.write_bytes(b'value = 1\n')
            plan={'mode':'diagnostic_probe_pair','probe_image':'local-image','probe_python':'/python',
                  'scope':'Fixture pair','goal':'Inspect value',
                  'diagnosis':{'action':'replan','reason':'Inspect','hypothesis':'Value is one','evidence':'Source',
                               'next_check':'Inspect value','previous_attempt_assessment':'Not executed'},
                  'source_files':{'sample.py':str(source)},'frozen_files':{str(source):file_hash(source)},
                  'initial_evidence':[{'path':'sample.py','text':'value = 1'}]}
            path=root/'plan.json';path.write_text(json.dumps(plan));path.with_suffix('.sha256').write_text(file_hash(path))
            owner=self
            class Model:
                calls=0
                def complete_json(self,messages,**kwargs):
                    self.calls+=1;data=json.loads(messages[1]['content'])
                    probe=data['probe_available']
                    value=owner.action('probe' if probe else 'answer')
                    if value['action']=='answer':value['evidence_ids']=[data['observations'][-1]['evidence_id']]
                    return Reply(json.dumps(value),10)
            model=Model()
            class Inspected:
                returncode=0;stdout='sha256:'+'a'*64
            with patch('examples.review_saved_diagnosis.subprocess.run',return_value=Inspected()), patch(
                    'keel.diagnostic_probe.run_probe',return_value={'kind':'execution','probe':{'stdout':'1'}}):
                report=execute(path,root/'out',model=model)
                self.assertEqual(report['status'],'completed_needs_review')
                self.assertEqual(model.calls,3)
                self.assertEqual([r['new_provider_calls'] for r in report['records']],[1,2])
                self.assertTrue(all(r['workspace_unchanged'] for r in report['records']))
                self.assertEqual(execute(path,root/'out',model=model),report)
                self.assertEqual(model.calls,3)

    def fixture(self, root, ledger):
        (root/'sample.py').write_bytes(b'value = 1\n')
        return Workspace(root,Budget(Limits(max_tokens=100000)),ledger,Trace(root/'trace.jsonl'))

    def action(self, action='probe'):
        return {'action':action,'path':'','query':'','start_line':0,'end_line':0,
                'code':'print(1)' if action=='probe' else '', 'reason':'Distinguish outputs',
                'conclusion':'unknown','answer':'Observed output is 1' if action=='answer' else '',
                'evidence_ids':['observation-1'] if action=='answer' else []}

    def test_probe_reuses_sandbox_limits_without_host_fallback(self):
        with tempfile.TemporaryDirectory() as temp, closing(Ledger(Path(temp)/'facts.sqlite')) as ledger:
            root=Path(temp)/'repo';root.mkdir();ws=self.fixture(root,ledger)
            with self.assertRaises(PolicyDenied):run_probe(ws,{'backend':'local'},'/python','print(1)')
            with patch.object(CommandRunner,'run',return_value={'returncode':0,'timeout':False,
                    'stdout':json.dumps({'stdout':'1','stderr':'','returncode':0,'timeout':False})}) as run:
                result=run_probe(ws,{'backend':'docker','image':'sha256:abc'},'/python','print(1)')
                args=run.call_args.args[0]
                self.assertEqual(args[0],'/python');self.assertEqual(args[3],BOOTSTRAP)
                self.assertEqual(result['probe']['stdout'],'1')
                self.assertLessEqual(run.call_args.kwargs['timeout'],15)
            command=CommandRunner({'backend':'docker','image':'sha256:abc'}).docker_command(['python'],root,None,'probe')
            for flag in ('--network=none','--read-only','--cap-drop=ALL','--security-opt=no-new-privileges','--user=65534:65534'):
                self.assertIn(flag,command)
            self.assertIn('RLIMIT_FSIZE',BOOTSTRAP)

    def test_model_probe_observation_then_answer_stays_distinct_from_acceptance(self):
        owner=self
        with tempfile.TemporaryDirectory() as temp, closing(Ledger(Path(temp)/'facts.sqlite')) as ledger:
            root=Path(temp)/'repo';root.mkdir();ws=self.fixture(root,ledger)
            class Model:
                calls=0
                def complete_json(self,messages,**kwargs):
                    self.calls+=1;return Reply(json.dumps(owner.action('probe' if self.calls==1 else 'answer')),10)
            with patch('keel.diagnostic_probe.run_probe',return_value={'kind':'execution','probe':{'stdout':'1'}}):
                report=investigate(Model(),ws,'Inspect','Question',[{'path':'sample.py','text':'value=1'}],{},
                    execution={'backend':'docker','image':'image'},python='/python')
            self.assertTrue(report['probe_used']);self.assertIn('not task repair',report['scope'])
            self.assertEqual(report['assessment']['evidence_ids'],['observation-1'])

    def test_readonly_arm_cannot_select_probe(self):
        owner=self
        with tempfile.TemporaryDirectory() as temp, closing(Ledger(Path(temp)/'facts.sqlite')) as ledger:
            root=Path(temp)/'repo';root.mkdir();ws=self.fixture(root,ledger)
            class Model:
                def complete_json(self,*args,**kwargs):return Reply(json.dumps(owner.action()),10)
            with patch('keel.diagnostic_probe.run_probe') as run:
                with self.assertRaises(ValueError):investigate(Model(),ws,'Inspect','Question',[],{})
                run.assert_not_called()

    def test_repeated_action_stops_without_another_execution(self):
        owner=self
        with tempfile.TemporaryDirectory() as temp, closing(Ledger(Path(temp)/'facts.sqlite')) as ledger:
            root=Path(temp)/'repo';root.mkdir();ws=self.fixture(root,ledger)
            class Model:
                def complete_json(self,*args,**kwargs):return Reply(json.dumps(owner.action()),10)
            with patch('keel.diagnostic_probe.run_probe',return_value={'kind':'execution'}) as run:
                with self.assertRaises(RecoveryStopped):investigate(Model(),ws,'Inspect','Question',[],{},
                    execution={'backend':'docker','image':'image'},python='/python')
                self.assertEqual(run.call_count,1)
