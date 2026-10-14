"""A proposal letter reads like a note from a colleague, not a form (2026-10-14).

The request part is the company AI's paragraph when it was written for this exact brief, checked for
prose and for numbers or contacts the brief never gave; otherwise the brief is laid out plainly. The
paragraph is written beside the lookup and saved on the conversation.
"""
import copy
import json
from types import SimpleNamespace

import pytest

from rndplz.domain import Person
from rndplz.engine import Engine
from rndplz.models import ExternalModel
from rndplz.public_web import PublicApp
from rndplz.request_letter import ASK, LetterError, letter_key, parse_letter, rule_text
from rndplz.service import Service


def row(text, quote='증류 효율을 높이고 싶어. 컬럼 안으로 액체가 끓어 올라.', **extra):
    return {'text': text, 'source_quote': quote, 'source_turn_id': 't1', **extra}


SPEC = {'summary': '증류 분리 효율 개선과 컬럼 내부 액체 상승 진단',
        'purposes': [row('증류 분리 효율 개선'), row('컬럼 내부 액체 상승 현상 진단')],
        'requested_help': [row('액체 상승 원인 진단 자문')],
        'conditions': [row('증류 실험 경험', kind='required'), row('C5 유분 경험', kind='preferred')],
        'open_questions': ['실험 규모'], 'has_content': True, 'revision': 'r1', 'source_turn_id': 't1'}
WRITTEN = ('증류 분리 효율을 높이려고 실험하고 있는데, 실험 중에 컬럼 안으로 액체가 끓어오르는 현상을 보았습니다.\n\n'
           '이 현상이 왜 생기는지 짚어 볼 점을 여쭙고 싶습니다.')


def raw(body):
    return json.dumps({'body': body}, ensure_ascii=False)


def test_written_paragraph_is_checked_as_prose_from_the_brief():
    assert parse_letter(raw(WRITTEN + '\n\n\n'), SPEC, 'advice') == WRITTEN
    # The ask's own numbers (15분) and the brief's (C5) may appear; a new one may not.
    assert parse_letter(raw(WRITTEN + ' C5 유분도 15분 정도면 됩니다.'), SPEC, 'advice')
    for body, reason in ((WRITTEN + ' 300도에서 생깁니다.', 'letter_new_number'),
                         (WRITTEN + ' https://example.com', 'letter_contact'),
                         (WRITTEN + ' kim@example.com', 'letter_contact'),
                         (WRITTEN + '\n- 원인 진단', 'letter_form'),
                         ('[의뢰 요약]\n' + WRITTEN, 'letter_form'),
                         ('짧습니다.', 'letter_length')):
        with pytest.raises(LetterError, match=reason):
            parse_letter(raw(body), SPEC, 'advice')
    for value in ('not json', json.dumps({'body': WRITTEN, 'extra': 1}), json.dumps({'body': 3})):
        with pytest.raises(LetterError):
            parse_letter(value, SPEC, 'advice')


def test_paragraph_belongs_to_one_brief_and_kind():
    changed = copy.deepcopy(SPEC)
    changed['requested_help'][0]['text'] = '다른 도움'
    assert letter_key(SPEC, 'advice') != letter_key(changed, 'advice')
    assert letter_key(SPEC, 'advice') != letter_key(SPEC, 'member')
    # Delivery metadata of the brief is not part of the letter.
    assert letter_key(SPEC, 'advice') == letter_key({**SPEC, 'revision': 'r2'}, 'advice')


def test_rule_text_lays_the_brief_out_without_form_fillers():
    text = rule_text(SPEC)
    assert text.startswith('지금 이런 일을 하고 있습니다.\n- 증류 분리 효율 개선\n- 컬럼 내부 액체 상승 현상 진단')
    assert '여쭙고 싶은 것은 이렇습니다.\n- 액체 상승 원인 진단 자문' in text
    assert '꼭 필요한 조건\n- 증류 실험 경험' in text and '있으면 좋은 조건\n- C5 유분 경험' in text
    assert '아직 정하지 못한 것\n- 실험 규모' in text
    assert '[' not in text and '미기재' not in text
    empty = {**SPEC, 'conditions': [], 'open_questions': [], 'requested_help': []}
    assert rule_text(empty) == '지금 이런 일을 하고 있습니다.\n- 증류 분리 효율 개선\n- 컬럼 내부 액체 상승 현상 진단'


@pytest.fixture
def service(tmp_path):
    people = {'P-MW': Person('P-MW', 'Manwoo Son', profile={'display_name': '손만우'}),
              'P-SITE': Person('P-SITE', 'Site Desk', virtual=True)}
    corpus = SimpleNamespace(people=people, records={}, by_person={}, topics=[], topic_by_id={}, questions=[])
    service = Service(Engine(corpus), tmp_path / 'state',
                      ExternalModel({'RNDPLZ_PROVIDER': 'none', 'RNDPLZ_MODEL_CALL_LIMIT': '0'}),
                      state_env={'RNDPLZ_STATE_BACKEND': 'file'})
    evidence = [{'id': 'R-1', 'title': '모노머 공정 증류 실험', 'date': '2020', 'virtual': False},
                {'id': 'R-2', 'title': '추출 공정 모델링', 'date': '', 'virtual': False}]
    session = {'id': 's1', 'kind': 'chat', 'original': '증류 효율', 'mode': 'advice', 'asker': 'lab', 'ready': True,
               'messages': [], 'model_id': 'aiu', 'request_spec': copy.deepcopy(SPEC), 'discovery': {'lookup_ready': True},
               'slots': {'target': '', 'conditions': '', 'resources': '', 'deadline': '', 'goal': ''},
               'result': {'topic_ids': [], 'claims': ['AI가 제안한 주장'], 'candidates': [
                   {'id': 'P-MW', 'name': 'Manwoo Son', 'virtual': False, 'evidence': evidence, 'purpose_relation': 'adjacent'},
                   {'id': 'P-SITE', 'name': 'Site Desk', 'virtual': True,
                    'evidence': [{'id': 'R-3', 'title': '현장 가상 기록', 'date': '2026', 'virtual': True}]}]}}
    service.store.transaction(lambda state: state['sessions'].append(session))
    return service


def test_letter_is_a_note_with_the_rule_text_until_a_paragraph_fits(service):
    body = service.draft('s1', 'P-MW')['body']
    assert body.startswith('손만우님, 안녕하세요.\n\n수소문에서 손만우님의 「모노머 공정 증류 실험」 외 1건의 기록을 보고 연락드립니다.'
                           ' 이번 일과 같은 분야는 아닐 수 있지만')
    assert rule_text(SPEC) in body
    assert ASK['advice'] + ' 일정은 손만우님 편하신 때에 맞추겠습니다.' in body
    assert body.endswith('바쁘신 중에 읽어 주셔서 감사합니다.\n— 시연 제안자\n\n참고한 기록\n- 모노머 공정 증류 실험 (2020)\n- 추출 공정 모델링')
    for filler in ('[막힌 현상]', '[목표]', '추가 협의', '미기재', '님께,'):
        assert filler not in body

    def write(text, key):
        def update(state):
            state['sessions'][0]['request_letter'] = {'key': key, 'body': text}
        service.store.transaction(update)

    write(WRITTEN, letter_key(SPEC, 'advice'))
    body = service.draft('s1', 'P-MW')['body']
    assert WRITTEN in body and rule_text(SPEC) not in body
    # A paragraph written for another brief is not used.
    write(WRITTEN, letter_key({**SPEC, 'summary': '다른 요청'}, 'advice'))
    assert rule_text(SPEC) in service.draft('s1', 'P-MW')['body']


def test_required_marks_survive_the_letter(service):
    def to_verify(state):
        state['sessions'][0]['mode'] = 'verify'
    service.store.transaction(to_verify)
    body = service.draft('s1', 'P-MW')['body']
    assert '검증 대상' in body and '> AI가 제안한 주장' in body
    assert ASK['verify'] in body
    site = service.draft('s1', 'P-SITE')['body']
    assert site.startswith('[시연용 가상 현장 기록에 기반한 제안]\n\nSite Desk님, 안녕하세요.')
    assert '- 현장 가상 기록 (2026) · 가상 현장 기록' in site
    saved = service.save_proposal({'session_id': 's1', 'candidate_ids': ['P-MW', 'P-SITE'], 'state': 'draft',
                                   'idempotency_key': 'k1'})
    assert len(saved) == 2


class Models:
    """The public model list with a company AI option; stream returns what the test sets."""
    def __init__(self, provider='aiu', reply=raw(WRITTEN)):
        self.provider, self.reply, self.calls = provider, reply, []

    def get(self, identifier):
        return {'id': identifier, 'provider': self.provider}

    def catalog(self):
        return {'models': [{'id': 'aiu', 'provider': 'aiu', 'enabled': True}, {'id': 'aiu:deep', 'provider': 'aiu', 'enabled': True}]}

    def stream(self, identifier, messages, *, contract=None):
        self.calls.append((identifier, contract, messages.generation_deadline is not None))
        yield self.reply


def letter_job(service, models):
    return PublicApp._request_letter(SimpleNamespace(models=models), service, 's1')


def test_paragraph_is_written_beside_the_lookup_and_saved(service):
    models = Models()
    finish = letter_job(service, models)
    prepared = {'id': 's1'}
    finish(prepared)
    key = letter_key(SPEC, 'advice')
    assert prepared['request_letter'] == {'key': key, 'body': WRITTEN}
    assert service.store.read()['sessions'][0]['request_letter'] == {'key': key, 'body': WRITTEN}
    assert models.calls == [('aiu', 'request_letter.v1', True)]
    assert WRITTEN in service.draft('s1', 'P-MW')['body']
    # Written once per brief.
    assert letter_job(service, models) is None


def test_deep_choice_uses_the_fast_app(service):
    def deep(state):
        state['sessions'][0]['model_id'] = 'aiu:deep'
    service.store.transaction(deep)
    models = Models()
    letter_job(service, models)({})
    assert models.calls[0][0] == 'aiu'


@pytest.mark.parametrize('models', [Models(provider='bridge'), Models(provider='guide')])
def test_other_models_keep_the_rule_text(service, models):
    assert letter_job(service, models) is None
    assert models.calls == []


def test_failed_or_unusable_paragraph_keeps_the_rule_text(service):
    for reply in ('not json', raw('짧음'), raw(WRITTEN + ' 010-1234-5678')):
        prepared = {}
        letter_job(service, Models(reply=reply))(prepared)
        assert 'request_letter' not in prepared
        assert 'request_letter' not in service.store.read()['sessions'][0]
    assert rule_text(SPEC) in service.draft('s1', 'P-MW')['body']


def test_brief_changed_while_writing_is_not_overwritten(service):
    class Changing(Models):
        def stream(self, identifier, messages, *, contract=None):
            def change(state):
                state['sessions'][0]['request_spec']['summary'] = '대화 중 바뀐 요청'
            service.store.transaction(change)
            yield self.reply
    prepared = {}
    letter_job(service, Changing())(prepared)
    assert 'request_letter' not in service.store.read()['sessions'][0]
    assert 'request_letter' not in prepared


def test_no_run_for_a_conversation_that_cannot_look_up_yet(service):
    def not_ready(state):
        state['sessions'][0]['discovery'] = {'lookup_ready': False}
    service.store.transaction(not_ready)
    models = Models()
    assert letter_job(service, models) is None
    assert models.calls == []
