"""합성 대화로 안내 버튼의 실제 상태와 단계별 검증 오류를 확인한다."""
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
import uuid

from rndplz.conversation import Conversation
from rndplz.domain import Contribution, Person, Record
from rndplz.engine import Engine
from rndplz.models import ExternalModel
from rndplz.scout_projection import project_session
from rndplz.service import Service


PLAN_ERROR = '모델의 검색 계획을 확인하지 못했어요. 요청을 다시 확인해 주세요.'
ANSWER_ERROR = '답변을 확인하는 중 문제가 생겨 보여 드리지 않았어요. 다시 시도해 주세요.'
BUTTON = '이 정보로 수소문하기'


def synthetic_corpus():
    person = Person('P-BATCH-C', 'Synthetic Researcher', org='합성 연구소',
                    profile={'curated': True, 'display_name': '연구가람', 'aliases': ['연구가람']})
    topic = {'id': 'T-BATCH-C', 'name': '증류', 'field': 'process_engineering', 'keywords': ['증류']}
    record = Record(id='R-BATCH-C', kind='career_record', title='증류 공정 개발',
                    text='증류 공정 개발과 실험을 수행한 합성 경력 기록.', date='2020',
                    people=[Contribution(person_id=person.id, name=person.name, role='recorded_role')],
                    tags=[topic['id']], field=topic['field'], scope='self_reported',
                    source_system='synthetic_fixture', source_id='R-BATCH-C', source_url='',
                    checked_at='2026-10-09', evidence_kind='career_experience')
    return SimpleNamespace(people={person.id: person}, records={record.id: record},
                           by_person={person.id: [record]}, topics=[topic],
                           topic_by_id={topic['id']: topic}, questions=[], errors=[])


class ScriptedModels:
    def __init__(self, *, guide=False, reject_plan=False):
        self.guide, self.reject_plan = guide, reject_plan
        self.contracts = []

    def get(self, identifier):
        return {'id': identifier, 'name': '합성 안내', 'provider': 'guide' if self.guide else 'fixture',
                'enabled': True, 'vision': False}

    def catalog(self, refresh=False):
        return {'models': [self.get('synthetic')], 'default': 'synthetic'}

    def stream(self, identifier, messages, *, contract=None):
        self.contracts.append(contract)
        if self.guide:
            raise AssertionError('안내 모드의 이름·주제 조회에는 모델을 호출하지 않는다.')
        if contract in ('dialogue_plan.v2', 'dialogue_plan.v2+think'):
            yield json.dumps({'request_effect': 'update', 'decision': 'answer', 'scope': None,
                              'brief': {'requested_help': [], 'open_questions': []},
                              'summary': '일반적인 연구 설명',
                              'reply': '연구가람 님이 있어요.' if self.reject_plan else '연구 방법을 설명할게요.',
                              'attachment_actions': []}, ensure_ascii=False)
        elif contract == 'dialogue_answer.v1':
            yield '연구가람 님이 있어요.'
        else:
            raise AssertionError('예상하지 못한 계약: ' + str(contract))


class BatchCConversationTests(unittest.TestCase):
    def conversation(self, **options):
        temporary = tempfile.TemporaryDirectory(prefix='batch-c-chat-', dir=Path(__file__).resolve().parents[1])
        self.addCleanup(temporary.cleanup)
        models = ScriptedModels(**options)
        service = Service(Engine(synthetic_corpus()), Path(temporary.name) / 'state',
                          ExternalModel({'RNDPLZ_PROVIDER': 'none', 'RNDPLZ_MODEL_CALL_LIMIT': '0'}), state_env={})
        return Conversation(service, models), models

    def turn(self, chat, text, sid=None):
        payload = {'text': text, 'model_id': 'synthetic', 'turn_id': uuid.uuid4().hex,
                   'model_selection_origin': 'explicit', 'attachments': []}
        if sid:
            payload['session_id'] = sid
        events = list(chat.stream(payload))
        stored = chat.service.store.read()['sessions'][-1]
        message = next(row for row in reversed(stored['messages']) if row['role'] == 'assistant')
        return events, stored, message, project_session(stored)

    def test_guide_name_lookup_has_no_button_instruction_or_current_brief(self):
        chat, models = self.conversation(guide=True)
        events, stored, message, shown = self.turn(chat, '연구가람의 경력을 찾아주세요.')
        self.assertEqual(message['status'], 'complete')
        self.assertEqual(stored['search_context']['kind'], 'person_lookup')
        self.assertNotIn(BUTTON, message['text'])
        self.assertIn('찾고 싶은 분야나 필요한 도움을 더 적어', message['text'])
        self.assertFalse((shown.get('discovery') or {}).get('lookup_ready'))
        self.assertFalse(shown['request_spec']['has_content'])
        self.assertNotIn(BUTTON, ''.join(event.get('text', '') for event in events))
        self.assertEqual(models.contracts, [])

    def test_guide_topic_lookup_keeps_instruction_with_current_nonempty_brief(self):
        chat, models = self.conversation(guide=True)
        _, stored, _, _ = self.turn(chat, '증류 공정 개발 전문가를 찾아주세요.')
        events, stored, message, shown = self.turn(chat, '이 정보로 수소문해 주세요.', stored['id'])
        self.assertEqual(message['status'], 'complete')
        self.assertEqual(stored['search_context']['kind'], 'recommend')
        self.assertIn(BUTTON, message['text'])
        self.assertTrue(shown['discovery']['lookup_ready'])
        self.assertTrue(shown['request_spec']['has_content'])
        self.assertEqual(shown['request_spec']['state'], 'current')
        self.assertEqual(shown['request_spec']['revision'], shown['discovery']['revision'])
        self.assertEqual(shown['scout']['revision'], shown['discovery']['revision'])
        self.assertIsNone(shown['pending'])
        self.assertIn(BUTTON, ''.join(event.get('text', '') for event in events))
        self.assertEqual(models.contracts, [])

    def test_consultation_rejection_names_answer_stage_and_keeps_diagnostic_reason(self):
        chat, models = self.conversation()
        events, _, message, shown = self.turn(chat, '연구 방법을 설명해 주세요.')
        self.assertEqual((message['status'], message['error']), ('error', ANSWER_ERROR))
        self.assertEqual(events[-1]['error'], ANSWER_ERROR)
        self.assertEqual(shown['messages'][-1]['error'], ANSWER_ERROR)
        self.assertNotIn('연구가람', ''.join(event.get('text', '') for event in events))
        self.assertEqual(message['model_consultation_attempts'][0]['reason'], 'consultation_identity_disclosure')
        self.assertEqual(message['model_plan_attempts'][0]['validation'], 'accepted')
        self.assertIn('dialogue_answer.v1', models.contracts)

    def test_plan_rejection_keeps_plan_stage_message_and_diagnostic_reason(self):
        chat, models = self.conversation(reject_plan=True)
        events, _, message, shown = self.turn(chat, '연구 방법을 설명해 주세요.')
        self.assertEqual((message['status'], message['error']), ('error', PLAN_ERROR))
        self.assertEqual(events[-1]['error'], PLAN_ERROR)
        self.assertEqual(shown['messages'][-1]['error'], PLAN_ERROR)
        self.assertEqual(message['model_plan_attempts'][0]['reason'], 'consultation_identity_disclosure')
        self.assertNotIn('dialogue_answer.v1', models.contracts)


if __name__ == '__main__':
    unittest.main()
