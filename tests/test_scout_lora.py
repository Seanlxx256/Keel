import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from keel.scout_lora import selected_positions,verify_weights,training_schedule
from keel.scout_tokenizer import MODEL,REVISION,file_hash


class ScoutLoraTests(unittest.TestCase):
    def test_training_stage_timeout_validates_before_dispatch(self):
        from keel.scout_training_setup import prepare
        for value in (0,-1,True,float('inf'),float('nan')):
            with self.subTest(value=value),self.assertRaisesRegex(ValueError,'timeout'):
                prepare('missing','missing','missing','missing',train_timeout=value)

    def test_environment_timeout_validates_before_dispatch(self):
        from keel.scout_training_setup import prepare
        for value in (0,-1,True,float('inf'),float('nan')):
            with self.subTest(value=value),self.assertRaisesRegex(ValueError,'environment stage timeout'):
                prepare('missing','missing','missing','missing',environment_timeout=value)

    def test_training_objective_is_validated_before_dispatch(self):
        from keel.scout_lora import validate_objective
        from keel.scout_training_setup import prepare
        self.assertEqual(validate_objective('candidate_scores'),'candidate_scores')
        with self.assertRaises(ValueError):prepare('missing','missing','missing','missing',objective='unrecognized')
    def test_declared_update_budget_preserves_epoch_order_without_success_stopping(self):
        lengths=list(range(1,16));full=training_schedule(lengths,2)
        self.assertEqual(training_schedule(lengths,2,24),full[:24])
        self.assertEqual({i for _,i in full[:15]},set(range(15)))
        for value in (0,-1,31,True,1.5):
            with self.assertRaises(ValueError):training_schedule(lengths,2,value)
    def test_fixed_epochs_visit_all_samples_without_early_success_selection(self):
        schedule=training_schedule([3,7,2,5,1,4],4)
        self.assertEqual(len(schedule),24)
        self.assertEqual(schedule[:6],[(1,i) for i in (1,3,5,0,2,4)])
        self.assertEqual(schedule[-6:],[(4,i) for i in (1,3,5,0,2,4)])
        for invalid in (0,-1,1.5):
            with self.assertRaises(ValueError):training_schedule([1],invalid)
    def test_completed_install_without_inventory_is_rechecked_without_installing(self):
        from keel.scout_training_setup import prepare
        from keel.scout_lora import PINS
        import sys
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);data=root/'data';data.mkdir();(data/'development.jsonl').write_text('{}');(data/'export.json').write_text('{"sample_count":4}')
            run=root/'tokenizer';run.mkdir();(run/'report.json').write_text('{}')
            site=root/'site';(site/'torch').mkdir(parents=True);(site/'torch/__init__.py').write_text('')
            old=root/'old';old.mkdir();env=old/'env'
            packages=env/('Lib/site-packages' if sys.platform=='win32' else f'lib/python{sys.version_info.major}.{sys.version_info.minor}/site-packages')
            packages.mkdir(parents=True);(packages/'keel-torch-source.pth').write_text(str(site)+'\n')
            identity={'model':MODEL,'revision':REVISION,'dataset':file_hash(data/'development.jsonl'),
                'tokenizer_report':file_hash(run/'report.json'),'pins':list(PINS),'torch_site':str(site),
                'torch_source':file_hash(site/'torch/__init__.py')}
            (old/'report.json').write_text(json.dumps({'identity':identity,'stages':[
                {'name':name,'returncode':0,'timeout':False} for name in ('venv','install')]}))
            for name in ('venv','install'):(old/(name+'-process.json')).write_text(json.dumps({'returncode':0,'timeout':False}))
            with patch('keel.scout_training_setup.training_inputs'),patch('keel.scout_training_setup.observed_stage',return_value={'returncode':1,'timeout':False}) as stage:
                with self.assertRaisesRegex(RuntimeError,'environment failed'):prepare(data,run,site,root/'new',recover_from=old)
            self.assertEqual(stage.call_count,1)
            self.assertEqual(stage.call_args.args[-1],'environment')
            self.assertIn('migration',json.loads((root/'new/report.json').read_text()))

    def test_causal_labels_shift_once_and_keep_last_target(self):
        self.assertEqual(selected_positions([-100,-100,7,8,9]),[1,2,3])

    def test_weights_must_remain_exact(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for name in ('config.json','model.safetensors'):(root/name).write_bytes(b'fixture')
            receipt={'model':MODEL,'revision':REVISION,'directory':str(root),
                'files':{name:file_hash(root/name) for name in ('config.json','model.safetensors')}}
            self.assertEqual(verify_weights(receipt),root)
            (root/'model.safetensors').write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError,'changed'):verify_weights(receipt)

    def test_selected_logits_loss_and_gradients_equal_full_causal_loss(self):
        try:import torch
        except ImportError:self.skipTest('Torch optional; run explicit Torch interpreter check')
        torch.manual_seed(42)
        hidden=torch.randn(1,8,4,requires_grad=True);weight=torch.randn(13,4,requires_grad=True)
        labels=torch.tensor([[-100,-100,-100,-100,-100,3,4,5]])
        full=torch.nn.functional.cross_entropy((hidden@weight.T)[:,:-1].reshape(-1,13),labels[:,1:].reshape(-1),ignore_index=-100)
        full_grads=torch.autograd.grad(full,(hidden,weight),retain_graph=True)
        positions=selected_positions(labels[0].tolist())
        selected=torch.nn.functional.cross_entropy(hidden[0,positions]@weight.T,labels[0,torch.tensor(positions)+1])
        selected_grads=torch.autograd.grad(selected,(hidden,weight))
        torch.testing.assert_close(full,selected)
        for actual,expected in zip(selected_grads,full_grads):torch.testing.assert_close(actual,expected)

    def test_stage_failure_recorded_without_replacing_old_outputs(self):
        from keel.scout_training_setup import prepare
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);data=root/'data';data.mkdir();(data/'development.jsonl').write_text('{}');(data/'export.json').write_text('{"sample_count":4}')
            run=root/'tokenizer';run.mkdir();(run/'report.json').write_text('{}')
            site=root/'site';(site/'torch').mkdir(parents=True);(site/'torch/__init__.py').write_text('')
            failed={'returncode':1,'timeout':False}
            with patch('keel.scout_training_setup.training_inputs'),patch('keel.scout_training_setup.observed_stage',return_value=failed):
                with self.assertRaisesRegex(RuntimeError,'venv failed'):prepare(data,run,site,root/'out')
            self.assertEqual(json.loads((root/'out/report.json').read_text())['status'],'incomplete')
            with patch('keel.scout_training_setup.training_inputs'):
                with self.assertRaises(FileExistsError):prepare(data,run,site,root/'out')

    def test_training_retry_reuses_verified_preparation_not_old_training_score(self):
        from keel.scout_training_setup import prepare
        import sys
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);data=root/'data';data.mkdir();(data/'development.jsonl').write_text('{}');(data/'export.json').write_text('{"sample_count":4}')
            run=root/'tokenizer';run.mkdir();(run/'report.json').write_text('{}')
            site=root/'site';(site/'torch').mkdir(parents=True);(site/'torch/__init__.py').write_text('')
            fail=True;calls=[]
            def stage(command,output,timeout,name):
                calls.append(name);output=Path(output)
                if name=='venv':
                    env=Path(command[-1]);python=env/('Scripts/python.exe' if sys.platform=='win32' else 'bin/python')
                    python.parent.mkdir(parents=True);python.write_bytes(b'fixture interpreter')
                    packages=env/('Lib/site-packages' if sys.platform=='win32' else f'lib/python{sys.version_info.major}.{sys.version_info.minor}/site-packages')
                    packages.mkdir(parents=True)
                if name=='environment':
                    (output/'environment.json').write_text(json.dumps({'python':command[0],
                        'python_sha256':file_hash(command[0]),'packages':{'fixture':'1'}}))
                if name=='download':
                    weights=output/'weights';weights.mkdir()
                    for filename in ('config.json','model.safetensors'):(weights/filename).write_bytes(b'fixture')
                    (weights/'weights.json').write_text(json.dumps({'model':MODEL,'revision':REVISION,'directory':str(weights),
                        'files':{n:file_hash(weights/n) for n in ('config.json','model.safetensors')}}))
                if name=='train':
                    if fail:return {'returncode':1,'timeout':False}
                    (output/'training').mkdir()
                    (output/'training/training.json').write_text(json.dumps({'status':'passed','steps':[{}]*4}))
                return {'returncode':0,'timeout':False}
            with patch('keel.scout_training_setup.training_inputs'),patch('keel.scout_training_setup.observed_stage',side_effect=stage):
                with self.assertRaisesRegex(RuntimeError,'train failed'):prepare(data,run,site,root/'first')
                fail=False;calls.clear()
                result=prepare(data,run,site,root/'second',recover_from=root/'first')
            self.assertEqual(calls,['environment','train'])
            self.assertEqual(result['status'],'passed')
            self.assertEqual(json.loads((root/'first/report.json').read_text())['status'],'incomplete')
