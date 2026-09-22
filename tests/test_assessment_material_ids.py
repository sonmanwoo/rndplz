"""Model assessments that echo an exposed name or title instead of its id.

Observed with gemma4:e4b on 2026-09-23: both response attempts named
"person_id": "Manfred Morari" for material id PUB-MORARI and were rejected as
assessment_unknown_person although quotes and record ids were exact. Only a
unique exact label is mapped back; ambiguous or unknown labels still fail.
"""
import json
import unittest

from rndplz.model_dialogue import (AssessmentValidationError, ResponseValidationError,
                                   parse_assessment, parse_response)


def material(pid, name, records):
    return {'id': pid, 'name': name, 'evidence': [
        {'id': rid, 'title': title, 'excerpt': excerpt, 'scope_label': 'public', 'source': 'test'}
        for rid, title, excerpt in records]}


MATERIALS = [
    material('PUB-RAWLINGS', 'James B. Rawlings',
             [('EXP02-PAPER-RAWLINGS-1992-1', 'Model-Predictive Control of Chemical Processes', '입력 제약을 검토한다.')]),
    material('PUB-MORARI', 'Manfred Morari',
             [('EXP02-PAPER-MORARI-1996-1', 'Robust constrained model predictive control', '모델 불확실성을 다룬다.'),
              ('EXP02-PAPER-MORARI-1999-2', 'Model predictive control: past, present and future', '발전 과제를 정리한다.')]),
]
BASE_PLAN = {'reply': '조회합니다.', 'intent': 'search', 'lookup_action': 'execute', 'summary': '',
             'interpretations': [{'label': 'MPC', 'groups': [{'topic_ids': [], 'queries': ['MPC']}]}],
             'person_names': [], 'conditions': [], 'record_ids': []}
USER_MESSAGES = [{'role': 'user', 'turn_id': 'turn-1', 'text': 'MPC를 연구한 사람을 찾고 있어요.'}]
ALLOWED_RECORDS = ['EXP02-PAPER-RAWLINGS-1992-1', 'EXP02-PAPER-MORARI-1996-1', 'EXP02-PAPER-MORARI-1999-2']


def response(rows, next_lookup=None):
    return json.dumps({'assessments': rows, 'reply': '두 분의 기록이 관련됩니다.', 'next_lookup': next_lookup},
                      ensure_ascii=False)


def row(pid, rid, quote='모델 불확실성을 다룬다.', relation='direct'):
    return {'person_id': pid, 'relation': relation, 'text': '관련 기록입니다.',
            'evidence': [{'record_id': rid, 'quote': quote}], 'missing': ''}


def parse(raw, materials=MATERIALS):
    return parse_response(raw, materials=materials, base_plan=BASE_PLAN, user_messages=USER_MESSAGES,
                          allowed_topic_ids=[], allowed_record_ids=ALLOWED_RECORDS, allow_next_lookup=False)


class MaterialIdCanonicalizationTests(unittest.TestCase):
    def test_exposed_name_is_mapped_to_person_id(self):
        raw = response([row('James B. Rawlings', 'EXP02-PAPER-RAWLINGS-1992-1', '입력 제약을 검토한다.'),
                        row('Manfred Morari', 'EXP02-PAPER-MORARI-1996-1')])
        parsed, next_plan = parse(raw)
        self.assertIsNone(next_plan)
        self.assertEqual([r['person_id'] for r in parsed['assessments']], ['PUB-RAWLINGS', 'PUB-MORARI'])
        self.assertEqual(parsed['assessments'][1]['text'], '관련 기록입니다.')

    def test_exposed_title_is_mapped_to_record_id(self):
        raw = response([row('PUB-RAWLINGS', ' Model-Predictive Control of Chemical Processes ', '입력 제약을 검토한다.'),
                        row('PUB-MORARI', 'robust constrained model predictive control')])
        parsed, _ = parse(raw)
        self.assertEqual(parsed['assessments'][0]['evidence'][0]['record_id'], 'EXP02-PAPER-RAWLINGS-1992-1')
        self.assertEqual(parsed['assessments'][1]['evidence'][0]['record_id'], 'EXP02-PAPER-MORARI-1996-1')

    def test_title_of_another_person_is_still_rejected(self):
        raw = response([row('PUB-RAWLINGS', 'Robust constrained model predictive control', '입력 제약을 검토한다.'),
                        row('PUB-MORARI', 'EXP02-PAPER-MORARI-1996-1')])
        with self.assertRaises(ResponseValidationError) as caught:
            parse(raw)
        self.assertEqual(caught.exception.reason, 'assessment_record_not_for_person')

    def test_unknown_name_is_still_rejected(self):
        raw = response([row('James Rawlings', 'EXP02-PAPER-RAWLINGS-1992-1', '입력 제약을 검토한다.'),
                        row('PUB-MORARI', 'EXP02-PAPER-MORARI-1996-1')])
        with self.assertRaises(ResponseValidationError) as caught:
            parse(raw)
        self.assertEqual(caught.exception.reason, 'assessment_unknown_person')

    def test_ambiguous_name_is_not_guessed(self):
        materials = [material('PUB-A', 'Kim Minsu', [('R-A', 'Paper A', 'A 본문')]),
                     material('PUB-B', 'Kim Minsu', [('R-B', 'Paper B', 'B 본문')])]
        raw = response([row('Kim Minsu', 'R-A', 'A 본문'), row('PUB-B', 'R-B', 'B 본문')])
        with self.assertRaises(ResponseValidationError) as caught:
            parse_response(raw, materials=materials, base_plan=BASE_PLAN, user_messages=USER_MESSAGES,
                           allowed_topic_ids=[], allowed_record_ids=['R-A', 'R-B'], allow_next_lookup=False)
        self.assertEqual(caught.exception.reason, 'assessment_unknown_person')

    def test_legacy_assessment_contract_maps_names_too(self):
        raw = json.dumps({'assessments': [row('James B. Rawlings', 'EXP02-PAPER-RAWLINGS-1992-1', '입력 제약을 검토한다.'),
                                          row('Manfred Morari', 'EXP02-PAPER-MORARI-1999-2', '발전 과제를 정리한다.')],
                          'empty_reply': ''}, ensure_ascii=False)
        parsed = parse_assessment(raw, materials=MATERIALS)
        self.assertEqual([r['person_id'] for r in parsed['assessments']], ['PUB-RAWLINGS', 'PUB-MORARI'])
        with self.assertRaises(AssessmentValidationError):
            parse_assessment(json.dumps({'assessments': [row('Nobody', 'EXP02-PAPER-RAWLINGS-1992-1')],
                                         'empty_reply': ''}), materials=MATERIALS)


if __name__ == '__main__':
    unittest.main()
