"""User-provided outcome and roles on a shared project record reach the corpus.

The GS hackathon 2026 developer-league record is shared by four registered
people. The user supplied the result (2nd place) and their own role (main
developer) on 2026-09-23; other participants' roles stay unrecorded.
"""
import os
from dataclasses import replace
import tempfile
import unittest

from rndplz.service import Service
from rndplz.engine import Engine

TEAM = ['LOCAL-MANWOO', 'LOCAL-JINHO', 'LOCAL-DASOL', 'LOCAL-HONG']


class ProjectRecordOutcomeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        os.environ['RNDPLZ_PUBLIC_PERSON_IDS'] = ','.join(TEAM)
        cls.corpus = Service(state_dir=cls.tmp.name).corpus

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_record_carries_result_and_role(self):
        record = self.corpus.records['PROJECT-HACKATHON-2026']
        self.assertIn('2위', record.title)
        self.assertIn('2위', record.text)
        self.assertIn('메인 개발자', record.text)
        self.assertEqual(record.details['outcome'], '개발자 리그 2위 (2026-09-22 본선)')
        self.assertEqual(record.details['roles'], {'LOCAL-MANWOO': '메인 개발자'})
        self.assertEqual({c.person_id for c in record.people}, set(TEAM))
        roles = {c.person_id: c.role for c in record.people}
        self.assertEqual(roles['LOCAL-MANWOO'], 'recorded_role')
        self.assertEqual(roles['LOCAL-JINHO'], 'participant_unspecified')

    def boundary(self, **details):
        record = self.corpus.records['PROJECT-HACKATHON-2026']
        return Engine(self.corpus).explain_record(replace(record, details=details))['boundary']

    def test_disclosure_distinguishes_user_provided_from_independently_verified(self):
        record = self.corpus.records['PROJECT-HACKATHON-2026']
        boundary = self.boundary(**record.details)
        self.assertIn('사용자 제공 자료에 기재된 내용이며 독립 검증하지 않았습니다', boundary)
        self.assertIn('성과·수상·일정은 자료에 기재된 범위', boundary)
        self.assertIn('역할은 일부 참여자만 기재', boundary)
        self.assertIn('나머지 참여자의 역할은 미기재', boundary)
        self.assertIn('주최는 미기재', boundary)
        self.assertNotIn('성과·수상은 미기재', boundary)
        self.assertNotIn('정확한 일정·주최는 미기재', boundary)
        self.assertIn('특정 기술 전문성·현재 소속·협업 가능성·계정 소유를 입증하지 않습니다', boundary)

    def test_only_missing_project_fields_are_unstated(self):
        boundary = self.boundary(outcome=' ', roles={'unknown': '역할', TEAM[0]: ' '})
        self.assertIn('성과·수상은 미기재', boundary)
        self.assertIn('참여자의 역할은 미기재', boundary)
        self.assertIn('주최는 미기재', boundary)
        boundary = self.boundary(outcome='제공된 성과', roles={pid: '제공된 역할' for pid in TEAM}, organizer='제공된 주최')
        self.assertNotIn('미기재', boundary)
        self.assertNotIn('일부 참여자', boundary)
        self.assertIn('주최는 사용자 제공 자료에 기재된 내용이며 독립 검증하지 않았습니다', boundary)

    def test_profiles_show_outcome_and_only_the_provided_role(self):
        def project(pid):
            return next(p for p in self.corpus.people[pid].profile['projects'] if p.get('id') == 'PROJECT-HACKATHON-2026')
        for pid in TEAM:
            self.assertIn('성과: 개발자 리그 2위', project(pid)['text'])
            self.assertEqual(project(pid)['date'], '2026-09')
        self.assertIn('역할: 메인 개발자 (사용자 제공)', project('LOCAL-MANWOO')['text'])
        for pid in TEAM[1:]:
            self.assertIn('참여 · 역할 미기재', project(pid)['text'])


if __name__ == '__main__':
    unittest.main()
