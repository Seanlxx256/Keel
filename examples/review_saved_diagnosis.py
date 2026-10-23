"""Exercise production supervision on a frozen saved diagnosis, without repairs."""
import argparse
import json
import subprocess
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from compass.progress import atomic_json
from keel.core import Budget, Ledger, Limits, Trace, RecoveryStopped, InvalidSelection, ModelCompletionError
from keel.evaluation_protocol import file_hash
from keel.models import Reply, from_config
from keel.recovery import RecoveryController, validate_critic_decision
from keel.workspace import Workspace


class ReviewEditsHeld(RuntimeError):
    """Production proposal validation finished; micro-review never applies edits."""


def execute_acquisition(plan_path, output, plan, identity, model=None):
    """Reuse production unknown routing with a saved reply and bounded live calls."""
    if model is None:
        model = from_config(json.loads(Path(plan['model_config']).read_text(encoding='utf-8')))
    if hasattr(model, 'check_credentials'):
        model.check_credentials()
    output.mkdir(parents=True, exist_ok=False)
    root = output/'workspace'; root.mkdir()
    for name, origin in plan['source_files'].items():
        target = (root/name).resolve()
        if not target.is_relative_to(root.resolve()):
            raise ValueError('Review source path escapes workspace')
        if origin not in plan['frozen_files']:
            raise ValueError('Review source is not frozen')
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(Path(origin).read_bytes())
    budget = Budget(Limits(max_model_calls=5, max_tokens=80000, max_tool_calls=20, max_wallclock=240))
    ledger = Ledger(output/'ledger.sqlite'); trace = Trace(output/'trace.jsonl')

    class ReadOnlyReviewWorkspace(Workspace):
        def replace(self, *args, **kwargs):
            raise ReviewEditsHeld('Validated edit batch held; no source edits applied')

    workspace = ReadOnlyReviewWorkspace(root, budget, ledger, trace)
    before = workspace.snapshot()
    controller = RecoveryController({'strategy':'adaptive', 'max_actions':4,
                                    'write_roots':['.'], 'diagnostic_handoff':True}, workspace)
    controller.current_decision = plan['diagnosis']
    controller.current_verification = plan['verification']
    report = {'status':'running', 'plan_sha256':identity, 'scope':plan['scope'],
              'new_provider_calls':0, 'saved_replay_calls':0}
    atomic_json(output/'report.json', report)

    def transcript(row):
        with (output/'model-transcript.jsonl').open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(row, ensure_ascii=False)+'\n')

    class SavedThenLive:
        calls = 0
        replayed = False
        def complete_json(self, messages, **kwargs):
            if not self.replayed:
                self.replayed = True
                report['saved_replay_calls'] = 1
                transcript({'event':'saved_reply_replayed', 'response':plan['saved_response'],
                            'scope':'No provider call or new paid usage; one host dispatch reservation'})
                return Reply(plan['saved_response'], 0)
            if self.calls >= 4:
                raise RuntimeError('Live acquisition call cap exceeded')
            self.calls += 1
            report.update(new_provider_calls=self.calls, pending_provider_call=self.calls, budget=budget.report())
            atomic_json(output/'report.json', report)
            kwargs['timeout'] = min(kwargs['timeout'], 60)
            transcript({'event':'request', 'call':self.calls, 'messages':messages, 'settings':kwargs})
            print(f'[Acquisition] live call {self.calls}/4; timeout <=60s', flush=True)
            try:
                reply = model.complete_json(messages, **kwargs)
            except Exception as error:
                row={'event':'error','call':self.calls,'error_type':type(error).__name__,
                     'tokens':getattr(error,'tokens',None)}
                if isinstance(error, ModelCompletionError):
                    row.update(completion_diagnostics=error.diagnostics, rejected_response_content=error.content)
                transcript(row)
                raise
            transcript({'event':'response','call':self.calls,'content':reply.content,'tokens':reply.tokens,
                        'metadata':getattr(reply,'metadata',None)})
            return reply

    proxy = SavedThenLive()
    try:
        controller.propose(proxy, workspace, plan['goal'], plan['edit_files'], plan['proposal_evidence'],
                           {'max_context_bytes':32000, 'max_output':2048})
        report['status'] = 'completed_needs_review'
    except ReviewEditsHeld:
        report['status'] = 'proposal_validated_edits_held'
    except RecoveryStopped as error:
        report.update(status='evidence_blocked', reason=str(error))
    except Exception as error:
        report.update(status='incomplete', error_type=type(error).__name__, reason=str(error)[:700])
    finally:
        unchanged = workspace.snapshot() == before
        report.update(new_provider_calls=proxy.calls, budget=budget.report(), recovery=controller.report(),
                      workspace_unchanged=unchanged, acceptance='not_executed')
        if not unchanged:
            report.update(status='incomplete', reason='Review workspace changed unexpectedly')
        if report['status'] != 'incomplete':
            report.pop('pending_provider_call', None)
        atomic_json(output/'report.json', report)
        ledger.close()
    if report['status'] != 'incomplete':
        atomic_json(output/'receipt.json', {'plan_sha256':identity, 'report_sha256':file_hash(output/'report.json')})
    return report


def execute_probe_pair(output, plan, identity, model=None):
    """Paired action-capability experiment, with independent arm receipts."""
    from keel.diagnostic_probe import investigate
    arms=plan.get('arms',['read_only','probe'])
    if (not isinstance(arms,list) or not 1<=len(arms)<=2 or len(arms)!=len(set(arms))
            or any(a not in ('read_only','probe') for a in arms)
            or plan.get('probe_policy','optional') not in ('optional','required')):
        raise ValueError('Invalid diagnostic probe arms or policy')
    if plan.get('probe_policy')=='required' and arms!=['probe']:
        raise ValueError('Required-probe capability review must be separately labeled probe-only')
    if model is None:
        model=from_config(json.loads(Path(plan['model_config']).read_text(encoding='utf-8')))
    if hasattr(model,'check_credentials'):model.check_credentials()
    # Resolve once before paid calls; the same immutable local image is used for
    # every probe. No pulling, building or network/environment repair here.
    inspected=subprocess.run(['docker','image','inspect','--format','{{.Id}}',plan['probe_image']],
                             capture_output=True,timeout=5,text=True)
    image=inspected.stdout.strip()
    if inspected.returncode or not image.startswith('sha256:'):
        raise ValueError('Local probe image unavailable; no provider call dispatched')
    output.mkdir(parents=True,exist_ok=True)
    manifest=output/'manifest.json';expected={'plan_sha256':identity,'image_id':image}
    if manifest.exists():
        if json.loads(manifest.read_text())!=expected:raise ValueError('Probe comparison identity changed')
    else:
        if list(output.iterdir()):raise ValueError('Unreceipted comparison output')
        atomic_json(manifest,expected)
    records=[]
    for arm in arms:
        target=output/arm;report_path=target/'report.json';receipt=target/'receipt.json'
        if target.exists():
            if not receipt.exists() or not report_path.exists() or json.loads(receipt.read_text())!={
                    'plan_sha256':identity,'report_sha256':file_hash(report_path)}:
                raise ValueError('Incomplete arm preserved; no automatic paid retry')
            records.append(json.loads(report_path.read_text(encoding='utf-8')));continue
        target.mkdir();root=target/'workspace';root.mkdir()
        for name,origin in plan['source_files'].items():
            path=(root/name).resolve()
            if not path.is_relative_to(root.resolve()) or origin not in plan['frozen_files']:
                raise ValueError('Probe source must be frozen and inside workspace')
            path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(Path(origin).read_bytes())
        budget=Budget(Limits(max_model_calls=3,max_tokens=60000,max_tool_calls=8,max_wallclock=120))
        ledger=Ledger(target/'ledger.sqlite');trace=Trace(target/'trace.jsonl')
        workspace=Workspace(root,budget,ledger,trace);before=workspace.snapshot()
        prior=plan.get('prior_probe_observations',[])
        if prior:
            from keel.candidate_imports import module_manifest
            current=module_manifest(root,[name for name,_ in workspace.files()])
            if arm!='probe' or plan.get('prior_probe_image_id')!=image:
                ledger.close();raise ValueError('Prior probe image/scope mismatch; no paid dispatch')
            for observation in prior:
                if not observation.get('candidate_manifest') or any(
                    name not in current or current[name]['sha256']!=row['sha256']
                    for name,row in observation['candidate_manifest'].items()):
                    ledger.close();raise ValueError('Prior probe source mismatch; no paid dispatch')
        report={'arm':arm,'status':'running','scope':plan['scope'],'new_provider_calls':0}
        atomic_json(report_path,report)

        class RecordedModel:
            calls=0
            def complete_json(self,messages,**kwargs):
                self.calls+=1;report.update(new_provider_calls=self.calls,budget=budget.report())
                atomic_json(report_path,report)
                kwargs['timeout']=min(kwargs['timeout'],60)
                print(f'[Probe comparison] {arm} call {self.calls}/3; timeout <=60s',flush=True)
                def save(row):
                    with (target/'model-transcript.jsonl').open('a',encoding='utf-8') as stream:
                        stream.write(json.dumps(row,ensure_ascii=False)+'\n')
                save({'event':'request','call':self.calls,'messages':messages,'settings':kwargs})
                try:reply=model.complete_json(messages,**kwargs)
                except Exception as error:
                    row={'event':'error','call':self.calls,'error_type':type(error).__name__,
                         'tokens':getattr(error,'tokens',None)}
                    if isinstance(error,ModelCompletionError):
                        row.update(completion_diagnostics=error.diagnostics,rejected_response_content=error.content)
                    save(row);raise
                save({'event':'response','call':self.calls,'content':reply.content,'tokens':reply.tokens})
                return reply

        proxy=RecordedModel()
        try:
            report['diagnosis']=investigate(proxy,workspace,plan['goal'],plan['diagnosis'],plan['initial_evidence'],
                {'max_context_bytes':32000,'max_output':2048},
                execution=({'backend':'docker','image':image,'cpus':1,'memory_mb':768,'pids_limit':64} if arm=='probe' else None),
                python=plan['probe_python'],require_probe=plan.get('probe_policy')=='required',
                candidate_imports=plan.get('candidate_imports',False),
                correct_failed_probe=plan.get('correct_failed_probe',False),
                continue_successful_probe=plan.get('continue_successful_probe',False),
                prior_probe_observations=prior)
            report['status']='completed_needs_review'
        except RecoveryStopped as error:report.update(status='evidence_blocked',reason=str(error))
        except Exception as error:report.update(status='incomplete',error_type=type(error).__name__,reason=str(error)[:700])
        finally:
            report.update(new_provider_calls=proxy.calls,budget=budget.report(),workspace_unchanged=workspace.snapshot()==before,
                          acceptance='not_executed',image_id=image)
            if not report['workspace_unchanged']:report.update(status='incomplete',reason='Unexpected source mutation')
            atomic_json(report_path,report);ledger.close()
        records.append(report)
        if report['status']=='incomplete':break
        atomic_json(receipt,{'plan_sha256':identity,'report_sha256':file_hash(report_path)})
    result={'status':'completed_needs_review' if len(records)==len(arms) and all(r['status']!='incomplete' for r in records) else 'incomplete',
            'new_provider_calls':sum(r['new_provider_calls'] for r in records),'records':records,
            'scope':plan['scope'],'automatic_quality_score':None}
    atomic_json(output/'report.json',result)
    return result


def execute(plan_path, output, *, model=None):
    plan = json.loads(plan_path.read_text(encoding='utf-8'))
    identity = file_hash(plan_path)
    if identity != plan_path.with_suffix('.sha256').read_text().strip():
        raise ValueError('Frozen plan changed')
    for path, expected in plan['frozen_files'].items():
        if file_hash(Path(path)) != expected:
            raise ValueError('Frozen input changed: '+path)
    validate_critic_decision(plan['diagnosis'])
    if plan.get('mode') == 'diagnostic_probe_pair':
        return execute_probe_pair(output,plan,identity,model)
    if output.exists():
        receipt = json.loads((output/'receipt.json').read_text()) if (output/'receipt.json').is_file() else None
        if not receipt or not (output/'report.json').is_file() or receipt != {
                'plan_sha256': identity, 'report_sha256': file_hash(output/'report.json')}:
            raise ValueError('Unfinished or altered review preserved; no automatic paid retry')
        return json.loads((output/'report.json').read_text(encoding='utf-8'))
    if plan.get('mode') == 'diagnostic_acquisition':
        return execute_acquisition(plan_path, output, plan, identity, model)
    if model is None:
        model = from_config(json.loads(Path(plan['model_config']).read_text(encoding='utf-8')))
    if hasattr(model, 'check_credentials'):
        model.check_credentials()
    output.mkdir(parents=True, exist_ok=False)
    (output/'workspace').mkdir()
    budget = Budget(Limits(max_model_calls=4, max_tokens=60000, max_tool_calls=1, max_wallclock=360))
    ledger = Ledger(output/'ledger.sqlite')
    trace = Trace(output/'trace.jsonl')
    controller = RecoveryController({'strategy': 'adaptive', 'max_actions': 4,
        'write_roots': ['.'], 'diagnosis_supervision': True},
        Workspace(output/'workspace', budget, ledger, trace))
    report = {'status': 'running', 'plan_sha256': identity, 'scope': plan['scope'],
              'original_diagnosis': plan['diagnosis'], 'new_provider_calls': 0}
    atomic_json(output/'report.json', report)

    class SavedThenLive:
        cached = False
        calls = 0
        def complete_json(self, messages, **kwargs):
            if not self.cached:
                self.cached = True
                trace.emit('critic', 'saved_diagnosis_replayed', scope='No provider call or new paid tokens')
                return Reply(json.dumps(plan['diagnosis']), 0)
            self.calls += 1
            if self.calls > 3:
                raise RuntimeError('Live supervision call cap exceeded')
            report['new_provider_calls'] = self.calls
            report['pending_provider_call'] = self.calls
            report['budget'] = budget.report()
            atomic_json(output/'report.json', report)
            print(f'[Supervision] live call {self.calls}/3; timeout <=120s', flush=True)
            kwargs['timeout'] = min(kwargs['timeout'], 120)
            return model.complete_json(messages, **kwargs)

    proxy = SavedThenLive()
    try:
        report['final_diagnosis'] = controller.decide(proxy, plan['goal'], plan['current_plan'],
            plan['verification'], {'max_context_bytes': 32000, 'max_output': 1024},
            source_review=plan['source_review'])
        report['status'] = 'completed_needs_review'
    except RecoveryStopped as error:
        report.update(status='supervision_stopped', reason=str(error))
    except Exception as error:
        report.update(status='incomplete', error_type=type(error).__name__)
        if isinstance(error, InvalidSelection):
            report['validation_error'] = str(error)
    finally:
        report.update(new_provider_calls=proxy.calls, budget=budget.report(), recovery=controller.report(),
                      final_diagnosis_provenance='Model output only; no probe, source edit or task acceptance.')
        if report['status'] != 'incomplete':
            report.pop('pending_provider_call', None)
        atomic_json(output/'report.json', report)
        ledger.close()
    if report['status'] != 'incomplete':
        atomic_json(output/'receipt.json', {'plan_sha256': identity, 'report_sha256': file_hash(output/'report.json')})
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--check-imports', action='store_true', help='Zero-model normal import check of frozen candidate edit modules; not a paid review')
    parser.add_argument('--compare-source-tests', action='store_true', help='Zero-model frozen baseline/candidate regression comparison')
    parser.add_argument('--resume-from',type=Path,help='Existing comparison report; reuse validated completed variants in a new output')
    parser.add_argument('--import-path', action='append', help='Explicit frozen source path for zero-model import checking; repeat for more modules')
    args = parser.parse_args()
    if args.compare_source_tests:
        if args.check_imports or args.import_path:
            parser.error('Source comparison cannot combine import-check options')
        from keel.source_comparison import compare_sources
        report=compare_sources(args.plan.resolve(),args.output.resolve(),
                               resume_from=args.resume_from.resolve() if args.resume_from else None)
        print(json.dumps({'status':report['status'],'model_calls':0,'report':str(args.output/'report.json')}))
        return 0 if report['status']=='compared' else 1
    if args.resume_from:
        parser.error('--resume-from requires --compare-source-tests')
    if args.check_imports:
        from keel.probe_preflight import check_imports
        report=check_imports(args.plan.resolve(),args.output.resolve(),targets=args.import_path)
        print(json.dumps({'status':report['status'],'model_calls':0,'report':str(args.output/'report.json')}))
        return 0 if report['status']=='passed' else 1
    if args.import_path:
        parser.error('--import-path requires --check-imports')
    if not args.execute:
        plan = json.loads(args.plan.read_text(encoding='utf-8'))
        print(json.dumps({'status': 'plan_only', 'max_new_provider_calls':
                          3*len(plan.get('arms',['read_only','probe'])) if plan.get('mode') == 'diagnostic_probe_pair' else
                          4 if plan.get('mode') == 'diagnostic_acquisition' else 3})); return 0
    report = execute(args.plan.resolve(), args.output.resolve())
    print(json.dumps({'status': report['status'], 'new_provider_calls': report['new_provider_calls'],
                      'report': str(args.output/'report.json')}))
    return 1 if report['status'] == 'incomplete' else 0


if __name__ == '__main__':
    raise SystemExit(main())
