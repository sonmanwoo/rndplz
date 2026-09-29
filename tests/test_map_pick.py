"""A person picked on the recommendation map, outside the result, can get the same request.

The letter says the requester chose them and lists their records instead of claiming a link;
the saved proposal is marked, and only people outside the result, in the current pool, can be picked.
"""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from rndplz.domain import Contribution, Person, Record
from rndplz.engine import Engine
from rndplz.models import ExternalModel
from rndplz.service import PickError, Service


def record(rid, pid, name, title, date):
    return Record(id=rid, kind='career_record', title=title, text=title, date=date,
                  people=[Contribution(person_id=pid, name=name, role='recorded_role')], tags=[],
                  field='process_engineering', scope='self_reported', source_system='user_provided_resume',
                  source_id=rid, source_url='', checked_at='2026-09-29', evidence_kind='career_experience')


class MapPickTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        people = {
            'P-MW': Person(id='P-MW', name='Manwoo Son', org='GS'),
            'P-RM': Person(id='P-RM', name='Robert McCormick', org='NREL',
                           profile={'curated': True, 'display_name': '로버트 맥코믹'}),
            'P-OLD': Person(id='P-OLD', name='Old Master', profile={'display_type': 'historical_researcher'}),
            'P-EMPTY': Person(id='P-EMPTY', name='No Records'),
        }
        records = {
            'R-MONO': record('R-MONO', 'P-MW', 'Manwoo Son', '모노머 공정 증류 실험', '2020'),
            'R-SAF1': record('R-SAF1', 'P-RM', 'Robert McCormick', '지속가능항공유 연료 특성', '2019'),
            'R-SAF2': record('R-SAF2', 'P-RM', 'Robert McCormick', '바이오 연료 산화 안정성', '2023'),
            'R-OLD': record('R-OLD', 'P-OLD', 'Old Master', '고전 증류 이론', '1950'),
        }
        by_person = {pid: [r for r in records.values() if r.people[0].person_id == pid] for pid in people}
        corpus = SimpleNamespace(people=people, records=records, by_person=by_person, topics=[], topic_by_id={},
                                 questions=[], errors=[], demo_pool={'version': 'pool-1'})
        state_dir = Path(self.tmp.name) / 'state'
        state_dir.mkdir()
        evidence = [{'id': 'R-MONO', 'title': '모노머 공정 증류 실험', 'date': '2020', 'virtual': False}]
        result = {'topic_ids': [], 'claims': [], 'pool_version': 'pool-1', 'candidates': [
            {'id': 'P-MW', 'name': 'Manwoo Son', 'virtual': False, 'lookup_only': False, 'evidence': evidence}]}
        base = {'kind': 'chat', 'created': 't', 'updated': 't', 'original': '증류 전문가를 찾고 있어',
                'turns': 1, 'mode': 'advice', 'asker': 'lab', 'messages': [], 'ready': True,
                'slots': {'target': '', 'conditions': '', 'resources': '', 'deadline': '', 'goal': '증류 자문'},
                'proposal_context': '원료 내 이취 물질 제거'}
        sessions = [{**base, 'id': 's1', 'result': result},
                    {**base, 'id': 's-old', 'result': {**result, 'pool_version': 'pool-0'}},
                    {**base, 'id': 's-none'}]
        (state_dir / 'state.json').write_text(json.dumps(
            {'version': 1, 'sessions': sessions, 'proposals': [], 'idempotency': {}}, ensure_ascii=False), encoding='utf-8')
        self.service = Service(Engine(corpus), state_dir,
                               ExternalModel({'RNDPLZ_PROVIDER': 'none', 'RNDPLZ_MODEL_CALL_LIMIT': '0'}),
                               state_env={'RNDPLZ_STATE_BACKEND': 'file'})

    def test_picked_letter_is_the_same_request_marked_as_the_requesters_choice(self):
        draft = self.service.draft('s1', 'P-RM', picked=True)
        body = draft['body']
        self.assertTrue(body.startswith('로버트 맥코믹님께,'))
        self.assertIn('원료 내 이취 물질 제거', body)
        self.assertIn('[직접 선택]', body)
        self.assertIn('관련성은 아직 확인되지 않았습니다', body)
        self.assertNotIn('[연결 근거]', body)
        # Newest record first, under the person's records rather than as a link to the request.
        self.assertLess(body.index('바이오 연료 산화 안정성'), body.index('지속가능항공유 연료 특성'))
        self.assertIn('[연결 근거]', self.service.draft('s1', 'P-MW')['body'])

    def test_only_people_outside_a_current_result_can_be_picked(self):
        cases = {('s1', 'P-MW'): '후보 카드', ('s1', 'P-OLD'): '역사적', ('s1', 'P-EMPTY'): '등록된 이력',
                 ('s1', 'P-NOBODY'): '명단에 없는', ('s-old', 'P-RM'): '현재 요청', ('s-none', 'P-RM'): '현재 요청'}
        for (sid, pid), words in cases.items():
            with self.subTest(sid=sid, pid=pid):
                with self.assertRaises(PickError) as caught:
                    self.service.draft(sid, pid, picked=True)
                self.assertIn(words, str(caught.exception))

    def test_saved_proposal_is_marked_and_needs_the_pick_flag(self):
        payload = {'session_id': 's1', 'candidate_ids': ['P-RM'], 'state': 'draft', 'idempotency_key': 'k1',
                   'bodies': {}}
        with self.assertRaises(ValueError):
            self.service.save_proposal(payload)  # not a candidate, not picked
        with self.assertRaises(ValueError):
            self.service.save_proposal({**payload, 'idempotency_key': 'k2', 'picked_ids': ['P-MW']})
        created = self.service.save_proposal({**payload, 'idempotency_key': 'k3', 'picked_ids': ['P-RM']})
        self.assertEqual((created[0]['recipient_id'], created[0]['recipient_name'], created[0]['selection']),
                         ('P-RM', '로버트 맥코믹', 'user_pick'))
        self.assertIn('[직접 선택]', created[0]['body'])
        self.assertEqual({e['id'] for e in created[0]['evidence']}, {'R-SAF1', 'R-SAF2'})
        mixed = self.service.save_proposal({**payload, 'idempotency_key': 'k4', 'candidate_ids': ['P-MW', 'P-RM'],
                                            'picked_ids': ['P-RM']})
        self.assertEqual([p.get('selection') for p in mixed], [None, 'user_pick'])
        sent = self.service.transition(created[0]['id'], 'sent')
        self.assertEqual(sent['state'], 'sent')


if __name__ == '__main__':
    unittest.main()
