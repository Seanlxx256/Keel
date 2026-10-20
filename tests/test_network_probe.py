import unittest
from unittest.mock import patch
from types import SimpleNamespace
from keel.network_probe import diagnose, run_probe
from keel.network_probe import PROBE, build_probe
from keel.network_probe import APT_PROBE
import contextlib
import io
import json


class NetworkProbeTests(unittest.TestCase):
    def test_unsigned_message_requires_matching_transient_inrelease_failure(self):
        from keel.network_probe import transient_apt_download
        fetch = 'E: Failed to fetch http://archive.ubuntu.com/ubuntu/dists/jammy/InRelease 502 Bad Gateway\n'
        unsigned = "E: The repository 'http://archive.ubuntu.com/ubuntu jammy InRelease' is not signed."
        self.assertTrue(transient_apt_download(fetch+unsigned))
        self.assertFalse(transient_apt_download(unsigned))
        self.assertFalse(transient_apt_download(fetch+unsigned.replace('jammy', 'other')))
        self.assertFalse(transient_apt_download(fetch+unsigned+'\nNO_PUBKEY 12345'))
        self.assertFalse(transient_apt_download(fetch+'E: Failed to fetch http://example/package.deb 404 Not Found'))

    def test_transient_fetch_retry_recovers_and_preserves_both_attempts(self):
        import tempfile,time
        from pathlib import Path
        from keel.network_probe import bounded_apt_attempts
        with tempfile.TemporaryDirectory() as temp:
            def execute(log, remaining):
                self.assertLessEqual(remaining, 60)
                failed = log.name.endswith('1.log')
                log.write_text('E: Failed to fetch http://example/a.deb 502 Bad Gateway\nE: Unable to fetch some archives' if failed else 'done')
                return SimpleNamespace(returncode=1 if failed else 0)
            with patch('keel.network_probe.time.sleep'):
                rows = bounded_apt_attempts(execute, Path(temp), attempts=3, deadline=time.monotonic()+60)
            self.assertEqual(len(rows), 2)
            self.assertTrue(rows[-1]['passed'])
            self.assertEqual(len(list(Path(temp).glob('*.log'))), 2)

    def test_dependency_script_and_auth_errors_are_not_retried(self):
        from keel.network_probe import transient_apt_download
        for text in ('E: Unable to locate package missing', ': invalid option name: pipefail',
                     'E: Failed to fetch http://example/a 401 Unauthorized',
                     'E: Failed to fetch http://example/a 502 Bad Gateway\nE: Unmet dependencies'):
            self.assertFalse(transient_apt_download(text))

    def test_retry_limit_stops_persistent_network_failure(self):
        import tempfile,time
        from pathlib import Path
        from keel.network_probe import bounded_apt_attempts
        with tempfile.TemporaryDirectory() as temp:
            def execute(log, remaining):
                log.write_text('E: Failed to fetch http://example/a connection timed out')
                return SimpleNamespace(returncode=1)
            with patch('keel.network_probe.time.sleep'):
                rows = bounded_apt_attempts(execute, Path(temp), attempts=3, deadline=time.monotonic()+60)
            self.assertEqual(len(rows), 3)
            self.assertFalse(rows[-1]['passed'])

    def test_original_apt_chain_extraction_rejects_shell_injection(self):
        from examples.check_repository_network import extract_apt
        original = 'apt-get -y update && apt-get -y upgrade && DEBIAN_FRONTEND=noninteractive apt-get install -y unzip texlive'
        self.assertEqual(extract_apt('git clone ignored\n'+original+'\npython -m pip install -e .'), original)
        for bad in (original+'; echo injected', original+' $(touch bad)', original+'\n'+original):
            with self.assertRaises(ValueError):
                extract_apt(bad)

    def test_apt_workload_preserves_command_and_records_result(self):
        from examples.check_repository_network import apt_workload
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script = root/'setup.sh'
            original = 'apt-get -y update && apt-get -y upgrade && apt-get install -y unzip'
            script.write_text(original)
            def harness(command, **kwargs):
                context = Path(command[-1])
                self.assertIn(original, (context/'apt.sh').read_text())
                self.assertNotIn(b'\r', (context/'apt.sh').read_bytes())
                self.assertNotIn(b'\r', (context/'Dockerfile').read_bytes())
                self.assertIn('sharing=locked', (context/'Dockerfile').read_text())
                return SimpleNamespace(returncode=0)
            with patch('examples.check_repository_network.subprocess.run', return_value=SimpleNamespace(stdout='sha256:'+'a'*64)), \
                 patch('examples.check_repository_network.run_harness', side_effect=harness):
                result = apt_workload(script, 'local:test', root, 120)
            self.assertEqual(result['status'], 'apt_completed')
            self.assertTrue((root/'diagnosis.json').exists())

    def test_apt_download_uses_acquisition_not_install_and_requires_success(self):
        def popen(command, **kwargs):
            from pathlib import Path
            self.assertEqual(command[:2], ['/usr/lib/apt/apt-helper', 'download-file'])
            Path(command[-1]).write_bytes(b'package')
            self.assertTrue(kwargs['start_new_session'])
            return SimpleNamespace(returncode=0, communicate=lambda timeout: (b'', b''))
        output = io.StringIO()
        with patch('sys.argv', ['probe', 'http://example.com/a.deb', '100']), \
             patch.dict('sys.modules', {'resource': SimpleNamespace(RLIMIT_FSIZE=1, setrlimit=lambda *args: None)}), \
             patch('subprocess.Popen', side_effect=popen), contextlib.redirect_stdout(output):
            exec(compile(APT_PROBE, '<apt-probe>', 'exec'), {})
        result = json.loads(output.getvalue().split('=', 1)[1])
        self.assertTrue(result['download_complete'])
        self.assertEqual(result['downloaded_bytes'], 7)

    def test_failed_build_keeps_bounded_redacted_diagnostics(self):
        with patch.dict('os.environ', {'KEEL_MODEL_API_KEY': 'sensitive-value'}), \
             patch('keel.network_probe.subprocess.run', return_value=SimpleNamespace(
                 returncode=1, stdout='', stderr='ERROR invalid reference format sensitive-value http://user:pass@example.com')):
            result = run_probe(['docker', 'build'])
        self.assertIn('invalid reference format', result['diagnostic'])
        self.assertNotIn('sensitive-value', result['diagnostic'])
        self.assertNotIn('user:pass', result['diagnostic'])

    def test_download_completion_is_distinct_from_byte_cap(self):
        for data, cap, complete in [(b'abc', 8, True), (b'abcdefgh', 4, False)]:
            response = io.BytesIO(data)
            response.status = 200
            response.headers = {'Content-Length': str(len(data))}
            output = io.StringIO()
            with patch('sys.argv', ['probe', 'http://example.com/a.deb', str(cap), 'full']), \
                 patch('socket.getaddrinfo', return_value=[]), \
                 patch('urllib.request.urlopen', return_value=response), contextlib.redirect_stdout(output):
                exec(compile(PROBE, '<probe>', 'exec'), {})
            value = json.loads(output.getvalue().split('=', 1)[1])
            self.assertEqual(value['download_complete'], complete)
            self.assertLessEqual(value['sample_bytes'], cap+1)

    def test_buildkit_stderr_result_is_read(self):
        with patch('keel.network_probe.subprocess.run', return_value=SimpleNamespace(
                returncode=0, stdout='', stderr='#8 0.2 KEEL_NETWORK_RESULT={"reachable":true}')):
            self.assertTrue(run_probe(['docker'])['observation']['reachable'])

    def test_build_uses_exact_local_identity_and_disposable_tag(self):
        base = 'sha256:'+'a'*64
        def process(command, **kwargs):
            return SimpleNamespace(returncode=0, stdout=base, stderr='')
        def build(command, **kwargs):
            from pathlib import Path
            dockerfile = (Path(command[-1])/'Dockerfile').read_text(encoding='utf-8')
            self.assertTrue(dockerfile.startswith('FROM local:test\n'))
            self.assertNotIn('FROM sha256:', dockerfile)
            return {'status': 'completed'}
        with patch('keel.network_probe.subprocess.run', side_effect=process), \
             patch('keel.network_probe.run_probe', side_effect=build) as probe:
            result = build_probe('local:test', ['http://example.com/a.deb', '100', 'full'])
        self.assertEqual(result['base_image_id'], base)
        command = probe.call_args.args[0]
        self.assertIn('--pull=false', command)
        self.assertIn('--no-cache', command)
        self.assertEqual(probe.call_args.kwargs['timeout'], 55)

    def test_build_rejects_changed_base_identity(self):
        with patch('keel.network_probe.subprocess.run', side_effect=[
                SimpleNamespace(returncode=0, stdout='sha256:'+'a'*64),
                SimpleNamespace(returncode=0, stdout='sha256:'+'b'*64),
                SimpleNamespace(returncode=0)]), \
             patch('keel.network_probe.run_probe', return_value={'status': 'completed'}):
            self.assertEqual(build_probe('local:test', [])['status'], 'base_identity_changed_or_unverified')

    def test_permissions_are_not_classified_as_remote_outage(self):
        with patch('keel.network_probe.subprocess.run', return_value=SimpleNamespace(
                returncode=1, stdout='', stderr='permission denied secret-value')):
            result = run_probe(['docker'])
        self.assertEqual(result['status'], 'permission_boundary')
        self.assertNotIn('secret-value', str(result))

    def test_separate_layers_and_no_image_pull_or_host_mount(self):
        with patch('keel.network_probe.run_probe', side_effect=[
                {'status': 'completed'}, {'status': 'permission_boundary'}]) as probe, \
             patch('keel.network_probe.subprocess.run'):
            result = diagnose('http://archive.ubuntu.com/ubuntu/', 'local:test')
        command = probe.call_args_list[1].args[0]
        self.assertIn('--pull=never', command)
        self.assertIn('--read-only', command)
        self.assertNotIn('-v', command)
        self.assertEqual(result['host']['status'], 'completed')
        self.assertEqual(result['container']['status'], 'permission_boundary')

    def test_credential_urls_are_rejected_before_execution(self):
        with patch('keel.network_probe.run_probe') as probe:
            with self.assertRaises(ValueError):
                diagnose('http://user:password@example.com/', 'local:test')
            probe.assert_not_called()
