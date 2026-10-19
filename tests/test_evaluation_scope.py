import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch
from compass.evaluation_scope import reference_scope,POLICY
from examples.run_structural_validation import task_run,digest


class EvaluationScopeTests(unittest.TestCase):
    def test_supported_source_and_unsupported_docs_config_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            (root/'a.py').write_text('x=1')
            (root/'doc.rst').write_text('Documentation')
            (root/'pyproject.toml').write_text('[build-system]')
            instance=dict(repo=str(root),core_files=['a.py','doc.rst','pyproject.toml'])
            report=reference_scope(instance)
            self.assertFalse(report['eligible'])
            self.assertEqual([r['path'] for r in report['blocked']],['doc.rst','pyproject.toml'])
            self.assertEqual(instance['core_files'],['a.py','doc.rst','pyproject.toml'])
            self.assertTrue(reference_scope(dict(repo=str(root),core_files=['a.py']))['eligible'])

    def test_ignored_and_oversized_python_do_not_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'build').mkdir()
            (root/'build/a.py').write_text('x=1')
            (root/'large.py').write_bytes(b' ' * 1_000_001)
            result=reference_scope(dict(repo=str(root),core_files=['build/a.py','large.py']))
            self.assertFalse(result['eligible'])
            self.assertEqual(result['blocked'][1]['reason'],'exceeds_index_file_size_limit')

    def test_runner_blocks_before_embedding_or_native_tools(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);repo=root/'repo';repo.mkdir();(repo/'doc.rst').write_text('docs')
            dataset=root/'data.jsonl';dataset.write_text('{}\n')
            planfile=root/'plan.json';planfile.write_text('{}')
            task=dict(instance_id='owner__repo-1',repository='owner/repo',base_commit='a'*40,
                      dataset=str(dataset),dataset_sha256=digest(dataset))
            index=Mock();native=Mock()
            with patch.multiple('examples.run_structural_validation',
                verify_plan=lambda _:dict(tasks=[task],policy={'scope_preflight':POLICY}),
                prepare_snapshot=lambda *a,**kw:repo,
                load_swe_instance=lambda *a,**kw:dict(repo=str(repo),core_files=['doc.rst']),
                bounded_index=index,compare=native):
                report=task_run(root,planfile,root/'output',1)
            self.assertEqual(report['status'],'out_of_scope')
            index.assert_not_called();native.assert_not_called()
            self.assertEqual(json.loads((root/'output/task-1/result.json').read_text())['stage'],'scope_preflight')


if __name__=='__main__':
    unittest.main()
