import os
import json
import tempfile
from pathlib import Path
import unittest
from unittest.mock import MagicMock,patch
from keel.scout_reproducibility import configure_environment,configure_torch,validate_policy,seed_training


class ScoutReproducibilityTests(unittest.TestCase):
    def test_strict_seeds_every_recorded_rng_without_changing_legacy(self):
        torch=MagicMock()
        with patch('random.seed') as python_seed,patch.dict('sys.modules',{'numpy':MagicMock()}) as modules:
            seed_training(torch,'legacy')
            python_seed.assert_not_called();modules['numpy'].random.seed.assert_not_called()
            seed_training(torch,'strict')
            python_seed.assert_called_once_with(42);modules['numpy'].random.seed.assert_called_once_with(42)
        self.assertEqual(torch.manual_seed.call_count,2)
    def test_legacy_does_not_reconfigure_process(self):
        with patch.dict(os.environ,{'CUBLAS_WORKSPACE_CONFIG':'existing'}):
            configure_environment('legacy')
            self.assertEqual(os.environ['CUBLAS_WORKSPACE_CONFIG'],'existing')
        torch=MagicMock()
        configure_torch(torch,'legacy')
        torch.use_deterministic_algorithms.assert_not_called()

    def test_strict_requires_exact_environment_and_fresh_cuda(self):
        with patch.dict(os.environ,{},clear=True):
            configure_environment('strict')
            self.assertEqual(os.environ['CUBLAS_WORKSPACE_CONFIG'],':4096:8')
        with patch.dict(os.environ,{'CUBLAS_WORKSPACE_CONFIG':':16:8'}):
            with self.assertRaises(ValueError):configure_environment('strict')
        torch=MagicMock();torch.cuda.is_initialized.return_value=True
        with self.assertRaisesRegex(RuntimeError,'fresh process'):configure_torch(torch,'strict')
        torch.use_deterministic_algorithms.assert_not_called()
        torch.cuda.is_initialized.return_value=False
        configure_torch(torch,'strict')
        torch.use_deterministic_algorithms.assert_called_once_with(True)

    def test_unknown_policy_rejected_before_preparation(self):
        from keel.scout_training_setup import prepare
        with self.assertRaises(ValueError):validate_policy('best_effort')
        with self.assertRaises(ValueError):prepare('missing','missing','missing','missing',reproducibility='bad')

    def test_evaluator_rejects_policy_mismatch_and_missing_strict_evidence(self):
        from keel.scout_adapter_eval import evaluation_inputs
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'training').mkdir()
            parent={'identity':{'reproducibility':'strict'}}
            (root/'report.json').write_text(json.dumps(parent))
            path=root/'training/training.json';path.write_text('{}')
            with patch('keel.scout_adapter_eval.training_inputs',return_value=(root,{})):
                with self.assertRaisesRegex(ValueError,'policy drift'):evaluation_inputs(root,root,root)
                path.write_text(json.dumps({'reproducibility':'strict'}))
                with self.assertRaisesRegex(ValueError,'execution configuration'):evaluation_inputs(root,root,root)

    def test_recovery_cannot_silently_change_training_policy(self):
        from keel.scout_training_setup import prepare
        from keel.scout_lora import PINS
        from keel.scout_tokenizer import MODEL,REVISION,file_hash
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);data=root/'data';data.mkdir();run=root/'tokenizer';run.mkdir()
            (data/'development.jsonl').write_text('{}')
            (data/'export.json').write_text('{"sample_count":1}')
            (run/'report.json').write_text('{}')
            site=root/'site';(site/'torch').mkdir(parents=True);(site/'torch/__init__.py').write_text('')
            identity={'model':MODEL,'revision':REVISION,'dataset':file_hash(data/'development.jsonl'),
                      'tokenizer_report':file_hash(run/'report.json'),'pins':list(PINS),'torch_site':str(site),
                      'torch_source':file_hash(site/'torch/__init__.py'),'epochs':1,'max_updates':None}
            old=root/'old';old.mkdir();(old/'report.json').write_text(json.dumps({'identity':identity}))
            with patch('keel.scout_training_setup.training_inputs'),patch('keel.scout_training_setup.observed_stage') as stage:
                with self.assertRaisesRegex(ValueError,'input drift'):
                    prepare(data,run,site,root/'new',recover_from=old,reproducibility='strict')
                with self.assertRaisesRegex(ValueError,'input drift'):
                    prepare(data,run,site,root/'new',recover_from=old,objective='candidate_scores')
                stage.assert_not_called();self.assertFalse((root/'new').exists())
