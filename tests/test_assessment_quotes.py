"""An assessment quote that writes a compatibility character still matches its record.

Hosted 2026-10-02 ("촉매 전문가를 찾고 싶어", 7 candidates): the record says "CO2J Project팀 책임.
CO₂ 화학적 전환용 …" and gemma4:e4b quoted it as "CO₂J …" on both attempts, so the whole
assessment of seven people was rejected (assessment_quote_not_exposed) and the scout failed.
"""
import unittest

from rndplz.model_dialogue import AssessmentValidationError, _source_span, _validate_assessment_rows

RECORD = 'CO2J Project팀 책임. CO₂ 화학적 전환용 촉매 설계·제법 개발 및 반응 활성 평가.'


def rows(quote):
    return [{'person_id': 'P-JO', 'relation': 'direct', 'evidence': [{'record_id': 'R-CO2J', 'quote': quote}]}]


class AssessmentQuoteTests(unittest.TestCase):
    def test_a_subscript_written_for_a_plain_digit_is_the_record_s_own_text(self):
        checked = rows('CO₂J Project팀 책임. CO₂ 화학적 전환용')
        _validate_assessment_rows(checked, {'P-JO': {'R-CO2J': [RECORD]}})
        self.assertEqual(checked[0]['evidence'][0]['quote'], 'CO2J Project팀 책임. CO₂ 화학적 전환용')

    def test_spacing_still_folds_and_other_words_are_still_rejected(self):
        self.assertEqual(_source_span('마찰마모', '윤활유 마찰 마모 시험'), '마찰 마모')
        with self.assertRaises(AssessmentValidationError) as caught:
            _validate_assessment_rows(rows('CO₂ 저장 공정 운전'), {'P-JO': {'R-CO2J': [RECORD]}})
        self.assertEqual(caught.exception.reason, 'assessment_quote_not_exposed')


if __name__ == '__main__':
    unittest.main()
