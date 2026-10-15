import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from keel.models import Reply
from examples.probe_agent_protocol import main


class ProtocolProbeTests(unittest.TestCase):
    def test_patch_control_is_separate_from_role_completion_and_never_executes_code(self):
        for response, expected in [({'old': 'API_VERSION = 1', 'new': 'API_VERSION = 2'}, True),
                                   ({'old': '', 'new': 'arbitrary code'}, False)]:
            with self.subTest(response=response), tempfile.TemporaryDirectory() as directory:
                replies = [Reply(json.dumps({'final': {'summary': 'Located file', 'files': ['app.py']}}), 10)]*2
                replies.append(Reply(json.dumps(response), 10))
                with patch('examples.probe_agent_protocol.OllamaModel') as model, contextlib.redirect_stdout(io.StringIO()):
                    model.return_value.complete_json.side_effect = replies
                    self.assertEqual(main(Path(directory)/'run'), 0)
                control = json.loads((Path(directory)/'run/patch-control.json').read_text())['record']
                self.assertEqual(control['exact_control_patch'], expected)
                self.assertFalse(control['code_executed'])
                protocol = json.loads((Path(directory)/'run/probe.json').read_text())
                self.assertEqual(len(protocol['records']), 2)
