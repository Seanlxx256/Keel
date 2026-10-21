import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from keel.models import Reply
from keel.runtime import run


class Model:
    def __init__(self, scope):
        self.scope, self.messages = scope, []

    def complete_json(self, messages, **kwargs):
        self.messages.append(messages)
        value = ({'files': self.scope.get('files', [])} if len(self.messages) == 1 else {k: v for k, v in self.scope.items() if k != 'files'}) if len(self.messages) <= 2 else {
            'edits': [{'path': 'module.py', 'old': 'return 1', 'new': 'return 2'}], 'summary': 'Update version'}
        return Reply(json.dumps(value), 100)


class LocalizedProposalTests(unittest.TestCase):
    def test_turn_limit_preserves_read_paths_as_validated_navigation_hints(self):
        (self.root/'aaa.py').write_bytes(b'def unrelated():\n    return 0\n')
        (self.root/'tests').mkdir()
        (self.root/'tests/test_fixture.py').write_bytes(b'assert True\n')
        owner = self
        class Investigating:
            def __init__(self): self.calls = 0
            def complete_json(self, messages, **kwargs):
                self.calls += 1
                if self.calls <= 2:
                    name = 'tests/test_fixture.py' if self.calls == 1 else 'module.py'
                    value = {'tool':'read_lines','arguments':{'path':name,'start_line':1,'end_line':2}}
                elif self.calls == 3:
                    data = json.loads(messages[1]['content'])
                    owner.assertEqual(data['paths'][0], 'module.py')
                    owner.assertNotIn('tests/test_fixture.py', data['paths'])
                    owner.assertIn('aaa.py', data['paths'])
                    value = {'files':['module.py']}
                elif self.calls == 4:
                    value = {'locations':['module.py:1']}
                else:
                    value = {'summary':'Update', 'edits':[{'path':'module.py','old':'return 1','new':'return 2'}]}
                return Reply(json.dumps(value),100)
        result = run({**self.config,'localization_tool_steps':2,
            'budget':{**self.config['budget'],'max_model_calls':5}},self.root,self.root/'.keel/hints',model=Investigating())
        self.assertEqual(result['status'],'passed',result.get('failure'))
        self.assertEqual(result['budget']['model_calls'],5)

    def test_external_validation_success_is_reported_and_missing_tools_rejected(self):
        for config in ({'localization_require_external': True},
                       {'localization_require_external': True, 'localization_tool_steps': 2}):
            with self.assertRaises(ValueError):
                run({**self.config, **config}, self.root, self.root/'.keel/rejected-external')
        class ExternalFirst(Model):
            def complete_json(self, messages, **kwargs):
                if not self.messages:
                    self.messages.append(messages)
                    # On the first turn the schema must exclude local tools/final.
                    aliases = [row['properties']['tool']['enum'][0] for row in kwargs['schema']['oneOf']]
                    self.asserted_aliases = aliases
                    return Reply(json.dumps({'tool': 'mcp__external__find', 'arguments': {}}), 100)
                saved = self.messages.pop(0)
                try:
                    return super().complete_json(messages, **kwargs)
                finally:
                    self.messages.insert(0, saved)
        model = ExternalFirst({'files': ['module.py'], 'locations': ['module.py:1']})
        config = {**self.config, 'localization_tool_steps': 1, 'localization_require_external': True,
            'budget': {**self.config['budget'], 'max_model_calls': 4},
            'mcp_servers': {'external': {'command': 'unused', 'tools': {'find': {
                'roles': ['scout'], 'read_only': True, 'description': 'Find symbols'}}}}}
        with patch('keel.mcp_client.McpTools.call', return_value={'content': [{'type': 'text', 'text': 'module.py:1'}]}):
            result = run(config, self.root, self.root/'.keel/external-success', model=model)
        self.assertEqual(model.asserted_aliases, ['mcp__external__find'])
        self.assertEqual(result['status'], 'passed')
        self.assertEqual(result['external_tool_validation'],
                         {'required': True, 'attempted': True, 'successful_requests': 1})

    def test_exploration_rejects_invalid_limits_and_non_readonly_mcp_tools(self):
        for value in (True, -1, 13):
            with self.assertRaises(ValueError):
                run({**self.config, 'localization_tool_steps': value}, self.root,
                    self.root/'.keel/rejected')
        with self.assertRaisesRegex(ValueError, 'read_only'):
            run({**self.config, 'localization_tool_steps': 2, 'mcp_servers': {
                'external': {'command': 'unused', 'tools': {'edit': {
                    'roles': ['scout'], 'description': 'unreviewed tool'}}}}},
                self.root, self.root/'.keel/rejected')

    def test_tool_exploration_recovers_mcp_failure_and_hands_evidence_to_selection(self):
        class Exploring:
            def __init__(self):
                self.messages = []
                self.actions = iter([
                    {'tool': 'read_file', 'arguments': {'path': 'module.py'}},
                    {'tool': 'mcp__external__find', 'arguments': {}},
                    {'tool': 'read_file', 'arguments': {'path': 'module.py'}},
                    {'final': {'summary': 'version returns 1', 'files': ['module.py']}},
                    {'locations': ['module.py:1']},
                    {'edits': [{'path': 'module.py', 'old': 'return 1', 'new': 'return 2'}], 'summary': 'Updated'}])
            def complete_json(self, messages, **kwargs):
                import copy
                self.messages.append(copy.deepcopy(messages))
                return Reply(json.dumps(next(self.actions)), 100)
        from keel.mcp_client import McpToolError
        model = Exploring()
        config = {**self.config, 'localization_tool_steps': 4, 'localization_require_external': True,
            'budget': {**self.config['budget'], 'max_model_calls': 6},
            'mcp_servers': {'external': {'command': 'unused', 'tools': {'find': {
                'roles': ['scout'], 'read_only': True, 'description': 'Find symbols'}}}}}
        with patch('keel.mcp_client.McpTools.call', side_effect=McpToolError('Server unavailable')):
            result = run(config, self.root, self.root/'.keel/exploring', model=model)
        self.assertEqual(result['status'], 'passed')
        self.assertIn('requires an authorized MCP', model.messages[1][-1]['content'])
        self.assertIn('Server unavailable', model.messages[2][-1]['content'])
        handed = json.loads(json.loads(model.messages[4][1]['content'])['goal'])
        self.assertIn('return 1', handed['untrusted_tool_evidence'][0]['preview'])
        self.assertEqual(result['budget']['model_calls'], 6)
        self.assertEqual(result['external_tool_calls']['mcp__external__find'],
                         {'completed': 0, 'failed': 1, 'denied': 0})
        self.assertEqual(result['external_tool_validation'],
                         {'required': True, 'attempted': True, 'successful_requests': 0})

    def test_tool_exploration_local_limit_falls_back_but_global_budget_does_not(self):
        class Exploring(Model):
            def complete_json(self, messages, **kwargs):
                if not self.messages:
                    self.messages.append(messages)
                    return Reply(json.dumps({'tool': 'read_file', 'arguments': {'path': 'module.py'}}), 100)
                # Base selector expects its first selection as call 1.
                saved = self.messages.pop(0)
                try:
                    return super().complete_json(messages, **kwargs)
                finally:
                    self.messages.insert(0, saved)
        for limit, expected in ((4, 'passed'), (1, 'failed')):
            model = Exploring({'files': ['module.py'], 'locations': ['module.py:1']})
            result = run({**self.config, 'localization_tool_steps': 1,
                'budget': {**self.config['budget'], 'max_model_calls': limit}},
                self.root, self.root/f'.keel/explore-limit-{limit}', model=model)
            self.assertEqual(result['status'], expected)
            if limit == 1:
                self.assertEqual(result['failure']['category'], 'budget_exhausted')
            (self.root/'module.py').write_bytes(b'def version():\n    return 1\n')

    def test_contract_selection_rejects_unknown_id_before_patch_and_obeys_budget(self):
        class InvalidSelection(Model):
            def complete_json(self, messages, **kwargs):
                if len(self.messages) == 2:
                    self.messages.append(messages)
                    return Reply(json.dumps({'contracts': ['9:999']}), 100)
                return super().complete_json(messages, **kwargs)
        config = {**self.config, 'budget': {**self.config['budget'], 'max_model_calls': 4},
            'select_dependency_contracts': True,
            'localization_dependencies': [{'module': 'fixture', 'distribution': 'fixture', 'version': '1'}]}
        evidence = [{'distribution': 'fixture', 'version': '1', 'signatures': ['def Pool.send(self)']}]
        for index, limit in enumerate((4, 2)):
            model = InvalidSelection({'files': ['module.py'], 'locations': ['module.py:1']})
            current = {**config, 'budget': {**config['budget'], 'max_model_calls': limit}}
            with patch('keel.dependency_evidence.collect_for_localization', return_value=evidence):
                result = run(current, self.root, self.root/f'.keel/bad-contract-{index}', model=model)
            self.assertEqual(result['status'], 'failed')
            self.assertEqual(result['failure']['stage'], 'scout')
            self.assertEqual(len(model.messages), 3 if limit == 4 else 2)
            self.assertIn('return 1', (self.root/'module.py').read_text())

    def test_model_selects_contract_ids_and_patch_gets_original_records_with_shared_budget(self):
        scope = {'files': ['module.py'], 'locations': ['module.py:1']}
        class Selecting(Model):
            def complete_json(self, messages, **kwargs):
                if len(self.messages) == 2:
                    self.messages.append(messages)
                    return Reply(json.dumps({'contracts': ['0:1']}), 100)
                return super().complete_json(messages, **kwargs)
        model = Selecting(scope)
        evidence = [{'distribution': 'fixture', 'version': '1',
            'signatures': ['def Pool.old(self)', 'def Pool.send(self, extensions)'], 'inventory_sha256': 'a'*64}]
        config = {**self.config, 'budget': {**self.config['budget'], 'max_model_calls': 4},
            'select_dependency_contracts': True,
            'localization_dependencies': [{'module': 'fixture', 'distribution': 'fixture', 'version': '1'}]}
        with patch('keel.dependency_evidence.collect_for_localization', return_value=evidence):
            result = run(config, self.root, self.root/'.keel/selected-contracts', model=model)
        self.assertEqual(result['status'], 'passed')
        self.assertEqual(result['budget']['model_calls'], 4)
        self.assertEqual(result['budget']['tokens'], 400)
        supplied = json.loads(model.messages[3][1]['content'])['installed_dependency_evidence'][0]
        self.assertEqual(supplied['signatures'], [evidence[0]['signatures'][1]])
        self.assertEqual(supplied['selected_signature_indices'], [1])
        self.assertEqual(supplied['available_signature_count'], 2)
        self.assertEqual(evidence[0]['signatures'], ['def Pool.old(self)', 'def Pool.send(self, extensions)'])

    def test_installed_contracts_reach_patch_request_without_becoming_edit_instructions(self):
        model = Model({'files': ['module.py'], 'locations': ['module.py:1']})
        evidence = [{'distribution': 'fixture', 'version': '1', 'signatures': ['def Pool.send(self, extensions)']}]
        config = {**self.config, 'localization_dependencies': [
            {'module': 'fixture', 'distribution': 'fixture', 'version': '1'}]}
        with patch('keel.dependency_evidence.collect_for_localization', return_value=evidence) as collector:
            result = run(config, self.root, self.root/'.keel/contracts', model=model)
        self.assertEqual(result['status'], 'passed')
        collector.assert_called_once()
        self.assertEqual(json.loads(model.messages[2][1]['content'])['installed_dependency_evidence'], evidence)
        self.assertIn('untrusted reference data', model.messages[2][0]['content'])
    def test_combined_symbol_map_reaches_patch_without_dropping_selected_files(self):
        names = ['module.py']
        for index in range(4):
            name = f'component_{index}.py'
            names.append(name)
            (self.root/name).write_bytes(''.join(
                f'def operation_{number:03}(value):\n    return value\n\n' for number in range(60)).encode())
        model = Model({'files': names, 'locations': ['module.py:1']})
        result = run(self.config, self.root, self.root/'.keel/combined', model=model)
        self.assertEqual(result['status'], 'passed')
        structure = json.loads(model.messages[1][1]['content'])['structure']
        self.assertEqual([r['path'] for r in structure], names)
        self.assertEqual(sum(len(r['symbols']) for r in structure), 241)
        events = [json.loads(line) for line in (self.root/'.keel/combined/trace.jsonl').read_text().splitlines()]
        anchor = [e for e in events if e.get('localization_stage') == 'anchor-selection']
        self.assertEqual(len(anchor), 1)
        self.assertLessEqual(anchor[0]['input_bytes'], 12000)
        self.assertEqual(result['budget']['model_calls'], 3)

    def test_compact_symbol_map_preserves_every_name_line_and_nested_duplicate(self):
        import ast
        from keel.localization import symbol_structure
        text = 'class A:\n    def get(self):\n        def inner(): pass\n        return inner()\nclass B:\n    async def get(self): pass\n'
        tree = ast.parse(text)
        expected = [(n.lineno, n.name) for n in ast.walk(tree)
            if isinstance(n, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))]
        result = symbol_structure('pkg/a.py', text)
        self.assertEqual(result['path'], 'pkg/a.py')
        self.assertEqual([tuple(v) for v in result['symbols']], expected)
        self.assertEqual(sum(name == 'get' for _, name in result['symbols']), 2)
        self.assertNotIn('location', json.dumps(result))

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root/'module.py').write_bytes(b'def version():\n    return 1\n')
        self.config = {'mode': 'localized-proposal', 'goal': 'Make version return 2',
            'budget': {'max_tool_calls': 30, 'max_model_calls': 3, 'max_tokens': 30000},
            'agent': {'max_context_bytes': 12000},
            'acceptance': [[sys.executable, '-c', 'import module; assert module.version() == 2']]}

    def test_model_localizes_then_existing_proposal_verifier_and_auditor_execute(self):
        model = Model({'files': ['module.py'], 'locations': ['module.py:1']})
        result = run(self.config, self.root, self.root/'.keel/run', model=model)
        self.assertEqual(result['status'], 'passed')
        self.assertEqual(result['budget']['model_calls'], 3)
        self.assertEqual(result['budget']['tokens'], 300)
        self.assertEqual(len(model.messages), 3)
        self.assertEqual(json.loads(model.messages[0][1]['content'])['paths'], ['module.py'])
        self.assertIn('symbols', json.loads(model.messages[1][1]['content'])['structure'][0])
        patch_input = json.loads(model.messages[2][1]['content'])
        self.assertEqual(patch_input['allowed_files'], ['module.py'])
        self.assertIn('return 1', patch_input['evidence'][0]['windows'][0]['text'])
        self.assertEqual(result['verification'][0]['returncode'], 0)

    def test_invalid_localization_never_reaches_patch_call(self):
        for index, scope in enumerate([
            {'files': ['../outside.py'], 'locations': ['module.py:1']},
            {'files': ['module.py'], 'locations': ['module.py:999']},
            {'files': ['module.py'], 'locations': ['module.py:1'], 'extra': True}]):
            with self.subTest(scope=scope):
                model = Model(scope)
                result = run(self.config, self.root, self.root/f'.keel/run-{index}', model=model)
                self.assertEqual(result['status'], 'failed')
                self.assertEqual(result['failure']['stage'], 'scout')
                self.assertEqual(len(model.messages), 1 if index == 0 else (3 if index == 1 else 2))
                self.assertIn('return 1', (self.root/'module.py').read_text())

    def test_operator_scope_is_rejected_and_context_cap_cannot_silently_truncate(self):
        with self.assertRaises(ValueError):
            run({**self.config, 'proposal': {'files': ['module.py'], 'locations': ['module.py:1']}},
                self.root, self.root/'.keel/invalid')
        model = Model({})
        result = run({**self.config, 'agent': {'max_context_bytes': 20}},
            self.root, self.root/'.keel/capped', model=model)
        self.assertEqual(result['failure']['category'], 'budget_exhausted')
        self.assertEqual(model.messages, [])

    def test_unselected_large_file_is_not_scanned_for_symbols(self):
        (self.root/'unrelated.py').write_bytes(('def unrelated():\n    pass\n'+'# large padding\n'*5000).encode())
        model = Model({'files': ['module.py'], 'locations': ['module.py:1']})
        result = run(self.config, self.root, self.root/'.keel/selected', model=model)
        self.assertEqual(result['status'], 'passed')
        self.assertIn('unrelated.py', json.loads(model.messages[0][1]['content'])['paths'])
        self.assertEqual([r['path'] for r in json.loads(model.messages[1][1]['content'])['structure']], ['module.py'])

    def test_anchor_stage_cannot_expand_scope_or_exceed_model_budget(self):
        (self.root/'other.py').write_bytes(b'def other():\n    return 1\n')
        class Expanding(Model):
            def complete_json(self, messages, **kwargs):
                self.messages.append(messages)
                value = {'files': ['module.py']} if len(self.messages) == 1 else {'locations': ['other.py:1']}
                return Reply(json.dumps(value), 100)
        model = Expanding({})
        result = run(self.config, self.root, self.root/'.keel/expanded', model=model)
        self.assertEqual(result['failure']['category'], 'model_error')
        self.assertEqual(len(model.messages), 3)
        model = Model({'files': ['module.py'], 'locations': ['module.py:1']})
        config = {**self.config, 'budget': {**self.config['budget'], 'max_model_calls': 1}}
        result = run(config, self.root, self.root/'.keel/budgeted', model=model)
        self.assertEqual(result['failure']['category'], 'budget_exhausted')
        self.assertEqual(len(model.messages), 1)

    def test_source_changed_during_selection_is_rejected_before_patch(self):
        target = self.root/'module.py'
        class Mutating(Model):
            def complete_json(self, messages, **kwargs):
                reply = super().complete_json(messages, **kwargs)
                if len(self.messages) == 2:
                    target.write_bytes(b'def version():\n    return 7\n')
                return reply
        model = Mutating({'files': ['module.py'], 'locations': ['module.py:1']})
        result = run(self.config, self.root, self.root/'.keel/stale', model=model)
        self.assertEqual(result['status'], 'failed')
        self.assertIn('Source changed', result['failure']['message'])
        self.assertEqual(len(model.messages), 2)
