import base64
import io
import json
import tempfile
import unittest
import uuid
from .public_web import PublicApp


class Client:
    def __init__(self, app):
        self.app, self.cookie, self.token = app, '', ''

    def call(self, path, payload=None, token=None, origin='http://localhost:8878', host='localhost:8878'):
        route, _, query = path.partition('?')
        body = json.dumps(payload).encode() if payload is not None else b''
        env = {'REQUEST_METHOD': 'POST' if payload is not None else 'GET', 'PATH_INFO': route,
               'QUERY_STRING': query, 'HTTP_HOST': host, 'HTTP_ORIGIN': origin,
               'HTTP_COOKIE': self.cookie, 'HTTP_X_RNDPLZ_TOKEN': self.token if token is None else token,
               'CONTENT_LENGTH': str(len(body)), 'wsgi.input': io.BytesIO(body)}
        result = {}
        def start(status, headers):
            result['status'] = int(status.split()[0]); result['headers'] = dict(headers)
        iterator = self.app(env, start)
        try: raw = b''.join(iterator)
        finally:
            if hasattr(iterator, 'close'): iterator.close()
        if 'Set-Cookie' in result['headers']: self.cookie = result['headers']['Set-Cookie'].split(';')[0]
        mime = result['headers'].get('Content-Type', '')
        result['data'] = [json.loads(line) for line in raw.splitlines()] if 'ndjson' in mime else json.loads(raw) if 'application/json' in mime else raw
        if isinstance(result['data'], dict) and 'token' in result['data']: self.token = result['data']['token']
        return result


class PublicTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = PublicApp(self.temp.name, {'RNDPLZ_LOCAL_PREVIEW': '1'})
        self.a, self.b = Client(self.app), Client(self.app)
        self.a.call('/api/chat/bootstrap'); self.b.call('/api/chat/bootstrap')

    def tearDown(self): self.temp.cleanup()

    def test_public_data_excludes_unapproved_people_and_photos(self):
        data = self.a.call('/api/admin')['data']
        self.assertEqual(len(data['featured']), 4)
        self.assertFalse(any(n['id'].startswith('LOCAL-') for n in data['nodes']))
        self.assertEqual(self.a.call('/api/person?id=LOCAL-MANWOO')['status'], 400)
        self.assertEqual(self.a.call('/portraits/manwoo.jpg')['status'], 404)
        self.assertEqual(self.a.call('/portraits/jinho-catalysis-bg.png')['status'], 404)
        self.assertEqual(self.a.call('/portraits/hinton.png')['status'], 200)

    def test_visitor_history_attachment_and_csrf_are_isolated(self):
        response = self.a.call('/api/chat', {'text': '앤드류 응 LDA', 'model_id': 'guide', 'turn_id': str(uuid.uuid4())})
        self.assertEqual(response['status'], 200)
        sid = response['data'][-1]['session']['id']
        self.assertEqual(len(self.a.call('/api/chat/bootstrap')['data']['history']), 1)
        self.assertEqual(self.b.call('/api/chat/bootstrap')['data']['history'], [])
        self.assertEqual(self.b.call('/api/chat/session?id=' + sid)['status'], 400)
        self.assertEqual(self.b.call('/api/chat/prepare', {'session_id': sid})['status'], 400)
        self.assertEqual(self.b.call('/api/chat/prepare', {'session_id': sid}, token=self.a.token)['status'], 403)
        file = self.a.call('/api/attachments', {'name': 'notes.txt', 'data': base64.b64encode('개인 메모'.encode()).decode()})['data']
        self.assertEqual(self.a.call('/api/attachment?id=' + file['id'])['status'], 200)
        self.assertEqual(self.b.call('/api/attachment?id=' + file['id'])['status'], 400)

    def test_public_guide_can_find_evidence_without_claiming_ai(self):
        session_id = None
        for text in ['앤드류 응 LDA 논문', '논문 100편을 토픽 모델링으로 분류하는 경험을 찾고 있어요']:
            result = self.a.call('/api/chat', {'text': text, 'session_id': session_id, 'model_id': 'guide', 'turn_id': str(uuid.uuid4())})
            session_id = result['data'][-1]['session']['id']
        prepared = self.a.call('/api/chat/prepare', {'session_id': session_id})['data']
        self.assertEqual(prepared['result']['candidates'][0]['id'], 'AI-NG')
        self.assertEqual(prepared['result']['candidates'][0]['evidence'][0]['id'], 'AI-PAPER-LDA')
        self.assertIn('AI 미연결', self.a.call('/api/chat/models')['data']['models'][0]['name'])

    def test_public_admin_operations_and_cross_origin_are_blocked(self):
        for route in ['/api/chat/configure', '/api/export', '/api/ai/draft']:
            self.assertEqual(self.a.call(route, {})['status'], 403)
        self.assertEqual(self.a.call('/api/chat/prepare', {}, origin='https://elsewhere.invalid')['status'], 403)
        self.assertEqual(self.a.call('/healthz', host='elsewhere.invalid')['status'], 421)
        self.assertEqual(self.a.call('/healthz')['status'], 200)

    def test_opt_in_personal_profiles_and_secure_cookie(self):
        app = PublicApp(self.temp.name + '/approved', {}, include_personal=True)
        if 'LOCAL-MANWOO' not in app.engine.corpus.people:
            self.skipTest('Personal source fixtures are excluded from the deployment snapshot')
        client = Client(app)
        result = client.call('/api/chat/bootstrap')
        self.assertIn('HttpOnly', result['headers']['Set-Cookie'])
        self.assertIn('Secure', result['headers']['Set-Cookie'])
        self.assertEqual(client.call('/portraits/manwoo.jpg')['status'], 200)
        self.assertEqual(len(client.call('/api/admin')['data']['featured']), 6)


if __name__ == '__main__': unittest.main()
