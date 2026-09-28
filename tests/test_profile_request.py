"""Gemma's reading of a profile sentence is kept only where the user wrote the value.

Model quality is measured by tests/eval_profile_request.py on local Ollama; these tests
cover the contract registration, the grounding rules and which model reads the sentence.
"""
import unittest

from rndplz.chat_models import OLLAMA_DETERMINISTIC_CONTRACTS, OLLAMA_NO_THINK_CONTRACTS, generation_spec
from rndplz.profile_reading import REQUEST_CONTRACT, ProfileReader, validate_request

SNAPSHOT = {'name': '', 'organization': '공정기술팀', 'role': '', 'skills': ['Python', 'Aspen Plus'],
            'interests': ['결정화'], 'career_titles': []}


class ContractTests(unittest.TestCase):
    def test_contract_is_registered_for_server_and_worker(self):
        spec = generation_spec(REQUEST_CONTRACT)
        self.assertEqual(spec['format']['properties']['kind']['enum'], ['edit', 'document', 'help'])
        self.assertIn(REQUEST_CONTRACT, OLLAMA_NO_THINK_CONTRACTS)
        self.assertIn(REQUEST_CONTRACT, OLLAMA_DETERMINISTIC_CONTRACTS)
        from rndplz.gemma_bridge import _worker_capabilities
        self.assertIn(REQUEST_CONTRACT, _worker_capabilities())


class GroundingTests(unittest.TestCase):
    def check(self, text, value):
        return validate_request(value, text, SNAPSHOT)

    def test_values_must_be_the_users_words(self):
        plan = self.check('소속이 바이오 공정팀으로 바뀌었어요', {'kind': 'edit', 'careers': [], 'edits': [
            {'action': 'set', 'field': 'organization', 'value': '바이오공정팀'},  # spacing differs: still the user's words
            {'action': 'set', 'field': 'role', 'value': '팀장'}]})
        self.assertEqual(plan, {'kind': 'edit', 'careers': [],
                                'edits': [{'action': 'set', 'field': 'organization', 'value': '바이오공정팀'}]})

    def test_list_fields_add_and_remove_only_existing_entries(self):
        plan = self.check('기술에서 python 빼고 CFD 넣어줘, 관심 분야 증류는 빼줘', {'kind': 'edit', 'careers': [], 'edits': [
            {'action': 'remove', 'field': 'skills', 'value': 'python'},
            {'action': 'set', 'field': 'skills', 'value': 'CFD'},
            {'action': 'remove', 'field': 'interests', 'value': '증류'},  # not in the profile
            {'action': 'add', 'field': 'organization', 'value': 'CFD'}]})  # add is for lists only
        self.assertEqual(plan['edits'], [{'action': 'remove', 'field': 'skills', 'value': 'python'},
                                         {'action': 'add', 'field': 'skills', 'value': 'CFD'}])

    def test_career_details_the_user_did_not_say_are_blank(self):
        plan = self.check('작년부터 폐플라스틱 열분해 과제 PM을 맡았어요', {'kind': 'edit', 'edits': [], 'careers': [
            {'title': '폐플라스틱 열분해 과제', 'organization': 'GS칼텍스', 'period': '2025-현재', 'role': 'PM',
             'description': '열분해 공정 개선을 주도'},
            {'title': '촉매 개발', 'organization': '', 'period': '', 'role': '', 'description': ''}]})
        self.assertEqual(plan['careers'], [{'title': '폐플라스틱 열분해 과제', 'organization': '', 'period': '',
                                            'role': 'PM', 'description': ''}])
        # A reworded period stays when its numbers were said; an invented end year does not.
        periods = [self.check('2019년 3월부터 2022년 말까지 여수공장 운전 엔지니어로 일했어요', {'kind': 'edit', 'edits': [], 'careers': [
            {'title': '운전 엔지니어', 'organization': '', 'period': period, 'role': '', 'description': ''}]})['careers'][0]['period']
            for period in ('2019년 3월 - 2022년 말', '2019-2023')]
        self.assertEqual(periods, ['2019년 3월 - 2022년 말', ''])
        # No project name: the job line is the title. A career repeated as an interest is the career only.
        plan = self.check('경력 추가: 2019~2022 여수공장 운전 엔지니어', {'kind': 'edit', 'careers': [
            {'title': '', 'organization': '여수공장', 'period': '2019~2022', 'role': '운전 엔지니어', 'description': ''}],
            'edits': [{'action': 'add', 'field': 'interests', 'value': '운전 엔지니어'}]})
        self.assertEqual((plan['edits'], plan['careers'][0]['title'], plan['careers'][0]['period']), ([], '운전 엔지니어', '2019~2022'))

    def test_edits_that_change_nothing_are_dropped(self):
        plan = self.check('예전 소속은 공정기술팀이었고 기술에 Python 있어요', {'kind': 'edit', 'careers': [], 'edits': [
            {'action': 'set', 'field': 'organization', 'value': '공정기술팀'},
            {'action': 'add', 'field': 'skills', 'value': 'Python'}]})
        self.assertEqual(plan, {'kind': 'help', 'edits': [], 'careers': []})

    def test_an_edit_without_grounded_values_becomes_help(self):
        for value in ({'kind': 'edit', 'edits': [{'action': 'set', 'field': 'bio', 'value': '공정 전문가'}], 'careers': []},
                      {'kind': 'delete_account'}, {}):
            with self.subTest(value=value):
                self.assertEqual(self.check('소개 좀 멋있게 바꿔줘', value), {'kind': 'help', 'edits': [], 'careers': []})
        self.assertEqual(self.check('이력서로 채워줘', {'kind': 'document', 'edits': [], 'careers': []})['kind'], 'document')
        # Grounded content outweighs the label (e4b filled a career and called it a document request).
        plan = self.check('새 과제 시작했어요: 바이오 항공유 전처리. 경력에 넣어 줘', {'kind': 'document', 'edits': [], 'careers': [
            {'title': '바이오 항공유 전처리', 'organization': '', 'period': '', 'role': '', 'description': ''}]})
        self.assertEqual((plan['kind'], len(plan['careers'])), ('edit', 1))


class ModelChoiceTests(unittest.TestCase):
    class Models:
        def __init__(self):
            row = {'provider': 'bridge', 'enabled': True}
            self.rows = [{**row, 'id': 'bridge', 'model': 'gemma4:e4b'}, {**row, 'id': 'bridge:gemma4:e2b', 'model': 'gemma4:e2b'},
                         {**row, 'id': 'bridge:gemma4:26b', 'model': 'gemma4:26b'}]
            self.used = []

        def get(self, identifier):
            return next(m for m in self.rows if m['id'] == identifier)

        def catalog(self, refresh=False):
            return {'models': self.rows}

        def stream(self, identifier, messages, *, contract=None):
            self.used.append(identifier)
            yield '{"kind":"help","edits":[],"careers":[]}'

    def test_the_chat_model_reads_the_sentence_but_e2b_hands_it_to_e4b(self):
        models = self.Models()
        reader = ProfileReader(models)
        for chosen in ('bridge', 'bridge:gemma4:26b', 'bridge:gemma4:e2b'):
            reader.interpret(chosen, '프로필 도와줘', SNAPSHOT)
        self.assertEqual(models.used, ['bridge', 'bridge:gemma4:26b', 'bridge'])


if __name__ == '__main__':
    unittest.main()
