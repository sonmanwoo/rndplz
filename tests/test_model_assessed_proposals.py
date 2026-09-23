"""A person the model assessed as direct or adjacent may receive a proposal.

Until 2026-09-23 a candidate found through the model-led lookup stayed
lookup_only unless the older rule-based discovery independently agreed, which
it almost never did for model-led conversations, so every person card said the
request could not be sent.
"""
import unittest

from rndplz.model_conversation import ModelConversation


def candidate(pid, name, record_ids):
    return {'id': pid, 'name': name, 'virtual': False, 'lookup_only': True, 'proposal_allowed': False,
            'proposal_unavailable_reason': '관련 기록 열람 결과입니다.',
            'evidence': [{'id': rid, 'title': rid} for rid in record_ids], 'matching_interpretations': []}


def assessed(rows):
    result = {'candidates': [candidate('P-MW', 'Manwoo Son', ['R-MONO', 'R-BIO']),
                             candidate('P-CAT', 'Catalyst Person', ['R-CAT']),
                             candidate('P-NONE', 'Nobody', ['R-X'])],
              'evidence': [], 'matching_record_ids': ['R-MONO', 'R-BIO', 'R-CAT', 'R-X'],
              'lookup_only': True, 'proposal_allowed': False, 'can_propose': False}
    assessment = {'assessments': rows}
    return ModelConversation._assessed_result(None, result, assessment, '답변')


class ModelAssessedProposalTests(unittest.TestCase):
    def test_direct_and_adjacent_people_become_proposable(self):
        value = assessed([
            {'person_id': 'P-MW', 'relation': 'direct', 'text': '증류 경험', 'missing': '',
             'evidence': [{'record_id': 'R-MONO', 'quote': 'q'}]},
            {'person_id': 'P-CAT', 'relation': 'adjacent', 'text': '촉매', 'missing': '증류 없음',
             'evidence': [{'record_id': 'R-CAT', 'quote': 'q'}]},
            {'person_id': 'P-NONE', 'relation': 'insufficient', 'text': '무관', 'missing': '', 'evidence': []},
        ])
        cards = {c['id']: c for c in value['candidates']}
        self.assertEqual(set(cards), {'P-MW', 'P-CAT'})
        for card in cards.values():
            self.assertFalse(card['lookup_only'])
            self.assertTrue(card['proposal_allowed'])
            self.assertEqual(card['proposal_unavailable_reason'], '')
            self.assertEqual(card['proposal_basis'], 'model_assessment')
        self.assertEqual([e['id'] for e in cards['P-MW']['evidence']], ['R-MONO'])
        self.assertTrue(value['can_propose'])
        self.assertTrue(value['proposal_allowed'])
        self.assertFalse(value['lookup_only'])

    def test_insufficient_only_keeps_the_lookup_read_only(self):
        value = assessed([
            {'person_id': 'P-MW', 'relation': 'insufficient', 'text': '무관', 'missing': '', 'evidence': []},
        ])
        self.assertEqual(value['candidates'], [])
        self.assertFalse(value['can_propose'])
        self.assertTrue(value['lookup_only'])
        self.assertEqual(value['lookup_resolution'], 'no_purpose_supported_records')


if __name__ == '__main__':
    unittest.main()
