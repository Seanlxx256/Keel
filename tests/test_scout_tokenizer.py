import unittest
from unittest.mock import patch
from pathlib import Path
import tempfile
import json
from keel.scout_tokenizer import encode_sample
from keel.scout_tokenizer_setup import prepare
from keel.scout_tokenizer import MODEL,REVISION,ASSET_FILES,file_hash
from keel.scout_tokenizer import environment_receipt


class CharacterTokenizer:
    eos_token_id=ord('!')
    def apply_chat_template(self,messages,**kwargs):
        assert kwargs['enable_thinking'] is False
        return 'prompt>'+('' if kwargs['add_generation_prompt'] else messages[-1]['content']+'!')
    def __call__(self,text,**kwargs):
        value={'input_ids':[ord(c) for c in text]}
        if kwargs.get('return_offsets_mapping'):value['offset_mapping']=[(i,i+1) for i in range(len(text))]
        return value
    def decode(self,ids,**kwargs):return ''.join(map(chr,ids))


class ScoutTokenizerTests(unittest.TestCase):
    def test_completed_check_metadata_adoption_preserves_source_and_rejects_data_drift(self):
        from keel.scout_tokenizer_setup import adopt_completed_check
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);assets=root/'assets';assets.mkdir();data=root/'data';data.mkdir();source=root/'check';source.mkdir()
            for name in ASSET_FILES:(assets/name).write_text(json.dumps({'model_type':'qwen3'}))
            receipt={'model':MODEL,'revision':REVISION,'files':{n:file_hash(assets/n) for n in ASSET_FILES}}
            (assets/'assets.json').write_text(json.dumps(receipt));(data/'development.jsonl').write_text('{}\n')
            (data/'export.json').write_text(json.dumps({'status':'exported_development_only','dataset_sha256':file_hash(data/'development.jsonl'),'sample_count':1}))
            checked={'status':'passed','model':MODEL,'revision':REVISION,'tokenizer_assets':receipt,'dataset_sha256':file_hash(data/'development.jsonl'),'samples':[{}]}
            (source/'check.json').write_text(json.dumps(checked));(source/'check-process.json').write_text(json.dumps({'returncode':0,'timeout':False}))
            original=(source/'check.json').read_bytes()
            adopted=adopt_completed_check(data,assets,source,root/'adopted')
            self.assertEqual(adopted['status'],'passed');self.assertEqual((source/'check.json').read_bytes(),original)
            (data/'development.jsonl').write_text('changed')
            with self.assertRaisesRegex(ValueError,'matching'):adopt_completed_check(data,assets,source,root/'bad')
    def test_environment_uses_selected_distribution_not_shadowed_last_entry(self):
        from types import SimpleNamespace
        distributions=[SimpleNamespace(metadata={'Name':name},version=version) for name,version in
            [('transformers','4.57.6'),('jinja2','3.1.6'),('jinja2','3.1.4')]]
        with tempfile.TemporaryDirectory() as tmp,patch('keel.scout_tokenizer.metadata.distributions',return_value=distributions),\
                patch('keel.scout_tokenizer.metadata.version',side_effect={'transformers':'4.57.6','jinja2':'3.1.6'}.__getitem__):
            receipt=environment_receipt(Path(tmp))
            self.assertEqual(receipt['packages']['jinja2'],'3.1.6')

    def test_full_template_masks_prompt_and_trains_target_eos(self):
        result=encode_sample(CharacterTokenizer(),{'prompt':[],'completion':[{'role':'assistant','content':'{}'}]})
        self.assertEqual(result['labels'],[-100]*7+[ord('{'),ord('}'),ord('!')])
        self.assertEqual(result['metrics']['labelled_tokens'],3)

    def test_crossing_boundary_requires_review(self):
        class Crossing(CharacterTokenizer):
            def __call__(self,text,**kwargs):
                value=super().__call__(text,**kwargs)
                if 'offset_mapping' in value:value['offset_mapping'][6]=(6,8)
                return value
        with self.assertRaisesRegex(ValueError,'crosses'):
            encode_sample(Crossing(),{'prompt':[],'completion':[{'role':'assistant','content':'{}'}]})

    def test_no_eos_is_rejected(self):
        tokenizer=CharacterTokenizer();tokenizer.eos_token_id=0
        with self.assertRaisesRegex(ValueError,'EOS'):
            encode_sample(tokenizer,{'prompt':[],'completion':[{'role':'assistant','content':'{}'}]})

    def test_preparation_failure_preserves_stage_and_never_overwrites(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);data=root/'data';data.mkdir()
            for name in ('export.json','development.jsonl'):(data/name).write_text('{}')
            failed={'returncode':1,'timeout':False,'stdout':'','stderr':'fixture error'}
            with patch('keel.scout_tokenizer_setup.CommandRunner.run',return_value=failed):
                with self.assertRaisesRegex(RuntimeError,'venv failed'):prepare(data,root/'out')
            report=json.loads((root/'out/report.json').read_text())
            self.assertEqual(report['status'],'incomplete')
            self.assertEqual(report['stages'][0]['name'],'venv')
            self.assertTrue((root/'out/venv-process.json').exists())
            with self.assertRaises(FileExistsError):prepare(data,root/'out')

    def test_recovery_rejects_drift_before_dispatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);data=root/'data';data.mkdir();old=root/'old';old.mkdir()
            for name in ('export.json','development.jsonl'):(data/name).write_text('{}')
            (old/'report.json').write_text(json.dumps({'identity':{}}))
            with patch('keel.scout_tokenizer_setup.CommandRunner.run') as runner:
                with self.assertRaisesRegex(ValueError,'changed'):prepare(data,root/'out',recover_from=old)
                runner.assert_not_called()
            self.assertFalse((root/'out').exists())

    def test_completed_dependencies_and_assets_reused_after_failed_check(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);data=root/'data';data.mkdir()
            for name in ('export.json','development.jsonl'):(data/name).write_text('{}')
            calls=[];fail_check=True
            def run(command,cwd,timeout):
                calls.append(command);out=Path(cwd)
                if 'venv' in command:
                    env=Path(command[-1]);python=env/('Scripts/python.exe' if __import__('os').name=='nt' else 'bin/python')
                    python.parent.mkdir(parents=True);python.write_bytes(b'fixture')
                if 'environment' in command:
                    (out/'environment.json').write_text(json.dumps({'python':command[0],
                        'python_sha256':file_hash(command[0]),'packages':{'fixture':'1'}}))
                if 'download' in command:
                    assets=out/'assets';assets.mkdir()
                    for name in ASSET_FILES:(assets/name).write_text(json.dumps({'model_type':'qwen3'}))
                    (assets/'assets.json').write_text(json.dumps({'model':MODEL,'revision':REVISION,
                        'files':{name:file_hash(assets/name) for name in ASSET_FILES}}))
                if 'check' in command:
                    if fail_check:return {'returncode':1,'timeout':False,'stdout':'','stderr':'fixture failure'}
                    (out/'check.json').write_text(json.dumps({'status':'passed'}))
                return {'returncode':0,'timeout':False,'stdout':'','stderr':''}
            with patch('keel.scout_tokenizer_setup.CommandRunner.run',side_effect=run):
                with self.assertRaises(RuntimeError):prepare(data,root/'first')
                fail_check=False;calls.clear()
                result=prepare(data,root/'second',recover_from=root/'first')
            self.assertEqual(result['status'],'passed')
            self.assertEqual(len(calls),2)
            self.assertIn('environment',calls[0]);self.assertIn('check',calls[1])
            self.assertEqual(json.loads((root/'first/report.json').read_text())['status'],'incomplete')
