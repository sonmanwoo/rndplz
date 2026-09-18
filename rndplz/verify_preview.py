"""Public UI review assets must not create sessions or expose other files."""
import unittest
from unittest.mock import Mock
from .public_web import PublicApp, PREVIEW_PREFIX, PREVIEW_FILES, WEB
from .verify_public import Client

class PreviewTests(unittest.TestCase):
    def setUp(self):
        self.app = PublicApp.__new__(PublicApp)
        self.app.allowed_hosts = {'localhost'}
        self.app.visitor = Mock(side_effect=AssertionError('static preview must not create visitor state'))
        self.client = Client(self.app)

    def test_seven_assets_are_exact_bytes_and_no_cookie_or_session(self):
        for suffix, (name, mime) in PREVIEW_FILES.items():
            with self.subTest(suffix=suffix):
                result = self.client.call(PREVIEW_PREFIX + suffix)
                self.assertEqual(result['status'], 200)
                self.assertEqual(result['data'], (WEB / PREVIEW_PREFIX.strip('/') / name).read_bytes())
                self.assertEqual(result['headers']['Content-Type'], mime)
                self.assertNotIn('Set-Cookie', result['headers'])
                self.assertIn("script-src 'self'", result['headers']['Content-Security-Policy'])
        self.app.visitor.assert_not_called()

    def test_path_traversal_unknown_file_and_other_revision_are_denied(self):
        for suffix in ('../public_web.py', '../../data/site_records_seed.json', '%2e%2e/public_web.py', 'images/../../app.js', 'unknown.json'):
            self.assertEqual(self.client.call(PREVIEW_PREFIX + suffix)['status'], 404)
        self.assertEqual(self.client.call('/ui-previews/UI-MAIN-001/r2/')['status'], 404)
        self.app.visitor.assert_not_called()

    def test_preview_is_read_only_and_host_checked(self):
        self.assertEqual(self.client.call(PREVIEW_PREFIX, {})['status'], 405)
        self.assertEqual(self.client.call(PREVIEW_PREFIX, host='elsewhere.invalid')['status'], 421)
        self.app.visitor.assert_not_called()

if __name__ == '__main__':
    unittest.main()
