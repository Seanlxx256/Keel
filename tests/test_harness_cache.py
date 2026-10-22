import copy
from types import SimpleNamespace
import unittest

from keel.harness_cache import apply_cache_scope


class CacheTests(unittest.TestCase):
    def spec(self):
        return SimpleNamespace(base_image_key='base:latest', env_image_key='env:hash',
            instance_dockerfile='FROM env:hash', repo_script_list=['git reset --hard pinned'],
            env_script_list=['pip install pinned'], instance_image_tag='latest', eval_script_list=['pytest original'])

    def test_identical_recipe_and_session_reuse_tag_without_changing_tests(self):
        a, b = self.spec(), self.spec()
        apply_cache_scope(a, 'a'*32); apply_cache_scope(b, 'a'*32)
        self.assertEqual(a.instance_image_tag, b.instance_image_tag)
        self.assertEqual(a.eval_script_list, ['pytest original'])
        tag = a.instance_image_tag; apply_cache_scope(a, 'a'*32)
        self.assertEqual(a.instance_image_tag, tag)

    def test_recipe_session_and_environment_policy_changes_invalidate(self):
        baseline = apply_cache_scope(self.spec(), 'a'*32).instance_image_tag
        for field, value in [('repo_script_list', ['changed']), ('env_image_key', 'different'),
                             ('env_script_list', ['changed']), ('instance_image_tag', 'overlay-tag')]:
            with self.subTest(field=field):
                spec = self.spec(); setattr(spec, field, value)
                self.assertNotEqual(apply_cache_scope(spec, 'a'*32).instance_image_tag, baseline)
        self.assertNotEqual(apply_cache_scope(self.spec(), 'b'*32).instance_image_tag, baseline)

    def test_invalid_or_stacked_scope_rejected(self):
        with self.assertRaises(ValueError): apply_cache_scope(self.spec(), 'arbitrary')
        spec = apply_cache_scope(self.spec(), 'a'*32)
        with self.assertRaises(ValueError): apply_cache_scope(spec, 'b'*32)
