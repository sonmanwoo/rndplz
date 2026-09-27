"""The privacy policy and terms are public pages (Google OAuth production branding links to them)."""
import io
import tempfile
import unittest
from pathlib import Path


class LegalPageTests(unittest.TestCase):
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

    def test_pages_are_served_and_link_each_other(self):
        for path, title, other in (('/privacy', '개인정보처리방침', '/terms'), ('/terms', '이용약관', '/privacy')):
            status, headers, body = self.get(path)
            self.assertEqual(status, 200)
            self.assertTrue(headers['Content-Type'].startswith('text/html'))
            self.assertIn('<title>' + title + ' — 수소문</title>', body)
            self.assertIn('href="' + other + '"', body)
            self.assertIn('시행일', body)


if __name__ == '__main__':
    unittest.main()
