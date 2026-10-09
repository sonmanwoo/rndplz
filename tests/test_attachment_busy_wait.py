"""An upload waits briefly for the same visitor's short requests instead of being turned away.

Production 2026-10-09: adding a profile document failed with "진행 중인 요청이 끝난 뒤 자료를 추가해 주세요." because the
account menu re-checks the session whenever the window regains focus — exactly when the file picker closes — and that
request was still in flight when the upload began.
"""
import hashlib
import io
import json
import tempfile
import threading
import time
import unittest
from http.cookies import SimpleCookie
from pathlib import Path

import rndplz.public_web as public_web

BEGIN = {'name': 'cv.txt', 'size': 5, 'sha256': hashlib.sha256(b'hello').hexdigest()}


class AttachmentBusyWaitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.app = public_web.PublicApp(state_dir=Path(cls.tmp.name) / 'state', env={
            'RNDPLZ_LOCAL_PREVIEW': '1', 'RNDPLZ_SESSION_SECRET': 's' * 64})

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def setUp(self):
        self.cookies, self.token = {}, ''
        self.token = self.call('GET', '/api/chat/bootstrap')[1]['token']
        self.context = list(self.app.contexts.values())[-1]  # this visitor (the newest context)
        self.wait = public_web.ATTACHMENT_BUSY_WAIT_SECONDS
        self.addCleanup(setattr, public_web, 'ATTACHMENT_BUSY_WAIT_SECONDS', self.wait)

    def call(self, method, path, body=None):
        raw = json.dumps(body).encode() if body is not None else b''
        environ = {'REQUEST_METHOD': method, 'PATH_INFO': path, 'QUERY_STRING': '', 'HTTP_HOST': '127.0.0.1',
                   'wsgi.input': io.BytesIO(raw), 'CONTENT_LENGTH': str(len(raw)), 'wsgi.url_scheme': 'http',
                   'HTTP_COOKIE': '; '.join(k + '=' + v for k, v in self.cookies.items())}
        if method == 'POST':
            environ.update(CONTENT_TYPE='application/json', HTTP_ORIGIN='http://127.0.0.1', HTTP_X_RNDPLZ_TOKEN=self.token)
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

    def hold(self, key, seconds=None):
        """Another request of this visitor in flight (key 'inflight') or a reply streaming (key 'active')."""
        with self.app.lock:
            self.context[key] += 1

        def release():
            with self.app.lock:
                self.context[key] -= 1
        if seconds is not None:
            threading.Timer(seconds, release).start()
        return release

    def test_upload_waits_for_a_short_request_to_finish(self):
        self.hold('inflight', seconds=0.3)  # the session re-check sent when the file picker closes
        started = time.monotonic()
        status, body = self.call('POST', '/api/attachments/begin', BEGIN)
        self.assertEqual(status, 200, body)
        self.assertRegex(body['upload_id'], r'^[a-f0-9]{32}$')
        self.assertGreaterEqual(time.monotonic() - started, 0.25)

    def test_upload_is_still_refused_while_another_request_stays_busy(self):
        for key in ('inflight', 'active'):
            with self.subTest(key=key):
                public_web.ATTACHMENT_BUSY_WAIT_SECONDS = 0.3
                release = self.hold(key)
                try:
                    started = time.monotonic()
                    status, body = self.call('POST', '/api/attachments/begin', BEGIN)
                    self.assertEqual((status, body['code']), (409, 'attachment_context_busy'))
                    self.assertGreaterEqual(time.monotonic() - started, 0.3)
                finally:
                    release()

    def test_upload_without_other_requests_does_not_wait(self):
        started = time.monotonic()
        status, body = self.call('POST', '/api/attachments/begin', BEGIN)
        self.assertEqual(status, 200, body)
        self.assertLess(time.monotonic() - started, 0.2)


if __name__ == '__main__':
    unittest.main()
