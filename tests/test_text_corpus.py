from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from compass.text_corpus import TextCorpus,chunks


class TextCorpusTests(unittest.TestCase):
    def test_git_inventory_failure_is_an_explicit_tool_error(self):
        from compass.text_corpus import inventory
        with tempfile.TemporaryDirectory() as directory:
            with patch('compass.text_corpus.subprocess.run',return_value=SimpleNamespace(returncode=128,stdout=b'')) as run:
                with self.assertRaisesRegex(ValueError,'Git-tracked source files'):inventory(Path(directory))
            self.assertIn('safe.directory='+Path(directory).resolve().as_posix(),run.call_args.args[0])

    def test_tracked_types_scope_resume_staleness_and_source_ranges(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);repo=root/'repo';repo.mkdir()
            subprocess.run(['git','init',str(repo)],capture_output=True,check=True)
            (repo/'a.py').write_text('def important():\n    return 1\n')
            (repo/'guide.rst').write_text('Configuration\n=============\nimportant settings\n')
            (repo/'pyproject.toml').write_text('[tool.important]\nenabled=true\n')
            subprocess.run(['git','-c','safe.directory='+str(repo),'add','.'],cwd=repo,capture_output=True,check=True)
            (repo/'untracked.md').write_text('important')
            with TextCorpus(root/'index.sqlite') as corpus:
                built=corpus.build(repo);self.assertEqual(built['files'],3)
                rows=corpus.search('important');self.assertEqual({r['path'] for r in rows},{'a.py','guide.rst','pyproject.toml'})
                self.assertEqual([r['path'] for r in corpus.search('important','python')],['a.py'])
                self.assertEqual(len(corpus.search('important','text')),2)
                for r in rows:self.assertLessEqual(r['end_line'],len((repo/r['path']).read_text().splitlines()))
                self.assertEqual(corpus.build(repo)['reused_files'],3)
                (repo/'guide.rst').write_text('different')
                with self.assertRaisesRegex(ValueError,'stale'):corpus.search('important')
                self.assertEqual(corpus.build(repo)['reused_files'],2)
                self.assertNotIn('guide.rst',{r['path'] for r in corpus.search('important')})

    def test_checkpoint_after_timeout_is_not_queryable_and_can_resume(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);repo=root/'repo';repo.mkdir()
            subprocess.run(['git','init',str(repo)],capture_output=True,check=True)
            (repo/'a.py').write_text('x=1')
            subprocess.run(['git','-c','safe.directory='+str(repo),'add','.'],cwd=repo,capture_output=True,check=True)
            with TextCorpus(root/'index.sqlite') as corpus:
                with self.assertRaises(TimeoutError):corpus.build(repo,timeout=0)
                with self.assertRaisesRegex(ValueError,'incomplete'):corpus.search('x')
                corpus.build(repo);self.assertEqual(len(corpus.search('x')),1)

    def test_chunk_boundaries_are_exact_and_bounded(self):
        pieces=list(chunks('\n'.join(str(i) for i in range(70))))
        self.assertEqual([(a,b) for a,b,_ in pieces],[(1,32),(33,64),(65,70)])
        self.assertEqual(list(chunks('')),[])


if __name__=='__main__':unittest.main()
