"""Deterministic, read-only agent tools over the public web corpus.

No PublicApp, Service, account store or model client is constructed here.
Each process keeps at most one corpus per publication configuration; callers
receive independent JSON values, never mutable corpus/profile references.
"""
from __future__ import annotations

import copy
from datetime import datetime, timezone
from functools import lru_cache
import json
import os
from pathlib import Path
import re

from .demo_pool import proposal_boundary
from .engine import MODE
from .people_map import build_capabilities
from .person_cards import PersonCards
from .public_read import (AVAILABILITY_NOTE, SOURCE_NOTE, build_public_engine,
                          person_payload, picked_candidate, record_payload, render_draft)

SCHEMA_VERSION = '1.0'
HANDOFF = '사람이 수소문 화면에서 근거와 초안을 확인·발송해 주세요. 이 도구는 발송하거나 제안함에 저장하지 않습니다.'


@lru_cache(maxsize=1)
def _pool_version():
    return json.loads(Path(__file__).with_name('demo_pool.json').read_text(encoding='utf-8'))['version']


def _envelope(status='ok', *, pool_version=None, **payload):
    from .engine import PUBLIC_RESEARCH_NOTE
    return {'schema_version': SCHEMA_VERSION,
            'pool_version': _pool_version() if pool_version is None else pool_version,
            'generated_at': datetime.now(timezone.utc).isoformat(),
            'notices': {'source': SOURCE_NOTE, 'availability': AVAILABILITY_NOTE,
                        'collaboration': PUBLIC_RESEARCH_NOTE},
            'status': status, **copy.deepcopy(payload)}


def error_response(code, message):
    """Errors deliberately do not echo IDs, query text, paths or exception details."""
    return _envelope('error', error={'code': code, 'message': message})


def _text(value, limit=20000, *, empty=False):
    if not isinstance(value, str) or len(value) > limit or (not empty and not value.strip()):
        raise ValueError('invalid_argument')
    return value.strip()


def _display_name(person):
    """The Korean-first name priority of the shared person-view displayName."""
    profile = person.get('profile') or {}
    values = [profile.get('display_name'), person.get('display_name'),
              profile.get('name_ko'), person.get('name_ko'), person.get('name')]
    names = [value.strip() for value in values if isinstance(value, str) and value.strip()]
    return next((value for value in names if re.search('[가-힣]', value)), names[0] if names else '이름 미확인')


def _evidence(row):
    # Keep the web's record classification, source and limitation together.
    return {**row, 'year': (re.search(r'\b(?:19|20)\d{2}\b', row.get('date', '')) or [''])[0]}


class AgentTools:
    def __init__(self, env=None):
        self.engine = build_public_engine(dict(os.environ if env is None else env))
        self.corpus = self.engine.corpus
        self.cards = PersonCards(self.corpus)
        self._capabilities = build_capabilities(self.corpus)

    def _response(self, status='ok', **payload):
        return _envelope(status, pool_version=self.corpus.demo_pool['version'], **payload)

    def find_people(self, query, limit=5):
        try:
            query = _text(query)
            if type(limit) is not int or not 1 <= limit <= 50:
                raise ValueError('invalid_argument')
        except ValueError:
            return error_response('invalid_argument', '질문은 1~20000자, 결과 수는 1~50 정수로 입력해 주세요.')
        result = self.engine.recommend(query, limit=limit)
        people = []
        for candidate in result['candidates'][:limit]:
            person = self.corpus.people[candidate['id']]
            people.append({'id': person.id, 'display_name': _display_name(candidate),
                           'name': candidate['name'], 'aliases': candidate['profile'].get('aliases', []),
                           'organization': candidate['org'], 'field': candidate['role'],
                           'reason': candidate['reason'],
                           'evidence': [_evidence(row) for row in candidate['evidence']],
                           'proposal_allowed': candidate['proposal_allowed'],
                           'proposal_unavailable_reason': candidate['proposal_unavailable_reason']})
        clarification = self.engine.clarify(query, result['mode'], 1)
        status = ('needs_clarification' if clarification else 'ok') if people else 'no_results'
        return self._response(status, people=people, mode=result['mode'],
                              clarification=clarification, message=result['empty_message'],
                              closest_topics=result['closest_topics'])

    def get_person(self, person_id):
        try:
            person_id = _text(person_id, 300)
        except ValueError:
            return error_response('invalid_argument', '인물 ID를 입력해 주세요.')
        if person_id not in self.corpus.people:
            return error_response('not_found', '인물 기록을 찾을 수 없습니다.')
        person = person_payload(self.engine, person_id)
        profile = person['profile']
        # Non-curated raw author profiles are not published by the web card.
        if profile.get('curated'):
            values = self.cards.values(person_id)
            fields, careers = values['fields'], values['careers']
        else:
            fields, careers = {}, []
        skills = list(dict.fromkeys(fields.get('skills', '').splitlines()))
        person.update(display_name=_display_name(person), aliases=profile.get('aliases', []),
                      organization=fields.get('organization') or person['org'],
                      role=fields.get('role', ''), bio=fields.get('bio', ''),
                      skills=skills or person['profile_topics'],
                      interests=fields.get('interests', '').splitlines(), careers=careers,
                      projects=profile.get('projects', []), sources=profile.get('sources', []))
        return self._response(person=person)

    def get_record(self, record_id):
        try:
            record_id = _text(record_id, 300)
        except ValueError:
            return error_response('invalid_argument', '근거 기록 ID를 입력해 주세요.')
        if record_id not in self.corpus.records:
            return error_response('not_found', '기록을 찾을 수 없습니다.')
        return self._response(record=record_payload(self.engine, record_id))

    def list_capabilities(self):
        return self._response(capabilities=[{'id': row['id'], 'name': row['label'],
                                            'people_count': len(row['people'])}
                                           for row in self._capabilities])

    def people_for_capability(self, capability_id):
        try:
            capability_id = _text(capability_id, 300)
        except ValueError:
            return error_response('invalid_argument', '역량 ID를 입력해 주세요.')
        capability = next((row for row in self._capabilities if row['id'] == capability_id), None)
        if capability is None:
            return error_response('not_found', '역량을 찾을 수 없습니다.')
        people = []
        for link in capability['people']:
            person = person_payload(self.engine, link['id'])
            people.append({'id': person['id'], 'display_name': _display_name(person),
                           'evidence_count': len(link['recordIds'])})
        return self._response(capability={'id': capability['id'], 'name': capability['label']}, people=people)

    def draft_request(self, person_ids, need, requester_note=''):
        try:
            need, requester_note = _text(need), _text(requester_note, empty=True)
            if not isinstance(person_ids, list) or not 1 <= len(person_ids) <= 7:
                raise ValueError('invalid_argument')
            person_ids = [_text(value, 300) for value in person_ids]
            if len(set(person_ids)) != len(person_ids):
                raise ValueError('invalid_argument')
        except ValueError:
            return error_response('invalid_argument', '중복 없는 수신 인물 1~7명과 요청 내용을 입력해 주세요. 요청·메모는 각각 20000자 이내입니다.')
        if any(pid not in self.corpus.people for pid in person_ids):
            return error_response('not_found', '인물 기록을 찾을 수 없습니다.')
        mode = self.engine.mode_for(need)
        session = {'id': 'agent-preview', 'original': need, 'mode': mode,
                   'slots': {'target': '', 'conditions': '', 'resources': requester_note,
                             'deadline': '', 'goal': need}}
        # Exactly Service.refresh's deterministic query and its default candidate limit.
        query = need + ' ' + ' '.join(str(v) for v in session['slots'].values() if v and str(v) not in need)
        session['result'] = self.engine.recommend(query, mode)
        drafts = []
        for pid in person_ids:
            candidate = next((row for row in session['result']['candidates'] if row['id'] == pid), None)
            if candidate is None:
                try:
                    candidate = picked_candidate(self.engine, session, pid)
                except ValueError as exc:
                    return error_response('draft_unavailable', str(exc))
            reason = proposal_boundary(self.corpus, pid, candidate['evidence'])
            if reason:
                return error_response('draft_unavailable', reason)
            draft = render_draft(self.corpus, session, candidate)
            name = draft['candidate']['profile']['display_name']
            drafts.append({'person_id': pid, 'display_name': name,
                           'title': f'{name}님께 {MODE[mode]} 의뢰',
                           'body': draft['body'], 'evidence': draft['evidence']})
        return self._response(drafts=drafts, handoff=HANDOFF)


@lru_cache(maxsize=1)
def _cached_tools(publish_personal, public_person_ids):
    return AgentTools({'RNDPLZ_PUBLISH_PERSONAL': publish_personal,
                       'RNDPLZ_PUBLIC_PERSON_IDS': public_person_ids})


def _call(method, *args, **kwargs):
    try:
        tools = _cached_tools(os.environ.get('RNDPLZ_PUBLISH_PERSONAL', ''),
                              os.environ.get('RNDPLZ_PUBLIC_PERSON_IDS', ''))
    except (ValueError, OSError, KeyError):
        return error_response('configuration_error', '공개 자료 또는 공개 범위 설정을 확인해 주세요.')
    return getattr(tools, method)(*args, **kwargs)


def find_people(query, limit=5):
    return _call('find_people', query, limit)


def get_person(person_id):
    return _call('get_person', person_id)


def get_record(record_id):
    return _call('get_record', record_id)


def list_capabilities():
    return _call('list_capabilities')


def people_for_capability(capability_id):
    return _call('people_for_capability', capability_id)


def draft_request(person_ids, need, requester_note=''):
    return _call('draft_request', person_ids, need, requester_note)
