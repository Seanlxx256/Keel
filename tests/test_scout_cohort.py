import unittest
from keel.scout_cohort import reserve_cohort


class CohortTests(unittest.TestCase):
    def test_one_source_block_does_not_discard_other_fixed_tasks(self):
        import json
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        from examples.prepare_scout_cohort_sources import execute
        from keel.scout_tokenizer import file_hash
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);inventory=root/'inventory.json'
            rows=[{'instance_id':name,'repo':'repo/project','base_commit':'a'*40,'previously_trained':False,
                   'partition':'transfer_review','source_status':'commit_available','source_repository':'local'} for name in ('one','two')]
            inventory.write_text(json.dumps({'status':'reserved_pending_source_export','rows':rows}))
            plan=root/'plan.json';plan.write_text(json.dumps({'inventory':str(inventory),'inputs':{str(inventory):file_hash(inventory)}}))
            def prepare(repo,commit,destination,**kwargs):
                if destination.parent.name=='one':raise ValueError('Symlink archive member is not exported')
                destination.mkdir(parents=True)
                destination.with_name(destination.name+'.export.json').write_text('{}')
            with patch('examples.prepare_scout_cohort_sources.prepare_archive_snapshot',side_effect=prepare),\
                 patch('examples.prepare_scout_cohort_sources.check_archive_snapshot',return_value={'files':{}}):
                report=execute(plan,root/'output')
            self.assertEqual(len(report['rows']),2)
            self.assertEqual(report['counts'],{'source_export_blocked':1,'exported_verified':1})
            self.assertFalse(report['rows'][0]['source_export_verified'])

    def test_group_reservation_preserves_trained_and_quarantine(self):
        tasks=[{'instance_id':name,'repo':repo,'base_commit':'a'*40,'problem_statement':'public'}
               for name,repo in [('train-1','train'),('train-2','train'),('eval-1','eval'),('hold-1','hold')]]
        prior={'train-1':{'partition':'training_review'},'hold-1':{'partition':'quarantine'}}
        partitions={'train':'training_review','eval':'transfer_review','hold':'quarantine'}
        result=reserve_cohort(tasks+tasks[:1],{'train-1'},prior,partitions)
        self.assertEqual(len(result),4)
        self.assertFalse(any(row['new_training_approved'] or row['independent_evaluation_eligible'] for row in result))
        self.assertEqual([r['partition'] for r in result if r['repo']=='train'],['training_review']*2)
        with self.assertRaisesRegex(ValueError,'boundary'):reserve_cohort(tasks,{'train-1'},prior,{**partitions,'hold':'training_review'})
        with self.assertRaises(ValueError):reserve_cohort(tasks,{'train-1'},prior,{**partitions,'train':'transfer_review'})

    def test_conflicting_identity_and_missing_repository_fail(self):
        task={'instance_id':'one','repo':'repo','base_commit':'a'*40,'problem_statement':'public'}
        with self.assertRaisesRegex(ValueError,'Conflicting'):reserve_cohort([task,{**task,'base_commit':'b'*40}],set(),{}, {'repo':'transfer_review'})
        with self.assertRaisesRegex(ValueError,'every repository'):reserve_cohort([task],set(),{}, {})
        with self.assertRaisesRegex(ValueError,'missing'):reserve_cohort([task],{'absent'},{},{'repo':'training_review'})
