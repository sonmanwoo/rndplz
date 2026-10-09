"""A bound account's 내 프로필 is its research-map card.

The first open starts from the card's own values; a saved change shows on the map card,
person detail and search records right away (and again after a restart); a change asked
for in the chat is a draft shown As is -> To be and is saved only when confirmed.
"""
import json
import tempfile
import unittest
from pathlib import Path

from rndplz.account_storage import AccountStorage
from rndplz.data import Corpus
from rndplz.demo_pool import project_corpus
from rndplz.engine import Engine
from rndplz.models import ExternalModel
from rndplz.people_map import build_people_map
from rndplz.person_cards import PersonCards
from rndplz.profile_chat import ProfileChat
from rndplz.profiles import Profiles, list_items, list_join
from rndplz.public_profiles import APPROVED_PERSON_IDS, restrict_personal_publication
from rndplz.service import Service

CURATED = {p['id']: p for p in json.loads(
    (Path(__file__).resolve().parents[1] / 'rndplz' / 'featured_people.json').read_text(encoding='utf-8'))['people']}
MANWOO = CURATED['LOCAL-MANWOO']


def public_engine():
    """The hosted server's corpus: the four approved cards, projected to the demo pool."""
    corpus = Corpus()
    restrict_personal_publication(corpus, APPROVED_PERSON_IDS)
    return Engine(project_corpus(corpus, allow_personal_omission=True))


def card_of(engine, person_id='LOCAL-MANWOO'):
    return next(p for p in build_people_map(engine)['people'] if p['id'] == person_id)


class PersonCardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.storage = AccountStorage(root / 'accounts.sqlite3', root / 'files', clock=lambda: 1_000_000)
        issued = self.storage.issue_invitation(600, person_id='LOCAL-MANWOO')
        self.storage.add_flow('state-' + '1' * 20, 'cookie-1', 'nonce', 'verifier', invitation=issued['invitation'])
        flow = self.storage.consume_flow('state-' + '1' * 20, 'cookie-1')
        self.account_id = self.storage.issue_session('sub-mw', '손만우', 'mw@example.com', enrollment_flow=flow)['account']['id']
        self.engine = public_engine()
        self.cards = PersonCards(self.engine.corpus)

    def profiles(self, card=True):
        return Profiles(self.storage.profile_store(self.account_id), public=True,
                        account={'id': self.account_id, 'verified': True, 'storage_lifetime': 'account_database'},
                        card=self.cards.binding('LOCAL-MANWOO') if card else None)

    def test_first_open_starts_from_the_card(self):
        before = card_of(self.engine)
        view = self.profiles().read()
        fields = view['profile']['fields']
        self.assertEqual((fields['name'], fields['organization'], fields['role']), ('손만우', 'GS칼텍스 · 바이오공정팀', '책임'))
        self.assertEqual(fields['bio'], MANWOO['biography'])
        self.assertEqual(fields['interests'].split('\n'), MANWOO['interests'])
        self.assertEqual(fields['skills'].split('\n')[:4], [*MANWOO['skills'], MANWOO['skill_groups'][0]['items'][0]])
        self.assertIn('HYSYS', fields['skills'].split('\n'))
        self.assertEqual({c['title'] for c in view['profile']['careers']}, {
            'Diols 탈색·탈취 공정 개발', '라텍스 유화 중합 모델링 · 필름 표면 불량 감지', '모노머 공정 모델링·최적화 및 증류·추출 실험'})
        self.assertEqual((view['scope']['kind'], view['scope']['person_id'], view['scope']['person_label']),
                         ('person_card', 'LOCAL-MANWOO', '손만우'))
        self.assertEqual(view['profile']['provenance']['name']['origin'], 'public_card')
        self.assertEqual((view['profile']['version'], view['card_update']['changed']), (1, []))
        self.assertEqual(card_of(self.engine)['profile'], before['profile'])  # opening does not change the card
        self.assertEqual(self.profiles().read()['profile']['version'], 1)  # seeded once

    def test_values_written_before_the_link_are_kept_and_shown(self):
        plain = self.profiles(card=False)
        self.assertEqual(plain.read()['scope']['kind'], 'account_private')  # without a card: private as before
        plain.save({'fields': {'bio': '내가 먼저 쓴 소개'}, 'base_version': 0, 'request_id': 'req-own-bio-00001'})
        view = self.profiles().read()
        self.assertEqual((view['profile']['fields']['bio'], view['profile']['fields']['name']), ('내가 먼저 쓴 소개', '손만우'))
        self.assertEqual(card_of(self.engine)['profile']['biography'], '내가 먼저 쓴 소개')

    def test_a_saved_change_is_the_card_on_the_map_and_in_search(self):
        curated_evidence = len(card_of(self.engine)['evidence'])
        profiles = self.profiles()
        view = profiles.read()
        skills = [s for s in view['profile']['fields']['skills'].split('\n') if s != 'HYSYS'] + ['공정 제어']
        new = {'title': 'TCB 솔벤트 정제', 'organization': 'GS칼텍스', 'period': '2026', 'role': '공정 개발',
               'description': '증류로 잔존 미세 물질 제거'}
        saved = profiles.save({'fields': {'role': '수석', 'skills': '\n'.join(skills)},
                               'careers': [*view['profile']['careers'], new], 'base_version': 1, 'request_id': 'req-card-edit-0001'})
        self.assertEqual(saved['card_update'], {'person_id': 'LOCAL-MANWOO', 'changed': ['role', 'skills', 'careers']})
        card = card_of(self.engine)
        self.assertEqual(card['org'], 'GS칼텍스 · 바이오공정팀 · 수석')
        self.assertNotIn('HYSYS', [item for group in card['profile']['skill_groups'] for item in group['items']])
        self.assertEqual(card['profile']['skills'], [*MANWOO['skills'], '공정 제어'])
        # Values the account left alone keep the curated card.
        self.assertEqual((card['profile']['tagline'], card['profile']['interests'], card['profile']['display_name']),
                         (MANWOO['tagline'], MANWOO['interests'], '손만우'))
        added = [e for e in card['evidence'] if e['title'] == 'TCB 솔벤트 정제']
        self.assertEqual((len(added), len(card['evidence'])), (1, curated_evidence + 1))
        self.assertEqual(card['profile']['timeline'][-1], {'record_id': added[0]['id'], 'date': '2026',
                                                        'text': 'GS칼텍스 · 공정 개발. 증류로 잔존 미세 물질 제거', 'url': '',
                                                        'title': 'TCB 솔벤트 정제'})  # the row's title heads its line (P1)
        self.assertTrue(any(r.title == 'TCB 솔벤트 정제' for r in self.engine.corpus.by_person['LOCAL-MANWOO']))

        # A restart shows the same card from the stored draft.
        restarted = public_engine()
        cards = PersonCards(restarted.corpus)
        for person_id, draft in self.storage.card_drafts():
            if draft.get('card', {}).get('person_id') == person_id:
                cards.apply(person_id, draft['profile'])
        again = card_of(restarted)
        self.assertEqual((again['org'], again['profile']['skills'], len(again['evidence'])),
                         (card['org'], card['profile']['skills'], curated_evidence + 1))

        # Saving the card's own values again gives the curated card back.
        latest = profiles.read()
        reverted = profiles.save({'fields': {'role': '책임', 'skills': view['profile']['fields']['skills']},
                                  'careers': view['profile']['careers'], 'base_version': latest['profile']['version'],
                                  'request_id': 'req-card-back-0001'})
        self.assertEqual(reverted['card_update']['changed'], [])
        self.assertEqual(card_of(self.engine)['profile'], card_of(public_engine())['profile'])

    def test_a_chat_command_is_a_draft_until_confirmed(self):
        profiles = self.profiles()
        profiles.read()
        state = Path(self.tmp.name) / 'chat'
        state.mkdir()
        service = Service(self.engine, state, ExternalModel({'RNDPLZ_PROVIDER': 'none', 'RNDPLZ_MODEL_CALL_LIMIT': '0'}),
                          state_env={'RNDPLZ_STATE_BACKEND': 'file'})
        body = ProfileChat(service, profiles).handle({'action': 'text', 'turn_id': 'turn-command-0000000001',
                                                      'text': '내 관심 분야에 수소 액화 추가해줘'})
        self.assertEqual(body['draft']['fields']['interests'].split('\n'), [*MANWOO['interests'], '수소 액화'])
        self.assertEqual((body['draft']['base_version'], body['profile_view']['profile']['version']), (1, 1))  # nothing saved yet
        self.assertEqual(body['reply'], "관심 분야 변경안을 프로필 창에 준비했어요. 맞으면 '이대로 저장'을 눌러 주세요.")
        self.assertEqual(card_of(self.engine)['profile']['interests'], MANWOO['interests'])  # the card waits for the confirm
        confirmed = ProfileChat(service, profiles).handle({
            'action': 'save', 'turn_id': 'turn-confirm-0000000001', 'session_id': body['session']['id'],
            'payload': {'fields': body['draft']['fields'], 'base_version': 1, 'request_id': 'draft-save-00000001'}})
        self.assertEqual(confirmed['reply'], '프로필 변경을 저장했어요. 연구맵 카드에도 바로 반영했어요.')
        self.assertEqual(card_of(self.engine)['profile']['interests'], [*MANWOO['interests'], '수소 액화'])

    def test_card_preview_shows_unsaved_edits_without_storing(self):
        profiles = self.profiles()
        view = profiles.read()
        before = card_of(self.engine)['profile']
        careers = [{k: row[k] for k in ('id', 'title', 'organization', 'period', 'role', 'description')}
                   for row in view['profile']['careers'][:1]]
        careers[0]['description'] = '미리보기 설명'
        card = profiles.card_preview({'fields': {'bio': '미리 보는 소개'}, 'careers': careers})['card']
        self.assertEqual((card['id'], card['profile']['biography']), ('LOCAL-MANWOO', '미리 보는 소개'))
        self.assertEqual([row['text'] for row in card['profile']['timeline']], ['GS칼텍스 바이오공정팀 · 책임. 미리보기 설명'])
        # The shared reader gets the same scoped non-career records and the draft careers.
        scoped = {r.id for r in self.engine.corpus.by_person['LOCAL-MANWOO'] if r.kind != 'career_record'}
        draft_ids = {row['record_id'] for row in card['profile']['timeline']}
        self.assertEqual({e['id'] for e in card['evidence']}, scoped | draft_ids)
        self.assertEqual(card['record_count'], len(card['evidence']))
        self.assertEqual([e['id'] for e in card['evidence'] if e['kind'] == 'career_record'],
                         [row['record_id'] for row in card['profile']['timeline']])
        # An unchanged preview and the actual map carry identical evidence, independent of row order.
        original = profiles.card_preview({})['card']
        current = card_of(self.engine)
        preview_evidence = {e['id']: e for e in original['evidence']}
        self.assertEqual(set(preview_evidence), {e['id'] for e in current['evidence']})
        self.assertEqual(preview_evidence,
                         {e['id']: {key: e[key] for key in preview_evidence[e['id']]}
                          for e in current['evidence']})
        self.assertEqual(card_of(self.engine)['profile'], before)  # the map card is unchanged
        self.assertEqual(profiles.read()['profile']['version'], view['profile']['version'])  # nothing saved
        self.assertEqual(profiles.card_preview({})['card']['profile']['biography'], MANWOO['biography'])
        with self.assertRaises(ValueError):
            self.profiles(card=False).card_preview({})  # only a bound account has a card

    def test_parallel_careers_keep_record_ids_when_saved_and_reordered(self):
        careers = self.profiles().read()['profile']['careers']
        for i, row in enumerate(careers):
            row['period'] = '2026'
            row['description'] = f'동일 기간의 별도 경력 {i}'
        self.cards.apply('LOCAL-MANWOO', {'fields': self.profiles().read()['profile']['fields'],
                                          'careers': list(reversed(careers))})
        card = card_of(self.engine)
        evidence = {entry['id']: entry for entry in card['evidence']}
        for entry, row in zip(card['profile']['timeline'], reversed(careers)):
            self.assertEqual(evidence[entry['record_id']]['title'], row['title'])
            self.assertIn(row['description'], entry['text'])
        from rndplz.person_cards import card_values
        person = self.engine.corpus.people['LOCAL-MANWOO']
        records = [r for r in self.engine.corpus.by_person[person.id] if r.kind == 'career_record']
        values = card_values(person, list(reversed(records)))
        descriptions = {row['title']: row['description'] for row in values['careers']}
        self.assertEqual(descriptions, {row['title']: row['description'] for row in careers})

    def test_curated_career_timeline_has_unambiguous_record_ids(self):
        corpus = Corpus()
        for pid, person in corpus.people.items():
            careers = [r for r in corpus.by_person[pid] if r.kind == 'career_record']
            if not careers:
                continue
            timeline = person.profile['timeline']
            self.assertEqual({entry['record_id'] for entry in timeline}, {record.id for record in careers})

    def test_career_rows_are_the_card_timeline_lines(self):
        careers = self.profiles().read()['profile']['careers']
        first = careers[0]
        self.assertEqual((first['organization'], first['role'], first['period']), ('GS칼텍스 바이오공정팀', '책임', '2023.01 — 현재'))
        self.assertTrue(first['description'].startswith('2023.01.30 입사. Diols 탈색·탈취 공정 개발'))
        # Saving the rows as they are leaves every timeline line as the card shows it.
        before = card_of(self.engine)['profile']['timeline']
        preview = self.profiles().card_preview({'careers': [{k: v for k, v in row.items()} for row in careers]})['card']
        self.assertEqual(preview['profile']['timeline'], before)

    def test_an_earlier_record_text_seed_is_upgraded_untouched(self):
        profiles = self.profiles()
        view = profiles.read()
        legacy = self.cards.legacy_careers('LOCAL-MANWOO')
        store = self.storage.profile_store(self.account_id)

        def downgrade(state):
            state['self_profile']['profile']['careers'] = legacy
        store.transaction(downgrade)
        self.cards.apply('LOCAL-MANWOO', {'fields': view['profile']['fields'], 'careers': legacy})
        self.assertEqual([{k: v for k, v in entry.items() if k != 'record_id'}
                          for entry in card_of(self.engine)['profile']['timeline']], MANWOO['timeline'])  # wording is unchanged
        upgraded = profiles.read()
        self.assertEqual(upgraded['profile']['careers'], self.cards.values('LOCAL-MANWOO')['careers'])
        self.assertEqual(upgraded['profile']['version'], view['profile']['version'] + 1)
        self.assertEqual(profiles.read()['profile']['version'], upgraded['profile']['version'])  # once

    def test_list_entries_with_commas_stay_whole(self):
        self.assertEqual(list_items('윤활유 배합, 평가\n기유 운전'), ['윤활유 배합, 평가', '기유 운전'])
        self.assertEqual(list_items('공정 제어, 증류; 추출'), ['공정 제어', '증류', '추출'])
        self.assertEqual(list_join(['윤활유 배합, 평가', '기유 운전']), '윤활유 배합, 평가\n기유 운전')
        self.assertEqual(list_join(['공정 제어', '증류']), '공정 제어, 증류')
        self.assertEqual(list_join(['공정 제어', '증류'], 'a\nb'), '공정 제어\n증류')


if __name__ == '__main__':
    unittest.main()
