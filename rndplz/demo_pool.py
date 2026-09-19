"""Explicit current demo selection; archives and stored results stay intact."""
from __future__ import annotations

import copy
import json
from pathlib import Path


def project_corpus(corpus, *, allow_personal_omission=False, manifest=None):
    """Create a current-search view without modifying the loaded source corpus."""
    policy = copy.deepcopy(manifest) if manifest is not None else json.loads(
        Path(__file__).with_name('demo_pool.json').read_text(encoding='utf-8'))
    ids, record_ids = policy['person_ids'], policy['record_ids']
    if (not isinstance(ids, list) or not isinstance(record_ids, list) or
        any(not isinstance(value, str) or not value for value in ids + record_ids)):
        raise ValueError('현재 시연 명단의 식별자 목록 형식을 확인해 주세요.')
    if policy.get('schema_version') != 1 or len(ids) != len(set(ids)) or len(record_ids) != len(set(record_ids)):
        raise ValueError('현재 시연 명단의 식별자 구성을 확인해 주세요.')
    if set(ids) & set(policy.get('excluded_person_ids', [])):
        raise ValueError('제외한 인물이 현재 명단에 포함돼 있습니다.')
    missing_people = set(ids) - set(corpus.people)
    permitted = set(policy.get('personal_person_ids', [])) if allow_personal_omission else set()
    if missing_people - permitted:
        raise ValueError('현재 시연 명단의 인물 원자료가 누락됐습니다.')
    # Only the public personal-data filter may omit these explicitly named records.
    permitted_records = set(policy.get('personal_record_ids', [])) if allow_personal_omission else set()
    if (set(record_ids) - set(corpus.records)) - permitted_records:
        raise ValueError('현재 시연 명단의 근거 원자료가 누락됐습니다.')
    view = copy.copy(corpus)
    view.people = {pid: corpus.people[pid] for pid in ids if pid in corpus.people}
    view.records = {rid: corpus.records[rid] for rid in record_ids if rid in corpus.records}
    view.by_person = {pid: [] for pid in view.people}
    for record in view.records.values():
        for contribution in record.people:
            if contribution.person_id in view.by_person:
                view.by_person[contribution.person_id].append(record)
    active_tags = {tag for record in view.records.values() for tag in record.tags}
    view.topics = [topic for topic in corpus.topics if topic['id'] in active_tags]
    view.topic_by_id = {topic['id']: topic for topic in view.topics}
    if active_tags - set(view.topic_by_id):
        raise ValueError('현재 근거의 주제 정의가 누락됐습니다.')
    view.demo_pool = policy
    return view


def historical_person(person):
    profile = person.profile or {}
    status = profile.get('current_status') or {}
    return (profile.get('affiliation_status') == 'deceased' or
            isinstance(status, dict) and status.get('category') == 'deceased' or
            profile.get('display_type') == 'historical_researcher')


def proposal_boundary(corpus, person_id, evidence):
    """Validate both the recipient and every selected historical evidence ID."""
    if not getattr(corpus, 'demo_pool', None):
        return None
    person = corpus.people.get(person_id)
    if person is None:
        return '현재 시연 명단 밖 인물입니다. 당시 결과는 보관되며, 새 질문으로 현재 근거를 찾아 주세요.'
    if historical_person(person):
        return '역사적 연구 자료를 열람하는 인물입니다. 자료 기반 질문은 준비할 수 있지만 자문 수신자로 제안할 수 없습니다.'
    if not isinstance(evidence, list) or not evidence:
        return '현재 시연 범위의 연결 근거를 다시 선택해 주세요.'
    for item in evidence:
        record = corpus.records.get(item.get('id')) if isinstance(item, dict) else None
        if record is None or not any(c.person_id == person_id for c in record.people):
            return '저장 당시 근거에 현재 시연 범위 밖 기록이 포함돼 있습니다. 원문은 보관되며, 새 질문으로 근거를 다시 찾아 주세요.'
    return None


def require_proposal_boundary(corpus, person_id, evidence):
    reason = proposal_boundary(corpus, person_id, evidence)
    if reason:
        raise ValueError(reason)


def present_session(session, corpus):
    """Annotate a response copy; do not migrate or rewrite stored conversations."""
    shaped = copy.deepcopy(session)
    policy = getattr(corpus, 'demo_pool', None)
    if not shaped or not policy or not isinstance(shaped.get('result'), dict):
        return shaped
    result = shaped['result']
    result['historical_result'] = result.get('pool_version') != policy['version']
    result['current_pool_version'] = policy['version']
    inactive = []
    for candidate in result.get('candidates', []):
        candidate['in_current_pool'] = candidate.get('id') in corpus.people
        for item in candidate.get('evidence', []):
            record = corpus.records.get(item.get('id'))
            item['in_current_pool'] = bool(record and any(c.person_id == candidate.get('id') for c in record.people))
        reason = proposal_boundary(corpus, candidate.get('id'), candidate.get('evidence'))
        candidate['proposal_allowed'] = not reason and not candidate.get('lookup_only', False)
        candidate['proposal_unavailable_reason'] = reason or ''
        if not candidate['in_current_pool']:
            inactive.append(candidate.get('id'))
    result['inactive_candidate_ids'] = inactive
    for choice in result.get('choices', []):
        choice['in_current_pool'] = choice.get('id') in corpus.people
    result['scope_note'] = ('저장 당시의 결과입니다. 현재 시연 범위와 다른 인물·근거는 새 제안에 사용할 수 없습니다.'
                            if result['historical_result'] else policy.get('note', ''))
    for author in result.get('author_strip', []):
        author['profile_available'] = author.get('id') in corpus.people
    if result.get('candidates') and not any(c.get('proposal_allowed') for c in result['candidates']):
        shaped['can_propose'] = False
    return shaped
