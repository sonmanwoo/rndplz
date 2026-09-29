"""A curated map card that its bound account edits through 내 프로필.

The card seeds the account's draft once. After that, each saved draft value that
differs from the curated card replaces it wherever the card shows: the research
map, person detail and recommendation evidence. Values the account never changed
keep the curated form (skill groups, timeline wording, record tags).
"""
from __future__ import annotations

import copy
import dataclasses
import hashlib
import threading

from .data import matches
from .domain import Contribution, Record
from .profiles import CAREER_FIELDS, list_items

UNSTATED_ORG = '소속 미기재'


def career_id(record_id):
    return hashlib.sha256(('card-career:' + record_id).encode()).hexdigest()[:32]


def _affiliation(profile):
    """(organization, role, merged): some cards keep the role as the last part of the affiliation line."""
    org = profile.get('org') or ''
    org = '' if org == UNSTATED_ORG else org
    role = profile.get('current_role') or profile.get('role') or ''
    if role or org.count(' · ') < 2:
        return org, role, False
    head, _, tail = org.rpartition(' · ')
    return head, tail, True


def card_values(person, careers):
    """The draft a bound account starts from: the card's own words, one list entry per line."""
    profile = person.profile
    organization, role, _ = _affiliation(profile)
    skills = [*profile.get('skills', []), *(item for group in profile.get('skill_groups', []) for item in group.get('items', []))]
    return {'fields': {'name': profile.get('display_name') or person.name, 'organization': organization, 'role': role,
                       'bio': profile.get('biography') or '', 'skills': '\n'.join(dict.fromkeys(skills)),
                       'interests': '\n'.join(profile.get('interests') or [])},
            'careers': [{'id': career_id(record.id), 'title': record.title, 'organization': '', 'period': record.date,
                         'role': '', 'description': record.text} for record in careers]}


def _career_text(row):
    prefix = ' · '.join(value for value in (row['organization'].strip(), row['role'].strip()) if value)
    return prefix + '. ' + row['description'].strip() if prefix else row['description'].strip()


class PersonCards:
    """Curated cards of the loaded corpus, kept so every apply starts from the curated card."""

    def __init__(self, corpus):
        self.corpus = corpus
        self.lock = threading.Lock()
        self.base = {}

    def available(self, person_id):
        person = self.corpus.people.get(person_id) if isinstance(person_id, str) else None
        return person_id in self.base or (person is not None and bool(person.profile.get('curated')) and not person.virtual)

    def _base(self, person_id):
        if person_id not in self.base:
            self.base[person_id] = (self.corpus.people[person_id], [
                record for record in self.corpus.by_person.get(person_id, []) if record.kind == 'career_record'])
        return self.base[person_id]

    def values(self, person_id):
        with self.lock:
            return copy.deepcopy(card_values(*self._base(person_id)))

    def label(self, person_id):
        person = self.corpus.people.get(person_id) or self._base(person_id)[0]
        return person.profile.get('display_name') or person.name

    def binding(self, person_id):
        return CardBinding(self, person_id)


    def apply(self, person_id, draft):
        """Show a saved draft (profile.fields/careers) as the card. Returns the changed items."""
        with self.lock:
            person, careers = self._base(person_id)
            seed = card_values(person, careers)
            fields = draft['fields']
            changed = [key for key in seed['fields'] if fields.get(key, '') != seed['fields'][key]]
            rows = [{key: row.get(key, '') for key in ('id', *CAREER_FIELDS)} for row in draft.get('careers', [])]
            careers_changed = rows != seed['careers']
            profile, org = copy.deepcopy(person.profile), person.org
            name = fields.get('name', '').strip()
            if 'name' in changed and name:
                profile['display_name'] = name
                if name not in profile.get('aliases', []):
                    profile['aliases'] = [*profile.get('aliases', []), name]
            if {'organization', 'role'} & set(changed):
                _, _, merged = _affiliation(person.profile)
                organization, role = fields['organization'].strip(), fields['role'].strip()
                if merged:
                    org = ' · '.join(value for value in (organization, role) if value) or UNSTATED_ORG
                else:
                    org = organization or UNSTATED_ORG
                    profile.pop('role', None)
                    if role:
                        profile['current_role'] = role
                    else:
                        profile.pop('current_role', None)
                profile['org'] = org
            if 'bio' in changed:
                profile['biography'] = fields['bio'].strip()
            if 'skills' in changed:
                wanted = list(dict.fromkeys(list_items(fields['skills'])))
                groups = [{**group, 'items': [item for item in group.get('items', []) if item in wanted]}
                          for group in person.profile.get('skill_groups', [])]
                profile['skill_groups'] = [group for group in groups if group['items']]
                grouped = {item for group in profile['skill_groups'] for item in group['items']}
                profile['skills'] = [item for item in wanted if item not in grouped]
            if 'interests' in changed:
                profile['interests'] = list_items(fields['interests'])
            records = careers
            if careers_changed:
                records, known = [], {career_id(record.id): record for record in careers}
                area = careers[0].field if careers else 'process_engineering'
                for row in rows:
                    text = _career_text(row)
                    title = row['title'].strip() or row['role'].strip() or row['organization'].strip() or '경력'
                    record = known.get(row['id'])
                    if record is not None:
                        original = next(item for item in seed['careers'] if item['id'] == row['id'])
                        if row != original:
                            record = dataclasses.replace(record, title=title, text=text, date=row['period'].strip())
                    else:
                        tags = [topic['id'] for topic in self.corpus.topics
                                if any(matches(title + ' ' + text, term) for term in topic['keywords'])]
                        record = Record('CAREER-CARD-' + row['id'][:12].upper(), 'career_record', title, text,
                                        row['period'].strip(), [Contribution(person.id, person.name, 'recorded_role')],
                                        tags, area, 'self_reported', 'user_provided_resume', row['id'], '',
                                        self.corpus.checked_at, 'career_experience', ['본인 계정에서 추가한 경력'],
                                        'local_self_reported', False, {'text_kind': 'self_reported', 'abstract_available': False})
                    records.append(record)
                profile['timeline'] = [{'date': row['period'].strip(), 'text': _career_text(row), 'url': ''} for row in rows]
            if changed or careers_changed:
                profile['sources'] = [*profile.get('sources', []), {'title': '본인 계정의 내 프로필에서 수정', 'url': ''}]
            card = dataclasses.replace(person, org=org, profile=profile) if (changed or careers_changed) else person
            # Swap whole dicts: requests iterating the corpus keep the one they started with.
            old = {record.id for record in self.corpus.by_person.get(person_id, []) if record.kind == 'career_record'}
            new_records = {rid: record for rid, record in self.corpus.records.items() if rid not in old}
            new_records.update({record.id: record for record in records})
            by_person = dict(self.corpus.by_person)
            by_person[person_id] = [record for record in self.corpus.by_person.get(person_id, [])
                                    if record.id not in old] + list(records)
            people = dict(self.corpus.people)
            people[person_id] = card
            self.corpus.people, self.corpus.records, self.corpus.by_person = people, new_records, by_person
            return changed + (['careers'] if careers_changed else [])


class CardBinding:
    """One bound account's card, as Profiles uses it."""

    def __init__(self, cards, person_id):
        self.cards, self.person_id = cards, person_id

    @property
    def label(self):
        return self.cards.label(self.person_id)

    def values(self):
        return self.cards.values(self.person_id)

    def publish(self, profile):
        return self.cards.apply(self.person_id, profile)
