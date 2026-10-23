"""Optional zero-model Docker integration fixture, independent of benchmark code."""
from contextlib import closing
import json
import os
from pathlib import Path
import tempfile
import unittest
import uuid

from compass.progress import atomic_json
from keel.core import Budget, Ledger, Limits, Trace
from keel.diagnostic_probe import run_probe
from keel.workspace import Workspace


@unittest.skipUnless(os.environ.get('KEEL_TEST_PROBE_PLAN'), 'Set KEEL_TEST_PROBE_PLAN for the zero-model Docker fixture')
class ProbeDockerFixtureTests(unittest.TestCase):
    def test_relative_import_in_actual_readonly_container(self):
        config=json.loads(Path(os.environ['KEEL_TEST_PROBE_PLAN']).read_text(encoding='utf-8'))
        artifact=Path('.keel/probe-selfchecks')/uuid.uuid4().hex;artifact.mkdir(parents=True)
        record={'status':'running','model_calls':0,
                'scope':'Synthetic package execution fixture; not model reasoning or task acceptance.'}
        atomic_json(artifact/'report.json',record)
        try:
            with tempfile.TemporaryDirectory() as temp, closing(Ledger(artifact/'ledger.sqlite')) as ledger:
                root=Path(temp);package=root/'probe_fixture_package';package.mkdir()
                (package/'__init__.py').write_bytes(b'from .api import value\n')
                (package/'api.py').write_bytes(b'from .helper import suffix\ndef value(): return "candidate"+suffix\n')
                (package/'helper.py').write_bytes(b'suffix = ":dependency"\n')
                budget=Budget(Limits(max_tool_calls=1,max_wallclock=30))
                ws=Workspace(root,budget,ledger,Trace(artifact/'trace.jsonl'));before=ws.snapshot()
                result=run_probe(ws,{'backend':'docker','image':config['probe_image']},config['probe_python'],
                    'import probe_fixture_package\nprint(probe_fixture_package.value())',candidate_imports=True)
                record.update(result=result,budget=budget.report(),workspace_unchanged=ws.snapshot()==before)
                self.assertEqual(result['outcome'],'completed',result)
                self.assertEqual(result['probe']['stdout'].strip(),'candidate:dependency')
                self.assertIn('__KEEL_CANDIDATE_IMPORTS__',result['probe']['stderr'])
                self.assertEqual(budget.model_calls,0);self.assertTrue(record['workspace_unchanged'])
            record['status']='passed'
        except Exception as error:
            record.update(status='failed',error_type=type(error).__name__,reason=str(error)[:1500])
            raise
        finally:
            atomic_json(artifact/'report.json',record)
            print('Zero-model Docker fixture artifacts: '+str(artifact),flush=True)
