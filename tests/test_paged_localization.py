import json
from pathlib import Path
import tempfile
import unittest
from keel.core import Budget, Limits, Ledger, Trace, InvalidSelection
from keel.workspace import Workspace
from keel.models import Reply
from keel.localization import paged_select


class PagedLocalizationTests(unittest.TestCase):
    def trial(self, mode):
        temp=tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root=Path(temp.name)
        ledger=Ledger(root/'facts.sqlite')
        self.addCleanup(ledger.close)
        workspace=Workspace(root,Budget(Limits(max_model_calls=20)),ledger,Trace(root/'trace.jsonl'))
        paths=[f'package/module_{i:03d}.py' for i in range(200)]
        class Model:
            def __init__(self): self.calls=[]
            def complete_json(self,messages,**kwargs):
                self.calls.append(messages)
                data=json.loads(messages[1]['content'])
                permitted=kwargs['schema']['properties']['files']['items']['enum']
                if set(permitted) != set(data['paths']) | set(data['previous_selection']):
                    raise AssertionError('Schema admits IDs outside displayed page/carry')
                if mode=='invalid' or (mode=='correct' and len(self.calls)==1):
                    values=['not_displayed.py']
                else:
                    values=[paths[-1]] if paths[-1] in data['paths'] else []
                return Reply(json.dumps({'files':values}),10)
        model=Model()
        return workspace,model,paths

    def test_empty_irrelevant_pages_reach_later_candidate(self):
        workspace,model,paths=self.trial('empty')
        result=paged_select(model,workspace,'Find target',{'max_context_bytes':4000},
            stage='file-selection',data={'paths':paths},keys=('files',),instruction='Select source files.')
        self.assertEqual(result,{'files':[paths[-1]]})
        self.assertGreater(len(model.calls),1)

    def test_invalid_page_id_gets_bounded_feedback_then_continues(self):
        workspace,model,paths=self.trial('correct')
        result=paged_select(model,workspace,'Find target',{'max_context_bytes':4000},
            stage='file-selection',data={'paths':paths},keys=('files',),instruction='Select source files.')
        self.assertEqual(result['files'],[paths[-1]])
        self.assertIn('Host validation rejected',model.calls[1][0]['content'])

    def test_repeated_invalid_page_id_still_fails_closed(self):
        workspace,model,paths=self.trial('invalid')
        with self.assertRaises(InvalidSelection):
            paged_select(model,workspace,'Find target',{'max_context_bytes':4000},
                stage='file-selection',data={'paths':paths},keys=('files',),instruction='Select source files.')
        self.assertEqual(len(model.calls),2)
