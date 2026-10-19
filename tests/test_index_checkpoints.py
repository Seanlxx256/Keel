from pathlib import Path
import tempfile
import unittest

from compass.index import build_index, RepositoryIndex
from compass.vectors import HashEmbedder


class CheckpointTests(unittest.TestCase):
    def test_interrupted_batches_resume_without_reembedding_completed_text(self):
        class Interrupting(HashEmbedder):
            def __init__(self):
                super().__init__()
                self.calls = []
            def embed(self, texts):
                self.calls.append(list(texts))
                if len(self.calls) == 2:
                    raise RuntimeError('simulated interruption')
                return super().embed(texts)
        class Counting(HashEmbedder):
            def __init__(self):
                super().__init__()
                self.texts = []
            def embed(self, texts):
                self.texts.extend(texts)
                return super().embed(texts)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'a.py').write_text('\n'.join(f'def function_{i}():\n    return {i}' for i in range(40)))
            first = Interrupting()
            with self.assertRaisesRegex(RuntimeError, 'simulated'):
                build_index(root, parser='python-ast', vector_store='sqlite', embedder=first, checkpoint_vectors=True)
            self.assertFalse((root/'.compass/current.json').exists())
            next_attempt, events = Counting(), []
            result = build_index(root, parser='python-ast', vector_store='sqlite', embedder=next_attempt,
                                 checkpoint_vectors=True, progress=events.append)
            self.assertEqual(result['update']['reused_vectors'], 32)
            self.assertEqual(len(next_attempt.texts), 8)
            self.assertFalse(set(next_attempt.texts) & set(first.calls[0]))
            self.assertTrue(any(e['stage'] == 'embed' and e['vectors_completed'] == 40 for e in events))
            with RepositoryIndex(root) as index:
                self.assertEqual(index.db.execute('select count(*) from vectors').fetchone()[0], 40)
            # Changed checkpoint identity must not reuse another model's vectors.
            changed = Counting()
            changed.checkpoint_identity = {'model_digest': 'different'}
            build_index(root, parser='python-ast', vector_store='sqlite', embedder=changed, checkpoint_vectors=True)
            self.assertEqual(len(changed.texts), 40)

    def test_expired_budget_does_not_publish_index(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'a.py').write_text('def f():\n    pass\n')
            with self.assertRaises(TimeoutError):
                build_index(root, parser='python-ast', max_wallclock=1e-12)
            self.assertFalse((root/'.compass/current.json').exists())
