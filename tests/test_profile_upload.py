"""Selected-provider document reading, review/save, retry and account-card regressions."""
import base64
import json
import unittest
import uuid

from rndplz.profile_reading import MAP_CONTRACT, ProfileReader, ReadingError, finalize, split_parts, verify_part
from rndplz.profiles import ProfileError, Profiles
from tests import test_profile_reading as reading_tests
from tests import test_person_card as card_tests
from tests.test_profile_reading import ScriptedModels, document
from tests.test_person_card import card_of, public_engine
from rndplz.person_cards import PersonCards


class SelectedModels(ScriptedModels):
    def __init__(self):
        super().__init__()
        self.requests = []
        self.empty = False
        self.fail_part = None

    def get(self, identifier):
        if identifier == 'missing':
            raise ValueError('not configured')
        return {'id': identifier, 'provider': identifier.split(':')[0], 'enabled': identifier != 'aiu:disabled'}

    def stream(self, identifier, messages, *, contract=None):
        payload = json.loads(messages[0]['content'])
        self.requests.append((identifier, contract, payload))
        if contract == MAP_CONTRACT and payload['part'].startswith(str(self.fail_part) + '/'):
            self.fail_part = None
            raise ReadingError('temporary failure')
        if self.empty:
            self.calls.append(contract)
            yield json.dumps({'careers': [], 'skills': [], 'interests': []})
        else:
            yield from super().stream(identifier, messages, contract=contract)


class UploadTests(unittest.TestCase):
    def setUp(self):
        flow = reading_tests.ProfileFlowTests(); flow.setUp()
        self.addCleanup(flow.doCleanups)
        self.models = SelectedModels()
        self.profiles = Profiles(flow.store, reader=ProfileReader(self.models))

    def request(self, **values):
        return {**values, 'base_version': self.profiles.read()['profile']['version'], 'request_id': 'req-' + uuid.uuid4().hex}

    def upload(self, text=None):
        text = text or document(15)
        view = self.profiles.upload(self.request(name='research.txt', data=base64.b64encode(text.encode()).decode()))
        return view['operation']['source_id']

    def read_all(self, identifier, model='aiu'):
        total = len(split_parts(self.profiles.source(identifier)['text']))
        return [self.profiles.read_part({'source_id': identifier, 'part': part, 'model_id': model}) for part in range(1,total+1)]

    def suggest(self, identifier):
        return self.profiles.suggest(self.request(source_ids=[identifier], model_id='aiu'))

    def test_enabled_selected_providers_never_switch_to_bridge(self):
        reader = ProfileReader(self.models)
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
        with self.assertRaises(ReadingError): reader._model('guide')

    def test_long_document_is_typed_and_does_not_autosave(self):
        self.profiles.save(self.request(fields={'name':'홍길동','skills':'Python'}))
        identifier = self.upload(document(900))
        before = self.profiles.read()['profile']
        parts = self.read_all(identifier)
        view = self.suggest(identifier)
        self.assertTrue(all(p['model_id']=='aiu' for p in parts))
        self.assertEqual(view['operation']['model_calls'], 1)  # merge only; part calls reported separately
        self.assertEqual(view['profile']['fields'], before['fields'])
        self.assertEqual(view['profile']['careers'], before['careers'])
        self.assertEqual({p['field'] for p in view['suggestions']}, {'skills','career'})
        second = self.models.requests[1][2]
        self.assertEqual(second['current_profile']['name'], '홍길동')
        self.assertIn('기술연구소', second['document_header'])
        self.assertTrue(all(identifier=='aiu' for identifier, _, _ in self.models.requests))

    def test_cached_retry_and_provider_change(self):
        identifier = self.upload(document(900))
        self.models.fail_part=2
        first=self.profiles.read_part({'source_id':identifier,'part':1,'model_id':'aiu'})
        with self.assertRaises(ProfileError):
            self.profiles.read_part({'source_id':identifier,'part':2,'model_id':'aiu'})
        again=self.profiles.read_part({'source_id':identifier,'part':1,'model_id':'aiu'})
        self.assertEqual((first['model_calls'],again['model_calls'],again['cached']),(1,0,True))
        self.read_all(identifier)
        changed=self.profiles.read_part({'source_id':identifier,'part':1,'model_id':'openai'})
        self.assertFalse(changed['cached'])
        with self.assertRaises(ProfileError) as error:
            self.suggest(identifier)
        self.assertEqual(error.exception.code,'reading_incomplete')

    def test_identity_change_requires_new_reading(self):
        identifier=self.upload();self.read_all(identifier)
        self.profiles.save(self.request(fields={'name':'다른 연구자'}))
        with self.assertRaises(ProfileError) as error:
            self.suggest(identifier)
        self.assertEqual(error.exception.code,'reading_incomplete')
        self.assertFalse(self.read_all(identifier)[0]['cached'])

    def test_unavailable_model_does_not_turn_document_into_paragraphs(self):
        identifier=self.upload()
        with self.assertRaises(ProfileError): self.read_all(identifier,'rules')
        self.assertEqual(self.models.requests,[])
        self.assertEqual(self.profiles.read()['suggestions'],[])

    def test_zero_candidates_stay_zero_when_refreshed(self):
        self.models.empty=True
        identifier=self.upload(document(900));self.read_all(identifier)
        view=self.suggest(identifier)
        self.assertEqual((view['operation']['created'],view['operation']['model_calls']),(0,0))
        view=self.profiles.suggest(self.request(source_ids=[identifier]))
        self.assertEqual(view['suggestions'],[])

    def test_review_can_correct_all_career_metadata_before_save(self):
        identifier=self.upload();self.read_all(identifier);view=self.suggest(identifier)
        career=next(p for p in view['suggestions'] if p['field']=='career')
        details={'title':'검토한 연구 실적','organization':'실제 소속','period':'2025','role':'공동연구자'}
        request=self.request(fields={},decisions=[{'id':career['id'],'decision':'edit','field':'career','career':details,'value':'확인한 수행 내용'}])
        self.assertEqual(self.profiles.read()['profile']['careers'],[])
        saved=self.profiles.save(request)
        for key,value in details.items(): self.assertEqual(saved['profile']['careers'][0][key],value)
        self.assertEqual(saved['profile']['careers'][0]['description'],'확인한 수행 내용')
        self.profiles.save(request)
        self.assertEqual(len(self.profiles.read()['profile']['careers']),1)

    def test_career_edits_cannot_inject_identity_or_other_fields(self):
        identifier=self.upload();self.read_all(identifier);view=self.suggest(identifier)
        career=next(p for p in view['suggestions'] if p['field']=='career')
        for details in ({'person_id':'other'},{'id':'a'*32},{'role':'x'*181}):
            with self.subTest(details=details), self.assertRaises(ProfileError):
                self.profiles.save(self.request(fields={},decisions=[{'id':career['id'],'decision':'edit','field':'career','career':details}]))
        self.assertEqual(self.profiles.read()['profile']['careers'],[])

    def test_reupload_does_not_duplicate_sources(self):
        identifier=self.upload();self.read_all(identifier)
        view=self.profiles.upload(self.request(name='renamed.txt',data=base64.b64encode(document(15).encode()).decode()))
        self.assertEqual((view['operation']['source_id'],view['operation']['duplicate']),(identifier,True))
        self.assertTrue(self.read_all(identifier)[0]['cached'])

    def test_merge_cannot_turn_a_career_into_a_skill(self):
        rows=[{'id':'c1','kind':'careers','quote':'근거','start':0,'end':2,'performer':'unclear'}]
        self.assertEqual(finalize({'skills':[{'value':'무근거 기술','from':['c1']}]},rows,{}),[])
        value={'careers':[{'title':'연구','description':'연구 내용','role':'책임 연구자','from':['c1']}]}
        proposal=finalize(value,rows,{})[0]
        self.assertEqual(proposal['career']['role'],'')
        self.assertEqual(proposal['participation'],'needs_review')
        self.assertTrue(proposal['after'].startswith('문서에 기술된 연구:'))

    def test_selected_save_updates_bound_card_and_persists_after_restart(self):
        account=card_tests.PersonCardTests();account.setUp();self.addCleanup(account.doCleanups)
        self.profiles=account.profiles();self.profiles.reader=ProfileReader(self.models)
        before=self.profiles.read()['profile'];map_before=card_of(account.engine)
        identifier=self.upload();self.read_all(identifier);view=self.suggest(identifier)
        self.assertEqual(card_of(account.engine)['profile'],map_before['profile'])
        decisions=[{'id':p['id'],'decision':'accept','field':p['field']} for p in view['suggestions']]
        self.profiles.card_preview({'fields':{},'decisions':decisions})
        self.assertEqual(card_of(account.engine)['profile'],map_before['profile'])
        saved=self.profiles.save(self.request(fields={},decisions=decisions))
        self.assertEqual(saved['profile']['fields']['name'],before['fields']['name'])
        self.assertTrue(all(c in saved['profile']['careers'] for c in before['careers']))
        self.assertEqual(len(saved['profile']['careers']),len(before['careers'])+1)
        card=card_of(account.engine)
        self.assertTrue(any(e['title']=='촉매 반응기 최적화' for e in card['evidence']))
        restarted=public_engine();cards=PersonCards(restarted.corpus)
        for person_id,draft in account.storage.card_drafts(): cards.apply(person_id,draft['profile'])
        self.assertEqual(card_of(restarted)['profile'],card['profile'])


if __name__=='__main__': unittest.main()
