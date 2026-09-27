"""Open Google sign-up with administrator approval.

A Google account outside the team is recorded as a pending request and gets no
session. The configured administrator approves it (optionally binding one
public person) or rejects it from the web account menu; without an
administrator, outsiders are refused as before.
"""
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from urllib.parse import parse_qs, urlsplit

from rndplz.account_storage import AccountStorage, AuthError
from rndplz.auth_service import AuthService, Config


def enroll(storage, invitation, sub, name, email, state, cookie):
    storage.add_flow(state, cookie, 'nonce', 'verifier', invitation=invitation)
    flow = storage.consume_flow(state, cookie)
    return storage.issue_session(sub, name, email, enrollment_flow=flow)


class SignupStorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.storage = AccountStorage(root / 'accounts.sqlite3', root / 'files', clock=lambda: 1_000_000)

    def test_request_waits_for_approval_then_binds_the_person(self):
        pending = self.storage.request_access('sub-jinho', '오진호', 'jinho@example.com')
        self.assertTrue(pending['pending'])
        with self.assertRaises(AuthError) as caught:
            self.storage.issue_session('sub-jinho', '오진호', 'jinho@example.com')
        self.assertEqual(caught.exception.code, 'team_member_not_allowed')
        self.assertEqual(self.storage.pending_count(), 1)
        self.assertEqual(self.storage.pending_requests()[0]['email'], 'jinho@example.com')
        self.assertEqual(self.storage.list_accounts()[0]['status'], 'pending')
        self.assertFalse(self.storage.has_login_members())
        # Asking again only refreshes the same request.
        again = self.storage.request_access('sub-jinho', '오진호', 'jinho@example.com')
        self.assertEqual(again['account_id'], pending['account_id'])
        self.assertEqual(self.storage.pending_count(), 1)
        decided = self.storage.decide_request(pending['account_id'], True, 'LOCAL-JINHO')
        self.assertEqual((decided['status'], decided['person_id']), ('approved', 'LOCAL-JINHO'))
        session = self.storage.issue_session('sub-jinho', '오진호', 'jinho@example.com')
        self.assertEqual(session['account']['person_id'], 'LOCAL-JINHO')
        self.assertEqual(self.storage.pending_count(), 0)
        self.assertEqual(self.storage.list_accounts()[0]['status'], 'active')
        with self.assertRaises(AuthError) as caught:
            self.storage.decide_request(pending['account_id'], True, None)
        self.assertEqual(caught.exception.code, 'request_not_pending')

    def test_rejected_request_cannot_ask_again(self):
        pending = self.storage.request_access('sub-x', 'Stranger', 'x@example.com')
        with self.assertRaises(AuthError):
            self.storage.decide_request(pending['account_id'], False, 'LOCAL-HONG')  # a rejection binds nobody
        self.assertEqual(self.storage.decide_request(pending['account_id'], False)['status'], 'rejected')
        with self.assertRaises(AuthError) as caught:
            self.storage.request_access('sub-x', 'Stranger', 'x@example.com')
        self.assertEqual(caught.exception.code, 'account_revoked')
        self.assertEqual(self.storage.list_accounts()[0]['status'], 'revoked')
        self.assertEqual(self.storage.pending_count(), 0)

    def test_person_already_bound_keeps_the_request_pending(self):
        issued = self.storage.issue_invitation(600, person_id='LOCAL-HONG')
        enroll(self.storage, issued['invitation'], 'sub-hong', '홍윤기', 'hong@example.com', 'state-' + '1' * 20, 'cookie-1')
        pending = self.storage.request_access('sub-other', 'Other', 'other@example.com')
        with self.assertRaises(AuthError) as caught:
            self.storage.decide_request(pending['account_id'], True, 'LOCAL-HONG')
        self.assertEqual(caught.exception.code, 'person_already_bound')
        self.assertEqual(self.storage.pending_count(), 1)
        self.assertEqual(self.storage.bound_person_ids(), {'LOCAL-HONG'})

    def test_invitation_enrollment_approves_a_pending_request(self):
        self.storage.request_access('sub-dasol', '정다솔', 'dasol@example.com')
        issued = self.storage.issue_invitation(600, person_id='LOCAL-DASOL')
        session = enroll(self.storage, issued['invitation'], 'sub-dasol', '정다솔', 'dasol@example.com',
                         'state-' + '2' * 20, 'cookie-2')
        self.assertEqual(session['account']['person_id'], 'LOCAL-DASOL')
        self.assertEqual(self.storage.pending_count(), 0)

    def test_pending_requests_are_capped(self):
        self.storage.PENDING_REQUEST_LIMIT = 2
        self.storage.request_access('sub-1', 'One', '')
        self.storage.request_access('sub-2', 'Two', '')
        with self.assertRaises(AuthError) as caught:
            self.storage.request_access('sub-3', 'Three', '')
        self.assertEqual(caught.exception.code, 'signup_requests_full')


class FakeTransport:
    def exchange(self, **_):
        return 'id-token'

    def keys(self, force=False):
        return {'keys': []}


def call(app, method, path, *, cookies=(), body=None, token='', query=''):
    raw = json.dumps(body).encode() if body is not None else b''
    environ = {'REQUEST_METHOD': method, 'PATH_INFO': path, 'QUERY_STRING': query, 'HTTP_HOST': '127.0.0.1',
               'wsgi.input': io.BytesIO(raw), 'CONTENT_LENGTH': str(len(raw)), 'wsgi.url_scheme': 'http'}
    if cookies:
        environ['HTTP_COOKIE'] = '; '.join(cookies)
    if method == 'POST':
        environ.update(CONTENT_TYPE='application/json', HTTP_ORIGIN='http://127.0.0.1', HTTP_X_RNDPLZ_TOKEN=token)
    captured = {}

    def start_response(status, headers):
        captured['status'], captured['headers'] = int(status.split()[0]), headers

    payload = b''.join(app(environ, start_response))
    def header(name):
        return [value for key, value in captured['headers'] if key.lower() == name]
    return captured['status'], header, json.loads(payload) if payload[:1] in (b'{', b'[') else None


def cookie_pair(header, name):
    return next(value.split(';')[0] for value in header('set-cookie')
                if value.startswith(name + '=') and 'Max-Age=0' not in value)


class SignupWebTests(unittest.TestCase):
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
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        storage = AccountStorage(Path(folder.name) / 'accounts.sqlite3', Path(folder.name) / 'files')
        issued = storage.issue_invitation(600, person_id='LOCAL-MANWOO')
        admin = enroll(storage, issued['invitation'], 'sub-admin', '손만우', 'mw@example.com', 'state-' + 'a' * 20, 'cookie-a')
        self.admin_cookie = '__Host-rndplz_account=' + admin['session_cookie']
        self.admin_csrf = admin['csrf']
        self.use_admins(storage, {admin['account']['id']})

    def use_admins(self, storage, admin_ids):
        config = Config('client', 'secret', 'https://example.test/auth/google/callback', frozenset(), True, frozenset(admin_ids))
        self.app.auth = AuthService(config, storage, transport=FakeTransport())
        self.app.contexts.clear()

    def google_login(self, sub, name, email):
        status, header, _ = call(self.app, 'GET', '/auth/google/start')
        self.assertEqual(status, 303)
        state = parse_qs(urlsplit(header('location')[0]).query)['state'][0]
        login_cookie = cookie_pair(header, '__Host-rndplz_login')
        claims = {'sub': sub, 'name': name, 'email': email, 'email_verified': True}
        with mock.patch('rndplz.auth_service.verify_google_token', return_value=claims):
            return call(self.app, 'GET', '/auth/google/callback', cookies=[login_cookie], query='code=abc&state=' + state)

    def decide(self, account_id, decision, person_id, token=None):
        return call(self.app, 'POST', '/api/account/requests/decide', cookies=[self.admin_cookie],
                    token=self.admin_csrf if token is None else token,
                    body={'account_id': account_id, 'decision': decision, 'person_id': person_id})

    def test_google_sign_up_waits_for_admin_approval(self):
        status, header, _ = self.google_login('sub-jinho', '오진호', 'jinho@example.com')
        self.assertEqual((status, header('location')), (303, ['/?account_pending=1']))
        self.assertFalse(any(value.startswith('__Host-rndplz_account=') and 'Max-Age=0' not in value
                             for value in header('set-cookie')))
        status, _, body = call(self.app, 'GET', '/api/account/requests')
        self.assertEqual((status, body['code']), (401, 'account_required'))
        status, _, body = call(self.app, 'GET', '/api/account/session', cookies=[self.admin_cookie])
        self.assertEqual((status, body['admin'], body['pending_requests'], body['signup_requests']), (200, True, 1, True))
        status, _, body = call(self.app, 'GET', '/api/account/requests', cookies=[self.admin_cookie])
        self.assertEqual(status, 200)
        request = body['requests'][0]
        self.assertEqual((request['display_name'], request['email']), ('오진호', 'jinho@example.com'))
        people = {row['person_id']: row for row in body['people']}
        self.assertEqual(set(people), {'LOCAL-MANWOO', 'LOCAL-JINHO', 'LOCAL-DASOL', 'LOCAL-HONG'})
        self.assertTrue(people['LOCAL-MANWOO']['bound'])
        self.assertEqual((people['LOCAL-JINHO']['name'], people['LOCAL-JINHO']['bound']), ('오진호', False))
        status, _, body = self.decide(request['account_id'], 'approve', 'LOCAL-NOPE')
        self.assertEqual((status, body['code']), (400, 'decision_invalid'))
        status, _, _ = self.decide(request['account_id'], 'approve', 'LOCAL-JINHO', token='wrong-token')
        self.assertEqual(status, 403)
        status, _, body = self.decide(request['account_id'], 'approve', 'LOCAL-JINHO')
        self.assertEqual((status, body['status'], body['pending_requests']), (200, 'approved', 0))
        status, header, _ = self.google_login('sub-jinho', '오진호', 'jinho@example.com')
        self.assertEqual((status, header('location')), (303, ['/?account_changed=1']))
        member_cookie = cookie_pair(header, '__Host-rndplz_account')
        status, _, body = call(self.app, 'GET', '/api/account/session', cookies=[member_cookie])
        self.assertEqual((body['authenticated'], body['account']['person_id'], body['admin']), (True, 'LOCAL-JINHO', False))
        self.assertNotIn('pending_requests', body)
        status, _, body = call(self.app, 'GET', '/api/account/requests', cookies=[member_cookie])
        self.assertEqual((status, body['code']), (403, 'admin_required'))

    def test_rejected_sign_up_is_refused_on_the_next_login(self):
        self.google_login('sub-x', 'Stranger', 'x@example.com')
        request = self.app.auth.storage.pending_requests()[0]
        status, _, body = self.decide(request['account_id'], 'reject', None)
        self.assertEqual((status, body['status']), (200, 'rejected'))
        status, _, body = self.google_login('sub-x', 'Stranger', 'x@example.com')
        self.assertEqual((status, body['code']), (401, 'account_revoked'))

    def test_without_an_administrator_outsiders_are_refused(self):
        self.use_admins(self.app.auth.storage, set())
        status, _, body = call(self.app, 'GET', '/api/account/session', cookies=[self.admin_cookie])
        self.assertEqual((body['admin'], body['signup_requests']), (False, False))
        status, _, body = self.google_login('sub-y', 'Nobody', 'y@example.com')
        self.assertEqual((status, body['code']), (403, 'team_member_not_allowed'))
        self.assertEqual(self.app.auth.storage.pending_count(), 0)


if __name__ == '__main__':
    unittest.main()
