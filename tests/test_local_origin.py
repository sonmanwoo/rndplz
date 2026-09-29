"""With a public origin configured, POSTs still come only from that origin, except from pages
loaded at this PC's loopback address (the operator's in-app browser blocks the Funnel address
after the first page)."""
import io
import json
import tempfile
import unittest
from http.cookies import SimpleCookie
from pathlib import Path

PUBLIC = 'https://rndplz.example.ts.net:8443'


class LocalOriginTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from rndplz.public_web import PublicApp
        cls.tmp = tempfile.TemporaryDirectory()
        cls.app = PublicApp(state_dir=Path(cls.tmp.name) / 'state', env={
            'RNDPLZ_SESSION_SECRET': 's' * 64, 'RNDPLZ_PUBLIC_ORIGIN': PUBLIC,
            'RNDPLZ_ALLOWED_HOSTS': 'rndplz.example.ts.net',
            'RNDPLZ_PUBLIC_PERSON_IDS': 'LOCAL-MANWOO,LOCAL-JINHO,LOCAL-DASOL,LOCAL-HONG'})

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def call(self, method, path, host, origin=None, body=None):
        raw = json.dumps(body).encode() if body is not None else b''
        environ = {'REQUEST_METHOD': method, 'PATH_INFO': path, 'QUERY_STRING': '', 'HTTP_HOST': host,
                   'wsgi.input': io.BytesIO(raw), 'CONTENT_LENGTH': str(len(raw)), 'wsgi.url_scheme': 'http',
                   'HTTP_COOKIE': '; '.join(k + '=' + v for k, v in self.cookies.items())}
        if method == 'POST':
            environ.update(CONTENT_TYPE='application/json', HTTP_ORIGIN=origin, HTTP_X_RNDPLZ_TOKEN=self.token)
        captured = {}

        def start_response(status, headers):
            captured['status'], captured['headers'] = int(status.split()[0]), headers

        payload = b''.join(self.app(environ, start_response))
        for key, value in captured['headers']:
            if key.lower() == 'set-cookie':
                cookie = SimpleCookie()
                cookie.load(value)
                for name, morsel in cookie.items():
                    self.cookies[name] = morsel.value
        return captured['status'], json.loads(payload) if payload[:1] == b'{' else None

    def post(self, host, origin):
        self.cookies, self.token = {}, ''
        self.token = self.call('GET', '/api/chat/bootstrap', host)[1]['token']
        return self.call('POST', '/api/chat/intent', host, origin, {'text': '안녕하세요', 'model_id': 'bridge'})[0]

    def test_public_and_loopback_pages_may_post_but_no_other_origin(self):
        self.assertEqual(self.post('rndplz.example.ts.net:8443', PUBLIC), 200)
        self.assertEqual(self.post('127.0.0.1:8000', 'http://127.0.0.1:8000'), 200)
        self.assertEqual(self.post('localhost:8000', 'http://localhost:8000'), 200)
        self.assertEqual(self.post('127.0.0.1:8000', 'https://evil.example'), 403)
        self.assertEqual(self.post('127.0.0.1:8000', 'http://127.0.0.1:9999'), 403)  # another local app
        self.assertEqual(self.post('rndplz.example.ts.net:8443', 'http://127.0.0.1:8000'), 403)


if __name__ == '__main__':
    unittest.main()
