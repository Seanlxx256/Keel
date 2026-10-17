import base64
import hashlib
import unittest
from urllib.parse import parse_qs, urlsplit
from keel.import_evidence import imported_symbol
from examples.trace_import_fix import trace


class ImportHistoryTests(unittest.TestCase):
    def test_alias_presence_and_absence_are_static_only(self):
        rows = imported_symbol(b'from werkzeug.urls import url_decode as decode\n', 'werkzeug.urls', 'url_decode')
        self.assertEqual(rows, [{'line': 1, 'local_name': 'decode'}])
        self.assertEqual(imported_symbol(b'from urllib.parse import parse_qs\n', 'werkzeug.urls', 'url_decode'), [])

    def fetch(self, route):
        before = b'from werkzeug.urls import url_decode\n'
        after = b'from urllib.parse import parse_qs\n'
        if '/contents/' in route:
            ref = parse_qs(urlsplit(route).query)['ref'][0]
            raw = before if ref == 'a'*40 else after
            return {'type': 'file', 'encoding': 'base64', 'size': len(raw),
                    'sha': hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest(),
                    'content': base64.b64encode(raw).decode()}
        if '/commits?' in route:
            return [{'sha': 'b'*40}]
        return {'sha': 'b'*40, 'parents': [{'sha': 'a'*40}],
                'files': [{'filename': 'src/utils.py', 'patch': '-from werkzeug.urls import url_decode'}]}

    def test_removal_requires_pinned_source_before_and_after(self):
        report = trace(self.fetch, 'org/repo', 'c'*40, 'src/utils.py', 'werkzeug.urls', 'url_decode')
        self.assertEqual(report['status'], 'static_import_removal_found')
        self.assertEqual(report['base_commit'], 'a'*40)
        self.assertFalse(report['benchmark_ready'])

    def test_corrupt_source_and_out_of_bounds_history_are_rejected(self):
        def bad(route):
            value = self.fetch(route)
            if '/contents/' in route:
                value['sha'] = '0'*40
            return value
        with self.assertRaises(ValueError):
            trace(bad, 'org/repo', 'c'*40, 'src/utils.py', 'werkzeug.urls', 'url_decode')
        with self.assertRaises(ValueError):
            trace(self.fetch, 'org/repo', 'c'*40, 'src/utils.py', 'werkzeug.urls', 'url_decode', limit=21)
