"""Gemma reads a whole private profile document in parts and proposes typed items.

Model quality is compared with a Claude reading on local Ollama outside the suite; these tests
cover the mechanics with a scripted model: parts, quote checks, merge ids, the per-instance text
limit, typed saves (skills append, careers keep title/period/role), the web route and a
document sent in chunks.
"""
import base64
import hashlib
import io
import json
import tempfile
import unittest
import uuid
from http.cookies import SimpleCookie
from pathlib import Path

from rndplz.attachments import Attachments, MAX_TEXT
from rndplz.profile_reading import (MAP_CONTRACT, MERGE_CONTRACT, PART_CHARS, ProfileReader, finalize,
                                    locate, split_parts, verify_part)
from rndplz.profiles import Profiles


def document(lines=900):
    rows = ['기술연구소 근무 기간 2024-2025, 촉매 반응기 최적화 담당.']
    for index in range(lines):
        rows.append(f'{index + 1}. 저는 촉매 반응기 운전 데이터를 분석하고 베이지안 최적화로 조건을 찾았습니다 (구간 {index}).')
    return '\n'.join(rows) + '\n'


class ScriptedModels:
    """Quotes the first line of each part (with a line break inside) and merges by id."""

    def __init__(self):
        self.calls = []

    def get(self, identifier):
        return {'id': identifier, 'provider': 'bridge', 'enabled': True}

    def stream(self, identifier, messages, *, contract=None):
        payload = json.loads(messages[0]['content'])
        self.calls.append(contract)
        if contract == MAP_CONTRACT:
            first = payload['text'].split('\n', 1)[0]
            quote = first[:20] + '\n' + first[20:60]  # whitespace differs from the text
            yield json.dumps({'careers': [{'title': '촉매 반응기 최적화', 'organization': '기술연구소', 'period': '2024-2025',
                                           'role': '분석 담당', 'description': '운전 데이터로 조건을 찾았습니다.', 'quote': quote,
                                           'performer': 'user'}],
                              'skills': [{'value': '베이지안 최적화', 'quote': quote, 'performer': 'user'},
                                         {'value': '지어낸 기술', 'quote': '원문에 없는 문장입니다 아주 길게', 'performer': 'user'},
                                         {'value': '에이전트가 한 분석', 'quote': quote, 'performer': 'system'}],
                              'interests': []}, ensure_ascii=False)
        elif contract == MERGE_CONTRACT:
            ids = [row['id'] for row in payload['candidates']]
            careers = [i for i in ids if i.startswith('c')]
            skills = [i for i in ids if i.startswith('s')]
            yield json.dumps({'careers': [{'title': '촉매 반응기 최적화', 'organization': '기술연구소', 'period': '2024-2025',
                                           'role': '분석 담당', 'description': '운전 데이터로 조건을 찾았습니다.', 'from': careers[:3]}],
                              'skills': [{'value': '베이지안 최적화', 'from': skills[:2]}, {'value': '출처 없는 기술', 'from': ['s999']}],
                              'interests': []}, ensure_ascii=False)
        else:
            raise AssertionError(contract)


class MechanicsTests(unittest.TestCase):
    def test_parts_cover_the_text_and_cut_at_lines(self):
        text = document()
        parts = split_parts(text)
        self.assertEqual(''.join(chunk for _, chunk in parts), text)
        self.assertTrue(all(len(chunk) <= PART_CHARS for _, chunk in parts))
        self.assertTrue(all(chunk.endswith('\n') for _, chunk in parts[:-1]))
        self.assertEqual(split_parts(text), parts)

    def test_quotes_are_located_ignoring_line_breaks(self):
        text = '가나다 라마바\n사아자 차카타 파하'
        self.assertEqual(text[slice(*locate('라마바 사아자 차카타', text))], '라마바\n사아자 차카타')
        self.assertIsNone(locate('없는 문장입니다 정말로', text))
        self.assertIsNone(locate('가나', text))  # too short to be evidence

    def test_unquoted_items_are_dropped(self):
        value = {'careers': [{'title': 'A', 'organization': '', 'period': '', 'role': '', 'description': 'B', 'quote': '라마바 사아자 차카타', 'performer': 'user'},
                             {'title': '', 'organization': '', 'period': '', 'role': '', 'description': 'B', 'quote': '라마바 사아자 차카타', 'performer': 'user'}],
                 'skills': [{'value': '분석', 'quote': '지어낸 근거 문장입니다 길게', 'performer': 'user'}], 'interests': []}
        kept, dropped = verify_part(value, '가나다 라마바\n사아자 차카타 파하', 100)
        self.assertEqual((len(kept), dropped), (1, 2))
        self.assertEqual((kept[0]['start'], kept[0]['quote']), (104, '라마바\n사아자 차카타'))

    def test_work_done_by_a_system_is_not_the_users_skill(self):
        text = '가나다 라마바\n사아자 차카타 파하'
        quote = '라마바 사아자 차카타'
        value = {'careers': [{'title': 'A', 'organization': '', 'period': '', 'role': 'user', 'description': 'B', 'quote': quote, 'performer': 'unclear'}],
                 'skills': [{'value': '설계', 'quote': quote, 'performer': 'user'}, {'value': '검정', 'quote': quote, 'performer': 'system'},
                            {'value': '분석', 'quote': quote, 'performer': 'team'}],
                 'interests': [{'value': '관심', 'quote': quote}]}
        kept, dropped = verify_part(value, text, 0)
        self.assertEqual(([row.get('value', row.get('title')) for row in kept], dropped), (['A', '설계', '관심'], 2))
        self.assertEqual(kept[0]['role'], '')  # a performer label in a field is cleared

    def test_reading_prefers_26b_when_offered(self):
        class Catalog(ScriptedModels):
            def catalog(self, refresh=False):
                row = {'provider': 'bridge', 'enabled': True}
                return {'models': [{**row, 'id': 'bridge', 'model': 'gemma4:e4b'}, {**row, 'id': 'bridge:gemma4:26b', 'model': 'gemma4:26b'}]}
        self.assertEqual(ProfileReader(Catalog())._model('bridge'), 'bridge:gemma4:26b')
        self.assertEqual(ProfileReader(ScriptedModels())._model('bridge'), 'bridge')

    def test_finalize_cites_candidates_and_skips_present_items(self):
        candidates = [{'id': 's1', 'kind': 'skills', 'value': 'DOE', 'quote': 'q1', 'start': 0, 'end': 2},
                      {'id': 's2', 'kind': 'skills', 'value': 'PatchCore', 'quote': 'q2', 'start': 5, 'end': 7}]
        value = {'careers': [], 'skills': [{'value': 'DOE', 'from': ['s1']}, {'value': 'PatchCore', 'from': ['s2']},
                                           {'value': 'Made up', 'from': ['s9']}], 'interests': []}
        proposals = finalize(value, candidates, {'skills': ['doe'], 'interests': [], 'career_titles': []})
        self.assertEqual([(p['field'], p['after'], p['quote']) for p in proposals], [('skills', 'PatchCore', 'q2')])

    def test_numbers_must_exist_in_the_document(self):
        candidates = [{'id': 'c1', 'kind': 'careers', 'quote': 'q', 'start': 0, 'end': 1}]
        row = {'title': '반응기 최적화', 'organization': '', 'role': '', 'from': ['c1']}
        text = '2023년부터 반응기 수율을 12.5% 높였다.'
        value = {'careers': [{**row, 'period': '2021-2022', 'description': '수율을 12.5% 높였다.'}], 'skills': [], 'interests': []}
        self.assertEqual(finalize(value, candidates, {}, text)[0]['career']['period'], '')  # invented period is cleared
        value = {'careers': [{**row, 'period': '2023', 'description': '수율을 40% 높였다.'}], 'skills': [], 'interests': []}
        self.assertEqual(finalize(value, candidates, {}, text), [])  # an invented metric drops the proposal


class ProfileFlowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

        class Store:
            def __init__(self, directory):
                self.directory, self.state = Path(directory), {}

            def read(self):
                return json.loads(json.dumps(self.state))

            def transaction(self, change):
                state = json.loads(json.dumps(self.state))
                result = change(state)
                self.state = state
                return result

        self.store = Store(self.tmp.name)
        self.models = ScriptedModels()
        self.profiles = Profiles(self.store, public=True, reader=ProfileReader(self.models))

    def request(self, **payload):
        return {**payload, 'base_version': self.profiles.read()['profile']['version'], 'request_id': 'req-' + uuid.uuid4().hex}

    def test_whole_document_to_typed_saves(self):
        text = document()
        self.assertGreater(len(text), MAX_TEXT)
        view = self.profiles.upload(self.request(name='cv.txt', data=base64.b64encode(text.encode()).decode()))
        source = view['sources'][0]
        self.assertFalse(source['truncated'])
        total = len(split_parts(text))
        for part in range(1, total + 1):
            result = self.profiles.read_part({'source_id': source['id'], 'part': part, 'model_id': 'bridge'})
            self.assertEqual((result['total'], result['kept'], result['dropped']), (total, 2, 2))
        self.assertTrue(result['done'])
        again = self.profiles.read_part({'source_id': source['id'], 'part': 1, 'model_id': 'bridge'})
        self.assertEqual(self.models.calls.count(MAP_CONTRACT), total)  # a read part is cached
        self.assertTrue(again['done'])
        version = self.profiles.read()['profile']['version']
        view = self.profiles.suggest(self.request(source_ids=[source['id']], model_id='bridge'))
        self.assertEqual(view['profile']['version'], version + 1)
        typed = [p for p in view['suggestions'] if p['method'] == 'model_reading']
        self.assertEqual(sorted(p['field'] for p in typed), ['career', 'skills'])
        career = next(p for p in typed if p['field'] == 'career')
        self.assertEqual(career['career']['period'], '2024-2025')
        self.assertIn(career['quote'].replace('\n', ''), text.replace('\n', ''))
        self.profiles.save(self.request(fields={'skills': 'Python'}))
        view = self.profiles.suggest(self.request(source_ids=[source['id']]))  # refresh re-bases, adds no paragraphs
        self.assertFalse(any(p['method'] == 'paragraph_rules' for p in view['suggestions']))
        decisions = [{'id': p['id'], 'decision': 'accept', 'field': p['field']} for p in typed]
        view = self.profiles.save(self.request(fields={}, decisions=decisions))
        self.assertEqual(view['profile']['fields']['skills'], 'Python, 베이지안 최적화')
        saved = view['profile']['careers'][0]
        self.assertEqual((saved['title'], saved['period'], saved['role']), ('촉매 반응기 최적화', '2024-2025', '분석 담당'))

    def test_merge_needs_every_part(self):
        view = self.profiles.upload(self.request(name='cv.txt', data=base64.b64encode(document().encode()).decode()))
        source = view['sources'][0]
        self.profiles.read_part({'source_id': source['id'], 'part': 1, 'model_id': 'bridge'})
        with self.assertRaises(Exception) as caught:
            self.profiles.suggest(self.request(source_ids=[source['id']], model_id='bridge'))
        self.assertEqual(getattr(caught.exception, 'code', None), 'reading_incomplete')

    def test_chat_attachments_keep_their_limit(self):
        chat = Attachments(Path(self.tmp.name) / 'chat')
        item = chat.upload({'name': 'long.txt', 'data': base64.b64encode(document().encode()).decode()})
        self.assertTrue(item['truncated'])
        self.assertLessEqual(len(chat.load(item['id'])['text']), MAX_TEXT)


class WebTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from rndplz.public_web import PublicApp
        cls.tmp = tempfile.TemporaryDirectory()
        cls.app = PublicApp(state_dir=Path(cls.tmp.name) / 'state', env={
            'RNDPLZ_LOCAL_PREVIEW': '1', 'RNDPLZ_SESSION_SECRET': 's' * 64,
            'RNDPLZ_PUBLIC_PERSON_IDS': 'LOCAL-MANWOO,LOCAL-JINHO,LOCAL-DASOL,LOCAL-HONG'})

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def call(self, method, path, body=None):
        raw = json.dumps(body, ensure_ascii=False).encode() if body is not None else b''
        environ = {'REQUEST_METHOD': method, 'PATH_INFO': path, 'QUERY_STRING': '', 'HTTP_HOST': '127.0.0.1',
                   'wsgi.input': io.BytesIO(raw), 'CONTENT_LENGTH': str(len(raw)), 'wsgi.url_scheme': 'http',
                   'HTTP_COOKIE': '; '.join(k + '=' + v for k, v in self.cookies.items())}
        if method == 'POST':
            environ.update(CONTENT_TYPE='application/json', HTTP_ORIGIN='http://127.0.0.1', HTTP_X_RNDPLZ_TOKEN=self.token)
        captured = {}

        def start_response(status, headers):
            captured['status'], captured['headers'] = int(status.split()[0]), headers

        payload = b''.join(self.app(environ, start_response))
        for key, value in captured['headers']:
            if key.lower() == 'set-cookie':
                cookie = SimpleCookie()
                cookie.load(value)
                for name, morsel in cookie.items():
                    self.cookies[name] = morsel.value
        return captured['status'], json.loads(payload) if payload[:1] == b'{' else None

    def test_large_document_reads_through_the_route(self):
        from rndplz.profile_reading import ProfileReader
        self.cookies, self.token = {}, ''
        self.token = self.call('GET', '/api/chat/bootstrap')[1]['token']
        context = list(self.app.contexts.values())[-1]  # this visitor (the newest context)
        context['profile'].reader = ProfileReader(ScriptedModels())
        big = (document() * 3).encode()  # ~0.6 MB of text, 1.6 MB with padding below
        big += b'\n' + ('여백 ' * 330000).encode()
        self.assertGreater(len(big), 1024 * 1024)
        body = {'action': 'upload', 'turn_id': 'turn-upload-000000001',
                'payload': {'name': 'cv.txt', 'data': base64.b64encode(big).decode(), 'base_version': 0, 'request_id': 'upload-0000001'}}
        status, view = self.call('POST', '/api/self-profile/chat', body)
        self.assertEqual(status, 200, view)
        source = view['profile_view']['sources'][0]
        self.assertEqual(view['profile_view']['limits']['extraction'], 'model_reading')
        status, result = self.call('POST', '/api/self-profile/read-part', {'source_id': source['id'], 'part': 1, 'model_id': 'bridge'})
        self.assertEqual((status, result['part'], result['kept'], result['dropped']), (200, 1, 2, 2))
        status, result = self.call('POST', '/api/self-profile/read-part', {'source_id': source['id'], 'part': 0, 'model_id': 'bridge'})
        self.assertEqual(status, 400)

    def test_a_document_sent_in_chunks_is_claimed_by_the_profile(self):
        # One 8 MB request failed from a phone; chat attachments already went in 512 KB chunks.
        from rndplz.attachment_uploads import CHUNK_BYTES
        self.cookies, self.token = {}, ''
        self.token = self.call('GET', '/api/chat/bootstrap')[1]['token']
        raw = (document() * 6).encode()  # two pieces
        self.assertGreater(len(raw), CHUNK_BYTES)
        status, begin = self.call('POST', '/api/attachments/begin', {'name': 'cv.txt', 'size': len(raw),
                                                                     'sha256': hashlib.sha256(raw).hexdigest()})
        self.assertEqual(status, 200, begin)
        turn = {'action': 'upload', 'turn_id': 'turn-chunked-000000001',
                'payload': {'upload_id': begin['upload_id'], 'base_version': 0, 'request_id': 'chunked-0000001'}}
        status, body = self.call('POST', '/api/self-profile/chat', {**turn, 'turn_id': 'turn-chunked-000000000'})
        self.assertEqual((status, body['code']), (409, 'attachment_upload_incomplete'))  # not every piece yet
        for index in range(begin['chunk_count']):
            piece = raw[index * CHUNK_BYTES:(index + 1) * CHUNK_BYTES]
            status, got = self.call('POST', '/api/attachments/chunk', {'upload_id': begin['upload_id'], 'index': index,
                                                                       'data': base64.b64encode(piece).decode()})
            self.assertEqual(status, 200, got)
        status, view = self.call('POST', '/api/self-profile/chat', turn)
        self.assertEqual(status, 200, view)
        sources = view['profile_view']['sources']
        self.assertEqual([(s['name'], s['size']) for s in sources], [('cv.txt', len(raw))])
        status, again = self.call('POST', '/api/self-profile/chat', turn)  # a retried turn: its record answers
        self.assertEqual((status, len(again['profile_view']['sources'])), (200, 1))
        other = {**turn, 'turn_id': 'turn-chunked-000000002', 'payload': {**turn['payload'], 'request_id': 'chunked-0000002'}}
        status, body = self.call('POST', '/api/self-profile/chat', other)
        self.assertEqual((status, body['code']), (410, 'attachment_upload_expired'))  # claimed once, staging gone


if __name__ == '__main__':
    unittest.main()
