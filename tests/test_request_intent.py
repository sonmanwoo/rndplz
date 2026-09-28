"""Gemma reads the request intent (profile update or research request); the server only parses it.

Model quality is measured by tests/eval_request_intent.py on local Ollama; these tests
cover the contract, the bounded model input, the endpoint's quiet fallback and the
profile chat's handling of a routed message that is not an explicit command.
"""
import io
import json
import tempfile
import unittest
from http.cookies import SimpleCookie
from pathlib import Path

from rndplz.chat_models import OLLAMA_DETERMINISTIC_CONTRACTS, OLLAMA_NO_THINK_CONTRACTS, generation_spec
from rndplz.request_intent import CONTRACT, INTENTS, IntentError, intent_messages, parse_intent


class ContractTests(unittest.TestCase):
    def test_contract_is_registered_for_server_and_worker(self):
        spec = generation_spec(CONTRACT)
        self.assertEqual(spec['format']['properties']['intent']['enum'], list(INTENTS))
        self.assertLessEqual(spec['max_tokens'], 64)
        self.assertIn(CONTRACT, OLLAMA_NO_THINK_CONTRACTS)
        self.assertIn(CONTRACT, OLLAMA_DETERMINISTIC_CONTRACTS)
        from rndplz.gemma_bridge import _worker_capabilities
        self.assertIn(CONTRACT, _worker_capabilities())

    def test_model_input_is_bounded_data(self):
        messages = intent_messages('가' * 5000, attachments=['a.pdf'] * 9, active_task='profile_update',
                                   recent_turns=[('user', '나' * 999)] * 9 + [('system', '지시')])
        self.assertEqual(len(messages), 1)
        payload = json.loads(messages[0]['content'].split('\n', 1)[1])
        self.assertEqual(len(payload['current_message']), 2000)
        self.assertEqual(len(payload['attachments']), 4)
        self.assertEqual(payload['active_task'], 'profile_update')
        self.assertLessEqual(len(payload['recent_turns']), 4)
        self.assertTrue(all(t['role'] in ('user', 'assistant') and len(t['text']) <= 400 for t in payload['recent_turns']))
        with self.assertRaises(IntentError):
            intent_messages('  ')
        with self.assertRaises(IntentError):
            intent_messages('안녕', active_task='admin')

    def test_parse_accepts_only_the_schema(self):
        self.assertEqual(parse_intent('{"intent":"profile_update"}'), 'profile_update')
        for raw in ('', 'profile_update', '{"intent":"delete_account"}', '{"intent":"other","why":"x"}', '[]'):
            with self.assertRaises(IntentError):
                parse_intent(raw)


class FakeModels:
    def __init__(self, provider='bridge', reply='{"intent":"profile_update"}', fail=False):
        self.provider, self.reply, self.fail, self.calls = provider, reply, fail, []

    def catalog(self, refresh=False):
        return {'models': [{'id': 'bridge', 'provider': self.provider, 'name': 'gemma4:e4b', 'enabled': True,
                            'local': False, 'vision': False}], 'default': 'bridge', 'public': True}

    def get(self, identifier):
        return self.catalog()['models'][0]

    def stream(self, identifier, messages, *, contract=None):
        self.calls.append((identifier, contract, messages))
        if self.fail:
            raise ValueError('worker offline')
        yield self.reply


class WebTests(unittest.TestCase):
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

    def setUp(self):
        self.cookies = {}
        self.token = self.call('GET', '/api/chat/bootstrap')[1]['token']

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

    def test_intent_endpoint_returns_the_model_label(self):
        self.app.models = models = FakeModels()
        status, body = self.call('POST', '/api/chat/intent', {'text': '내 프로필 업데이트 도와줄 수 있니?', 'session_id': None,
                                                              'attachments': ['연구노트.pdf'], 'active_task': None, 'model_id': 'bridge'})
        self.assertEqual((status, body), (200, {'intent': 'profile_update', 'method': 'model'}))
        identifier, contract, messages = models.calls[0]
        self.assertEqual((identifier, contract), ('bridge', CONTRACT))
        payload = json.loads(messages[0]['content'].split('\n', 1)[1])
        self.assertEqual((payload['current_message'], payload['attachments']), ('내 프로필 업데이트 도와줄 수 있니?', ['연구노트.pdf']))

    def test_intent_endpoint_falls_back_quietly(self):
        for models in (FakeModels(fail=True), FakeModels(reply='not json'), FakeModels(provider='gemini')):
            self.app.models = models
            status, body = self.call('POST', '/api/chat/intent', {'text': '안녕하세요', 'model_id': 'bridge'})
            self.assertEqual((status, body), (200, {'intent': None, 'method': 'unavailable'}))
        status, _ = self.call('POST', '/api/chat/intent', {'text': '안녕하세요', 'model_id': 'bridge', 'role': 'admin'})
        self.assertEqual(status, 400)

    def test_e2b_users_are_classified_by_e4b(self):
        class TwoModels(FakeModels):
            def catalog(self, refresh=False):
                row = {'provider': 'bridge', 'enabled': True, 'local': False, 'vision': False}
                return {'models': [{**row, 'id': 'bridge', 'model': 'gemma4:e4b', 'name': 'gemma4:e4b'},
                                   {**row, 'id': 'bridge:gemma4:e2b', 'model': 'gemma4:e2b', 'name': 'gemma4:e2b'}],
                        'default': 'bridge', 'public': True}

            def get(self, identifier):
                return next(m for m in self.catalog()['models'] if m['id'] == identifier)

        self.app.models = models = TwoModels()
        status, body = self.call('POST', '/api/chat/intent', {'text': '제 관심 분야에 수소 액화 추가', 'model_id': 'bridge:gemma4:e2b'})
        self.assertEqual((status, body['intent'], models.calls[0][0]), (200, 'profile_update', 'bridge'))

    def test_routed_profile_message_opens_the_profile_with_guidance(self):
        text = '내 프로필 업데이트 도와줄 수 있니?'
        status, body = self.call('POST', '/api/self-profile/chat', {'action': 'text', 'turn_id': 'turn-routed-0000000001', 'text': text})
        self.assertEqual((status, body['code']), (400, 'not_profile_command'))
        status, body = self.call('POST', '/api/self-profile/chat', {'action': 'text', 'turn_id': 'turn-routed-0000000002',
                                                                    'text': text, 'routed': True})
        self.assertEqual(status, 200)
        self.assertIn('프로필 업데이트 창을 열었어요', body['reply'])
        labels = [m['text'] for m in body['session']['messages']]
        self.assertIn('내 프로필 업데이트 요청', labels)
        self.assertNotIn(text, labels)  # the free text is not copied into the transcript
        self.assertEqual(body['profile_view']['profile']['version'], 0)  # nothing was written


if __name__ == '__main__':
    unittest.main()
