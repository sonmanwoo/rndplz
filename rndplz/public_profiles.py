"""The two previously approved public cards, without expanding model scope."""
from __future__ import annotations

import copy

APPROVED_PERSON_IDS = frozenset({'LOCAL-MANWOO', 'LOCAL-JINHO'})
APPROVED_RECORD_IDS = frozenset({
    'CAREER-MW-BIO', 'CAREER-MW-POLYMER', 'CAREER-MW-MONOMER',
    'CAREER-JO-CO2J', 'CAREER-JO-CO2L', 'CAREER-JO-ENERGY',
    'CAREER-JO-LOHC', 'CAREER-JO-METHANOL', 'CAREER-JO-BIO',
})


def selected_public_people(env):
    raw = env.get('RNDPLZ_PUBLIC_PERSON_IDS', '')
    if not isinstance(raw, str):
        raise ValueError('공개 인물 설정을 확인해 주세요.')
    if not raw:
        return frozenset()
    parts = [value.strip() for value in raw.split(',')]
    if (not all(parts) or len(parts) != len(set(parts))
            or not set(parts) <= APPROVED_PERSON_IDS):
        raise ValueError('공개 인물 설정을 확인해 주세요.')
    return frozenset(parts)


def restrict_personal_publication(corpus, selected):
    """Filter the already loaded corpus; never retrieve omitted private records."""
    personal = {pid for pid, person in corpus.people.items()
                if person.profile.get('source_type') in ('self_reported', 'provided_resume')}
    visible = set(selected) & personal & APPROVED_PERSON_IDS
    hidden = personal - visible
    corpus.people = {pid: person for pid, person in corpus.people.items() if pid not in hidden}
    corpus.records = {rid: record for rid, record in corpus.records.items()
                      if not any(c.person_id in hidden for c in record.people)
                      and (not any(c.person_id in visible for c in record.people)
                           or rid in APPROVED_RECORD_IDS)}
    corpus.by_person = {pid: [record for record in records if record.id in corpus.records]
                        for pid, records in corpus.by_person.items() if pid in corpus.people}
    # Corpus appends shared project participation to profile timelines. Publish
    # only the existing card; unrelated later project records stay omitted.
    for pid in visible:
        person = copy.copy(corpus.people[pid])
        person.profile = copy.deepcopy(person.profile)
        if 'projects' in person.profile:
            person.profile['projects'] = [item for item in person.profile['projects']
                                          if not isinstance(item, dict) or not item.get('id')
                                          or item['id'] in APPROVED_RECORD_IDS]
        corpus.people[pid] = person
