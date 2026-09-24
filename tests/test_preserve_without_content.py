"""A second greeting whose plan says preserve while adding an open question.

Observed with gemma4:e4b on 2026-09-24 (think=false evaluation, and as a repaired
first attempt with the default): after "안녕하세요." the reply to "안녕" came back as
request_effect=preserve with an open question. The earlier greeting left a request
without content, so there was nothing to preserve and the turn failed after repair.
Runs through the actual Conversation/Service/StateStore; only the model is scripted.
"""
import copy
import json
import tempfile
from types import SimpleNamespace
import unittest
import uuid

EMPTY_SCOPE = {'purposes': [], 'interpretations': [], 'record_ids': [], 'person_names': [], 'conditions': []}
FOLLOW_UP = '특별히 궁금하신 점이나 오늘 논의하고 싶은 주제가 있으신가요?'


def source_turns(messages):
    for row in messages:
        for line in row.get('content', '').splitlines():
            if line.startswith('{'):
                try:
                    value = json.loads(line)
                except ValueError:
                    continue
                if isinstance(value, dict) and 'current_turn_id' in value and 'source_turns' in value:
                    return value['source_turns']
    raise AssertionError('source turns not found in the model request')


class ScriptedModels:
    def __init__(self, plans):
        self.plans = plans
        self.calls = []

    def get(self, identifier):
        return {'id': identifier, 'name': 'Scripted', 'provider': 'fixture', 'enabled': True, 'vision': False}

    def catalog(self, refresh=False):
        return {'models': [self.get('scripted')], 'default': 'scripted'}

    def stream(self, identifier, messages, *, contract=None):
        self.calls.append(contract)
        if contract == 'dialogue_plan.v2':
            source = source_turns(messages)[-1]
            attempt = sum(c == 'dialogue_plan.v2' for c in self.calls)
            yield json.dumps(self.plans(source['input_text'], source['turn_id'], attempt), ensure_ascii=False)
        elif contract == 'dialogue_answer.v1':
            yield '무엇을 도와드릴까요?'
        else:
            raise AssertionError('unexpected contract ' + str(contract))


def plan(effect, *, help_items=(), questions=(), summary='인사'):
    return {'request_effect': effect, 'decision': 'answer', 'scope': copy.deepcopy(EMPTY_SCOPE),
            'brief': {'requested_help': list(help_items), 'open_questions': list(questions)},
            'summary': summary, 'reply': '안녕하세요.', 'attachment_actions': []}


class PreserveWithoutContentTests(unittest.TestCase):
    def converse(self, plans, texts):
        from rndplz.conversation import Conversation
        from rndplz.engine import Engine
        from rndplz.models import ExternalModel
        from rndplz.service import Service

        temporary = tempfile.TemporaryDirectory(prefix='rndplz-preserve-')
        self.addCleanup(temporary.cleanup)
        corpus = SimpleNamespace(people={}, records={}, by_person={}, topics=[], topic_by_id={}, questions=[], errors=[])
        models = ScriptedModels(plans)
        service = Service(Engine(corpus), temporary.name + '/state',
                          ExternalModel({'RNDPLZ_PROVIDER': 'none', 'RNDPLZ_MODEL_CALL_LIMIT': '0'}), state_env={})
        chat = Conversation(service, models)
        sid, statuses = None, []
        for text in texts:
            payload = {'text': text, 'model_id': 'scripted', 'turn_id': uuid.uuid4().hex,
                       'model_selection_origin': 'explicit', 'attachments': []}
            if sid:
                payload['session_id'] = sid
            list(chat.stream(payload))
            sid = sid or service.store.read()['sessions'][-1]['id']
            stored = next(row for row in service.store.read()['sessions'] if row['id'] == sid)
            statuses.append(next(m for m in reversed(stored['messages']) if m['role'] == 'assistant').get('status'))
        return statuses, models.calls, stored

    def test_second_greeting_preserve_with_question_completes_without_repair(self):
        def plans(text, turn, attempt):
            if text == '안녕하세요.':
                return plan('update', questions=['어떤 주제로 이야기할까요?'])
            return plan('preserve', questions=[FOLLOW_UP], summary='다시 인사')

        statuses, calls, stored = self.converse(plans, ['안녕하세요.', '안녕'])
        self.assertEqual(statuses, ['complete', 'complete'])
        self.assertEqual(calls.count('dialogue_plan.v2'), 2)
        self.assertIs(stored['request_spec']['has_content'], False)

    def test_request_with_content_still_rejects_preserve_with_changes(self):
        seed = '증류 경험이 있는 분을 찾고 싶어요.'

        def plans(text, turn, attempt):
            if text == seed:
                return plan('update', help_items=[{'text': '증류 경험', 'source_turn_id': turn, 'source_quote': '증류 경험'}],
                            summary='증류 경험')
            if attempt == 2:
                return plan('preserve', questions=[FOLLOW_UP], summary='다시 인사')
            return plan('preserve', summary='다시 인사')

        statuses, calls, stored = self.converse(plans, [seed, '고마워요'])
        self.assertEqual(statuses, ['complete', 'complete'])
        # The first preserve adds a question to a request with content: rejected, then repaired.
        self.assertEqual(calls.count('dialogue_plan.v2'), 3)
        self.assertEqual(stored['request_spec']['requested_help'][0]['text'], '증류 경험')
        self.assertEqual(stored['request_spec']['open_questions'], [])


if __name__ == '__main__':
    unittest.main()
