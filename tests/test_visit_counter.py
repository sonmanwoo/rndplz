"""Daily visit counts (2026-10-14): a person's page views, keys only; automated browsers and bots left out."""
import io
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from rndplz.account_storage import AccountStorage
from rndplz.auth_service import AuthService, Config
from rndplz.visit_counter import VisitCounter, visit_counts
from tests.test_signup_requests import FakeTransport, call, enroll

PERSON = 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Version/18.0 Mobile Safari/604.1'
HEADLESS = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) HeadlessChrome/141.0.0.0 Safari/537.36'
NOON = datetime(2026, 10, 14, 3, 0, tzinfo=timezone.utc)


class CounterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name) / 'visits'
        self.counter = VisitCounter(self.dir, b's' * 32)

    def test_people_are_counted_once_a_day_and_machines_not_at_all(self):
        visitor = {'sid': 'a' * 32}
        self.assertTrue(self.counter.record(visitor, '/', PERSON, now=NOON))
        self.assertTrue(self.counter.record(visitor, '/explore', PERSON, now=NOON))
        self.assertTrue(self.counter.record({'sid': 'b' * 32, 'account': {'id': 'acc-1'}}, '/', PERSON, now=NOON))
        # The same account from another login is the same person.
        self.assertTrue(self.counter.record({'sid': 'c' * 32, 'account': {'id': 'acc-1'}}, '/', PERSON, now=NOON))
        for agent in (HEADLESS, 'Googlebot/2.1 (+http://www.google.com/bot.html)', 'curl/8.4.0', 'python-requests/2.32', ''):
            self.assertFalse(self.counter.record({'sid': 'd' * 32}, '/', agent, now=NOON))
        self.assertFalse(self.counter.record({}, '/', PERSON, now=NOON))
        day = json.loads((self.dir / '2026-10-14.json').read_text(encoding='utf-8'))
        self.assertEqual((day['views'], len(day['visitors']), len(day['accounts'])), (4, 2, 1))
        self.assertEqual(day['pages'], {'/': 3, '/explore': 1})
        raw = json.dumps(day)
        self.assertNotIn('a' * 32, raw)
        self.assertNotIn('acc-1', raw)
        self.assertTrue(all(len(key) == 16 for key in day['visitors']))

    def test_periods_count_distinct_people(self):
        visitor = {'sid': 'a' * 32}
        self.counter.record(visitor, '/', PERSON, now=datetime(2026, 10, 10, 3, tzinfo=timezone.utc))
        self.counter.record(visitor, '/', PERSON, now=NOON)
        self.counter.record({'sid': 'e' * 32}, '/', PERSON, now=datetime(2026, 9, 30, 3, tzinfo=timezone.utc))
        (self.dir / 'notes.json').write_text('{}', encoding='utf-8')
        since = {'today': datetime(2026, 10, 14, tzinfo=timezone.utc), 'week': datetime(2026, 10, 8, tzinfo=timezone.utc), 'all': None}
        rows, first = visit_counts(self.dir, since)
        self.assertEqual(rows['today'], {'visitors': 1, 'accounts': 0, 'views': 1})
        self.assertEqual(rows['week'], {'visitors': 1, 'accounts': 0, 'views': 2})
        self.assertEqual(rows['all'], {'visitors': 2, 'accounts': 0, 'views': 3})
        self.assertEqual(first, '2026-09-30')
        self.assertEqual(visit_counts(Path(self.tmp.name) / 'none', since)[0]['all']['visitors'], 0)


class WebTests(unittest.TestCase):
    def test_pages_are_counted_for_people_and_shown_to_the_admin(self):
        from rndplz.public_web import PublicApp
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        app = PublicApp(state_dir=Path(tmp.name) / 'state', env={
            'RNDPLZ_LOCAL_PREVIEW': '1', 'RNDPLZ_SESSION_SECRET': 's' * 64,
            'RNDPLZ_PUBLIC_PERSON_IDS': 'LOCAL-MANWOO,LOCAL-JINHO,LOCAL-DASOL,LOCAL-HONG'})
        storage = AccountStorage(Path(tmp.name) / 'accounts.sqlite3', Path(tmp.name) / 'files')
        admin = enroll(storage, storage.issue_invitation(600, person_id='LOCAL-MANWOO')['invitation'],
                       'sub-admin', '손만우', 'mw@example.com', 'state-' + 'a' * 20, 'cookie-a')
        app.auth = AuthService(Config('client', 'secret', 'https://example.test/auth/google/callback', frozenset(), True,
                                      frozenset({admin['account']['id']})), storage, transport=FakeTransport())
        cookie = '__Host-rndplz_account=' + admin['session_cookie']

        def page(path, agent, cookies=()):
            environ = {'REQUEST_METHOD': 'GET', 'PATH_INFO': path, 'QUERY_STRING': '', 'HTTP_HOST': '127.0.0.1',
                       'wsgi.input': io.BytesIO(b''), 'CONTENT_LENGTH': '0', 'wsgi.url_scheme': 'http',
                       'HTTP_USER_AGENT': agent}
            if cookies:
                environ['HTTP_COOKIE'] = '; '.join(cookies)
            status = {}
            b''.join(app(environ, lambda s, h: status.setdefault('code', int(s.split()[0]))))
            return status['code']

        self.assertEqual(page('/', PERSON), 200)
        self.assertEqual(page('/privacy', PERSON), 200)
        self.assertEqual(page('/', HEADLESS), 200)
        self.assertEqual(page('/craft.css', PERSON), 200)          # a file, not a page
        self.assertEqual(page('/admin/connections', PERSON, (cookie,)), 200)  # the admin page itself is not counted
        status, _, body = call(app, 'GET', '/api/account/connections', cookies=(cookie,))
        self.assertEqual(status, 200)
        self.assertEqual(body['visits']['all']['views'], 2)
        self.assertEqual(body['visits']['all']['visitors'], 2)  # each anonymous request without a cookie is a new visitor
