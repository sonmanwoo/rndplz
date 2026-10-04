"""Chemical engineering coverage must be searchable and stay evidence-scoped."""
import copy
import unittest
from rndplz.data import Corpus
from rndplz.demo_pool import project_corpus, historical_person
from rndplz.engine import Engine
from rndplz.evidence_search import PublicEvidenceSearch
from rndplz.people_map import build_people_map, build_capabilities
from rndplz.public_profiles import restrict_personal_publication

CASES={
 'PUB-PANAGIOTOPOULOS':('열역학','thermodynamics'),
 'PUB-KISS':('반응증류','reactive distillation'),
 'PUB-LIVINGSTON':('나노여과','nanofiltration'),
 'PUB-DOHERTY':('결정화','polymorph'),
 'PUB-CURTIS':('다상유동','particle flow'),
 'PUB-MCKINLEY':('점탄성','rheology'),
 'PUB-PRATHER':('발효','fermentation'),
 'PUB-SEO-SANGWOO':('세포공장','synthetic biology'),
 'PUB-CHOI-JANGWOOK':('배터리 진단','battery diagnostics'),
 'PUB-SRINIVASAN':('공정안전','process safety'),
 'PUB-ELIMELECH':('담수화','desalination'),
 'PUB-JENSEN':('연속흐름','flow chemistry'),
 'PUB-ELHALWAGI':('기술경제성','process integration'),
 'PUB-GLADDEN':('자기공명','magnetic resonance'),
 'PUB-KIM-JONGHAK':('기체 분리','gas separation'),
 'PUB-HUBER':('폐플라스틱','waste plastics')
}

class ChemicalPoolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.full=Corpus()
        cls.corpus=project_corpus(cls.full)
        cls.engine=Engine(cls.corpus)

    def test_research_cards_have_owned_source_and_honest_status(self):
        self.assertEqual(self.full.errors,[])
        for pid in CASES:
            with self.subTest(pid=pid):
                p=self.corpus.people[pid]; records=self.corpus.by_person[pid]
                self.assertTrue(records)
                self.assertEqual(p.profile['collaboration_availability'],'미확인')
                self.assertFalse(p.profile['real_contact_enabled'])
                self.assertFalse(p.profile['current_employment_verified'])
                for r in records:
                    self.assertTrue(r.source_url.startswith('https://'))
                    self.assertEqual(r.scope,'public_research_case')
                    self.assertTrue(any(c.person_id==pid for c in r.people))
                    if r.kind=='public_profile_record':
                        self.assertEqual(r.details['publication_type'],'official_research_profile')
                        self.assertFalse(r.details['abstract_available'])
                        if not r.date:
                            self.assertNotEqual(r.date,r.checked_at)

    def test_korean_and_english_searches_reach_all_added_people(self):
        search=PublicEvidenceSearch(self.engine)
        for pid,queries in CASES.items():
            for query in queries:
                with self.subTest(person=pid,query=query):
                    result=search.search({'intent':'search','lookup_action':'execute',
                      'interpretations':[{'label':query,'groups':[{'topic_ids':[],'queries':[query]}]}]})
                    self.assertIn(pid,[p['id'] for p in result['candidates']])

    def test_every_new_card_has_a_real_category_edge(self):
        payload=build_people_map(self.engine)
        found=set()
        for category in payload['capabilities']:
            for link in category['people']:
                own={r.id for r in self.corpus.by_person[link['id']]}
                self.assertTrue(link['recordIds'])
                self.assertLessEqual(set(link['recordIds']),own)
                found.add(link['id'])
        self.assertLessEqual(set(CASES),found)
        self.assertEqual(payload['counts']['unlinked_records'],0)

    def test_public_projection_does_not_reintroduce_private_people(self):
        public=Corpus()
        restrict_personal_publication(public,[])
        view=project_corpus(public,allow_personal_omission=True)
        payload=build_people_map(Engine(view))
        self.assertFalse(any(p['id'].startswith('LOCAL-') for p in payload['people']))
        self.assertFalse(any(l['id'].startswith('LOCAL-') for c in payload['capabilities'] for l in c['people']))
        self.assertLessEqual(set(CASES),set(view.people))

    def test_missing_and_foreign_records_cannot_form_edges(self):
        view=copy.copy(self.corpus)
        owner='PUB-LIVINGSTON'; foreign='PUB-CURTIS'
        view.people={owner:view.people[owner]}
        record=self.corpus.by_person[foreign][0]
        view.records={record.id:record}
        view.by_person={owner:[record]}
        self.assertEqual(build_capabilities(view),[])

    def test_future_tagged_record_links_without_javascript_person_ids(self):
        view=copy.copy(self.corpus)
        person=copy.deepcopy(view.people['PUB-LIVINGSTON'])
        person.id='SYNTHETIC-FUTURE-MEMBRANE'
        record=copy.deepcopy(view.by_person['PUB-LIVINGSTON'][0])
        record.id='SYNTHETIC-FUTURE-RECORD'
        record.people[0].person_id=person.id
        view.people={person.id:person}; view.records={record.id:record}; view.by_person={person.id:[record]}
        categories=build_capabilities(view)
        membrane=next(c for c in categories if c['id']=='membranes')
        self.assertEqual(membrane['people'][0]['recordIds'],[record.id])
        self.assertEqual(membrane['people'][0]['id'],person.id)

    def test_prior_status_and_exclusion_are_preserved(self):
        self.assertNotIn('PUB-LEE-SANGYUP',self.corpus.people)
        self.assertTrue(historical_person(self.corpus.people['PUB-GRUBBS']))
        self.assertTrue(self.corpus.people['PUB-DOHERTY'].profile['retired_or_emeritus'])
        kwon=self.corpus.records['PUBLIC-KWON-LG-RND']
        self.assertEqual(kwon.scope,'public_profile')

if __name__=='__main__':unittest.main()
