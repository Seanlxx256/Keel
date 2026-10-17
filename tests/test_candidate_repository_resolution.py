import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from examples import prepare_independent_candidates as runner
from examples.mine_upgradebench import GitHub


class RepositoryResolutionTests(unittest.TestCase):
    def trial(self, candidate_repo='org/new', resolved='org/new'):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        (root/'examples').mkdir()
        (root/'keel').mkdir()
        for name in ('examples/mine_upgradebench.py', 'examples/prepare_independent_candidates.py', 'keel/candidate_selection.py'):
            (root/name).write_text('fixture')
        (root/'examples/evaluation_development_registry.json').write_text(json.dumps({
            'tasks': [{'repository': 'org/dev'}], 'repository_aliases': {}}))
        policy = {'schema_version': 1, 'repositories': ['org/old'], 'query': 'compatibility',
                  'limit_per_repository': 1, 'pages': 1, 'seed': 42, 'selected_repositories': 1,
                  'max_changed_python_sources': 3, 'localization_policy': 'base only',
                  'attempt_policy': 'first', 'scope': 'metadata'}
        (root/'policy.json').write_text(json.dumps(policy))
        def get(client, route):
            return client._save(route, json.dumps({'full_name': resolved}).encode())
        def collect(repo, fetch, **kwargs):
            fetch('/repos/'+repo)
            kwargs['on_candidate']({'repository': candidate_repo, 'number': 1,
                'title': 'Compatibility update', 'merged': True, 'files': ['source.py'],
                'base_commit': 'a'*40, 'gold_commit': 'b'*40, 'ci_paths': []})
        with patch.object(runner, '__file__', str(root/'examples/prepare_independent_candidates.py')), \
             patch('sys.argv', ['prepare', '--policy', str(root/'policy.json'), '--execute']), \
             patch.object(GitHub, '_get', get), patch.object(runner, 'collect', collect), \
             contextlib.redirect_stdout(io.StringIO()):
            code = runner.main()
        output = next((root/'.keel/independent-candidates').iterdir())
        return code, json.loads((output/'collections.json').read_text()), json.loads((output/'shortlist.json').read_text())

    def test_verified_transfer_keeps_policy_identity_and_records_new_identity(self):
        code, collections, shortlist = self.trial()
        self.assertEqual(code, 0)
        self.assertEqual(shortlist['selected'][0]['repository'], 'org/old')
        row = collections['org/old']['candidates'][0]
        self.assertEqual(row['resolved_repository'], 'org/new')
        self.assertEqual(row['repository_resolution_route'], '/repos/org/old')

    def test_unverified_candidate_repo_fails_without_poisoning_checkpoint(self):
        code, collections, shortlist = self.trial(candidate_repo='other/unrelated')
        self.assertEqual(code, 1)
        self.assertEqual(collections['org/old']['candidates'], [])
        self.assertEqual(shortlist['status'], 'incomplete')

    def test_transfer_into_development_repo_is_rejected(self):
        code, collections, shortlist = self.trial(candidate_repo='org/dev', resolved='org/dev')
        self.assertEqual(code, 1)
        self.assertEqual(collections['org/old']['status'], 'failed')
