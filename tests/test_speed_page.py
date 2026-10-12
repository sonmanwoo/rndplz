"""The connection check page (/speed): served like the legal pages, its script same-origin and read only."""
import io
import re
import tempfile
import unittest
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / 'rndplz' / 'web'


class SpeedPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from rndplz.public_web import PublicApp
        cls.tmp = tempfile.TemporaryDirectory()
        cls.app = PublicApp(state_dir=Path(cls.tmp.name) / 'state', env={
            'RNDPLZ_LOCAL_PREVIEW': '1', 'RNDPLZ_SESSION_SECRET': 's' * 64,
            'RNDPLZ_PUBLIC_PERSON_IDS': 'LOCAL-MANWOO,LOCAL-JINHO,LOCAL-DASOL,LOCAL-HONG'})

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def get(self, path):
        captured = {}
        def start_response(status, headers):
            captured['status'], captured['headers'] = int(status.split()[0]), dict(headers)
        body = b''.join(self.app({'REQUEST_METHOD': 'GET', 'PATH_INFO': path, 'QUERY_STRING': '', 'HTTP_HOST': '127.0.0.1',
                                  'wsgi.input': io.BytesIO(b''), 'CONTENT_LENGTH': '0', 'wsgi.url_scheme': 'http'}, start_response))
        return captured['status'], captured['headers'], body.decode('utf-8')

    def test_page_and_script_are_served(self):
        status, headers, body = self.get('/speed')
        self.assertEqual(status, 200)
        self.assertIn('<title>연결 속도 측정 — 수소문</title>', body)
        self.assertIn('<meta name="robots" content="noindex">', body)
        # The policy allows only same-origin scripts: the page's script is a file, never inline.
        self.assertIn("script-src 'self'", headers['Content-Security-Policy'])
        self.assertNotRegex(body, r'<script>(?!</script>)')
        self.assertRegex(body, r'<script src="/speed\.js(\?v=[0-9a-f]+)?" defer></script>')
        status, headers, script = self.get('/speed.js')
        self.assertEqual(status, 200)
        self.assertTrue(headers['Content-Type'].startswith('text/javascript'))

    def test_script_only_reads(self):
        script = (WEB / 'speed.js').read_text(encoding='utf-8')
        self.assertEqual(sorted(set(re.findall(r"fetch\('([^'?]+)", script))), ['/api/people-map', '/healthz'])
        for written in ('localStorage', 'sessionStorage', 'sendBeacon', "method:", 'XMLHttpRequest', 'indexedDB'):
            self.assertNotIn(written, script)

    def test_healthz_answers_with_a_query(self):
        captured = {}
        def start_response(status, headers):
            captured['status'] = int(status.split()[0])
        body = b''.join(self.app({'REQUEST_METHOD': 'GET', 'PATH_INFO': '/healthz', 'QUERY_STRING': 'n=3-1760000000000', 'HTTP_HOST': '127.0.0.1',
                                  'wsgi.input': io.BytesIO(b''), 'CONTENT_LENGTH': '0', 'wsgi.url_scheme': 'http'}, start_response))
        self.assertEqual(captured['status'], 200)
        self.assertIn(b'ok', body)


if __name__ == '__main__':
    unittest.main()
