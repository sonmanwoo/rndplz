"""Read-only people-map projection of the already scoped service corpus.

Uses the same IDs and explanations as person detail. It does not load new
sources, read visitor state, infer current employment, or invoke a model.
"""
from collections import Counter
from datetime import datetime, timezone

PROFILE_KEYS = {
    'id', 'slug', 'name', 'display_name', 'aliases', 'org', 'org_type', 'curated',
    'source_type', 'tagline', 'biography', 'skills', 'skill_groups', 'interests',
    'timeline', 'projects', 'education', 'sources', 'portrait', 'portrait_note',
    'profile_note', 'featured_work', 'topics', 'award', 'affiliation',
    'affiliation_as_of', 'current_role', 'role', 'field_label', 'research_field',
    'checked_at', 'limit', 'internal_employee', 'employment_verification',
    'collaboration_availability', 'contact_consent', 'retired_or_emeritus',
    'current_status', 'affiliation_status', 'display_type', 'profile_observed_as_of',
}


def build_people_map(engine):
    corpus = engine.corpus
    people, featured, linked = [], [], set()
    for person in corpus.people.values():
        records = corpus.by_person.get(person.id, [])
        evidence = [engine.explain_record(record, next(
            contribution for contribution in record.people
            if contribution.person_id == person.id
        )) for record in records]
        curated = bool(person.profile.get('curated'))
        profile = {key: value for key, value in person.profile.items()
                   if curated and key in PROFILE_KEYS}
        if curated:
            featured.append(person.id)
        if person.virtual:
            org_basis = '가상 현장 기록의 소속 표기'
        elif curated:
            org_basis = '공개된 프로필의 소속 표기 · 현재 재직 확인 아님'
        else:
            org_basis = '기존 OpenAlex 스냅샷의 마지막 알려진 소속 · 현재 재직 확인 아님'
        people.append({
            'id': person.id, 'name': person.name,
            'display_name': profile.get('display_name') or person.name,
            'aliases': person.profile.get('aliases', []), 'org': person.org,
            'org_type': person.org_type, 'org_name': person.profile.get('org_name') or person.org,
            'org_as_of': profile.get('affiliation_as_of') or None,
            'org_basis': org_basis, 'virtual': person.virtual, 'featured': curated,
            'record_count': len(evidence), 'topic_ids': sorted({tag for record in records for tag in record.tags}),
            'person_confirmed': False, 'profile': profile, 'evidence': evidence,
        })
        linked.update(item['id'] for item in evidence)
    kinds = Counter(record.kind for record in corpus.records.values())
    return {
        'schema_version': 'people-map-existing-v1', 'complete': True,
        'source': {
            'generated_at': datetime.now(timezone.utc).isoformat(),
            'method': '현재 서비스에서 제공하는 인물·근거 기록을 읽기 전용으로 연결',
            'note': '공개 논문·제공 경력·가상 현장 기록이며 사내 실명부가 아닙니다.',
            'availability_note': '현재 소속·가용 시간·연락 의향은 미확인',
        },
        'counts': {
            'people': len(people), 'nonvirtual_people': sum(not p['virtual'] for p in people),
            'virtual_people': sum(p['virtual'] for p in people), 'featured_people': len(featured),
            'portrait_people': sum(bool(p['profile'].get('portrait', {}).get('path')) for p in people),
            'records': len(corpus.records), 'linked_records': len(linked),
            'unlinked_records': len(set(corpus.records) - linked),
            'paper_records': kinds['paper'] + kinds['preprint'],
            'career_records': kinds['career_record'], 'site_records': kinds['site_record'],
        },
        'featured_ids': featured, 'topics': corpus.topics, 'people': people,
    }
