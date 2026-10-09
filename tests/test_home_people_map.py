"""The home's small map preserves the full map's public presentation and order."""
from types import SimpleNamespace

import pytest

from rndplz.data import Corpus
from rndplz.demo_pool import project_corpus
from rndplz.domain import Person
from rndplz.engine import Engine
from rndplz.people_map import build_home_people_map, build_people_map
from rndplz.public_profiles import APPROVED_PERSON_IDS, restrict_personal_publication


def home_projection(full):
    """Project the existing API contract, independently of the home builder."""
    people = []
    for person in full['people']:
        profile = person['profile']
        projected = {}
        if 'display_name' in profile:
            projected['display_name'] = profile['display_name']
        if 'path' in (profile.get('portrait') or {}):
            projected['portrait'] = {'path': profile['portrait']['path']}
        people.append({'id': person['id'], 'name': person['name'], 'profile': projected})
    return {
        'schema_version': 'people-map-home-v1',
        'people': people,
        'capabilities': [
            {'id': category['id'], 'people': [{'id': link['id']} for link in category['people']]}
            for category in full['capabilities']
        ],
    }


@pytest.mark.parametrize('approved', [None, (), APPROVED_PERSON_IDS])
def test_home_matches_full_map_projection_with_same_scope_and_order(approved):
    corpus = Corpus()
    if approved is not None:
        restrict_personal_publication(corpus, approved)
    engine = Engine(project_corpus(corpus, allow_personal_omission=True))
    full = build_people_map(engine)
    home = build_home_people_map(engine)
    # List equality covers person order, paths, names, fields and all field links.
    assert home == home_projection(full)
    assert full['schema_version'] == 'people-map-existing-v1'
    assert full['complete'] is True
    assert all('evidence' in person for person in full['people'])
    if approved == ():
        assert not any(person['id'].startswith('LOCAL-') for person in home['people'])
        assert not any(link['id'].startswith('LOCAL-')
                       for category in home['capabilities'] for link in category['people'])


def test_home_keeps_name_fallback_and_curated_publication_boundary():
    people = [
        Person(id='first', name='Latin Name', profile={
            'curated': True, 'display_name': '한글 이름',
            'portrait': {'path': '/portraits/first.png', 'background': '/private.png'},
            'biography': 'Detailed biography', 'csrf_token': 'never publish',
        }),
        Person(id='second', name='Fallback Name', profile={'curated': True}),
        Person(id='third', name='Public Name', profile={
            'display_name': 'Uncurated Name', 'portrait': {'path': '/portraits/third.png'},
        }),
    ]
    corpus = SimpleNamespace(people={person.id: person for person in people},
                             by_person={}, records={}, topic_by_id={})
    # No explain_record method: the home path must not build detailed evidence.
    engine = SimpleNamespace(corpus=corpus)
    home = build_home_people_map(engine)
    assert home['people'] == [
        {'id': 'first', 'name': 'Latin Name', 'profile': {
            'display_name': '한글 이름', 'portrait': {'path': '/portraits/first.png'},
        }},
        {'id': 'second', 'name': 'Fallback Name', 'profile': {}},
        {'id': 'third', 'name': 'Public Name', 'profile': {}},
    ]
    assert home['capabilities'] == []
    # Fresh requests see edits to the same scoped card, without a stale data cache.
    people[0].profile['display_name'] = '변경 이름'
    people[0].profile['portrait']['path'] = '/portraits/changed.jpg'
    updated = build_home_people_map(engine)
    assert updated['people'][0]['profile'] == {
        'display_name': '변경 이름', 'portrait': {'path': '/portraits/changed.jpg'},
    }
    assert home['people'][0]['profile']['portrait']['path'] == '/portraits/first.png'
