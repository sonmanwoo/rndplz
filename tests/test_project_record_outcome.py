"""User-provided outcome and roles on a shared project record reach the corpus.

The GS hackathon 2026 developer-league record is shared by four registered
people. The user supplied the result (2nd place) and their own role (main
developer) on 2026-09-23; other participants' roles stay unrecorded.
"""
import os
import tempfile
import unittest

from rndplz.service import Service

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
