import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch


class WorkerRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        # The module constructs its normal app once; isolate that local fixture.
        with patch.dict(os.environ, {'RNDPLZ_STATE_DIR': cls.temp.name, 'RNDPLZ_LOCAL_PREVIEW': '1'}, clear=True):
            from rndplz.public_web import PublicApp
        cls.app_type = PublicApp

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def setUp(self):
        self.app = self.app_type(state_dir=Path(self.temp.name) / 'app', env={'RNDPLZ_LOCAL_PREVIEW': '1'})
        self.app.env['APP_RUNTIME'] = 'hosted_public'
        self.calls = []
        bridge = SimpleNamespace(authorized=lambda token: token == 'fixture',
            control=lambda command: self.calls.append(command) or {'active_jobs': 0, 'draining': False, 'models': ['gemma4:e4b'], 'capabilities': []},
            poll=lambda *a, **kw: self.calls.append('poll'),
            deliver=lambda payload: self.calls.append('result'))
        self.app.models = SimpleNamespace(bridge=bridge, scoped_bridge=True)

    def request(self, *, method='POST', token='', payload=None):
        raw = json.dumps(payload or {'control': 'status'}).encode()
        response = []
        environ = {'REQUEST_METHOD': method, 'PATH_INFO': '/api/worker/poll', 'QUERY_STRING': '',
            'HTTP_HOST': 'localhost', 'wsgi.url_scheme': 'http', 'wsgi.input': io.BytesIO(raw),
            'CONTENT_LENGTH': str(len(raw)), 'HTTP_X_RNDPLZ_BRIDGE': token}
        body = b''.join(self.app(environ, lambda status, headers: response.append((status, headers))))
        return int(response[0][0].split()[0]), json.loads(body)

    def test_hosted_worker_route_is_opt_in(self):
        self.app.models.scoped_bridge = False
        self.assertEqual(self.request(token='fixture')[0], 404)
        self.assertEqual(self.calls, [])

    def test_unauthenticated_control_never_touches_relay(self):
        self.assertEqual(self.request()[0], 403)
        self.assertEqual(self.calls, [])

    def test_authenticated_status_uses_only_control(self):
        status, body = self.request(token='fixture')
        self.assertEqual(status, 200)
        self.assertEqual(body['models'], ['gemma4:e4b'])
        self.assertEqual(self.calls, ['status'])

    def test_read_method_does_not_poll_or_claim(self):
        self.assertEqual(self.request(method='GET', token='fixture')[0], 405)
        self.assertEqual(self.calls, [])


if __name__ == '__main__':
    unittest.main()
