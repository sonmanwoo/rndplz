"""A person's own introduction link (a personal site) reaches the map and the person API as a link.

2026-10-05: 손만우 asked to point his card at his scroll resume on GitHub Pages so people see that a
profile can be introduced in one's own way. The link is data only: never fetched, never evidence.
"""
import json
import unittest
from pathlib import Path

from rndplz.people_map import PROFILE_KEYS
from tests.test_person_card import public_engine


class ProfileLinkTests(unittest.TestCase):
    def test_the_resume_link_is_well_formed_and_passes_through(self):
        data = json.loads((Path(__file__).resolve().parents[1] / 'rndplz' / 'featured_people.json').read_text(encoding='utf-8'))
        me = next(p for p in data['people'] if p['id'] == 'LOCAL-MANWOO')
        self.assertEqual([link['url'] for link in me['links']], ['https://sonmanwoo.github.io/BioProcess_Lab/resume/'])
        self.assertTrue(all(link['url'].startswith('https://') and link['label'] for link in me['links']))
        self.assertIn('links', PROFILE_KEYS)
        engine = public_engine()
        profile = engine.corpus.people['LOCAL-MANWOO'].profile
        self.assertEqual(profile['links'][0]['kind'], 'personal_site')
        for person in engine.corpus.people.values():  # no other card carries a link by accident
            for link in person.profile.get('links', []):
                self.assertTrue(link['url'].startswith('https://'))


if __name__ == '__main__':
    unittest.main()
