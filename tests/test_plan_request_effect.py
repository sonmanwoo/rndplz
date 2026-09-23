"""Plans that say request_effect=preserve when there is nothing to preserve.

Observed with gemma4:e4b on 2026-09-23 (PC hosting): greetings such as
"안녕하세요" produced preserve with either a clarifying open question or an
all-empty scope object, and both were rejected as preserve_request_has_changes
before any answer was shown. The two raw plans below are the recorded outputs.
"""
import json
import unittest

from rndplz.model_dialogue import PlanValidationError, parse_request_effect, plan_repair_feedback

GREETING_WITH_QUESTION = json.dumps({
    "request_effect": "preserve", "decision": "answer", "scope": None,
    "brief": {"requested_help": [], "open_questions": ["어떤 연구 경험이나 논문 분야에 대해 도움을 받고 싶으신가요?"]},
    "summary": "사용자가 대화를 시작하며 인사하였습니다.", "reply": "안녕하세요. 어떤 주제가 궁금하신가요?",
    "attachment_actions": []}, ensure_ascii=False)
GREETING_EMPTY_SCOPE = json.dumps({
    "request_effect": "preserve", "decision": "answer",
    "scope": {"purposes": [], "interpretations": [], "record_ids": [], "person_names": [], "conditions": []},
    "brief": {"requested_help": [], "open_questions": []},
    "summary": "사용자님께서 다시 인사해주셨습니다.", "reply": "다시 인사해주셔서 감사합니다.",
    "attachment_actions": []}, ensure_ascii=False)
PRESERVE_WITH_NEW_PURPOSE = json.dumps({
    "request_effect": "preserve", "decision": "answer",
    "scope": {"purposes": [{"source_turn_id": "t1", "source_quote": "증류 경험", "text": "증류 경험자 찾기"}],
              "interpretations": [], "record_ids": [], "person_names": [], "conditions": []},
    "brief": {"requested_help": [], "open_questions": []},
    "summary": "요약", "reply": "답", "attachment_actions": []}, ensure_ascii=False)


class PreserveWithoutRequestTests(unittest.TestCase):
    def test_first_turn_preserve_with_question_becomes_update(self):
        self.assertEqual(parse_request_effect(GREETING_WITH_QUESTION, preserve_available=False), "update")

    def test_first_turn_preserve_with_empty_scope_becomes_update(self):
        self.assertEqual(parse_request_effect(GREETING_EMPTY_SCOPE, preserve_available=False), "update")

    def test_later_turn_open_question_still_rejects_preserve(self):
        with self.assertRaises(PlanValidationError) as caught:
            parse_request_effect(GREETING_WITH_QUESTION, preserve_available=True)
        self.assertEqual(caught.exception.reason, "preserve_request_has_changes")
        feedback = plan_repair_feedback(caught.exception)
        self.assertEqual(feedback["field"], "$.request_effect")
        self.assertIn("preserve only keeps", feedback["expected"]["constraint"])

    def test_later_turn_empty_scope_object_counts_as_null(self):
        self.assertEqual(parse_request_effect(GREETING_EMPTY_SCOPE, preserve_available=True), "preserve")

    def test_preserve_with_actual_scope_content_is_rejected_even_without_request(self):
        # Nothing to preserve turns it into an update; with a request it stays an error.
        self.assertEqual(parse_request_effect(PRESERVE_WITH_NEW_PURPOSE, preserve_available=False), "update")
        with self.assertRaises(PlanValidationError):
            parse_request_effect(PRESERVE_WITH_NEW_PURPOSE, preserve_available=True)

    def test_update_is_unchanged(self):
        raw = GREETING_WITH_QUESTION.replace('"preserve"', '"update"', 1)
        self.assertEqual(parse_request_effect(raw), "update")
        self.assertEqual(parse_request_effect(raw, preserve_available=False), "update")


if __name__ == "__main__":
    unittest.main()
