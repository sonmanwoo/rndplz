"""One person written as several assessment rows is folded into one row.

Observed with gemma4:e4b on 2026-09-23 (PC hosting): the model split its
assessment of LOCAL-MANWOO into three paragraph rows with the same person_id,
and both the response and its repair were rejected as
assessment_duplicate_person although every quote and record id was exact.
"""
import json
import unittest

from rndplz.model_dialogue import ResponseValidationError, parse_assessment, parse_response

MATERIALS = [
    {'id': 'LOCAL-MANWOO', 'name': 'Manwoo Son', 'evidence': [
        {'id': 'CAREER-MW-MONOMER', 'title': '모노머 공정 모델링·최적화 및 증류·추출 실험',
         'excerpt': '모노머 공정 모델링 및 최적화, 증류 및 추출 실험 수행.', 'scope_label': '본인 제공 경력', 'source': 'user_provided_resume'},
        {'id': 'CAREER-MW-BIO', 'title': 'Diols 탈색·탈취 공정 개발',
         'excerpt': '증류, 흡착, 수소화반응 등을 활용한 Diols 탈색·탈취 공정 개발.', 'scope_label': '본인 제공 경력', 'source': 'user_provided_resume'}]},
    {'id': 'PUB-OTHER', 'name': 'Other Person', 'evidence': [
        {'id': 'R-OTHER', 'title': '촉매 반응기 설계', 'excerpt': '고정층 촉매 반응기 설계.', 'scope_label': 'public', 'source': 'test'}]},
]
BASE_PLAN = {'reply': '조회합니다.', 'intent': 'search', 'lookup_action': 'execute', 'summary': '',
             'interpretations': [{'label': '증류', 'groups': [{'topic_ids': [], 'queries': ['증류']}]}],
             'person_names': [], 'conditions': [], 'record_ids': []}
USER_MESSAGES = [{'role': 'user', 'turn_id': 'turn-1', 'text': '증류 기술로 제거하고 싶어'}]
ALLOWED = ['CAREER-MW-MONOMER', 'CAREER-MW-BIO', 'R-OTHER']


def row(pid, relation, text, citations, missing=''):
    return {'person_id': pid, 'relation': relation, 'text': text,
            'evidence': [{'record_id': rid, 'quote': quote} for rid, quote in citations], 'missing': missing}


def parse(rows, next_lookup=None):
    raw = json.dumps({'assessments': rows, 'reply': '검토했습니다.', 'next_lookup': next_lookup}, ensure_ascii=False)
    return parse_response(raw, materials=MATERIALS, base_plan=BASE_PLAN, user_messages=USER_MESSAGES,
                          allowed_topic_ids=[], allowed_record_ids=ALLOWED, allow_next_lookup=False)


OTHER = row('PUB-OTHER', 'insufficient', '촉매 기록입니다.', [])


class DuplicateRowMergeTests(unittest.TestCase):
    def test_paragraph_rows_for_one_person_become_one_row(self):
        rows = [row('LOCAL-MANWOO', 'adjacent', '첫 문단', [('CAREER-MW-MONOMER', '증류 및 추출 실험 수행.')], missing=''),
                row('LOCAL-MANWOO', 'adjacent', '둘째 문단', [('CAREER-MW-BIO', '증류, 흡착, 수소화반응')], missing='TCB 사례 없음'),
                row('LOCAL-MANWOO', 'adjacent', '셋째 문단', [('CAREER-MW-MONOMER', '증류 및 추출 실험 수행.')], missing='순도 미정'),
                OTHER]
        parsed, _ = parse(rows)
        self.assertEqual([r['person_id'] for r in parsed['assessments']], ['LOCAL-MANWOO', 'PUB-OTHER'])
        merged = parsed['assessments'][0]
        self.assertEqual(merged['text'], '첫 문단')
        self.assertEqual(merged['relation'], 'adjacent')
        self.assertEqual([c['record_id'] for c in merged['evidence']], ['CAREER-MW-MONOMER', 'CAREER-MW-BIO'])
        self.assertEqual(merged['missing'], 'TCB 사례 없음')

    def test_weakest_relation_wins_when_rows_disagree(self):
        rows = [row('LOCAL-MANWOO', 'direct', '직접', [('CAREER-MW-MONOMER', '증류 및 추출 실험 수행.')]),
                row('LOCAL-MANWOO', 'adjacent', '인접', [('CAREER-MW-BIO', '증류, 흡착, 수소화반응')]),
                OTHER]
        parsed, _ = parse(rows)
        self.assertEqual(parsed['assessments'][0]['relation'], 'adjacent')

    def test_evidence_union_is_capped_at_three_citations(self):
        rows = [row('LOCAL-MANWOO', 'adjacent', 'a', [('CAREER-MW-MONOMER', '증류 및 추출 실험 수행.'), ('CAREER-MW-BIO', '증류, 흡착')]),
                row('LOCAL-MANWOO', 'adjacent', 'b', [('CAREER-MW-BIO', '흡착, 수소화반응'), ('CAREER-MW-MONOMER', '모노머 공정 모델링')]),
                OTHER]
        parsed, _ = parse(rows)
        self.assertEqual(len(parsed['assessments'][0]['evidence']), 2)

    def test_other_person_coverage_is_still_required(self):
        rows = [row('LOCAL-MANWOO', 'adjacent', 'a', [('CAREER-MW-MONOMER', '증류 및 추출 실험 수행.')]),
                row('LOCAL-MANWOO', 'adjacent', 'b', [('CAREER-MW-BIO', '증류, 흡착')])]
        with self.assertRaises(ResponseValidationError) as caught:
            parse(rows)
        self.assertEqual(caught.exception.reason, 'assessment_person_coverage')

    def test_legacy_assessment_contract_merges_too(self):
        raw = json.dumps({'assessments': [
            row('LOCAL-MANWOO', 'adjacent', 'a', [('CAREER-MW-MONOMER', '증류 및 추출 실험 수행.')]),
            row('LOCAL-MANWOO', 'insufficient', 'b', []), OTHER], 'empty_reply': ''}, ensure_ascii=False)
        parsed = parse_assessment(raw, materials=MATERIALS)
        self.assertEqual([r['person_id'] for r in parsed['assessments']], ['LOCAL-MANWOO', 'PUB-OTHER'])
        self.assertEqual(parsed['assessments'][0]['relation'], 'insufficient')


if __name__ == '__main__':
    unittest.main()
