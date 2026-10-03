"""The consultation tells the user what its lookup found instead of only asking questions.

Observed with gemma4:e4b on 2026-09-30: "윤활유 마찰 마모 테스트를 누구에게 의뢰해야 해?" matched
three registered people on the first turn, but the answers kept asking questions for eight
turns, the query drifted to "마찰학" (no record says that), and "정다솔한테 의뢰할까?" was
answered with "I cannot check that person". A replay also failed turns on a quote copied
without a space and on an empty group beside a names-only lookup. Runs through the actual
Conversation/Service; only the model is scripted.
"""
import inspect
import json
import tempfile
import unittest
from unittest.mock import patch
import uuid
from types import SimpleNamespace

from rndplz.domain import Contribution, Person, Record
from rndplz.evidence_search import _stem_hits
from rndplz.scout_projection import project_session

ASK = '윤활유 마찰 마모 테스트를 누구에게 의뢰해야 해?'
NAMED = '정다솔한테 의뢰할까?'
SLIP = '정다솔에게 윤활유 마찰 마모 테스트를 맡겨도 될까?'
WHO = '윤활유 마찰 마모 관련 테스트를 의뢰하고 싶은데 누구에게 해야해?'
WHAT = '윤활유 마찰 계수가 뭐야?'
WHO_OFFER = '윤활유 마찰 테스트를 해 본 전문가를 추천해 줘'
FOLLOW = '정다솔 님께 맡겨도 될까?'
OLIGO = '에틸렌 oligomerization 연구 전문가를 찾아줘'
BILINGUAL = '윤활유 lubricant 전문가를 찾아줘'
ANSWER = '테스트 목적을 조금 더 알려 주실 수 있을까요?'
NARROW = '조금 더 알려 주시면 더 맞는 분으로 좁혀 드리고, 바로 보시려면 ‘이 정보로 수소문하기’를 눌러 주세요.'
CARD_LINE = '정다솔 님은 수소문에 등록된 분이에요 — GS칼텍스 · 윤활유기술개발팀 · 산업용 윤활유 개발 경험. 아래에서 이력을 바로 볼 수 있어요.'


def record(rid, pid, name, title, text):
    return Record(id=rid, kind='career_record', title=title, text=text, date='2020',
                  people=[Contribution(person_id=pid, name=name, role='recorded_role')], tags=[],
                  field='process_engineering', scope='self_reported', source_system='user_provided_resume',
                  source_id=rid, source_url='', checked_at='2026-09-30', evidence_kind='career_experience')


def corpus():
    people = {
        'P-DS': Person(id='P-DS', name='Dasol Jung', org='GS칼텍스 · 윤활유기술개발팀',
                       profile={'curated': True, 'display_name': '정다솔', 'aliases': ['정다솔', 'Dasol Jung'],
                                'tagline': '산업용 윤활유 개발 경험'}),
        'P-HS': Person(id='P-HS', name='Hugh Spikes', org='Imperial College London'),
        'P-CAT': Person(id='P-CAT', name='Catalyst Person', org='GS'),
        'P-HY': Person(id='P-HY', name='Yoon-Ki Hong', org='GS칼텍스'),
    }
    records = {
        'R-LUBE': record('R-LUBE', 'P-DS', 'Dasol Jung', '산업용 윤활유 제품 개발', '산업용 윤활유 제품 개발과 시장 대응.'),
        'R-TRIB': record('R-TRIB', 'P-HS', 'Hugh Spikes', '경계 윤활에서의 마찰 조정제', '마찰과 마모를 줄이는 첨가제의 거동.'),
        'R-CAT': record('R-CAT', 'P-CAT', 'Catalyst Person', '촉매 반응기 설계', '고정층 촉매 반응기 설계와 실험.'),
        'R-OLIGO': record('R-OLIGO', 'P-HY', 'Yoon-Ki Hong', '올레핀 올리고머화 방법', '올레핀 올리고머화 촉매계.'),
    }
    by_person = {}
    for row in records.values():
        for contribution in row.people:
            by_person.setdefault(contribution.person_id, []).append(row)
    return SimpleNamespace(people=people, records=records, by_person=by_person, topics=[],
                           topic_by_id={}, questions=[], errors=[])


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


def plan(decision, turn, quote, queries, names=()):
    return {'request_effect': 'update', 'decision': decision,
            'scope': {'purposes': [{'source_turn_id': turn, 'source_quote': quote, 'text': '윤활유 마찰 마모 테스트 의뢰'}],
                      'interpretations': [{'label': '윤활유 마찰 마모', 'groups': [{'topic_ids': [], 'queries': list(queries)}]}],
                      'record_ids': [], 'person_names': list(names), 'conditions': []},
            'brief': {'requested_help': [{'source_turn_id': turn, 'source_quote': quote, 'text': '테스트를 맡을 사람 찾기'}],
                      'open_questions': []},
            'summary': '윤활유 마찰 마모 테스트를 맡을 사람', 'reply': '조회해 볼게요.', 'attachment_actions': []}


PLANS = {
    ASK: lambda turn: plan('lookup', turn, ASK, ['윤활유', '마찰']),
    # the drifted field name of the observed session
    NAMED: lambda turn: plan('clarify', turn, NAMED, ['마찰학']),
    # a quote copied without a space, and an empty group beside the name
    SLIP: lambda turn: plan('clarify', turn, SLIP.replace('마찰 마모', '마찰마모'), [], names=['정다솔']),
    # questions only, without any search scope (about one in four e4b first turns)
    WHO: lambda turn: plan('clarify', turn, WHO, []),
    WHAT: lambda turn: plan('clarify', turn, WHAT, []),
    # questions first, with a search scope the model only offers
    WHO_OFFER: lambda turn: plan('clarify', turn, WHO_OFFER, ['윤활유']),
    # a follow-up question: preserve, but the request is copied into scope and brief on both attempts
    FOLLOW: lambda turn: {**plan('answer', turn, FOLLOW, ['윤활유', '마찰']), 'request_effect': 'preserve'},
    # a mixed-language phrase that no record has
    OLIGO: lambda turn: plan('lookup', turn, OLIGO, ['에틸렌 oligomerization']),
    # the same word in two languages; the records have only the Korean one
    BILINGUAL: lambda turn: plan('lookup', turn, BILINGUAL, ['윤활유', 'lubricant']),
}


class ScriptedModels:
    def __init__(self):
        self.answer_inputs = []

    def get(self, identifier):
        return {'id': identifier, 'name': 'Scripted', 'provider': 'fixture', 'enabled': True, 'vision': False}

    def catalog(self, refresh=False):
        return {'models': [self.get('scripted')], 'default': 'scripted'}

    def stream(self, identifier, messages, *, contract=None):
        # A repair attempt asks for the same contract with thinking ("+think").
        if contract in ('dialogue_plan.v2', 'dialogue_plan.v2+think'):
            source = source_turns(messages)[-1]
            yield json.dumps(PLANS[source['input_text']](source['turn_id']), ensure_ascii=False)
        elif contract == 'dialogue_refine.v1':
            self.refine_inputs = getattr(self, 'refine_inputs', []) + [messages[-1]['content']]
            yield json.dumps({'decision': 'execute', 'interpretations': [
                {'label': '올리고머화', 'groups': [{'topic_ids': [], 'queries': ['올리고머화', 'oligomerization']}]}]}, ensure_ascii=False)
        elif contract == 'dialogue_answer.v1':
            self.answer_inputs.append('\n'.join(row.get('content', '') for row in messages))
            yield ANSWER
        else:
            raise AssertionError('unexpected contract ' + str(contract))


class ConsultationFindingsTests(unittest.TestCase):
    def converse(self, texts):
        from rndplz.conversation import Conversation
        from rndplz.engine import Engine
        from rndplz.models import ExternalModel
        from rndplz.service import Service

        temporary = tempfile.TemporaryDirectory(prefix='rndplz-findings-')
        self.addCleanup(temporary.cleanup)
        self.models = ScriptedModels()
        service = Service(Engine(corpus()), temporary.name + '/state',
                          ExternalModel({'RNDPLZ_PROVIDER': 'none', 'RNDPLZ_MODEL_CALL_LIMIT': '0'}), state_env={})
        chat = Conversation(service, self.models)
        sid, snapshots = None, []
        for text in texts:
            payload = {'text': text, 'model_id': 'scripted', 'turn_id': uuid.uuid4().hex,
                       'model_selection_origin': 'explicit', 'attachments': []}
            if sid:
                payload['session_id'] = sid
            list(chat.stream(payload))
            sid = sid or service.store.read()['sessions'][-1]['id']
            stored = next(row for row in service.store.read()['sessions'] if row['id'] == sid)
            snapshots.append((next(m for m in reversed(stored['messages']) if m['role'] == 'assistant'),
                              dict(stored['scout']), project_session(stored)))
        self.service, self.sid = service, sid
        return snapshots

    def test_a_lookup_the_user_asked_for_says_how_many_and_keeps_narrowing(self):
        # 2026-10-02: the scout no longer starts by itself; the answer asks one narrowing question
        # and the server says how many candidates the current conditions have.
        (message, scout, shown), = self.converse([ASK])
        self.assertEqual(message['status'], 'complete')
        self.assertEqual(message['text'], ANSWER + '\n\n지금 조건에 맞는 기록이 있는 후보가 2명이에요. ' + NARROW)
        self.assertEqual(len(self.models.answer_inputs), 1)
        self.assertIn('"anonymous_record_linked_people_count": 2', self.models.answer_inputs[0])
        self.assertEqual((scout['count'], scout.get('auto'), scout['disclosed']), (2, None, False))
        self.assertNotIn('auto', shown['scout'])
        self.assertNotIn('정다솔', json.dumps(shown, ensure_ascii=False))

    def test_a_named_registered_person_is_recognised_and_a_drifted_query_still_finds_records(self):
        _, (message, scout, shown) = self.converse([ASK, NAMED])
        self.assertEqual(message['status'], 'complete')
        self.assertEqual(message['text'], ANSWER + '\n\n' + CARD_LINE +
                         '\n\n지금 조건에 맞는 기록이 있는 후보가 1명이에요. ' + NARROW)
        self.assertEqual(message['mentions'], [{'id': 'P-DS', 'name': '정다솔'}])
        self.assertEqual(scout['count'], 1)  # "마찰학" matched "마찰" by its stem
        self.assertNotIn('auto', shown['scout'])
        self.assertEqual(shown['messages'][-1]['mentions'], [{'id': 'P-DS', 'name': '정다솔'}])
        self.assertEqual(len(self.models.answer_inputs), 2)
        self.assertIn('"mentioned_registered_people"', self.models.answer_inputs[1])
        self.assertIn('산업용 윤활유 제품 개발', self.models.answer_inputs[1])

    def test_a_squeezed_quote_and_an_empty_group_do_not_fail_the_turn(self):
        (message, scout, _), = self.converse([SLIP])
        self.assertEqual((message['status'], message['error']), ('complete', ''))
        self.assertEqual(message['text'], ANSWER + '\n\n' + CARD_LINE +
                         '\n\n지금 조건에 맞는 기록이 있는 후보가 1명이에요. ' + NARROW)
        self.assertEqual(scout['count'], 1)  # the names-only lookup found the named person

    def test_a_who_question_planned_as_questions_only_still_looks_up_its_topic_words(self):
        (message, scout, shown), = self.converse([WHO])
        self.assertEqual(message['model_plan']['interpretations'], [
            {'label': '사람을 묻는 말의 주제어', 'groups': [{'topic_ids': [], 'queries': ['윤활유', '마찰', '마모']}]}])
        self.assertTrue(message['text'].endswith('후보가 2명이에요. ' + NARROW))
        self.assertEqual((scout['count'], scout.get('auto'), shown['scout'].get('auto')), (2, None, None))
        self.assertEqual(len(self.models.answer_inputs), 1)

    def test_a_who_question_with_an_offered_scope_runs_the_lookup(self):
        (message, scout, _), = self.converse([WHO_OFFER])
        self.assertEqual((message['model_plan']['intent'], message['model_plan']['lookup_action']), ('search', 'execute'))
        self.assertEqual((scout['count'], scout.get('auto'), len(self.models.answer_inputs)), (1, None, 1))

    def test_a_preserve_that_restates_the_request_is_answered_not_failed(self):
        (_, before, _), (message, scout, _) = self.converse([ASK, FOLLOW])
        self.assertEqual((message['status'], message['error']), ('complete', ''))
        self.assertEqual([a['validation'] for a in message['model_plan_attempts']], ['rejected', 'accepted'])
        self.assertEqual(message['text'], ANSWER + '\n\n' + CARD_LINE)
        self.assertEqual(scout['count'], before['count'])  # the accepted request and its lookup are kept

    def test_a_lookup_that_matched_nobody_is_rewritten_with_the_records_words(self):
        (message, scout, _), = self.converse([OLIGO])
        self.assertIn('올리고머화', self.models.refine_inputs[0])  # every title's words reach the rewrite
        self.assertEqual(message['model_plan']['interpretations'][0]['groups'][0]['queries'], ['올리고머화', 'oligomerization'])
        self.assertEqual([a['phase'] for a in message['model_plan_attempts']], ['interpret', 'refine'])
        self.assertEqual(scout['count'], 1)
        self.assertTrue(message['text'].endswith('후보가 1명이에요. ' + NARROW))

    def test_a_translation_beside_a_matching_word_spends_no_rewrite(self):
        (message, scout, _), = self.converse([BILINGUAL])
        self.assertEqual([a['phase'] for a in message['model_plan_attempts']], ['interpret'])
        self.assertFalse(hasattr(self.models, 'refine_inputs'))
        self.assertEqual(scout['count'], 1)

    def test_a_closing_choice_line_becomes_buttons_and_leaves_the_answer(self):
        # The answer may end with one multiple-choice question; it is stored as choices, not text,
        # and the server's candidate-count notice still follows the answer.
        from rndplz.model_dialogue import split_choice_block
        self.assertEqual(split_choice_block('본문\n[선택] 이유는? | 안정성 | 규격 | 친환경'),
                         ('본문', {'question': '이유는?', 'options': ['안정성', '규격', '친환경']}))
        self.assertEqual(split_choice_block('본문\n[선택] 이유는? | 하나뿐'), ('본문\n[선택] 이유는? | 하나뿐', None))
        self.assertEqual(split_choice_block('[선택] 질문만 | 가 | 나'), ('', {'question': '질문만', 'options': ['가', '나']}))
        original = ScriptedModels.stream

        def with_choice(models, identifier, messages, *, contract=None):
            for piece in original(models, identifier, messages, contract=contract):
                yield piece
            if contract == 'dialogue_answer.v1':
                yield '\n\n[선택] 시험의 목적은? | 첨가제 선정 | 제품 규격 확인 | 고장 원인 분석'

        with patch.object(ScriptedModels, 'stream', with_choice):
            (message, scout, shown), = self.converse([ASK])
        self.assertEqual(message['text'], ANSWER + '\n\n지금 조건에 맞는 기록이 있는 후보가 2명이에요. ' + NARROW)
        self.assertEqual(message['choices'], {'question': '시험의 목적은?', 'options': ['첨가제 선정', '제품 규격 확인', '고장 원인 분석']})
        self.assertEqual(shown['messages'][-1]['choices'], message['choices'])

    def test_a_disallowed_next_lookup_does_not_fail_the_scout(self):
        # 2026-10-04, hosted (Gemini flash): the assessment carried a next_lookup the server had not
        # allowed; the scout failed twice and the button then said to send a new message.
        from rndplz.conversation import Conversation
        original = ScriptedModels.stream
        responses = []

        def exposed_ids(messages):
            ids = []
            for row in messages:
                for line in row.get('content', '').splitlines():
                    if line.startswith('{') and 'retrieved_materials' in line:
                        try:
                            ids += [m['id'] for m in json.loads(line).get('retrieved_materials', [])]
                        except ValueError:
                            pass
            return ids

        def with_response(models, identifier, messages, *, contract=None):
            if contract == 'dialogue_response.v1':
                script = responses[0]  # a function of the exposed materials, or a fixed response
                value = script(exposed_ids(messages)) if callable(script) else script
                yield json.dumps(value, ensure_ascii=False)
                return
            yield from original(models, identifier, messages, contract=contract)

        def prepare(chat, sid):
            session = next(s for s in chat.service.store.read()['sessions'] if s['id'] == sid)
            value = chat.prepare({'session_id': sid, 'discovery_revision': session['model_plan_revision']})
            if inspect.isgenerator(value):
                for _ in value:
                    pass
            return next(s for s in chat.service.store.read()['sessions'] if s['id'] == sid)

        def insufficient(ids):
            return {'assessments': [{'person_id': pid, 'relation': 'insufficient', 'text': '근거가 부족합니다.',
                                     'evidence': [], 'missing': '윤활유 시험 수행 기록이 없음'} for pid in ids],
                    'reply': '아직 근거가 부족합니다.',
                    'next_lookup': {'interpretations': [{'label': '재조회', 'groups': [{'topic_ids': [], 'queries': ['마모']}]}], 'record_ids': []}}
        # After an all-insufficient pass the server asks once more over the same materials, without a lookup.
        with patch.object(ScriptedModels, 'stream', with_response):
            responses[:] = [insufficient]
            (message, scout, _), = self.converse([ASK])
            chat = Conversation(self.service, self.models)
            after = prepare(chat, self.sid)
            self.assertEqual((after['scout']['status'], after['scout']['disclosed']), ('complete', True))
            self.assertIsNone(after['messages'][-1].get('next_lookup'))
            # A validation failure keeps the request (plan, revision, count) instead of wiping it; the
            # turn's call ledger (4) is spent by then, so the button reports the budget, not a stale request.
            responses[:] = [{'assessments': [{'person_id': 'NOBODY', 'relation': 'insufficient', 'text': 'x', 'evidence': [], 'missing': 'x'}],
                             'reply': 'x', 'next_lookup': None}]
            (message, scout, _), = self.converse([ASK])
            chat = Conversation(self.service, self.models)
            with self.assertRaises(ValueError):  # the failure reaches the button
                prepare(chat, self.sid)
            failed = next(s for s in self.service.store.read()['sessions'] if s['id'] == self.sid)
            self.assertEqual(failed['messages'][-1]['status'], 'error')
            self.assertIsNotNone(failed['model_plan'])
            self.assertEqual((failed['model_plan_revision'], failed['scout']['count']), (message['scout_revision'], 2))
            self.assertFalse(failed['discovery']['lookup_ready'])  # the ledger, not a lost request
            from rndplz.model_conversation import ModelResponseBudgetExhausted
            with self.assertRaises(ModelResponseBudgetExhausted):
                prepare(chat, self.sid)

    def test_a_question_about_a_topic_is_not_turned_into_a_lookup(self):
        (message, scout, shown), = self.converse([WHAT])
        self.assertEqual((message['text'], message['model_plan']['interpretations']), (ANSWER, []))
        self.assertEqual((scout['count'], scout.get('auto'), len(self.models.answer_inputs)), (None, None, 1))

    def test_stem_fallback_is_only_for_a_single_long_hangul_term(self):
        records = corpus().records
        self.assertEqual([(rid, hit['match_mode'], hit['relaxed_term']) for rid, hit in _stem_hits('마찰학', records)],
                         [('R-TRIB', 'term_stem', '마찰')])
        for query in ('마찰', 'Tribology', '마찰학 시험', '촉매'):
            self.assertEqual(_stem_hits(query, records), [])


if __name__ == '__main__':
    unittest.main()
