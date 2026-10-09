"""2026-10-10 chat 24e4d63b: a Gemma answer showed `execution_observation` and LaTeX arrows, every answer
opened with '현재 조회 요약에서는', and the final assessment of three people was cut off at 4096 tokens."""
import unittest

from rndplz.model_dialogue import ANSWER_SYSTEM, generation_contract, plain_reply

BACKSLASH = chr(92)


class PlainReplyTests(unittest.TestCase):
    def test_internal_names_read_as_everyday_words(self):
        text = ('이전 조회 요약(`execution_observation`)에서는 촉매 주제가 보이고, historical_disclosures 기준으로는 없습니다. '
                '`not_executed` 상태이고 현재 조회 요약에서는 확인되지 않음.')
        plain = plain_reply(text)
        for internal in ('execution_observation', 'historical_disclosures', 'not_executed', '`', '조회 요약'):
            self.assertNotIn(internal, plain)
        self.assertIn('이전에 확인한 자료', plain)
        self.assertIn('아직 조회하지 않음', plain)

    def test_latex_arrows_and_instruction_words_read_plainly(self):
        arrow = '$' + BACKSLASH + 'rightarrow$'
        text = '합성 ' + arrow + ' 반응성 평가 ' + arrow + ' 응용. **추정되는 이면:** A ' + BACKSLASH + 'to B'
        self.assertEqual(plain_reply(text), '합성 → 반응성 평가 → 응용. **함께 생각해 볼 점:** A → B')

    def test_ordinary_text_is_untouched(self):
        text = '메탈로센 촉매 합성과 반응성 평가 경험이 있는 연구자를 찾아볼게요.\n[선택] 무엇이 먼저인가요? | 합성 | 평가'
        self.assertEqual(plain_reply(text), text)

    def test_prompt_no_longer_teaches_the_system_phrase(self):
        self.assertNotIn('현재 조회 요약에서는', ANSWER_SYSTEM)
        self.assertIn('이미 말한 주제 목록은 되풀이하지', ANSWER_SYSTEM)
        self.assertIn('함께 생각해 볼 점', ANSWER_SYSTEM)

    def test_several_assessments_fit_the_answer_budget(self):
        self.assertEqual(generation_contract('dialogue_response.v1')['max_tokens'], 8192)
        self.assertEqual(generation_contract('dialogue_assessment.v1')['max_tokens'], 8192)


if __name__ == '__main__':
    unittest.main()
