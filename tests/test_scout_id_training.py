import json
from pathlib import Path
import tempfile
import unittest
from keel.scout_id_training import export_ids, original_examples, export_auxiliary, export_lookup_only
from keel.scout_tokenizer import file_hash
from tests.test_scout_candidate_ids import fixture


class IdTrainingTests(unittest.TestCase):
    def test_subset_preserves_complete_rows_and_rejects_rewritten_teacher(self):
        from keel.scout_id_training import export_subset,validate_subset_indices,training_task_universe
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'source';source.mkdir();row=fixture()
            data=source/'development.jsonl';data.write_text(json.dumps(row)+'\n')
            (source/'export.json').write_text(json.dumps({'status':'exported_development_only','sample_count':1,
                'dataset_sha256':file_hash(data),'tasks':['training']}))
            export_ids(source,root/'ids');export_subset(root/'ids',[0],root/'subset')
            self.assertEqual(training_task_universe(json.loads((root/'subset/export.json').read_text())),['training'])
            self.assertEqual((root/'ids/development.jsonl').read_bytes(),(root/'subset/development.jsonl').read_bytes())
            self.assertEqual(original_examples(root/'subset')[0],[row])
            changed=root/'subset/development.jsonl';changed.write_text('{}\n')
            meta=root/'subset/export.json';value=json.loads(meta.read_text());value['dataset_sha256']=file_hash(changed)
            meta.write_text(json.dumps(value))
            with self.assertRaisesRegex(ValueError,'Subset'):original_examples(root/'subset')
        for invalid in ([],[True],[0,0],[-1],[1]):
            with self.assertRaises(ValueError):validate_subset_indices(invalid,1)
    def test_diverse_queries_exclude_control_and_ignore_repair_teacher(self):
        import copy
        from keel.scout_lookup_data import lookup_variants
        from keel.scout_candidate_ids import lookup_example,decode_ids
        row=fixture();row['prompt'][0]['content']=row['prompt'][0]['content'].replace('Select 1..8 definition locations.', 'Select 1..8 definition locations from the supplied structure for repair.')
        unchanged=copy.deepcopy(row);variants,manifest=lookup_variants(row)
        self.assertEqual(len(variants),6)
        self.assertEqual(len({json.dumps(r,sort_keys=True) for r in variants}),6)
        for item in manifest['variants']:
            self.assertNotEqual(item['query'],manifest['excluded_query'])
            actual,mapping,spec,scoring,_=lookup_example(row,presentation='without_goal',query=item['query'],permutation=item['permutation'])
            self.assertEqual(json.loads(decode_ids(actual['completion'][0]['content'],mapping,spec)),json.loads(scoring['completion'][0]['content']))
        changed=copy.deepcopy(row);changed['completion'][0]['content']='{"locations":["unknown:999"]}'
        self.assertEqual(lookup_variants(changed),(variants,manifest))
        self.assertEqual(row,unchanged)
    def test_auxiliary_preserves_prefix_and_never_includes_other_catalogs(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);source=root/'source';source.mkdir()
            row=fixture()
            row['prompt'][0]['content']=row['prompt'][0]['content'].replace('Select 1..8 definition locations.', 'Select 1..8 definition locations from the supplied structure for repair.')
            data=source/'development.jsonl';data.write_text(json.dumps(row)+'\n')
            (source/'export.json').write_text(json.dumps({'status':'exported_development_only','dataset_sha256':file_hash(data),'sample_count':1,'tasks':['training']}))
            export_ids(source,root/'ids');report=export_auxiliary(root/'ids',root/'aux')
            lookup=export_lookup_only(root/'ids',root/'lookup')
            self.assertEqual(lookup['sample_count'],1)
            self.assertEqual(original_examples(root/'lookup')[0],[row])
            diverse=export_lookup_only(root/'ids',root/'diverse',diverse=True)
            self.assertEqual(diverse['sample_count'],6)
            self.assertEqual(original_examples(root/'diverse')[0],[row])
            lookup_data=root/'lookup/development.jsonl';lookup_data.write_text('{}\n')
            with self.assertRaisesRegex(ValueError,'Lookup-only'):original_examples(root/'lookup')
            self.assertEqual(report['tasks'],['training']);self.assertEqual(report['sample_count'],2)
            self.assertTrue((root/'aux/development.jsonl').read_bytes().startswith((root/'ids/development.jsonl').read_bytes()))
            self.assertEqual(original_examples(root/'aux')[0],[row])
            actual=root/'aux/development.jsonl'
            values=actual.read_text().splitlines();tail=json.loads(values[-1]);tail['completion'][0]['content']='{"candidate_ids":[0]}'
            actual.write_text(values[0]+'\n'+json.dumps(tail)+'\n')
            meta=root/'aux/export.json';changed=json.loads(meta.read_text());changed['dataset_sha256']=file_hash(actual);meta.write_text(json.dumps(changed))
            with self.assertRaisesRegex(ValueError,'Auxiliary lookup'):original_examples(root/'aux')

    def test_original_scoring_rejects_mapping_and_source_drift(self):
        from tests.test_scout_adapter_eval import example
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary); source=root/'source';source.mkdir()
            rows=[example(),fixture()]
            data=source/'development.jsonl'
            data.write_text(''.join(json.dumps(row)+'\n' for row in rows),encoding='utf-8')
            (source/'export.json').write_text(json.dumps({'status':'exported_development_only',
                'dataset_sha256':file_hash(data),'sample_count':2,'tasks':['development']}))
            export_ids(source,root/'out')
            self.assertEqual(original_examples(root/'out')[0],rows)
            actual=[json.loads(line) for line in (root/'out/development.jsonl').read_text().splitlines()]
            self.assertEqual(actual[0],rows[0])
            mapping=root/'out/mappings.json';original=mapping.read_bytes()
            mapping.write_text('{}')
            with self.assertRaisesRegex(ValueError,'Mapping'):original_examples(root/'out')
            mapping.write_bytes(original)
            data.write_text('{}\n')
            with self.assertRaisesRegex(ValueError,'source changed'):original_examples(root/'out')

    def test_encoding_preserves_logical_target_and_original(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); source = root/'source'; source.mkdir()
            row = fixture()
            (source/'development.jsonl').write_text(json.dumps(row)+'\n', encoding='utf-8')
            identity = file_hash(source/'development.jsonl')
            (source/'export.json').write_text(json.dumps({'status':'exported_development_only',
                'dataset_sha256':identity, 'sample_count':1, 'tasks':['development']}))
            report = export_ids(source, root/'out')
            actual = json.loads((root/'out/development.jsonl').read_text())
            self.assertEqual(json.loads(actual['completion'][0]['content']), {'candidate_ids':[1]})
            self.assertEqual(file_hash(source/'development.jsonl'), identity)
            self.assertEqual(report['transformed_samples'], [0])
            restored, receipt = original_examples(root/'out')
            self.assertEqual(restored, [row])
            self.assertEqual(receipt['sha256'], identity)
            encoded = root/'out/development.jsonl'
            encoded.write_text(encoded.read_text().replace('candidate_ids', 'wrong_ids'))
            with self.assertRaisesRegex(ValueError, 'Encoded'): original_examples(root/'out')
            with self.assertRaises(FileExistsError): export_ids(source, root/'out')
            (source/'development.jsonl').write_text('{}\n')
            with self.assertRaisesRegex(ValueError, 'unchanged'): export_ids(source, root/'bad')
            self.assertFalse((root/'bad').exists())
