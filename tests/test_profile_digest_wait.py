"""A long document's reading survives a phone dropping a silent request.

Production 2026-10-09: a 70-page report was read by the company AI in 108 s, but the phone had dropped the request
before the answer came back ("전송 결과를 확인하지 못했습니다"). The server now reads in the background and answers
"reading" until the proposal is ready; the page asks again.
"""
import base64
import io
import json
import tempfile
import time
import unittest
from http.cookies import SimpleCookie
from pathlib import Path

import rndplz.public_web as public_web
from rndplz.chat_models import AIU_PROFILE_APP
from rndplz.profile_reading import ProfileReader
from tests.test_profile_reading import DigestModels, document


class SlowModels(DigestModels):
    def __init__(self, seconds, reject=()):
        super().__init__(reject)
        self.seconds = seconds

    def stream(self, identifier, messages, *, contract=None):
        time.sleep(self.seconds)
        yield from super().stream(identifier, messages, contract=contract)


class DigestWaitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.app = public_web.PublicApp(state_dir=Path(cls.tmp.name) / 'state', env={
            'RNDPLZ_LOCAL_PREVIEW': '1', 'RNDPLZ_SESSION_SECRET': 's' * 64,
            'RNDPLZ_PUBLIC_PERSON_IDS': 'LOCAL-MANWOO,LOCAL-JINHO,LOCAL-DASOL,LOCAL-HONG'})

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def call(self, method, path, body=None):
        raw = json.dumps(body, ensure_ascii=False).encode() if body is not None else b''
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

    def setUp(self):
        self.cookies, self.token = {}, ''
        self.token = self.call('GET', '/api/chat/bootstrap')[1]['token']
        self.context = list(self.app.contexts.values())[-1]  # this visitor (the newest context)
        self.addCleanup(setattr, public_web, 'DIGEST_WAIT_SECONDS', public_web.DIGEST_WAIT_SECONDS)
        body = {'action': 'upload', 'turn_id': 'turn-upload-000000001',
                'payload': {'name': 'report.txt', 'data': base64.b64encode(document(40).encode()).decode(),
                            'base_version': 0, 'request_id': 'upload-0000001'}}
        status, view = self.call('POST', '/api/self-profile/chat', body)
        self.assertEqual(status, 200, view)
        self.source = view['profile_view']['sources'][0]['id']

    def ask(self):
        return self.call('POST', '/api/self-profile/digest', {'source_id': self.source})

    def ask_until_ready(self, limit=5.0):
        answers, until = [], time.monotonic() + limit
        while time.monotonic() < until:
            status, body = self.ask()
            answers.append((status, body.get('status')))
            if body.get('status') != 'reading':
                return status, body, answers
        self.fail(f'no proposal within {limit} s: {answers}')

    def test_a_slow_reading_answers_reading_then_the_proposal_once(self):
        public_web.DIGEST_WAIT_SECONDS = 0.15
        models = SlowModels(0.6)
        self.context['profile'].reader = ProfileReader(models)
        status, body, answers = self.ask_until_ready()
        self.assertEqual(answers[0], (200, 'reading'))
        self.assertGreater(len(answers), 2)  # asked again while it read
        self.assertEqual((status, body['proposal']['careers'][0]['title']), (200, '촉매 반응기 최적화'))
        self.assertEqual(len(models.calls), 1)  # the asks share one reading
        status, again = self.ask()  # later: the stored proposal, at once
        self.assertEqual((status, again['cached']), (200, True))

    def test_a_quick_reading_answers_at_once(self):
        models = DigestModels()
        self.context['profile'].reader = ProfileReader(models)
        status, body = self.ask()
        self.assertEqual((status, body['proposal']['careers'][0]['title']), (200, '촉매 반응기 최적화'))

    def test_a_failed_reading_reaches_the_next_ask(self):
        public_web.DIGEST_WAIT_SECONDS = 0.15
        self.context['profile'].reader = ProfileReader(SlowModels(0.4, reject=('aiu', AIU_PROFILE_APP)))
        status, body, answers = self.ask_until_ready()
        self.assertEqual(answers[0], (200, 'reading'))
        self.assertEqual((status, body['code']), (503, 'model_unavailable'))


if __name__ == '__main__':
    unittest.main()
