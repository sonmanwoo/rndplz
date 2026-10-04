"""Attachment bodies reach the final answer and the scout assessment once, not twice.

Reported 2026-10-04 with two real PDFs (40,000 + 13,872 extracted characters) on the company AI:
the plan passed, but the answer's grounding carried the full source texts beside the conversation
bodies (118,750 > 96,000 characters) and, once that was fixed, the assessment's
original_user_sources did the same (99,612 > 96,000). Both now carry previews, like the plan.
Independent review and minimal patch: Codex, _work/two-pdf-review-20261004.
"""
import base64
import json
import tempfile
import time
import unittest
from types import SimpleNamespace

from rndplz.chat_models import generation_spec, input_limit


def conversation():
    from rndplz.conversation import Conversation
    from rndplz.engine import Engine
    from rndplz.models import ExternalModel
    from rndplz.service import Service

    directory = tempfile.TemporaryDirectory(prefix='rndplz-dedup-')
    corpus = SimpleNamespace(people={}, records={}, by_person={}, topics=[], topic_by_id={}, questions=[], errors=[])
    service = Service(Engine(corpus), directory.name + '/state',
                      ExternalModel({'RNDPLZ_PROVIDER': 'none', 'RNDPLZ_MODEL_CALL_LIMIT': '0'}), state_env={})
    return directory, Conversation(service, SimpleNamespace())


QUESTION = '두 문서의 기술 전문가를 찾고 있어'


class AttachmentInputDedupTests(unittest.TestCase):
    def setUp(self):
        self.directory, self.chat = conversation()
        self.addCleanup(self.directory.cleanup)
        self.option = {'id': 'aiu', 'provider': 'aiu', 'vision': False}

    def install(self, texts):
        refs = [{'id': self.chat.attachments.upload({'name': f'document-{i}.txt', 'data': base64.b64encode(t.encode('utf-8')).decode()})['id']}
                for i, t in enumerate(texts)]
        turn = 'turn-1'
        plan = {'intent': 'search', 'lookup_action': 'execute', 'summary': '두 문서의 기술 전문가 탐색',
                'interpretations': [{'label': '증류', 'groups': [{'topic_ids': [], 'queries': ['증류']}]}],
                'person_names': [], 'conditions': [], 'record_ids': []}
        spec = {'summary': plan['summary'], 'purposes': [], 'conditions': [], 'open_questions': [], 'has_content': True,
                'requested_help': [{'source_turn_id': turn, 'source_quote': QUESTION, 'text': '두 문서의 기술 전문가 탐색'}],
                'revision': 'r1', 'source_turn_id': turn, 'source_revision': 'r1'}
        self.session = {'id': 'session-1', 'pending': turn, 'model_plan': plan, 'model_plan_revision': 'r1', 'request_spec': spec,
                        'messages': [{'role': 'user', 'text': QUESTION, 'turn_id': turn, 'attachments': refs}]}
        self.sources = self.chat._model_sources(self.session)
        self.basis = {'source_turns': self.sources, 'historical_disclosures': [], 'record_catalog': None,
                      'record_ids': [], 'exposed_topic_ids': [], 'planning_record_ids': []}

    def answer(self, tools=None):
        return self.chat._model_consultation_messages(self.session, self.option, self.session['model_plan'], 'r1', None,
                                                      self.basis, time.monotonic() + 30, self.session['request_spec'], tools)

    def assess(self):
        result = {'candidates': [], 'matched_candidate_count': 0}
        return self.chat._model_answer_messages(self.session, self.option, self.session['model_plan'], result, basis=self.basis,
                                                allow_next_lookup=True, previous_attempts=[], execution_observation={})

    @staticmethod
    def size(messages, contract):
        return len(generation_spec(contract)['system']) + sum(len(m['content']) for m in messages)

    def test_two_maximum_extracts_fit_the_company_ai_and_appear_once(self):
        self.install(['가' * 40000, '나' * 40000])
        answer, assessment = self.answer(), self.assess()
        self.assertLessEqual(self.size(answer, 'dialogue_answer.v1'), input_limit(self.option))
        self.assertLessEqual(self.size(assessment, 'dialogue_response.v1'), input_limit(self.option))
        combined = '\n'.join(m['content'] for m in answer)
        self.assertEqual(combined.count('가' * 16000), 1)  # the body once (cut to the budget), not again in the grounding
        self.assertIn('앞 16000자만 포함했습니다(전체 40000자)', combined)
        self.assertIn('앞 8000자만 포함했습니다', '\n'.join(m['content'] for m in assessment))

    def test_server_validation_sources_are_untouched_and_the_tool_path_keeps_previews(self):
        self.install(['가' * 40000, '나' * 13872])
        before = json.dumps(self.sources, ensure_ascii=False)
        self.answer(); self.assess()
        self.assertEqual(json.dumps(self.sources, ensure_ascii=False), before)
        self.assertEqual([len(t) for t in self.sources[0]['source_texts']], [40000, 13872])
        with_tools = json.dumps(self.answer(tools=[]), ensure_ascii=False)
        self.assertIn('preview_only_use_attachment_tools_for_further_reading', with_tools)
        self.assertNotIn('나' * 13872, with_tools)

    def test_the_operator_pc_keeps_its_limit(self):
        self.option = {'id': 'bridge', 'provider': 'bridge', 'vision': False}
        self.install(['가' * 40000, '나' * 13872])
        self.assertLessEqual(self.size(self.answer(), 'dialogue_answer.v1'), 60000)
        self.assertLessEqual(self.size(self.assess(), 'dialogue_response.v1'), 60000)


if __name__ == '__main__':
    unittest.main()
