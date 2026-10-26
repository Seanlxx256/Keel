import copy,json,tempfile,unittest
from pathlib import Path
from keel.scout_candidate_ids import numbered_example,decode_ids,numbered_prompt
from keel.scout_id_training import export_ids,original_examples
from keel.scout_permutation_data import export_permutations
from keel.scout_tokenizer import file_hash
from tests.test_scout_candidate_ids import fixture


class PermutationDataTests(unittest.TestCase):
    def test_shuffle_roundtrip_metadata_and_target_independence(self):
        row=fixture();payload=json.loads(row['prompt'][-1]['content'])
        for item in payload['structure']:item['definition_bytes']=[f'metadata-{s[0]}' for s in item['symbols']]
        row['prompt'][-1]['content']=json.dumps(payload);before=copy.deepcopy(row)
        for mode in ['shuffle_ids:train-1','shuffle_catalog:train-1','shuffle_catalog:eval-1']:
            actual,mapping,spec=numbered_example(row,permutation=mode)
            self.assertEqual(json.loads(decode_ids(actual['completion'][0]['content'],mapping,spec)),json.loads(row['completion'][0]['content']))
            changed=copy.deepcopy(row);changed['completion'][0]['content']='{"locations":["wrong:999"]}'
            self.assertEqual(numbered_prompt(row['prompt'],permutation=mode),numbered_prompt(changed['prompt'],permutation=mode))
            self.assertEqual(numbered_example(row,permutation=mode),numbered_example(row,permutation=mode))
            for item in json.loads(actual['prompt'][-1]['content'])['structure']:
                for symbol,metadata in zip(item['symbols'],item['definition_bytes']):
                    self.assertEqual(metadata,f'metadata-{symbol[0]}')
        self.assertEqual(row,before)

    def test_export_restores_logical_cohort_and_rejects_changed_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'source';source.mkdir();row=fixture()
            data=source/'development.jsonl';data.write_text(json.dumps(row)+'\n')
            (source/'export.json').write_text(json.dumps({'status':'exported_development_only','sample_count':1,
                'dataset_sha256':file_hash(data),'tasks':['train']}))
            export_ids(source,root/'ids')
            meta=export_permutations(root/'ids',['original','shuffle_ids:train-1'],root/'aug')
            self.assertEqual(meta['sample_count'],2);self.assertEqual(meta['original_sample_count'],1)
            self.assertEqual(original_examples(root/'aug')[0],[row])
            path=root/'aug/development.jsonl';values=[json.loads(s) for s in path.read_text().splitlines()]
            values[1]['completion'][0]['content']='{"candidate_ids":[999]}'
            path.write_text(''.join(json.dumps(v)+'\n' for v in values))
            meta['dataset_sha256']=file_hash(path);(root/'aug/export.json').write_text(json.dumps(meta))
            with self.assertRaisesRegex(ValueError,'Permutation'):original_examples(root/'aug')
