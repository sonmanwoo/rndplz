"""The header's 15-second reel icon opens a same-origin video that phones can play (byte ranges)."""
import io
import tempfile
import unittest
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / 'rndplz' / 'web'
VIDEO = '/video/susomun-reel-15s.mp4'


class PromoReelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from rndplz.public_web import PublicApp
        cls.tmp = tempfile.TemporaryDirectory()
        cls.app = PublicApp(state_dir=Path(cls.tmp.name) / 'state', env={
            'RNDPLZ_LOCAL_PREVIEW': '1', 'RNDPLZ_SESSION_SECRET': 's' * 64,
            'RNDPLZ_PUBLIC_PERSON_IDS': 'LOCAL-MANWOO,LOCAL-JINHO,LOCAL-DASOL,LOCAL-HONG'})
        cls.raw = (WEB / VIDEO.lstrip('/')).read_bytes()

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def request(self, path, method='GET', range_header=None):
        captured = {}
        def start_response(status, headers):
            captured['status'], captured['headers'] = int(status.split()[0]), dict(headers)
        environ = {'REQUEST_METHOD': method, 'PATH_INFO': path, 'QUERY_STRING': '', 'HTTP_HOST': '127.0.0.1',
                   'wsgi.input': io.BytesIO(b''), 'CONTENT_LENGTH': '0', 'wsgi.url_scheme': 'http'}
        if range_header:
            environ['HTTP_RANGE'] = range_header
        body = b''.join(self.app(environ, start_response))
        return captured['status'], captured['headers'], body

    def test_pages_have_the_icon_and_its_script(self):
        for page in ('/', '/explore'):
            status, _, body = self.request(page)
            self.assertEqual(status, 200)
            self.assertIn(b'data-promo-reel', body)
            self.assertRegex(body, rb'<script src="/promo-reel\.js\?v=[a-f0-9]{10}" defer></script>')
        status, headers, body = self.request('/promo-reel.js')
        self.assertEqual(status, 200)
        self.assertTrue(headers['Content-Type'].startswith('text/javascript'))
        self.assertIn(VIDEO.encode(), body)

    def test_full_video_and_poster(self):
        status, headers, body = self.request(VIDEO)
        self.assertEqual((status, headers['Content-Type'], headers['Accept-Ranges']), (200, 'video/mp4', 'bytes'))
        self.assertEqual(body, self.raw)
        self.assertEqual(headers['Cache-Control'], 'no-store')
        status, headers, _ = self.request('/video/susomun-reel-poster.webp')
        self.assertEqual((status, headers['Content-Type']), (200, 'image/webp'))

    def test_byte_ranges(self):
        size = len(self.raw)
        for header, start, end in (('bytes=0-1', 0, 1), ('bytes=100-', 100, size - 1), ('bytes=-10', size - 10, size - 1),
                                   (f'bytes=5-{size + 50}', 5, size - 1)):
            status, headers, body = self.request(VIDEO, range_header=header)
            self.assertEqual(status, 206, header)
            self.assertEqual(headers['Content-Range'], f'bytes {start}-{end}/{size}')
            self.assertEqual(body, self.raw[start:end + 1])
        status, headers, body = self.request(VIDEO, range_header=f'bytes={size}-')
        self.assertEqual((status, headers['Content-Range'], body), (416, f'bytes */{size}', b''))

    def test_only_listed_files_and_get(self):
        self.assertEqual(self.request('/video/other.mp4')[0], 404)
        self.assertEqual(self.request(VIDEO, method='POST')[0], 405)


if __name__ == '__main__':
    unittest.main()
