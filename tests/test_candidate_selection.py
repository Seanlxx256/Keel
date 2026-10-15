import contextlib
import copy
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.parse import urlencode

from keel.candidate_selection import shortlist, validate_policy


def policy():
    return {'schema_version': 1, 'repositories': ['org/one', 'org/two'], 'query': 'compatibility',
        'limit_per_repository': 5, 'pages': 1, 'seed': 42, 'selected_repositories': 2,
        'max_changed_python_sources': 3, 'localization_policy': 'base only',
        'attempt_policy': 'first', 'scope': 'metadata'}


def row(repo, number):
    return {'repository': repo, 'number': number, 'title': 'Add dependency compatibility',
        'merged': True, 'base_commit': 'a'*40, 'gold_commit': 'b'*40,
        'files': ['src/app.py'], 'ci_paths': []}


KNOWN = {'tasks': [{'id': 'dev', 'repository': 'org/dev'}], 'repository_aliases': {'old/dev': 'org/dev'}}


class CandidateSelectionTests(unittest.TestCase):
    def test_v2_missing_commit_is_visible_exclusion_not_a_ready_candidate(self):
        amended = {**policy(), 'schema_version': 2,
                   'missing_commit_policy': 'record_exclusion_count_toward_limit'}
        inputs = self.collections()
        inputs['org/one']['candidates'][0].update(base_commit=None, metadata_error='merge_commit_unavailable')
        result = shortlist(amended, KNOWN, inputs)
        rejected = [r for r in result['screened'] if r['repository']=='org/one' and r['number']==1][0]
        self.assertIn('merge_commit_unavailable', rejected['reasons'])
        self.assertFalse(rejected['eligible_metadata_only'])
        self.assertEqual(result['independent_tasks_ready'], 0)

    def collections(self):
        return {repo: {'status': 'completed', 'candidates': [row(repo, 1), row(repo, 2)]}
                for repo in policy()['repositories']}

    def test_selection_is_order_independent_and_does_not_use_model_outcomes(self):
        inputs = self.collections()
        first = shortlist(policy(), KNOWN, inputs)
        for state in inputs.values():
            state['candidates'].reverse()
            for candidate in state['candidates']:
                candidate['model_passed'] = True
        second = shortlist(policy(), KNOWN, dict(reversed(list(inputs.items()))))
        self.assertEqual(first, second)
        self.assertEqual(len({row['repository'] for row in first['selected']}), 2)

    def test_partial_or_insufficient_pool_never_silently_selects_survivors(self):
        for change in ('partial', 'empty'):
            inputs = self.collections()
            if change == 'partial':
                inputs['org/one']['status'] = 'failed'
            else:
                inputs['org/one']['candidates'] = []
            result = shortlist(policy(), KNOWN, inputs)
            self.assertEqual(result['selected'], [])
            self.assertGreater(len(result['screened']), 0)

    def test_rejection_reasons_and_duplicate_aliases_are_visible(self):
        inputs = self.collections()
        inputs['org/one']['candidates'][0]['files'] = ['README.md']
        result = shortlist(policy(), KNOWN, inputs)
        rejected = [row for row in result['screened'] if not row['eligible_metadata_only']]
        self.assertIn('source_count_outside_policy', rejected[0]['reasons'])
        inputs['org/one']['candidates'].append(row('org/one', 2))
        with self.assertRaises(ValueError):
            shortlist(policy(), KNOWN, inputs)
        bad = policy()
        bad['repositories'][0] = 'OLD/DEV'
        with self.assertRaises(ValueError):
            validate_policy(bad, KNOWN)

    def test_live_collector_boundary_can_be_replayed_offline_with_same_shortlist(self):
        from examples import prepare_independent_candidates as cli
        from examples.mine_upgradebench import GitHub
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'examples').mkdir()
            (root/'keel').mkdir()
            for path in ('examples/prepare_independent_candidates.py', 'examples/mine_upgradebench.py', 'keel/candidate_selection.py'):
                (root/path).write_text('fixture code')
            (root/'examples/evaluation_development_registry.json').write_text(json.dumps(KNOWN))
            plan = policy()
            plan.update(repositories=['org/one'], selected_repositories=1)
            plan_path = root/'policy.json'
            plan_path.write_text(json.dumps(plan))
            params = urlencode({'q': 'repo:org/one is:pr is:merged compatibility in:title',
                                'sort': 'updated', 'order': 'desc', 'per_page': 100, 'page': 1})
            routes = {'/repos/org/one': {'full_name': 'org/one'},
                '/search/issues?'+params: {'incomplete_results': False, 'items': [{'number': 1}]},
                '/repos/org/one/pulls/1': {'merged': True, 'changed_files': 1, 'merge_commit_sha': 'b'*40, 'title': 'Add compatibility'},
                '/repos/org/one/pulls/1/files?per_page=100&page=1': [{'filename': 'src/app.py'}],
                '/repos/org/one/commits/'+'b'*40: {'sha': 'b'*40, 'parents': [{'sha': 'a'*40}]},
                '/repos/org/one/git/trees/'+'b'*40+'?recursive=1': {'truncated': False, 'tree': []}}
            base_args = ['prepare', '--policy', str(plan_path)]
            with patch.object(cli, '__file__', str(root/'examples/prepare_independent_candidates.py')), contextlib.redirect_stdout(io.StringIO()), patch('urllib.request.urlopen', side_effect=AssertionError('No network')):
                with patch.object(cli, 'GitHub', side_effect=lambda path: GitHub(path, cached=routes)), patch('sys.argv', base_args+['--execute']), patch.object(cli.uuid, 'uuid4', return_value=SimpleNamespace(hex='first')):
                    self.assertEqual(cli.main(), 0)
                first = root/'.keel/independent-candidates/first'
                with patch.object(cli, 'GitHub', side_effect=AssertionError('Replay must not create network client')), patch('sys.argv', base_args+['--replay-from', str(first)]), patch.object(cli.uuid, 'uuid4', return_value=SimpleNamespace(hex='second')):
                    self.assertEqual(cli.main(), 0)
            second = root/'.keel/independent-candidates/second'
            self.assertEqual(json.loads((first/'shortlist.json').read_text()), json.loads((second/'shortlist.json').read_text()))
            receipts = first/'repositories/org--one/receipts.json'
            missing = '/repos/org/one/commits/'+'b'*40
            receipts.write_text(json.dumps([r for r in json.loads(receipts.read_text()) if r['route'] != missing]))
            requested = []
            def missing_only(client, route):
                requested.append(route)
                return client._save(route, json.dumps(routes[route]).encode())
            with patch.object(cli, '__file__', str(root/'examples/prepare_independent_candidates.py')), contextlib.redirect_stdout(io.StringIO()), patch('urllib.request.urlopen', side_effect=AssertionError('No network')):
                with patch.object(GitHub, '_get', missing_only), patch('sys.argv', base_args+['--resume-from', str(first)]), patch.object(cli.uuid, 'uuid4', return_value=SimpleNamespace(hex='third')):
                    self.assertEqual(cli.main(), 0)
                self.assertEqual(requested, [missing])
                with patch.object(GitHub, '_get', side_effect=ValueError('HTTP 422')), patch('sys.argv', base_args+['--resume-from', str(first)]), patch.object(cli.uuid, 'uuid4', return_value=SimpleNamespace(hex='failed')):
                    self.assertEqual(cli.main(), 1)
            failed = root/'.keel/independent-candidates/failed'
            self.assertEqual(json.loads((failed/'collections.json').read_text())['org/one']['failed_route'], missing)
            self.assertEqual(json.loads((failed/'shortlist.json').read_text())['selected'], [])
            amended = {**plan, 'schema_version': 2, 'missing_commit_policy': 'record_exclusion_count_toward_limit'}
            amended_path = root/'policy-v2.json'
            amended_path.write_text(json.dumps(amended))
            original_bytes = (first/'shortlist.json').read_bytes()
            with patch.object(cli, '__file__', str(root/'examples/prepare_independent_candidates.py')), contextlib.redirect_stdout(io.StringIO()), patch.object(GitHub, '_get', missing_only), patch('sys.argv', ['prepare', '--policy', str(amended_path), '--cache-from', str(first)]), patch.object(cli.uuid, 'uuid4', return_value=SimpleNamespace(hex='v2')):
                self.assertEqual(cli.main(), 0)
            updated = json.loads((root/'.keel/independent-candidates/v2/plan.json').read_text())
            self.assertEqual(updated['prior_collection']['mode'], 'new_v2_cache_reuse')
            self.assertEqual(updated['policy']['schema_version'], 2)
            self.assertEqual((first/'shortlist.json').read_bytes(), original_bytes)
