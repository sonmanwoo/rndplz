"""The operator's connection counts (2026-10-14).

Counts only, over every conversation folder, read and never written; the page and its numbers open for
the admin account alone. Saved letters now keep how much of their draft they kept and where its
request part came from.
"""
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from rndplz.account_storage import AccountStorage
from rndplz.auth_service import AuthService, Config
from rndplz.connection_metrics import collect, draft_similarity
from rndplz.domain import Person
from rndplz.engine import Engine
from rndplz.models import ExternalModel
from rndplz.service import Service
from tests.test_signup_requests import FakeTransport, call, enroll

NOW = datetime(2026, 10, 14, 3, 0, tzinfo=timezone.utc)  # 12:00 KST


def session(sid, created, *, searched=True, user=True, cards=('P-1', 'P-2')):
    return {'id': sid, 'created': created, 'messages': [{'role': 'user', 'text': '요청'}] if user else [],
            'scout': {'disclosed': searched}, 'result': {'candidates': [{'id': c} for c in cards]}}


def letter(sid, recipient, created, state='sent', **extra):
    return {'id': sid + recipient, 'session_id': sid, 'recipient_id': recipient, 'state': state,
            'created': created, 'body': '비밀 편지 본문', **extra}


def write(root, name, sessions, proposals=()):
    folder = Path(root) / name
    folder.mkdir(parents=True)
    (folder / 'state.json').write_text(json.dumps({'version': 1, 'sessions': sessions, 'proposals': list(proposals),
                                                   'idempotency': {}}, ensure_ascii=False), encoding='utf-8')


class CollectTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = self.root = self.tmp.name
        write(root, 'a' * 32, [session('s1', '2026-10-14T01:00:00+00:00'),                     # today
                               session('s2', '2026-10-10T01:00:00+00:00'),                     # this week
                               session('s3', '2026-09-30T01:00:00+00:00'),                     # earlier
                               session('s4', '2026-10-14T01:00:00+00:00', searched=False),     # talked only
                               session('s5', '2026-10-14T01:00:00+00:00', searched=False, user=False)],
              [letter('s1', 'P-1', '2026-10-14T02:00:00+00:00', draft_similarity=1.0, letter_source='model'),
               letter('s1', 'P-9', '2026-10-14T02:00:00+00:00', selection='user_pick', draft_similarity=.9, letter_source='model'),
               letter('s2', 'P-2', '2026-10-10T02:00:00+00:00', state='draft', draft_similarity=.5, letter_source='rule'),
               letter('s3', 'P-7', '2026-09-30T02:00:00+00:00')])
        write(root, 'account-' + 'b' * 64, [session('t1', '2026-10-13T16:00:00+00:00')])  # 01:00 KST on the 14th
        (Path(root) / ('c' * 32)).mkdir()  # a visitor who never talked
        (Path(root) / ('d' * 32)).mkdir()
        (Path(root) / ('d' * 32) / 'state.json').write_text('{broken', encoding='utf-8')

    def test_counts_by_period_and_kind(self):
        before = {p: p.read_bytes() for p in Path(self.root).rglob('state.json')}
        result = collect(self.root, now=NOW)
        today, week, every = (result['periods'][name] for name in ('today', 'week', 'all'))
        self.assertEqual(result['since'], {'today': '2026-10-14', 'week': '2026-10-08', 'all': None})
        self.assertEqual((today['started'], today['searched'], today['proposed'], today['sent']), (3, 2, 1, 1))
        self.assertEqual(today['searched_by'], {'visitor': 1, 'account': 1})
        self.assertEqual((week['searched'], week['proposed'], week['sent']), (3, 2, 1))
        self.assertEqual((every['started'], every['searched'], every['proposed'], every['sent']), (5, 4, 3, 2))
        self.assertEqual(today['choice'], {'first': 1, 'other': 0, 'picked': 1, 'unknown': 0})
        self.assertEqual(every['choice'], {'first': 1, 'other': 1, 'picked': 1, 'unknown': 1})
        self.assertEqual((every['letters'], every['letters_sent']), (4, 3))
        self.assertEqual(today['edit'], {'same': 1, 'light': 1, 'heavy': 0})
        self.assertEqual(week['edit'], {'same': 1, 'light': 1, 'heavy': 1})
        self.assertEqual(every['letter'], {'model': 2, 'rule': 1})
        # Read only, and only numbers come out.
        self.assertEqual({p: p.read_bytes() for p in Path(self.root).rglob('state.json')}, before)
        self.assertNotIn('비밀', json.dumps(result, ensure_ascii=False))
        self.assertNotIn('P-1', json.dumps(result))

    def test_similarity(self):
        self.assertEqual(draft_similarity('같은 편지', '같은 편지'), 1.0)
        self.assertLess(draft_similarity('손만우님, 안녕하세요. 증류 자문을 여쭙고 싶습니다.', '전혀 다른 내용으로 새로 썼습니다.'), .5)
        self.assertIsNone(draft_similarity(None, '편지'))
        self.assertEqual(collect(Path(self.root) / 'missing', now=NOW)['periods']['all']['started'], 0)


class SavedLetterTests(unittest.TestCase):
    def test_saved_letter_keeps_how_much_of_the_draft_it_kept(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        corpus = SimpleNamespace(people={'P-1': Person('P-1', 'Researcher', profile={'display_name': '연구자'})},
                                 records={}, by_person={}, topics=[], topic_by_id={}, questions=[])
        service = Service(Engine(corpus), Path(tmp.name) / 'state',
                          ExternalModel({'RNDPLZ_PROVIDER': 'none', 'RNDPLZ_MODEL_CALL_LIMIT': '0'}),
                          state_env={'RNDPLZ_STATE_BACKEND': 'file'})
        service.store.transaction(lambda state: state['sessions'].append({
            'id': 's1', 'original': '시험 자문', 'mode': 'advice', 'asker': 'lab', 'ready': True, 'messages': [],
            'slots': {'target': '', 'conditions': '', 'resources': '', 'deadline': '', 'goal': ''},
            'result': {'topic_ids': [], 'claims': [], 'candidates': [
                {'id': 'P-1', 'name': 'Researcher', 'virtual': False,
                 'evidence': [{'id': 'R-1', 'title': '시험 기록', 'date': '2026', 'virtual': False}]}]}}))
        draft = service.draft('s1', 'P-1')
        self.assertEqual(draft['letter'], 'request')
        kept = service.save_proposal({'session_id': 's1', 'candidate_ids': ['P-1'], 'state': 'sent', 'idempotency_key': 'k1'})[0]
        self.assertEqual((kept['draft_similarity'], kept['letter_source']), (1.0, 'request'))
        edited = service.save_proposal({'session_id': 's1', 'candidate_ids': ['P-1'], 'state': 'sent', 'idempotency_key': 'k2',
                                        'bodies': {'P-1': '연구자님, 제 말로 새로 쓴 짧은 부탁입니다.'}})[0]
        self.assertLess(edited['draft_similarity'], .8)


class AdminOnlyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from rndplz.public_web import PublicApp
        cls.tmp = tempfile.TemporaryDirectory()
        cls.app = PublicApp(state_dir=Path(cls.tmp.name) / 'state', env={
            'RNDPLZ_LOCAL_PREVIEW': '1', 'RNDPLZ_SESSION_SECRET': 's' * 64,
            'RNDPLZ_PUBLIC_PERSON_IDS': 'LOCAL-MANWOO,LOCAL-JINHO,LOCAL-DASOL,LOCAL-HONG'})
        write(cls.app.directory, 'e' * 32, [session('s1', '2026-10-14T01:00:00+00:00')],
              [letter('s1', 'P-1', '2026-10-14T02:00:00+00:00')])

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        storage = AccountStorage(Path(folder.name) / 'accounts.sqlite3', Path(folder.name) / 'files')
        admin = enroll(storage, storage.issue_invitation(600, person_id='LOCAL-MANWOO')['invitation'],
                       'sub-admin', '손만우', 'mw@example.com', 'state-' + 'a' * 20, 'cookie-a')
        member = enroll(storage, storage.issue_invitation(600, person_id='LOCAL-JINHO')['invitation'],
                        'sub-member', '오진호', 'jh@example.com', 'state-' + 'b' * 20, 'cookie-b')
        self.admin = '__Host-rndplz_account=' + admin['session_cookie']
        self.member = '__Host-rndplz_account=' + member['session_cookie']
        config = Config('client', 'secret', 'https://example.test/auth/google/callback', frozenset(), True,
                        frozenset({admin['account']['id']}))
        self.app.auth = AuthService(config, storage, transport=FakeTransport())
        self.app.contexts.clear()

    def test_page_and_numbers_open_for_the_admin_account_only(self):
        for cookies in ((), (self.member,)):
            status, _, _ = call(self.app, 'GET', '/admin/connections', cookies=cookies)
            self.assertEqual(status, 404)
        self.assertEqual(call(self.app, 'GET', '/api/account/connections')[0], 401)
        self.assertEqual(call(self.app, 'GET', '/api/account/connections', cookies=(self.member,))[0], 403)
        self.assertEqual(call(self.app, 'GET', '/api/account/connections', cookies=(self.admin,), query='days=7')[0], 400)
        status, header, _ = call(self.app, 'GET', '/admin/connections', cookies=(self.admin,))
        self.assertEqual(status, 200)
        self.assertTrue(header('content-type')[0].startswith('text/html'))
        status, _, body = call(self.app, 'GET', '/api/account/connections', cookies=(self.admin,))
        self.assertEqual(status, 200)
        self.assertEqual((body['periods']['all']['searched'], body['periods']['all']['sent']), (1, 1))
        # The script holds no numbers; it is public like every other script.
        self.assertEqual(call(self.app, 'GET', '/admin-connections.js')[0], 200)
        status, _, account = call(self.app, 'GET', '/api/account/session', cookies=(self.admin,))
        self.assertTrue(account['admin'])
