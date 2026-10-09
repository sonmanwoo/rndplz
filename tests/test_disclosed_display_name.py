"""A person already shown in the conversation may be named by any of their names in a follow-up answer.

Production 2026-10-09: after a lookup showed three people, "바이오 유래물질 전문가가 세명 중 누구니?" was answered
with "손만우(Manwoo Son)" and rejected as a new identity, because only the record name and id were kept as disclosed.
"""
import tempfile
import unittest
from types import SimpleNamespace

from rndplz.domain import Person
from rndplz.model_dialogue import PlanValidationError


def conversation(people):
    from rndplz.conversation import Conversation
    from rndplz.engine import Engine
    from rndplz.models import ExternalModel
    from rndplz.service import Service

    directory = tempfile.TemporaryDirectory(prefix='rndplz-disclosed-')
    corpus = SimpleNamespace(people={p.id: p for p in people}, records={}, by_person={}, topics=[], topic_by_id={},
                             questions=[], errors=[])
    service = Service(Engine(corpus), directory.name + '/state',
                      ExternalModel({'RNDPLZ_PROVIDER': 'none', 'RNDPLZ_MODEL_CALL_LIMIT': '0'}), state_env={})
    return directory, Conversation(service, SimpleNamespace())


MANWOO = Person('LOCAL-MANWOO', 'Manwoo Son',
                profile={'aliases': ['손만우', 'manwooson', 'Manwoo Son', 'Son Manwoo'], 'display_name': '손만우'})
DOHERTY = Person('PUB-DOHERTY', 'Michael F. Doherty',
                 profile={'aliases': ['Michael F. Doherty', 'Michael Doherty']})
HONG = Person('LOCAL-HONG', 'Gildong Hong', profile={'aliases': ['홍길동']})
SOURCES = [{'text': '바이오 유래물질 전문가가 세명 중 누구니?'}]
SHOWN = [{'people': [{'id': 'LOCAL-MANWOO', 'name': 'Manwoo Son'}, {'id': 'PUB-DOHERTY', 'name': 'Michael F. Doherty'}]}]


def reply(text):
    return {'reply': text, 'summary': '', 'person_names': [], 'conditions': []}


class DisclosedDisplayNameTests(unittest.TestCase):
    def setUp(self):
        self.directory, self.chat = conversation([MANWOO, DOHERTY, HONG])
        self.addCleanup(self.directory.cleanup)

    def test_shown_person_named_by_korean_display_name_or_alias(self):
        self.chat._check_consultation_reply(reply('관련 경력이 확인되는 분은 **손만우(Manwoo Son)** 님입니다.'), SOURCES, SHOWN)
        self.chat._check_consultation_reply(reply('Michael Doherty 님은 결정화 설계 쪽입니다.'), SOURCES, SHOWN)

    def test_person_not_shown_is_still_rejected_by_any_name(self):
        for text in ('홍길동 님도 있습니다.', 'Gildong Hong 님도 있습니다.', 'LOCAL-HONG'):
            with self.assertRaises(PlanValidationError) as caught:
                self.chat._check_consultation_reply(reply(text), SOURCES, SHOWN)
            self.assertEqual(caught.exception.reason, 'consultation_identity_disclosure')

    def test_nothing_shown_yet_keeps_rejecting_corpus_names(self):
        with self.assertRaises(PlanValidationError):
            self.chat._check_consultation_reply(reply('손만우 님이 맞습니다.'), SOURCES, [])

    def test_shown_name_in_conditions_is_still_rejected(self):
        plan = {**reply('조건을 정리했어요.'), 'conditions': [{'text': '손만우와 같은 경력'}]}
        with self.assertRaises(PlanValidationError):
            self.chat._check_consultation_reply(plan, SOURCES, SHOWN)


if __name__ == '__main__':
    unittest.main()
