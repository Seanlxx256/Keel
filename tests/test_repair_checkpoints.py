import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from keel.models import Reply
from keel.runtime import run
from keel.repair_checkpoints import verification_score


def feedback(preservation_failures, target_failures=0, identity='a'*64):
    value={'grading_status':'graded','failure_kind':'test_failure',
           'test_universe_sha256':identity,
           'test_counts':{'FAIL_TO_PASS':{'success':1-target_failures,'failure':target_failures},
                          'PASS_TO_PASS':{'success':2-preservation_failures,'failure':preservation_failures}}}
    return [{'returncode':1,'timeout':False,'stdout':json.dumps(value),'stderr':''}]


class RepairCheckpointTests(unittest.TestCase):
    def test_grade_errors_and_missing_test_identity_are_not_ranked(self):
        self.assertIsNone(verification_score([{'returncode':1,'stdout':'{}'}]))
        self.assertIsNone(verification_score([{'timeout':True,'stdout':feedback(1)[0]['stdout']}]))

    def test_failed_adaptive_attempt_restores_seed_without_claiming_pass(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=root/'module.py'
            source.write_bytes(b'def value():\r\n    return 1\r\n')
            replies=[{'action':'replan','reason':'Inspect source','hypothesis':'Incorrect return',
                      'evidence':'Saved test failed','next_check':'Read value implementation',
                      'previous_attempt_assessment':'Saved source fails a preservation test'},
                     {'files':['module.py']},{'locations':['module.py:1']},
                     {'summary':'Try change','edits':[{'path':'module.py','old':'return 1','new':'return 2'}]}]
            class Model:
                def complete_json(self,*args,**kwargs):return Reply(json.dumps(replies.pop(0)),10)
            config={'mode':'localized-proposal','goal':'Fix behavior','preserve_repair_candidates':True,
                    'verification_repair_attempts':0,'budget':{'max_model_calls':4},
                    'recovery':{'strategy':'adaptive','max_actions':6,'write_roots':['.']},
                    'continuation_context':{'verification':feedback(1),'changes':{},
                                            'provenance':{'source_files':{'module.py':'seed'}}},
                    'acceptance':[['python','-c','pass']]}
            with patch('keel.workspace.Workspace.verify',return_value=feedback(2)):
                result=run(config,root,root/'.keel/run',model=Model())
            self.assertEqual(result['status'],'failed')
            self.assertEqual(result['selected_repair_candidate']['selected_label'],'saved-seed')
            self.assertEqual(result['selected_repair_candidate']['restored_files'],['module.py'])
            self.assertEqual(source.read_bytes(),b'def value():\r\n    return 1\r\n')
            self.assertEqual(result['verification_attempts'][0]['verification'],feedback(2))
            self.assertEqual((root/'.keel/run/changes.patch').read_bytes(),b'')
            self.assertEqual(len(list((root/'.keel/run/repair-candidates').glob('*/candidate.json'))),2)

    def test_incomparable_test_universes_do_not_replace_selected_candidate(self):
        from keel.repair_checkpoints import RepairCheckpoints
        from types import SimpleNamespace
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'module.py').write_bytes(b'old')
            ws=SimpleNamespace(path=lambda name,write=False:root/name,trace=Mock(),root=root)
            checkpoints=RepairCheckpoints(ws,root)
            checkpoints.observe(feedback(1),['module.py'],'seed')
            (root/'module.py').write_bytes(b'new')
            checkpoints.observe(feedback(0,identity='b'*64),['module.py'],'other-tests')
            self.assertEqual(checkpoints.best['label'],'seed')
            blob=Path(checkpoints.best['sources']['module.py']['blob'])
            blob.write_bytes(b'tampered')
            with self.assertRaisesRegex(ValueError,'hash changed'):
                checkpoints.restore_on_failure({'module.py':b'old'})
            self.assertEqual((root/'module.py').read_bytes(),b'new')
