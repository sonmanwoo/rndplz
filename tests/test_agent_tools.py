"""도구의 공개 계약과 실제 웹 투영을 비교한다. 서버와 브라우저는 시작하지 않는다."""
import builtins
import copy
import io
import json
import socket
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode

import pytest

from rndplz.agent_tools import AgentTools
from rndplz.data import Corpus
from rndplz.demo_pool import historical_person
from rndplz.models import ExternalModel
from rndplz.people_map import build_capabilities
from rndplz.person_cards import PersonCards
from rndplz.public_profiles import APPROVED_PERSON_IDS
from rndplz.public_web import PublicApp
from rndplz.service import Service


BASE_ENV = {'RNDPLZ_LOCAL_PREVIEW': '1', 'RNDPLZ_SESSION_SECRET': 's' * 64,
            'RNDPLZ_PROVIDER': 'none', 'RNDPLZ_MODEL_CALL_LIMIT': '0'}
QUERY = '연속흐름 반응 공정 설계에 관한 자문이 필요합니다.'
SCOPE_CASES = [
    {},
    {'RNDPLZ_PUBLIC_PERSON_IDS': sorted(APPROVED_PERSON_IDS)[0]},
    {'RNDPLZ_PUBLIC_PERSON_IDS': ','.join(sorted(APPROVED_PERSON_IDS))},
    {'RNDPLZ_PUBLISH_PERSONAL': '1'},
]


def web_json(app, path, identifier=None, cookie=''):
    """실제 WSGI 진입점을 메모리에서 호출한다. 수신 소켓은 없다."""
    environ = {'REQUEST_METHOD': 'GET', 'PATH_INFO': path,
               'QUERY_STRING': urlencode({'id': identifier}) if identifier else '',
               'HTTP_HOST': '127.0.0.1', 'wsgi.url_scheme': 'http',
               'wsgi.input': io.BytesIO(), 'CONTENT_LENGTH': '0', 'HTTP_COOKIE': cookie}
    captured = {}

    def start_response(status, headers):
        captured.update(status=int(status.split()[0]), headers=dict(headers))

    response = app(environ, start_response)
    try:
        raw = b''.join(response)
    finally:
        if hasattr(response, 'close'):
            response.close()
    assert captured['status'] == 200
    return json.loads(raw), captured['headers'].get('Set-Cookie', cookie).split(';', 1)[0]


@pytest.fixture(scope='module')
def tools():
    return AgentTools(env=BASE_ENV)


@pytest.fixture(scope='module')
def full_corpus():
    return Corpus()


def assert_envelope(response, tools):
    assert json.loads(json.dumps(response, ensure_ascii=False)) == response
    assert response['schema_version'] == '1.0'
    assert response['pool_version'] == tools.corpus.demo_pool['version']
    assert datetime.fromisoformat(response['generated_at']).tzinfo is not None
    assert response['status'] in {'ok', 'no_results', 'needs_clarification', 'error'}
    assert isinstance(response['notices'], dict)
    assert any('미확인' in value for value in response['notices'].values())
    assert any('공개' in value for value in response['notices'].values())
    assert 'score_internal' not in json.dumps(response)
    assert 'score' not in response


def assert_error(response, tools):
    assert_envelope(response, tools)
    assert response['status'] == 'error'
    assert isinstance(response['error']['code'], str) and response['error']['code']
    assert isinstance(response['error']['message'], str) and response['error']['message']


def test_find_people_contract_uses_engine_recommend_and_limit(tools, monkeypatch):
    original = tools.engine.recommend
    calls = []

    def observed(*args, **kwargs):
        calls.append((args, kwargs))
        return original(*args, **kwargs)

    monkeypatch.setattr(tools.engine, 'recommend', observed)
    response = tools.find_people(QUERY, limit=2)
    assert_envelope(response, tools)
    assert len(calls) == 1
    assert calls[0][0][0] == QUERY
    expected = original(QUERY, limit=2)
    assert [person['id'] for person in response['people']] == [
        candidate['id'] for candidate in expected['candidates']][:2]
    assert 0 < len(response['people']) <= 2
    for person, candidate in zip(response['people'], expected['candidates']):
        assert {'id', 'display_name', 'name', 'aliases', 'organization', 'field',
                'reason', 'evidence'} <= person.keys()
        assert person['reason'] == candidate['reason']
        assert person['display_name'] == (
            tools.corpus.people[person['id']].profile.get('display_name') or candidate['name'])
        assert person['evidence']
        for record in person['evidence']:
            assert {'id', 'title', 'year', 'kind', 'evidence_label', 'url'} <= record.keys()
            assert record['id'] in tools.corpus.records
            assert record['title'] and isinstance(record['year'], str)
            assert record['kind'] and isinstance(record['url'], str)
            assert any('\uac00' <= character <= '\ud7a3' for character in record['evidence_label'])


def test_empty_and_ambiguous_queries_preserve_web_guidance(tools):
    unknown = tools.find_people('zxqv_없는_연구_987654321')
    assert_envelope(unknown, tools)
    assert unknown['status'] == 'no_results'
    assert unknown['people'] == []
    assert unknown['message'] == tools.engine.recommend('zxqv_없는_연구_987654321')['empty_message']
    ambiguous = tools.find_people('연속흐름')
    assert_envelope(ambiguous, tools)
    assert ambiguous['status'] == 'needs_clarification'
    assert ambiguous['clarification'] == tools.engine.clarify(
        '연속흐름', tools.engine.mode_for('연속흐름'), 1)


def test_capabilities_keep_map_order_and_exact_owned_evidence_counts(tools):
    expected = build_capabilities(tools.corpus)
    response = tools.list_capabilities()
    assert_envelope(response, tools)
    assert response['status'] == 'ok'
    assert response['capabilities'] == [
        {'id': item['id'], 'name': item['label'], 'people_count': len(item['people'])}
        for item in expected]
    for capability in expected:
        result = tools.people_for_capability(capability['id'])
        assert_envelope(result, tools)
        assert result['status'] == 'ok'
        assert result['capability'] == {'id': capability['id'], 'name': capability['label']}
        assert result['people'] == [
            {'id': link['id'], 'display_name': (
                tools.corpus.people[link['id']].profile.get('display_name')
                or tools.corpus.people[link['id']].name),
             'evidence_count': len(link['recordIds'])}
            for link in capability['people']]


@pytest.mark.parametrize('scope_env', SCOPE_CASES,
                         ids=['default', 'one-approved', 'all-approved', 'personal-opt-in'])
def test_scope_matches_actual_web_and_hidden_personal_data_never_leaks(
        scope_env, tmp_path, full_corpus):
    env = {**BASE_ENV, **scope_env}
    tools = AgentTools(env=env)
    app = PublicApp(state_dir=tmp_path / 'web-state', env=env)
    web, cookie = web_json(app, '/api/people-map')
    assert set(tools.corpus.people) == {person['id'] for person in web['people']}
    assert set(tools.corpus.records) == set(app.engine.corpus.records)
    outputs = [tools.find_people(QUERY), tools.list_capabilities()]
    web_public = [web]
    for web_person in web['people']:
        pid = web_person['id']
        response = tools.get_person(pid)
        assert_envelope(response, tools)
        assert response['status'] == 'ok'
        person, cookie = web_json(app, '/api/person', pid, cookie)
        web_public.append(person)
        assert {key: response['person'][key] for key in person} == person
        assert {'display_name', 'aliases', 'organization', 'role', 'bio', 'skills',
                'interests', 'careers', 'projects', 'sources'} <= response['person'].keys()
        outputs.append(response)
    for rid in tools.corpus.records:
        response = tools.get_record(rid)
        assert_envelope(response, tools)
        record, cookie = web_json(app, '/api/record', rid, cookie)
        web_public.append(record)
        assert response['status'] == 'ok'
        assert response['record'] == record
        outputs.append(response)
    for capability in outputs[1]['capabilities']:
        outputs.append(tools.people_for_capability(capability['id']))
    eligible = next(person['id'] for person in outputs[0]['people']
                    if not historical_person(tools.corpus.people[person['id']]))
    draft = tools.draft_request([eligible], QUERY)
    assert_envelope(draft, tools)
    assert draft['status'] == 'ok'
    outputs.append(draft)
    hidden = [person for pid, person in full_corpus.people.items()
              if pid not in tools.corpus.people and person.profile.get('source_type')
              in ('self_reported', 'provided_resume')]
    forbidden = set()
    for person in hidden:
        forbidden.update([person.id, person.name, person.profile.get('display_name', ''),
                          *person.profile.get('aliases', [])])
        outputs.extend([tools.get_person(person.id), tools.find_people(person.name),
                        tools.draft_request([person.id], QUERY)])
    hidden_records = {record.id for record in full_corpus.records.values()
                      if any(contribution.person_id in {person.id for person in hidden}
                             for contribution in record.people)}
    for rid in hidden_records:
        response = tools.get_record(rid)
        assert_error(response, tools)
        outputs.append(response)
    encoded = json.dumps(outputs, ensure_ascii=False)
    # 실제 비공개 값을 실패 메시지에 출력하지 않는다.
    assert not any(value and value in encoded for value in forbidden)
    # 공개 참여자의 웹 프로젝트 카드에 남는 공유 프로젝트 ID 참조는 그대로다.
    # 그 기록 상세는 위에서 차단하며, 웹에 없는 비공개 기록 ID는 내보내지 않는다.
    web_encoded = json.dumps(web_public, ensure_ascii=False)
    assert not any(rid in encoded for rid in hidden_records if rid not in web_encoded)


def test_curated_card_values_are_shared_and_uncurated_profile_is_not_published(tools):
    assert isinstance(tools.cards, PersonCards)
    pid = next(pid for pid, person in tools.corpus.people.items() if person.profile.get('curated'))
    expected = tools.cards.values(pid)
    result = tools.get_person(pid)['person']
    for field in ('organization', 'role', 'bio'):
        assert result[field] == expected['fields'][field]
    assert result['display_name'] == expected['fields']['name']
    assert result['skills'] == (expected['fields']['skills'].splitlines() or result['profile_topics'])
    assert result['interests'] == expected['fields']['interests'].splitlines()
    assert result['careers'] == expected['careers']
    person = tools.corpus.people[pid]
    original = copy.deepcopy(person.profile)
    try:
        person.profile = {'curated': False, 'biography': 'UNPUBLISHED_PROFILE_SENTINEL',
                          'skills': ['UNPUBLISHED_PROFILE_SENTINEL']}
        shaped = tools.get_person(pid)
        assert shaped['person']['profile'] == {}
        assert 'UNPUBLISHED_PROFILE_SENTINEL' not in json.dumps(shaped)
    finally:
        person.profile = original


@pytest.mark.parametrize('note', ['', '검토할 공정도와 운전 자료가 있습니다.'])
@pytest.mark.parametrize('picked', [False, True], ids=['recommended', 'map-pick'])
def test_draft_body_matches_web_template_and_remains_a_human_handoff(tools, tmp_path, note, picked):
    web_service = Service(tools.engine, tmp_path / 'web-state', ExternalModel(env=BASE_ENV),
                          state_env={'RNDPLZ_STATE_BACKEND': 'file'})
    session = web_service.converse({'text': QUERY, 'skip': True, 'slots': {'resources': note}})
    candidates = {candidate['id'] for candidate in session['result']['candidates']}
    if picked:
        pid = next(pid for pid, person in tools.corpus.people.items()
                   if pid not in candidates and not historical_person(person)
                   and tools.corpus.by_person.get(pid))
    else:
        pid = next(pid for pid in candidates if not historical_person(tools.corpus.people[pid]))
    expected = web_service.draft(session['id'], pid, picked=picked)
    before = web_service.store.read()
    response = tools.draft_request([pid], QUERY, requester_note=note)
    assert_envelope(response, tools)
    assert response['status'] == 'ok'
    assert len(response['drafts']) == 1
    draft = response['drafts'][0]
    assert draft['person_id'] == pid
    assert draft['body'] == expected['body']
    assert draft['evidence'] == [
        {key: value for key, value in record.items() if key != 'in_current_pool'}
        for record in expected['evidence']]
    assert draft['title'] and draft['display_name']
    assert draft['body'].startswith(draft['display_name'] + '님께,\n')
    assert '사람' in response['handoff'] and '수소문' in response['handoff']
    assert '확인' in response['handoff'] and '발송' in response['handoff']
    assert web_service.store.read() == before


def test_historical_people_cannot_receive_drafts(tools):
    pid = next(pid for pid, person in tools.corpus.people.items() if historical_person(person))
    response = tools.draft_request([pid], QUERY)
    assert_error(response, tools)
    assert '역사적' in response['error']['message']
    assert not response.get('drafts')


def test_multiple_drafts_preserve_recipient_order_and_fail_as_one_result(tools):
    candidates = tools.find_people(QUERY, limit=7)['people']
    eligible = [person['id'] for person in candidates
                if not historical_person(tools.corpus.people[person['id']])][:2]
    assert len(eligible) == 2
    response = tools.draft_request(eligible, QUERY)
    assert_envelope(response, tools)
    assert response['status'] == 'ok'
    assert [draft['person_id'] for draft in response['drafts']] == eligible
    historical = next(pid for pid, person in tools.corpus.people.items() if historical_person(person))
    failed = tools.draft_request([eligible[0], historical], QUERY)
    assert_error(failed, tools)
    assert not failed.get('drafts')


def test_returned_objects_cannot_mutate_the_cached_public_corpus(tools):
    pid = next(iter(tools.corpus.people))
    first = tools.get_person(pid)
    expected = copy.deepcopy(first['person'])
    first['person']['evidence'].clear()
    first['person']['profile'].clear()
    first['person']['skills'].append('CALLER_MUTATION')
    assert tools.get_person(pid)['person'] == expected
    catalog = tools.list_capabilities()
    original = copy.deepcopy(catalog['capabilities'])
    catalog['capabilities'][0]['people_count'] = -1
    assert tools.list_capabilities()['capabilities'] == original


def test_module_cache_rechecks_publication_environment_and_rejects_invalid_config(monkeypatch):
    import rndplz.agent_tools as module

    monkeypatch.delenv('RNDPLZ_PUBLISH_PERSONAL', raising=False)
    monkeypatch.delenv('RNDPLZ_PUBLIC_PERSON_IDS', raising=False)
    pid = sorted(APPROVED_PERSON_IDS)[0]
    assert module.get_person(pid)['status'] == 'error'
    monkeypatch.setenv('RNDPLZ_PUBLIC_PERSON_IDS', pid)
    assert module.get_person(pid)['status'] == 'ok'
    monkeypatch.delenv('RNDPLZ_PUBLIC_PERSON_IDS')
    assert module.get_person(pid)['status'] == 'error'
    monkeypatch.setenv('RNDPLZ_PUBLIC_PERSON_IDS', 'INVALID_PRIVATE_SETTING')
    error = module.list_capabilities()
    assert error['status'] == 'error'
    assert error['error']['code'] == 'configuration_error'
    assert 'INVALID_PRIVATE_SETTING' not in json.dumps(error)
    monkeypatch.setenv('RNDPLZ_PUBLISH_PERSONAL', '1')
    assert module.get_person(pid)['status'] == 'ok'
    module._cached_tools.cache_clear()


@pytest.mark.parametrize(('method', 'args'), [
    ('find_people', (None,)), ('find_people', (' ',)), ('find_people', ('x' * 20001,)),
    ('find_people', (QUERY, 0)), ('find_people', (QUERY, 51)), ('find_people', (QUERY, True)),
    ('find_people', (QUERY, 1.5)), ('get_person', (None,)), ('get_person', ('x' * 301,)),
    ('get_record', ({},)), ('get_record', ('',)), ('people_for_capability', ([],)),
    ('draft_request', ([], QUERY)), ('draft_request', (['x'] * 8, QUERY)),
    ('draft_request', (['x', 'x'], QUERY)), ('draft_request', ('x', QUERY)),
    ('draft_request', ([None], QUERY)), ('draft_request', (['x'], '')),
    ('draft_request', (['x'], QUERY, 'x' * 20001)),
])
def test_invalid_inputs_are_json_errors_without_echo(tools, method, args):
    response = getattr(tools, method)(*args)
    assert_error(response, tools)
    assert QUERY not in json.dumps(response, ensure_ascii=False)
    assert 'xxx' not in json.dumps(response, ensure_ascii=False)


@pytest.mark.parametrize('method', ['get_person', 'get_record', 'people_for_capability'])
def test_unknown_identifiers_are_not_reflected(tools, method):
    response = getattr(tools, method)('UNPUBLISHED_PRIVATE_IDENTIFIER')
    assert_error(response, tools)
    assert 'UNPUBLISHED_PRIVATE_IDENTIFIER' not in json.dumps(response)


def test_all_tools_are_read_only_without_services_state_or_network(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail('읽기 전용 도구가 상태 생성 또는 외부 호출을 시도했습니다.')

    original_open = builtins.open

    def read_only_open(file, mode='r', *args, **kwargs):
        assert not set(str(mode)) & set('wax+')
        return original_open(file, mode, *args, **kwargs)

    monkeypatch.setattr(PublicApp, '__init__', forbidden)
    monkeypatch.setattr(Service, '__init__', forbidden)
    monkeypatch.setattr(ExternalModel, '__init__', forbidden)
    monkeypatch.setattr(socket, 'create_connection', forbidden)
    monkeypatch.setattr(socket.socket, 'connect', forbidden)
    monkeypatch.setattr(Path, 'mkdir', forbidden)
    monkeypatch.setattr(Path, 'write_text', forbidden)
    monkeypatch.setattr(Path, 'write_bytes', forbidden)
    monkeypatch.setattr(builtins, 'open', read_only_open)
    env = {**BASE_ENV, 'RNDPLZ_STATE_DIR': str(tmp_path / 'must-not-exist')}
    tools = AgentTools(env=env)
    before = copy.deepcopy((tools.corpus.people, tools.corpus.records, tools.corpus.by_person))
    found = tools.find_people(QUERY)
    pid = found['people'][0]['id']
    rid = found['people'][0]['evidence'][0]['id']
    capability = tools.list_capabilities()['capabilities'][0]['id']
    responses = [found, tools.get_person(pid), tools.get_record(rid),
                 tools.people_for_capability(capability), tools.draft_request([pid], QUERY)]
    assert all(response['status'] != 'error' for response in responses)
    assert (tools.corpus.people, tools.corpus.records, tools.corpus.by_person) == before
    assert not list(tmp_path.iterdir())
