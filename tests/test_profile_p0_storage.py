"""P0 identity and document lineage from adoption through storage, cards and map records."""
import base64
import copy
import json
import uuid
import unittest

from rndplz.evidence_search import PublicEvidenceSearch
from rndplz.person_cards import PersonCards, _source_projection
from rndplz.profiles import ProfileError, Profiles, _source_summary
from tests import test_person_card as card_tests
from tests import test_profile_reading as reading_tests
from tests.test_person_card import card_of, public_engine


class ProfileP0StorageTests(unittest.TestCase):
    def setUp(self):
        flow = reading_tests.ProfileFlowTests()
        flow.setUp()
        self.addCleanup(flow.doCleanups)
        self.store = flow.store
        self.profiles = Profiles(self.store)

    def request(self, **payload):
        return {**payload, 'base_version': self.profiles.read()['profile']['version'],
                'request_id': 'p0-' + uuid.uuid4().hex}

    def upload(self):
        return self.profiles.upload(self.request(name='프로필-시험.txt',
            data=base64.b64encode('시험 연구소 연구팀 연구원'.encode()).decode()))['operation']['source_id']

    def test_legacy_draft_gets_empty_slots_without_losing_saved_values(self):
        self.profiles.save(self.request(fields={'name': '기존 이름'}))
        for field in ('department', 'aliases', 'tagline'):
            self.store.state['self_profile']['profile']['fields'].pop(field)
        before = copy.deepcopy(self.store.state)
        fields = self.profiles.read()['profile']['fields']
        self.assertEqual((fields['name'], fields['department'], fields['aliases'], fields['tagline']),
                         ('기존 이름', '', [], ''))
        self.assertEqual(self.store.state, before)  # compatibility reads do not write
        saved = self.profiles.save(self.request(fields={'aliases': ['English Name', ' English Name ', '다른 이름']}))
        self.assertEqual(saved['profile']['fields']['aliases'], ['English Name', '다른 이름'])
        self.assertEqual(Profiles(self.store).read()['profile']['fields']['aliases'], ['English Name', '다른 이름'])
        for invalid in ('English Name', [1], ['a'] * 21, ['a' * 121]):
            with self.subTest(invalid=invalid), self.assertRaises(ProfileError):
                self.profiles.save(self.request(fields={'aliases': invalid}))

    def test_adopted_identity_and_career_keep_source_and_manual_edit_lineage(self):
        source_id = self.upload()
        metadata = {'source_ids': [source_id], 'edited': False}
        fields = {'name': '시험 이름', 'organization': '시험 연구소', 'department': '연구팀',
                  'role': '연구원', 'aliases': ['Fixture Name'], 'tagline': '시험 연구를 합니다.'}
        saved = self.profiles.save(self.request(fields=fields,
            field_sources={key: metadata for key in fields}, careers=[{
                'title': '검증 경력', 'description': '자료에서 채택한 설명', **metadata}]))
        profile = saved['profile']
        career = profile['careers'][0]
        self.assertNotIn('source_ids', career)  # metadata has one canonical home
        for key in [*fields, 'career:' + career['id']]:
            provenance = profile['provenance'][key]
            self.assertEqual(provenance['source_ids'], [source_id])
            self.assertEqual(provenance['origin'], 'source_claim')
            self.assertEqual(provenance['sources'], [{'id': source_id, 'title': '프로필-시험.txt',
                                                     'url': '', 'status': 'active'}])
        saved = self.profiles.save(self.request(fields={'role': '수정한 연구원'},
            careers=[{**career, 'description': '사용자가 수정한 설명'}]))
        for key in ('role', 'career:' + career['id']):
            self.assertEqual(saved['profile']['provenance'][key]['origin'], 'user_edited_source')
            self.assertEqual(saved['profile']['provenance'][key]['source_ids'], [source_id])
        # Explicit edits in the proposal are distinguished even on the first adoption.
        saved = self.profiles.save(self.request(fields={'tagline': '고친 소개'},
            field_sources={'tagline': {'source_ids': [source_id], 'edited': True}}))
        self.assertEqual(saved['profile']['provenance']['tagline']['review'], 'edited_accepted')
        saved = self.profiles.undo(self.request(version=saved['profile']['version']))
        self.assertEqual(saved['profile']['fields']['tagline'], fields['tagline'])
        self.assertEqual(saved['profile']['provenance']['tagline']['origin'], 'source_claim')

    def test_source_validation_is_atomic_for_fields_careers_and_previews(self):
        source_id = self.upload()
        before = copy.deepcopy(self.store.state)
        for metadata in ({'source_ids': ['f' * 32]}, {'source_ids': [source_id], 'edited': 'yes'},
                         {'source_ids': [source_id], 'title': 'forged'}, {'source_ids': source_id}):
            with self.subTest(metadata=metadata), self.assertRaises(ProfileError):
                self.profiles.save(self.request(fields={'bio': '변경 시도'}, field_sources={'bio': metadata}))
            self.assertEqual(self.store.state, before)
        with self.assertRaises(ProfileError):
            self.profiles.save(self.request(fields={'bio': '변경 시도'}, careers=[{
                'title': '새 경력', 'source_ids': ['e' * 32]}]))
        self.assertEqual(self.store.state, before)
        self.profiles.source_action(self.request(id=source_id, action='unlink'))
        with self.assertRaises(ProfileError):
            self.profiles.save(self.request(fields={'bio': '변경 시도'},
                field_sources={'bio': {'source_ids': [source_id]}}))

    def test_unlink_warns_and_delete_redacts_aliases_source_names_and_undo(self):
        source_id = self.upload()
        saved = self.profiles.save(self.request(fields={'aliases': ['Fixture Alias']},
            field_sources={'aliases': {'source_ids': [source_id]}}))
        version = saved['profile']['version']
        self.profiles.source_action(self.request(id=source_id, action='unlink'))
        saved = self.profiles.save(self.request(fields={'aliases': ['Edited Alias']}))
        self.assertEqual(saved['profile']['provenance']['aliases']['evidence_status'], 'requires_review')
        with self.assertRaises(ProfileError):
            self.profiles.undo(self.request(version=version))
        view = self.profiles.source_action(self.request(id=source_id, action='delete'))
        self.assertEqual(view['profile']['fields']['aliases'], [])
        self.assertNotIn('프로필-시험.txt', json.dumps(view, ensure_ascii=False))
        self.assertNotIn('Fixture Alias', json.dumps(view, ensure_ascii=False))
        self.assertEqual(view['profile']['provenance']['aliases']['sources'][0]['title'], '삭제한 자료')

    def test_new_adoption_keeps_inactive_older_lineage_for_accumulated_fields(self):
        old_id = self.upload()
        values = {'bio': '기존 소개', 'skills': '기존 기술', 'interests': '기존 관심', 'aliases': ['Old Alias']}
        self.profiles.save(self.request(fields=values,
            field_sources={key: {'source_ids': [old_id], 'edited': True} for key in values}))
        self.profiles.source_action(self.request(id=old_id, action='unlink'))
        new_id = self.upload()
        combined = {key: value + (['New Alias'] if isinstance(value, list) else '\n새 항목')
                    for key, value in values.items()}
        saved = self.profiles.save(self.request(fields=combined,
            field_sources={key: {'source_ids': [new_id], 'edited': False} for key in combined}))
        for key in values:
            provenance = saved['profile']['provenance'][key]
            self.assertEqual(provenance['source_ids'], [old_id, new_id])
            self.assertEqual(provenance['evidence_status'], 'requires_review')
            self.assertEqual(provenance['origin'], 'user_edited_source')

    def test_source_links_never_expose_private_endpoints_or_unsafe_urls(self):
        source = {'id': 'a' * 32, 'name': '시험 자료', 'status': 'active', 'access': 'private',
                  'url': 'https://example.org/api/self-profile/source/' + 'a' * 32}
        self.assertEqual(_source_summary(source)['url'], '')
        for url in ('/api/self-profile/source/id', 'javascript:alert(1)', 'file:///private.txt',
                    'https://user:password@example.org/report'):
            with self.subTest(url=url):
                self.assertEqual(_source_summary({**source, 'access': 'public', 'url': url})['url'], '')
        public_url = 'https://example.org/research/profile'
        self.assertEqual(_source_summary({**source, 'access': 'public', 'url': public_url})['url'], public_url)
        legacy = _source_projection({'source_ids': [source['id']], 'origin': 'user_edited_source',
                                     'evidence_status': 'linked_claim'})
        self.assertEqual(legacy['source_review'], '자료 기반 + 사용자 수정 · 출처 확인 필요')
        self.assertEqual(legacy['sources'], [])


class ProfileP0ProjectionTests(ProfileP0StorageTests):
    def setUp(self):
        account = card_tests.PersonCardTests()
        account.setUp()
        self.addCleanup(account.doCleanups)
        self.account = account
        self.profiles = account.profiles()
        self.profiles.read()
        self.store = None

    # Projection uses a separate account-bound store, so only its own scenarios are collected.
    test_legacy_draft_gets_empty_slots_without_losing_saved_values = None
    test_adopted_identity_and_career_keep_source_and_manual_edit_lineage = None
    test_source_validation_is_atomic_for_fields_careers_and_previews = None
    test_unlink_warns_and_delete_redacts_aliases_source_names_and_undo = None
    test_new_adoption_keeps_inactive_older_lineage_for_accumulated_fields = None
    test_source_links_never_expose_private_endpoints_or_unsafe_urls = None

    def test_identity_alias_search_and_lineage_reach_card_map_and_restart(self):
        source_id = self.upload()
        before = self.profiles.read()['profile']
        metadata = {'source_ids': [source_id], 'edited': True}
        fields = {'organization': '검증 연구소', 'department': '시험 부서', 'role': '시험 직위',
                  'aliases': ['Unique Fixture Alias'], 'tagline': '한 줄 시험 소개'}
        payload = {'fields': fields, 'field_sources': {key: metadata for key in fields},
                   'careers': [*before['careers'], {'title': '출처가 있는 시험 경력', 'description': '검증 설명', **metadata}]}
        preview = self.profiles.card_preview(payload)['card']
        self.assertNotIn('Unique Fixture Alias', card_of(self.account.engine)['aliases'])
        self.assertEqual(preview['profile']['provenance']['role']['source_review'], '자료 기반 + 사용자 수정')
        self.assertNotIn('reviewer', preview['profile']['provenance']['role'])
        saved = self.profiles.save(self.request(**payload))
        card = card_of(self.account.engine)
        self.assertEqual(card['profile']['department'], fields['department'])
        self.assertEqual(card['org_name'], fields['organization'])
        self.assertEqual(card['profile']['tagline'], fields['tagline'])
        self.assertIn('Unique Fixture Alias', card['aliases'])
        selected, unresolved, ambiguous = PublicEvidenceSearch(self.account.engine)._names(
            ['Unique Fixture Alias'], self.account.engine.corpus.people)
        self.assertEqual((selected, unresolved, ambiguous), ({'LOCAL-MANWOO'}, [], []))
        evidence = next(e for e in card['evidence'] if e['title'] == '출처가 있는 시험 경력')
        timeline = next(e for e in card['profile']['timeline'] if e['record_id'] == evidence['id'])
        for projection in (evidence, timeline, card['profile']['provenance']['role']):
            self.assertEqual(projection['source_ids'], [source_id])
            self.assertEqual(projection['sources'][0]['title'], '프로필-시험.txt')
            self.assertEqual(projection['sources'][0]['url'], '')
            self.assertEqual(projection['source_review'], '자료 기반 + 사용자 수정')
        restarted = public_engine()
        cards = PersonCards(restarted.corpus)
        for person_id, draft in self.account.storage.card_drafts():
            cards.apply(person_id, draft['profile'])
        self.assertEqual(card_of(restarted)['profile'], card['profile'])
        # Saving with the same contents and a new source still projects the lineage.
        key = 'career:' + saved['profile']['careers'][-1]['id']
        self.assertEqual(saved['profile']['provenance'][key]['origin'], 'user_edited_source')
        self.profiles.source_action(self.request(id=source_id, action='unlink'))
        warned = card_of(self.account.engine)
        self.assertEqual(warned['profile']['provenance']['role']['source_review'],
                         '자료 기반 + 사용자 수정 · 출처 확인 필요')
        warned_evidence = next(e for e in warned['evidence'] if e['id'] == evidence['id'])
        self.assertEqual(warned_evidence['source_review'], '자료 기반 + 사용자 수정 · 출처 확인 필요')
        self.assertEqual(warned_evidence['sources'][0]['status'], 'unlinked')

    def test_preview_rejects_foreign_source_and_source_deletion_reaches_map(self):
        with self.assertRaises(ProfileError):
            self.profiles.card_preview({'fields': {'role': '변경'},
                                       'field_sources': {'role': {'source_ids': ['f' * 32]}}})
        source_id = self.upload()
        self.profiles.save(self.request(fields={'aliases': ['Alias From Source']},
            field_sources={'aliases': {'source_ids': [source_id]}}))
        self.profiles.source_action(self.request(id=source_id, action='delete'))
        card = card_of(self.account.engine)
        self.assertNotIn('Alias From Source', card['aliases'])
        self.assertNotIn('프로필-시험.txt', json.dumps(card, ensure_ascii=False))


if __name__ == '__main__':
    unittest.main()
