"""Attachment bodies on the unscoped (operator-PC Gemma) path.

Reported 2026-09-26: a 5-page Korean paper (13,872 extracted chars) failed with
"대화와 생성 계약이 모델 입력 범위를 넘었습니다" because the plan input carried the
body twice (conversation message and source_turns). Bodies now appear once, share a
budget newest first, and a cut body says so instead of failing the turn.
"""
import base64
import tempfile
from types import SimpleNamespace
import unittest

from rndplz.attachment_context import source_previews


def conversation():
    from rndplz.conversation import Conversation
    from rndplz.engine import Engine
    from rndplz.models import ExternalModel
    from rndplz.service import Service

    directory = tempfile.TemporaryDirectory(prefix='rndplz-attach-')
    corpus = SimpleNamespace(people={}, records={}, by_person={}, topics=[], topic_by_id={}, questions=[], errors=[])
    service = Service(Engine(corpus), directory.name + '/state',
                      ExternalModel({'RNDPLZ_PROVIDER': 'none', 'RNDPLZ_MODEL_CALL_LIMIT': '0'}), state_env={})
    return directory, Conversation(service, SimpleNamespace())


class AttachmentBudgetTests(unittest.TestCase):
    def setUp(self):
        self.directory, self.chat = conversation()
        self.addCleanup(self.directory.cleanup)

    def attach(self, name, text):
        return self.chat.attachments.upload({'name': name, 'data': base64.b64encode(text.encode('utf-8')).decode()})['id']

    def session(self, *turns):
        return {'messages': [{'role': 'user', 'text': text, 'attachments': [{'id': i} for i in ids]} for text, ids in turns]}

    def body(self, content):
        return content.split('[첨부 본문]\n', 1)[1].split('\n[첨부 끝]', 1)[0]

    def test_single_paper_is_kept_whole_without_a_note(self):
        first = self.attach('paper.txt', '가' * 13872)
        messages = self.chat.model_messages(self.session(('이 논문을 함께 공부할 동료를 찾고 있어', [first])), {'vision': False})
        self.assertEqual(len(self.body(messages[0]['content'])), 13872)
        self.assertNotIn('만 포함했습니다', messages[0]['content'])

    def test_bodies_share_the_budget_newest_first(self):
        older = self.attach('older.txt', '가' * 15000)
        newer = self.attach('newer.txt', '나' * 15000)
        messages = self.chat.model_messages(self.session(('첫 자료', [older]), ('두 번째 자료', [newer])), {'vision': False})
        self.assertEqual(len(self.body(messages[1]['content'])), 15000)
        self.assertEqual(len(self.body(messages[0]['content'])), 28000 - 15000)
        self.assertIn('앞 13000자만 포함했습니다(전체 15000자)', messages[0]['content'])
        self.assertLessEqual(sum(len(m['content']) for m in messages), 36000)

    def test_assessment_budget_is_smaller(self):
        first = self.attach('paper.txt', '가' * 13872)
        messages = self.chat.model_messages(self.session(('자료', [first])), {'vision': False}, attachment_budget=8000)
        self.assertEqual(len(self.body(messages[0]['content'])), 8000)
        self.assertIn('앞 8000자만 포함했습니다(전체 13872자)', messages[0]['content'])

    def test_reader_tool_preview_is_unchanged(self):
        first = self.attach('paper.txt', '가' * 13872)
        messages = self.chat.model_messages(self.session(('자료', [first])), {'vision': False}, attachment_preview=True)
        self.assertEqual(len(self.body(messages[0]['content'])), 600)
        self.assertIn('첨부 읽기 도구', messages[0]['content'])

    def test_plan_context_preview_points_to_the_conversation_copy(self):
        sources = [{'turn_id': 't1', 'source_texts': ['가' * 13872],
                    'source_attachments': [{'name': 'paper.pdf', 'positions': {'basis': 'offsets'}}]}]
        preview = source_previews(sources, reading_scope='preview_here_full_text_in_conversation_message')
        self.assertEqual(len(preview[0]['source_texts'][0]), 600)
        self.assertEqual(preview[0]['attachment_reading_scope'], 'preview_here_full_text_in_conversation_message')
        self.assertNotIn('positions', preview[0]['source_attachments'][0])
        self.assertEqual(len(sources[0]['source_texts'][0]), 13872)
        self.assertEqual(source_previews(sources)[0]['attachment_reading_scope'],
                         'preview_only_use_attachment_tools_for_further_reading')


if __name__ == '__main__':
    unittest.main()
