import json
from pathlib import Path
import tempfile
import unittest

from examples.configure_mcp_tools import configure
from examples.setup_serena import launch_config
from examples.configure_serena_project import update_config


class ExternalSetupTests(unittest.TestCase):
    def test_empty_language_config_is_fixed_without_replacing_existing_servers(self):
        data={'language_servers':[],'read_only':False,'project_name':'fixture','ignored_paths':['build']}
        result=update_config(data,'python')
        self.assertEqual(data['language_servers'],['python'])
        self.assertTrue(data['read_only'])
        self.assertEqual(data['ignored_paths'],['build'])
        self.assertEqual(result['previous_language_servers'],[])
        data['language_servers']=['python_jedi']
        update_config(data,'python')
        self.assertEqual(data['language_servers'],['python_jedi'])
    def test_generated_profile_uses_real_schema_and_only_explicit_selection(self):
        connection={'external':{'command':'server','tools':{}}}
        discovered={'tools':[{'name':'lookup','input_schema':{'type':'object','properties':{'query':{'type':'string'}}}},
                             {'name':'execute_shell_command','input_schema':{'type':'object'}}]}
        profile=configure(connection,discovered,'external',['lookup'],roles=['scout'],read_only=True)
        self.assertEqual(set(profile['external']['tools']),{'lookup'})
        self.assertEqual(profile['external']['tools']['lookup']['input_schema'],discovered['tools'][0]['input_schema'])
        self.assertEqual(connection['external']['tools'],{})
        with self.assertRaises(ValueError):
            configure(connection,discovered,'external',['guessed_tool'],roles=['scout'],read_only=True)

    def test_serena_launch_is_isolated_and_adapts_only_to_available_flags(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            config=launch_config(root,root/'python.exe',root/'serena.exe',
                                 '--agent-interface --enable-web-dashboard --open-web-dashboard')
            self.assertEqual(config['serena']['tools'],{})
            text=(root/'.keel/tools/launch-serena.py').read_text(encoding='utf-8')
            self.assertIn('serena-workspaces',text)
            self.assertIn('from launch_serena import launch',text)
            self.assertIn('--agent-interface',text)
            self.assertIn("'--project', '.'",text)
            self.assertNotIn('--enable-gui-log-window',text)
            compile(text,'launcher','exec')
