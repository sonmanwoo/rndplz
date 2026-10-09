"""합성 인물만으로 초안, 경로별 편지, 제안함의 표시명을 확인한다."""
import copy
from types import SimpleNamespace

import pytest

from rndplz.domain import Person
from rndplz.engine import Engine
from rndplz.models import ExternalModel
from rndplz.service import Service


@pytest.fixture
def draft_service(tmp_path):
    people = {
        'P-DISPLAY': Person('P-DISPLAY', 'Synthetic Researcher',
                            profile={'display_name': '시험 연구자'}),
        'P-RECORD': Person('P-RECORD', 'Recorded Researcher'),
        'P-BLANK': Person('P-BLANK', 'Blank Profile Researcher',
                          profile={'display_name': '  '}),
    }
    corpus = SimpleNamespace(people=people, records={}, by_person={}, topics=[],
                             topic_by_id={}, questions=[])
    service = Service(Engine(corpus), tmp_path / 'state',
                      ExternalModel({'RNDPLZ_PROVIDER': 'none', 'RNDPLZ_MODEL_CALL_LIMIT': '0'}),
                      state_env={'RNDPLZ_STATE_BACKEND': 'file'})
    candidates = [
        {'id': person.id, 'name': person.name, 'virtual': False,
         'evidence': [{'id': 'R-' + person.id, 'title': '시험 기록',
                       'date': '2026', 'virtual': False}]}
        for person in people.values()
    ]
    base = {'id': 'names', 'original': '시험 자문', 'mode': 'advice', 'asker': 'lab',
            'ready': True, 'messages': [],
            'slots': {'target': '', 'conditions': '', 'resources': '', 'deadline': '', 'goal': ''},
            'result': {'topic_ids': [], 'claims': [], 'candidates': candidates}}
    route = copy.deepcopy(base)
    route.update(id='route', mode='resource_request')
    for index, candidate in enumerate(route['result']['candidates'], 1):
        candidate.update(route_order=index, route_total=len(candidates), route_role='시험 경로')
    service.store.transaction(lambda state: state['sessions'].extend([base, route]))
    return service


@pytest.mark.parametrize(('pid', 'name'), [
    ('P-DISPLAY', '시험 연구자'),
    ('P-RECORD', 'Recorded Researcher'),
    ('P-BLANK', 'Blank Profile Researcher'),
])
def test_draft_candidate_and_greeting_use_corpus_display_name(draft_service, pid, name):
    before = draft_service.store.read()['sessions']
    draft = draft_service.draft('names', pid)
    assert draft['candidate']['profile']['display_name'] == name
    assert draft['body'].startswith(name + '님께,\n')
    # 표시용 응답을 만들면서 저장된 후보나 코퍼스를 바꾸지 않는다.
    assert draft_service.store.read()['sessions'] == before
    assert draft['candidate']['name'] == draft_service.corpus.people[pid].name


def test_route_letters_and_saved_recipient_names_share_display_rule(draft_service):
    expected = {'P-DISPLAY': '시험 연구자', 'P-RECORD': 'Recorded Researcher',
                'P-BLANK': 'Blank Profile Researcher'}
    for pid, name in expected.items():
        draft = draft_service.draft('route', pid)
        assert draft['candidate']['profile']['display_name'] == name
        assert '\n\n' + name + '님께,\n' in draft['body']
        assert draft['candidate']['route_total'] == 3
    proposals = draft_service.save_proposal({
        'session_id': 'route', 'candidate_ids': list(expected),
        'state': 'draft', 'idempotency_key': 'synthetic-route',
    })
    assert {p['recipient_id']: p['recipient_name'] for p in proposals} == expected
    for proposal in proposals:
        assert '\n\n' + expected[proposal['recipient_id']] + '님께,\n' in proposal['body']


def test_prepared_draft_preview_keeps_display_name(draft_service, monkeypatch):
    import rndplz.scout_projection

    monkeypatch.setattr(rndplz.scout_projection, 'project_session', lambda session: session)
    prepared = draft_service.session('names')
    prepared.update(can_propose=True, scout={'revision': 'r1', 'disclosed': True},
                    discovery={'revision': 'r1'}, prepared_discovery_revision='r1')
    for candidate in prepared['result']['candidates']:
        candidate['proposal_allowed'] = True
    response = draft_service.prepared_draft_response(prepared)
    preview = response['draft_previews']['items'][0]
    assert preview['candidate']['name'] == 'Synthetic Researcher'
    assert preview['candidate']['profile']['display_name'] == '시험 연구자'
    assert preview['body'].startswith('시험 연구자님께,\n')
