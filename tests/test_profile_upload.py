"""Profile sentences keep the chat's provider; documents, review saves and account-card regressions."""
import base64
import unittest
import uuid

from rndplz.profile_reading import ProfileReader, ReadingError
from rndplz.profiles import ProfileError, Profiles
from tests import test_profile_reading as reading_tests
from tests import test_person_card as card_tests
from tests.test_profile_reading import DigestModels, document
from tests.test_person_card import card_of, public_engine
from rndplz.person_cards import PersonCards


class SelectedModels(DigestModels):
    def get(self, identifier):
        if identifier == 'missing':
            raise ValueError('not configured')
        return {'id': identifier, 'provider': identifier.split(':')[0], 'enabled': identifier != 'aiu:disabled'}


class UploadTests(unittest.TestCase):
    def setUp(self):
        flow = reading_tests.ProfileFlowTests(); flow.setUp()
        self.addCleanup(flow.doCleanups)
        self.models = DigestModels()
        self.profiles = Profiles(flow.store, reader=ProfileReader(self.models))

    def request(self, **values):
        return {**values, 'base_version': self.profiles.read()['profile']['version'], 'request_id': 'req-' + uuid.uuid4().hex}

    def upload(self, text=None):
        text = text or document(15)
        view = self.profiles.upload(self.request(name='research.txt', data=base64.b64encode(text.encode()).decode()))
        return view['operation']['source_id']

    def paragraph(self, identifier):
        view = self.profiles.suggest(self.request(source_ids=[identifier]))
        return next(p for p in view['suggestions'] if p['source_id'] == identifier)

    def test_enabled_selected_providers_never_switch_to_bridge(self):
        reader = ProfileReader(SelectedModels())
        for model in ('aiu', 'aiu:research', 'ollama', 'openai', 'claude', 'gemini'):
            with self.subTest(model=model):
                self.assertEqual(reader._model(model), model)
        for model in ('rules', 'missing', 'aiu:disabled'):
            with self.subTest(model=model), self.assertRaises(ReadingError):
                reader._model(model)

    def test_deployed_public_catalog_accepts_aiu_but_rejects_guide(self):
        from rndplz.public_web import PublicModels
        models=PublicModels({'RNDPLZ_PUBLIC_MODEL':'bridge','RNDPLZ_AIU_API_KEY':'fixture-key',
                             'RNDPLZ_AIU_URL':'https://api.aiu.gscaltex.com/ext/v1/workflows/run'})
        reader=ProfileReader(models)
        self.assertEqual(reader._model('aiu'),'aiu')
        self.assertEqual(reader.digest_models(),['aiu'])
        with self.assertRaises(ReadingError): reader._model('guide')

    def test_review_can_correct_all_career_metadata_before_save(self):
        proposal=self.paragraph(self.upload())
        details={'title':'검토한 연구 실적','organization':'실제 소속','period':'2025','role':'공동연구자'}
        request=self.request(fields={},decisions=[{'id':proposal['id'],'decision':'edit','field':'career','career':details,'value':'확인한 수행 내용'}])
        self.assertEqual(self.profiles.read()['profile']['careers'],[])
        saved=self.profiles.save(request)
        for key,value in details.items(): self.assertEqual(saved['profile']['careers'][0][key],value)
        self.assertEqual(saved['profile']['careers'][0]['description'],'확인한 수행 내용')
        self.profiles.save(request)
        self.assertEqual(len(self.profiles.read()['profile']['careers']),1)

    def test_career_edits_cannot_inject_identity_or_other_fields(self):
        proposal=self.paragraph(self.upload())
        for details in ({'person_id':'other'},{'id':'a'*32},{'role':'x'*181}):
            with self.subTest(details=details), self.assertRaises(ProfileError):
                self.profiles.save(self.request(fields={},decisions=[{'id':proposal['id'],'decision':'edit','field':'career','career':details}]))
        self.assertEqual(self.profiles.read()['profile']['careers'],[])

    def test_reupload_does_not_duplicate_sources_or_readings(self):
        identifier=self.upload();self.profiles.digest({'source_id':identifier})
        view=self.profiles.upload(self.request(name='renamed.txt',data=base64.b64encode(document(15).encode()).decode()))
        self.assertEqual((view['operation']['source_id'],view['operation']['duplicate']),(identifier,True))
        self.assertTrue(self.profiles.digest({'source_id':identifier})['cached'])
        self.assertEqual(len(self.models.calls),1)

    def test_a_kept_proposal_updates_the_bound_card_and_persists_after_restart(self):
        account=card_tests.PersonCardTests();account.setUp();self.addCleanup(account.doCleanups)
        self.profiles=account.profiles();self.profiles.reader=ProfileReader(self.models)
        before=self.profiles.read()['profile'];map_before=card_of(account.engine)
        result=self.profiles.digest({'source_id':self.upload()})
        self.assertEqual(self.models.calls[0][1]['current_card']['name'],before['fields']['name'])
        self.assertEqual(card_of(account.engine)['profile'],map_before['profile'])  # reading changes nothing
        # The page puts the kept items into the draft as typed edits; 변경 저장 saves them.
        proposal=result['proposal'];careers=[{k:v for k,v in c.items()} for c in before['careers']]+proposal['careers']
        fields={'skills':', '.join([before['fields']['skills'],*proposal['skills']]).strip(', ')}
        self.profiles.card_preview({'fields':fields,'careers':careers})
        self.assertEqual(card_of(account.engine)['profile'],map_before['profile'])
        saved=self.profiles.save(self.request(fields=fields,careers=careers))
        self.assertEqual(saved['profile']['fields']['name'],before['fields']['name'])
        self.assertEqual(len(saved['profile']['careers']),len(before['careers'])+1)
        card=card_of(account.engine)
        self.assertTrue(any(e['title']=='촉매 반응기 최적화' for e in card['evidence']))
        restarted=public_engine();cards=PersonCards(restarted.corpus)
        for person_id,draft in account.storage.card_drafts(): cards.apply(person_id,draft['profile'])
        self.assertEqual(card_of(restarted)['profile'],card['profile'])


if __name__=='__main__': unittest.main()
