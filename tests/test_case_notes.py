"""How a request turned out, kept as a case note (2026-10-15)."""
import copy
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from rndplz.account_storage import AccountStorage
from rndplz.auth_service import AuthService, Config
from rndplz.case_notes import CaseShelf, apply, draft, validate
from rndplz.connection_metrics import collect
from rndplz.domain import Person
from rndplz.engine import Engine
from rndplz.models import ExternalModel
from rndplz.service import Service
from tests.test_signup_requests import FakeTransport, call, enroll

G1, G2 = 'a' * 32, 'b' * 32
NOW = datetime(2026, 10, 15, 3, 0, tzinfo=timezone.utc)


def state():
    session = {'id': 's1', 'original': '증류 효율', 'created': '2026-10-08T01:00:00+00:00', 'messages': [{'role': 'user'}],
               'scout': {'disclosed': True},
               'request_spec': {'summary': '증류 효율 개선', 'purposes': [{'text': '증류 분리 효율 개선'}, {'text': '컬럼 액체 상승 진단'}]},
               'result': {'candidates': [{'id': 'P-2'}, {'id': 'P-1'}]}}
    letter = lambda pid, name, group, state_='sent', **extra: {
        'id': pid + group[:4], 'group_id': group, 'session_id': 's1', 'recipient_id': pid, 'recipient_name': name,
        'state': state_, 'created': '2026-10-08T02:00:00+00:00',
        'evidence': [{'title': '모노머 공정 증류 실험'}], **extra}
    return {'version': 1, 'sessions': [session], 'idempotency': {},
            'proposals': [letter('P-1', '손만우', G1), letter('P-2', '오진호', G1), letter('P-3', '홍윤기', G2, 'draft')]}


class RulesTests(unittest.TestCase):
    def test_validate(self):
        ok = validate({'group_id': G1, 'result': 'unsolved', 'reasons': ['unreachable'], 'notes': {'tried': ' 보냈지만 답이 없었다 '},
                       'visibility': 'team'})
        self.assertEqual(ok['notes'], {'tried': '보냈지만 답이 없었다'})
        for bad in ({'group_id': 'x', 'result': 'solved'},
                    {'group_id': G1, 'result': 'great'},
                    {'group_id': G1, 'result': 'solved', 'reasons': ['field']},                  # reasons only when not solved
                    {'group_id': G1, 'result': 'unsolved', 'reasons': ['mood']},
                    {'group_id': G1, 'result': 'solved', 'notes': {'tried': '...'}},             # not a field of this result
                    {'group_id': G1, 'result': 'solved', 'notes': {'helped': 'x' * 1001}},
                    {'group_id': G1, 'result': 'ongoing', 'visibility': 'team'},
                    {'group_id': G1, 'result': 'solved', 'extra': 1}):
            with self.assertRaises(ValueError):
                validate(bad)

    def test_draft_and_apply(self):
        data = state()
        sheet = draft(data, G1, now=NOW)
        self.assertEqual(sheet['recipients'], ['손만우', '오진호'])
        self.assertEqual(sheet['days'], 7)
        self.assertEqual(sheet['route'], '수소문 추천 2번째 카드 · 근거 「모노머 공정 증류 실험」')
        self.assertEqual(sheet['problem'], '증류 분리 효율 개선 · 컬럼 액체 상승 진단')
        self.assertIsNone(sheet['saved'])
        with self.assertRaises(ValueError):
            draft(data, G2)  # a draft-only send has no result to leave
        note = apply(data, validate({'group_id': G1, 'result': 'partial', 'notes': {'helped': '조언'}}), now=NOW)
        self.assertEqual([p.get('outcome', {}).get('case_id') for p in data['proposals']], [note['case_id']] * 2 + [None])
        self.assertEqual((note['days'], note['visibility']), (7, 'private'))
        again = apply(data, validate({'group_id': G1, 'result': 'solved'}), now=NOW)
        self.assertEqual(again['case_id'], note['case_id'])  # the same note, changed
        self.assertEqual(draft(data, G1)['saved']['result'], 'solved')
        picked = state()
        picked['proposals'][0]['selection'] = 'user_pick'
        self.assertTrue(draft(picked, G1)['route'].startswith('연구 맵에서 직접 고른 분'))


class ShelfTests(unittest.TestCase):
    def test_team_notes_wait_for_the_admin(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        shelf = CaseShelf(Path(tmp.name) / 'cases')
        data = state()
        note = apply(data, validate({'group_id': G1, 'result': 'unsolved', 'reasons': ['field'], 'notes': {'tried': '보냄'},
                                     'visibility': 'team'}), now=NOW)
        case = shelf.share(note, ['손만우', '오진호'])
        self.assertEqual((case['review'], case['recipients']), ('pending', []))  # no names on a send that did not work
        shelf.review(note['case_id'], 'approved')
        self.assertEqual(shelf.all()[0]['review'], 'approved')
        # The same note again keeps the decision; a changed one waits again.
        self.assertEqual(shelf.share(note, ['손만우'])['review'], 'approved')
        changed = apply(data, validate({'group_id': G1, 'result': 'solved', 'notes': {'helped': '해결'}, 'visibility': 'team'}), now=NOW)
        case = shelf.share(changed, ['손만우', '오진호'])
        self.assertEqual((case['review'], case['recipients']), ('pending', ['손만우', '오진호']))
        # Taken back to private, the shared copy goes.
        private = apply(data, validate({'group_id': G1, 'result': 'solved', 'visibility': 'private'}), now=NOW)
        self.assertIsNone(shelf.share(private, ['손만우']))
        self.assertEqual(shelf.all(), [])
        for bad in (('nope', 'approved'), (note['case_id'], 'maybe')):
            with self.assertRaises(ValueError):
                shelf.review(*bad)


class ServiceAndMetricsTests(unittest.TestCase):
    def test_record_and_count(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        corpus = SimpleNamespace(people={'P-1': Person('P-1', 'A')}, records={}, by_person={}, topics=[], topic_by_id={}, questions=[])
        root = Path(tmp.name) / 'state'
        service = Service(Engine(corpus), root / ('c' * 32), ExternalModel({'RNDPLZ_PROVIDER': 'none', 'RNDPLZ_MODEL_CALL_LIMIT': '0'}),
                          state_env={'RNDPLZ_STATE_BACKEND': 'file'})
        seeded = state()
        service.store.transaction(lambda s: s.update(copy.deepcopy(seeded)))
        self.assertEqual(service.outcome_draft({'group_id': G1})['recipients'], ['손만우', '오진호'])
        with self.assertRaises(ValueError):
            service.outcome_draft({'group_id': G1, 'x': 1})
        note, names = service.record_outcome({'group_id': G1, 'result': 'unsolved', 'reasons': ['unreachable', 'changed'],
                                              'notes': {'tried': '답이 없었다'}, 'visibility': 'team'})
        self.assertEqual((note['result'], names), ('unsolved', ['손만우', '오진호']))
        every = collect(root, now=NOW)['periods']['all']  # sent on 10-08, before this week
        self.assertEqual((every['sends'], every['outcome']['unsolved'], every['shared']), (1, 1, 1))
        self.assertEqual((every['stuck']['unreachable'], every['stuck']['changed'], every['stuck']['field']), (1, 1, 0))


class AdminTests(unittest.TestCase):
    def test_only_the_admin_sees_and_decides_shared_cases(self):
        from rndplz.public_web import PublicApp
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        app = PublicApp(state_dir=Path(tmp.name) / 'state', env={
            'RNDPLZ_LOCAL_PREVIEW': '1', 'RNDPLZ_SESSION_SECRET': 's' * 64,
            'RNDPLZ_PUBLIC_PERSON_IDS': 'LOCAL-MANWOO,LOCAL-JINHO,LOCAL-DASOL,LOCAL-HONG'})
        storage = AccountStorage(Path(tmp.name) / 'accounts.sqlite3', Path(tmp.name) / 'files')
        admin = enroll(storage, storage.issue_invitation(600, person_id='LOCAL-MANWOO')['invitation'],
                       'sub-admin', '손만우', 'mw@example.com', 'state-' + 'a' * 20, 'cookie-a')
        member = enroll(storage, storage.issue_invitation(600, person_id='LOCAL-JINHO')['invitation'],
                        'sub-member', '오진호', 'jh@example.com', 'state-' + 'b' * 20, 'cookie-b')
        app.auth = AuthService(Config('client', 'secret', 'https://example.test/auth/google/callback', frozenset(), True,
                                      frozenset({admin['account']['id']})), storage, transport=FakeTransport())
        note = apply(state(), validate({'group_id': G1, 'result': 'solved', 'notes': {'helped': '조언'}, 'visibility': 'team'}), now=NOW)
        app.cases.share(note, ['손만우'])
        admin_cookie = '__Host-rndplz_account=' + admin['session_cookie']
        member_cookie = '__Host-rndplz_account=' + member['session_cookie']
        self.assertEqual(call(app, 'GET', '/api/account/cases')[0], 401)
        self.assertEqual(call(app, 'GET', '/api/account/cases', cookies=(member_cookie,))[0], 403)
        status, _, body = call(app, 'GET', '/api/account/cases', cookies=(admin_cookie,))
        self.assertEqual((status, body['cases'][0]['recipients']), (200, ['손만우']))
        review = {'case_id': note['case_id'], 'decision': 'approved'}
        self.assertEqual(call(app, 'POST', '/api/account/cases/review', cookies=(member_cookie,), token=member['csrf'], body=review)[0], 403)
        status, _, body = call(app, 'POST', '/api/account/cases/review', cookies=(admin_cookie,), token=admin['csrf'], body=review)
        self.assertEqual((status, body['review']), (200, 'approved'))
        self.assertEqual(call(app, 'POST', '/api/account/cases/review', cookies=(admin_cookie,), token=admin['csrf'],
                              body={**review, 'extra': 1})[0], 400)
