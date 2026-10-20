"""Security review checklist fixes (2026-10-20).

Ten idle minutes end a login session, every response over HTTPS carries HSTS,
/healthz answers GET only, failed logins share one error code, design drafts
stay off the public address, the admin's sign-up list masks emails, access
decisions leave an append-only history, and a first login or sign-up request
agrees to the privacy notice before anything about the person is stored.
"""
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from urllib.parse import parse_qs, urlsplit

from rndplz.account_storage import AccountStorage, AuthError, CONSENT_VERSION
from rndplz.auth_service import AuthService, Config
from tests.test_signup_requests import FakeTransport, call, cookie_pair, enroll


class Clock:
    def __init__(self, now=1_000_000):
        self.now = now

    def __call__(self):
        return self.now


class StorageCase(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.clock = Clock()
        self.storage = AccountStorage(self.root / 'accounts.sqlite3', self.root / 'files', clock=self.clock)

    def member_session(self, sub='sub-member'):
        issued = self.storage.issue_invitation(600)
        return enroll(self.storage, issued['invitation'], sub, 'Member', 'member@example.com',
                      'state-' + sub.ljust(20, 'x'), 'cookie-' + sub)

    def rows(self, sql, *args):
        db = sqlite3.connect(self.root / 'accounts.sqlite3')
        db.row_factory = sqlite3.Row
        try:
            return db.execute(sql, args).fetchall()
        finally:
            db.close()


class IdleTimeoutTests(StorageCase):
    def test_activity_keeps_the_session_and_ten_idle_minutes_end_it(self):
        cookie = self.member_session()['session_cookie']
        for _ in range(4):  # 9 minutes between requests, 36 minutes in all
            self.clock.now += 540
            self.assertIsNotNone(self.storage.authenticate(cookie))
        self.clock.now += 600
        self.assertIsNone(self.storage.authenticate(cookie))
        # Revoked for good: the session does not come back even if the clock reads earlier.
        self.clock.now -= 300
        self.assertIsNone(self.storage.authenticate(cookie))
        self.assertEqual(self.rows('SELECT revoked FROM sessions')[0]['revoked'], 1)

    def test_profile_writes_also_check_idleness(self):
        issued = self.member_session()
        store = self.storage.profile_store(issued['account']['id'], session_cookie=issued['session_cookie'])
        self.clock.now += 601
        with self.assertRaises(AuthError) as caught:
            store.read()
        self.assertEqual(caught.exception.code, 'session_idle_timeout')

    def test_session_from_before_the_check_counts_from_its_issue_time(self):
        cookie = self.member_session()['session_cookie']
        db = sqlite3.connect(self.root / 'accounts.sqlite3')
        db.execute('UPDATE sessions SET last_seen=NULL')
        db.commit()
        db.close()
        self.clock.now += 599
        self.assertIsNotNone(self.storage.authenticate(cookie))
        self.clock.now += 599
        self.assertIsNotNone(self.storage.authenticate(cookie))  # the request above wrote last_seen
        self.clock.now += 600
        self.assertIsNone(self.storage.authenticate(cookie))


class PermissionHistoryTests(StorageCase):
    def test_grants_rejections_and_revocations_name_actor_target_and_time(self):
        member = self.member_session()
        approved = self.storage.request_access('sub-a', 'A', 'a@example.com')
        rejected = self.storage.request_access('sub-b', 'B', 'b@example.com')
        self.clock.now += 10
        self.storage.decide_request(approved['account_id'], True, 'LOCAL-JINHO', actor='admin-id')
        self.storage.decide_request(rejected['account_id'], False, actor='admin-id')
        self.clock.now += 10
        self.storage.revoke_account(member['account']['id'])
        self.storage.bind_person(approved['account_id'], None)
        history = self.storage.permission_history()
        self.assertEqual([(row['action'], row['actor'], row['target_account_id']) for row in reversed(history)], [
            ('invitation_enrolled', history[-1]['actor'], member['account']['id']),
            ('request_approved', 'admin-id', approved['account_id']),
            ('request_rejected', 'admin-id', rejected['account_id']),
            ('account_revoked', 'local_operator', member['account']['id']),
            ('person_bound', 'local_operator', approved['account_id'])])
        self.assertTrue(history[-1]['actor'].startswith('invitation:'))
        self.assertEqual(history[-2]['detail'], {'person_id': 'LOCAL-JINHO'})
        self.assertEqual([row['occurred_at'] for row in history[:2]], [1_000_020, 1_000_020])

    def test_history_is_append_only(self):
        self.member_session()
        db = sqlite3.connect(self.root / 'accounts.sqlite3')
        try:
            for sql in ('UPDATE permission_history SET actor=?', 'DELETE FROM permission_history WHERE actor<>?'):
                with self.subTest(sql=sql), self.assertRaises(sqlite3.DatabaseError):
                    db.execute(sql, ('someone',))
        finally:
            db.close()

    def test_failed_decision_leaves_no_history(self):
        pending = self.storage.request_access('sub-a', 'A', 'a@example.com')
        self.storage.decide_request(pending['account_id'], False)
        with self.assertRaises(AuthError):
            self.storage.decide_request(pending['account_id'], True)
        self.assertEqual([row['action'] for row in self.storage.permission_history()], ['request_rejected'])


class ConsentStorageTests(StorageCase):
    def test_a_login_with_a_version_waits_for_agreement_and_writes_nothing_before(self):
        self.storage.allowed_subs = frozenset({'sub-team'})
        with self.assertRaises(AuthError) as caught:
            self.storage.issue_session('sub-team', 'Team', 't@example.com', consent_version=CONSENT_VERSION)
        self.assertEqual(caught.exception.code, 'consent_required')
        self.assertEqual(self.rows('SELECT count(*) AS n FROM accounts')[0]['n'], 0)
        with self.assertRaises(AuthError):
            self.storage.request_access('sub-out', 'Out', 'o@example.com', consent_version=CONSENT_VERSION)
        self.assertEqual(self.storage.pending_count(), 0)
        session = self.storage.issue_session('sub-team', 'Team', 't@example.com', consent_version=CONSENT_VERSION,
                                             consent_given=True)
        self.assertEqual([tuple(row) for row in self.rows('SELECT * FROM privacy_consents')],
                         [(session['account']['id'], CONSENT_VERSION, 1_000_000)])
        # Agreed once: the next login of the same version goes straight through.
        self.clock.now += 100
        self.storage.issue_session('sub-team', 'Team', 't@example.com', consent_version=CONSENT_VERSION)
        listed = self.storage.list_accounts()[0]
        self.assertEqual((listed['consent_version'], listed['consented_at']), (CONSENT_VERSION, 1_000_000))
        # A new notice version asks again.
        with self.assertRaises(AuthError):
            self.storage.issue_session('sub-team', 'Team', 't@example.com', consent_version='privacy-next')

    def test_hold_is_one_use_and_expires(self):
        cookie = self.storage.hold_for_consent('sub-x', 'X', 'x@example.com', 'request')
        self.assertEqual(self.storage.take_consent_hold(cookie)['google_sub'], 'sub-x')
        with self.assertRaises(AuthError):
            self.storage.take_consent_hold(cookie)
        cookie = self.storage.hold_for_consent('sub-x', 'X', 'x@example.com', 'request')
        self.clock.now += 600
        with self.assertRaises(AuthError):
            self.storage.take_consent_hold(cookie)
        self.assertEqual(self.rows('SELECT count(*) AS n FROM consent_holds')[0]['n'], 0)


class MaskedRequestTests(StorageCase):
    def test_pending_requests_mask_the_email(self):
        self.storage.request_access('sub-a', '오진호', 'jinho@example.com')
        self.storage.request_access('sub-b', 'B', '')
        self.assertEqual(sorted(row['email'] for row in self.storage.pending_requests()), ['', 'j***@example.com'])


class WebCase(unittest.TestCase):
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
        self.storage = AccountStorage(Path(folder.name) / 'accounts.sqlite3', Path(folder.name) / 'files')
        issued = self.storage.issue_invitation(600, person_id='LOCAL-MANWOO')
        admin = enroll(self.storage, issued['invitation'], 'sub-admin', '손만우', 'mw@example.com', 'state-' + 'a' * 20, 'cookie-a')
        self.admin_id, self.admin_csrf = admin['account']['id'], admin['csrf']
        self.admin_cookie = '__Host-rndplz_account=' + admin['session_cookie']
        config = Config('client', 'secret', 'https://example.test/auth/google/callback', frozenset({'sub-team'}), True,
                        frozenset({self.admin_id}))
        self.app.auth = AuthService(config, self.storage, transport=FakeTransport())
        self.app.contexts.clear()

    def callback(self, sub, name='Name', email='name@example.com', *, start=None, cookies=()):
        if start is None:
            status, header, _ = call(self.app, 'GET', '/auth/google/start')
            self.assertEqual(status, 303)
        else:
            header = start
        state = parse_qs(urlsplit(header('location')[0]).query)['state'][0]
        login_cookie = cookie_pair(header, '__Host-rndplz_login')
        claims = {'sub': sub, 'name': name, 'email': email, 'email_verified': True}
        with mock.patch('rndplz.auth_service.verify_google_token', return_value=claims):
            return call(self.app, 'GET', '/auth/google/callback', cookies=[login_cookie, *cookies],
                        query='code=abc&state=' + state)

    def answer(self, consent_cookie, decision, cookies=()):
        _, header, body = call(self.app, 'GET', '/api/account/session', cookies=list(cookies))
        visitor = [cookie_pair(header, 'rndplz_visitor')] if any(
            value.startswith('rndplz_visitor=') for value in header('set-cookie')) else []
        return call(self.app, 'POST', '/auth/consent', cookies=[*visitor, *cookies, consent_cookie],
                    token=body['token'], body={'decision': decision})


class ConsentWebTests(WebCase):
    def test_first_login_asks_for_consent_then_logs_in(self):
        status, header, _ = self.callback('sub-team', 'Team', 'team@example.com')
        self.assertEqual((status, header('location')), (303, ['/auth/consent']))
        self.assertFalse(any(value.startswith('__Host-rndplz_account=') and 'Max-Age=0' not in value
                             for value in header('set-cookie')))
        self.assertEqual(len(self.storage.list_accounts()), 1)  # only the admin: nothing stored before agreement
        consent_cookie = cookie_pair(header, '__Host-rndplz_consent')
        status, _, _ = call(self.app, 'GET', '/auth/consent')
        self.assertEqual(status, 200)
        status, header, body = self.answer(consent_cookie, 'agree')
        self.assertEqual((status, body['location']), (200, '/?account_changed=1'))
        member_cookie = cookie_pair(header, '__Host-rndplz_account')
        _, _, session = call(self.app, 'GET', '/api/account/session', cookies=[member_cookie])
        self.assertEqual((session['authenticated'], session['account']['display_name']), (True, 'Team'))
        team = next(row for row in self.storage.list_accounts() if row['display_name'] == 'Team')
        self.assertEqual(team['consent_version'], CONSENT_VERSION)
        self.assertIsInstance(team['consented_at'], int)
        # The consent cookie is used once.
        status, _, body = self.answer(consent_cookie, 'agree')
        self.assertEqual((status, body['code']), (403, 'login_failed'))
        # The next login does not ask again.
        status, header, _ = self.callback('sub-team', 'Team', 'team@example.com')
        self.assertEqual(header('location'), ['/?account_changed=1'])

    def test_declining_stores_nothing(self):
        _, header, _ = self.callback('sub-out', 'Out', 'out@example.com')
        status, _, body = self.answer(cookie_pair(header, '__Host-rndplz_consent'), 'decline')
        self.assertEqual((status, body['location'], body['declined']), (200, '/', True))
        self.assertEqual((len(self.storage.list_accounts()), self.storage.pending_count()), (1, 0))

    def test_sign_up_request_records_consent_with_the_request(self):
        _, header, _ = self.callback('sub-out', 'Out', 'out@example.com')
        status, _, body = self.answer(cookie_pair(header, '__Host-rndplz_consent'), 'agree')
        self.assertEqual((status, body['location']), (200, '/?account_pending=1'))
        self.assertEqual(self.storage.pending_count(), 1)
        pending = next(row for row in self.storage.list_accounts() if row['status'] == 'pending')
        self.assertEqual(pending['consent_version'], CONSENT_VERSION)

    def test_invitation_enrollment_waits_on_consent_and_keeps_the_invitation(self):
        issued = self.storage.issue_invitation(600, person_id='LOCAL-HONG')
        _, header, body = call(self.app, 'GET', '/api/account/session')
        visitor = cookie_pair(header, 'rndplz_visitor')
        status, header, body = call(self.app, 'POST', '/auth/google/enroll', cookies=[visitor], token=body['token'],
                                    body={'invitation': issued['invitation']})
        self.assertEqual(status, 200)
        start = lambda name: [body['authorization_url']] if name == 'location' else header(name)
        _, header, _ = self.callback('sub-hong', '홍윤기', 'hong@example.com', start=start)
        self.assertEqual(header('location'), ['/auth/consent'])
        self.assertEqual(self.storage.invitation_status(issued['invitation_id'])['status'], 'bound')
        status, _, body = self.answer(cookie_pair(header, '__Host-rndplz_consent'), 'agree')
        self.assertEqual((status, body['location']), (200, '/?account_changed=1'))
        self.assertEqual(self.storage.invitation_status(issued['invitation_id'])['status'], 'consumed')
        self.assertIn('LOCAL-HONG', self.storage.bound_person_ids())

    def test_consent_answer_needs_the_page_token_and_a_known_decision(self):
        _, header, _ = self.callback('sub-team')
        consent_cookie = cookie_pair(header, '__Host-rndplz_consent')
        status, _, _ = call(self.app, 'POST', '/auth/consent', cookies=[consent_cookie], token='wrong',
                            body={'decision': 'agree'})
        self.assertEqual(status, 403)
        _, header, body = call(self.app, 'GET', '/api/account/session')
        status, _, body = call(self.app, 'POST', '/auth/consent', token=body['token'],
                               cookies=[cookie_pair(header, 'rndplz_visitor'), consent_cookie], body={'decision': 'maybe'})
        self.assertEqual((status, body['code']), (400, 'consent_invalid'))


class LoginErrorTests(WebCase):
    def test_every_failed_login_answers_with_one_code(self):
        self.app.auth.signup_requests_enabled = False
        self.storage.revoke_account(self.admin_id)
        failures = {
            'not on the team': self.callback('sub-stranger'),
            'revoked': self.callback('sub-admin'),
            'bad state': call(self.app, 'GET', '/auth/google/callback', query='code=abc&state=nope'),
            'provider error': call(self.app, 'GET', '/auth/google/callback', query='error=access_denied'),
            'ambiguous query': call(self.app, 'GET', '/auth/google/callback', query='code=a&code=b&state=s'),
        }
        for reason, (status, _, body) in failures.items():
            with self.subTest(reason=reason):
                self.assertEqual((status, body['code']), (403, 'login_failed'))
        with mock.patch.object(self.app.auth, 'finish', side_effect=RuntimeError('boom')):
            status, _, body = self.callback('sub-team')
        self.assertEqual((status, body['code']), (503, 'login_failed'))


class AdminWebTests(WebCase):
    def test_request_list_is_masked_and_decision_names_the_admin(self):
        self.storage.request_access('sub-out', '오진호', 'jinho@example.com')
        status, _, body = call(self.app, 'GET', '/api/account/requests', cookies=[self.admin_cookie])
        self.assertEqual((status, body['requests'][0]['email']), (200, 'j***@example.com'))
        status, _, _ = call(self.app, 'POST', '/api/account/requests/decide', cookies=[self.admin_cookie],
                            token=self.admin_csrf, body={'account_id': body['requests'][0]['account_id'],
                                                         'decision': 'approve', 'person_id': 'LOCAL-JINHO'})
        self.assertEqual(status, 200)
        latest = self.storage.permission_history()[0]
        self.assertEqual((latest['action'], latest['actor']), ('request_approved', self.admin_id))


class ResponseHeaderTests(WebCase):
    def test_hsts_only_over_https(self):
        _, header, _ = call(self.app, 'GET', '/healthz')
        self.assertEqual(header('strict-transport-security'), [])
        with mock.patch.object(self.app, 'secure', True):
            for path in ('/healthz', '/', '/api/account/session', '/missing'):
                with self.subTest(path=path):
                    _, header, _ = call(self.app, 'GET', path)
                    self.assertEqual(header('strict-transport-security'), ['max-age=31536000; includeSubDomains'])

    def test_healthz_answers_get_only(self):
        self.assertEqual(call(self.app, 'GET', '/healthz')[0], 200)
        for method in ('POST', 'PUT', 'DELETE', 'HEAD', 'OPTIONS'):
            with self.subTest(method=method):
                status, header, _ = call(self.app, method, '/healthz')
                self.assertEqual((status, header('allow')), (405, ['GET']))

    def test_design_drafts_are_off_unless_enabled(self):
        path = '/ui-previews/UI-MAIN-001/r1/index.html'
        self.assertEqual(call(self.app, 'GET', path)[0], 404)
        self.assertEqual(call(self.app, 'GET', '/ui-previews/')[0], 404)
        with mock.patch.object(self.app, 'ui_previews', True):
            self.assertEqual(call(self.app, 'GET', path)[0], 200)


if __name__ == '__main__':
    unittest.main()
