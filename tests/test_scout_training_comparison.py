import copy
import unittest
from keel.scout_training_comparison import compare_observations


class ScoutTrainingComparisonTests(unittest.TestCase):
    def inputs(self):
        train={'status':'passed','steps':[{'input_tokens':10,'labelled_tokens':2}]*4,
            'epochs':2,'seed':42,'lora':{'r':4},'weights':{'files':{'model':'pinned'}}}
        def report(n):
            return {'status':'completed','generation':{'max_new_tokens':256},'dataset_sha256':'transfer',
                'rows':[{'arm':arm,'sample':i,'labelled_tokens':2,'teacher_nll':1.0,'finish_reason':'eos',
                    'score':{'json_valid':True,'contract_valid':True,'teacher_selection_equal':False}}
                    for arm in ('base','adapter') for i in range(n)]}
        return [[{'id':'a'}],[{'id':'a'},{'id':'b'}],copy.deepcopy(train),copy.deepcopy(train),report(1),report(2),report(1),report(1),4]

    def test_added_training_fit_never_inflates_common_or_transfer_metrics(self):
        args=self.inputs()
        for row in args[5]['rows']:
            if row['sample']==1:row['score']['teacher_selection_equal']=True
        result=compare_observations(*args)
        self.assertEqual(result['common_controls']['new']['adapter']['teacher_selection_equal'],0)
        self.assertEqual(result['added_controls']['new_only']['adapter']['teacher_selection_equal'],1)
        self.assertFalse(result['production_promoted']);self.assertIsNone(result['selected_checkpoint'])

    def test_changed_examples_generation_updates_or_transfer_are_rejected(self):
        for index,change in [(1,lambda x:x[0].update(id='changed')),
                             (3,lambda x:x['steps'].pop()),
                             (5,lambda x:x['generation'].update(max_new_tokens=512)),
                             (7,lambda x:x.update(dataset_sha256='changed'))]:
            args=self.inputs();change(args[index])
            with self.subTest(index=index),self.assertRaises(ValueError):compare_observations(*args)

    def test_missing_rows_or_changed_training_controls_are_rejected(self):
        args=self.inputs();args[5]['rows'].pop()
        with self.assertRaisesRegex(ValueError,'rows'):compare_observations(*args)
        args=self.inputs();args[3]['seed']=43
        with self.assertRaisesRegex(ValueError,'control changed'):compare_observations(*args)
