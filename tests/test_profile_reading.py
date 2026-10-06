"""The company AI reads a whole private profile document once and proposes card changes.

2026-10-06: the 9,000-character part reading with quotes and a merge was built for the
operator-PC Gemma; the company AI (AiU) reads a 70-page note in one call. These tests cover the
mechanics with a scripted model: one call within the input budget, what the server keeps (new
items, numbers and wording the document states), the profile app falling back to the chat's app,
the cache beside the draft, deletion, the web route and a document sent in chunks.
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
from rndplz.chat_models import AIU_PROFILE_APP, AiuRejected, ChatModels
from rndplz.profile_reading import DIGEST_CONTRACT, DOCUMENT_CHARS, ProfileReader, ReadingError, finish_digest
from rndplz.profiles import ProfileError, Profiles


def document(lines=900):
    rows = ['기술연구소 근무 기간 2024-2025, 촉매 반응기 최적화 담당.']
    for index in range(lines):
        rows.append(f'{index + 1}. 저는 촉매 반응기 운전 데이터를 분석하고 베이지안 최적화로 조건을 찾았습니다 (구간 {index}).')
    return '\n'.join(rows) + '\n'


PROPOSAL = {'summary': '촉매 반응기 운전 기록', 'bio_addition': '촉매 반응기 운전 데이터를 분석해 베이지안 최적화로 조건을 찾았습니다.',
            'skills': ['베이지안 최적화', '운전 데이터 분석'], 'interests': ['반응기 최적화'],
            'careers': [{'title': '촉매 반응기 최적화', 'organization': '기술연구소', 'period': '2024-2025', 'role': '최적화 담당',
                         'description': '운전 데이터로 반응 조건을 찾았습니다.'}]}


class DigestModels:
    """A scripted company AI: the profile app and the chat's app answer the digest contract."""

    def __init__(self, reject=()):
        self.calls, self.reject = [], set(reject)

    def get(self, identifier):
        if identifier not in ('aiu', AIU_PROFILE_APP):
            raise ValueError('not configured')
        return {'id': identifier, 'provider': 'aiu', 'enabled': True}

    def stream(self, identifier, messages, *, contract=None):
        if contract != DIGEST_CONTRACT:
            raise AssertionError(contract)
        self.calls.append((identifier, json.loads(messages[0]['content'])))
        if identifier in self.reject:
            raise AiuRejected('사내 AI가 요청을 거절했습니다 (HTTP 400).')
        yield json.dumps(PROPOSAL, ensure_ascii=False)


CARD = {'name': '홍길동', 'organization': '', 'role': '', 'bio': '', 'skills': [], 'interests': [], 'careers': []}


class DigestTests(unittest.TestCase):
    def test_one_call_reads_the_document_within_the_input_budget(self):
        models = DigestModels()
        text = document()
        model_id, proposal = ProfileReader(models).digest('cv.txt', text, CARD)
        self.assertEqual((model_id, len(models.calls)), (AIU_PROFILE_APP, 1))
        self.assertEqual(models.calls[0][1]['document'], text)
        self.assertEqual([c['title'] for c in proposal['careers']], ['촉매 반응기 최적화'])
        longer = text * 3
        ProfileReader(models).digest('cv.txt', longer, CARD)
        sent = models.calls[1][1]
        self.assertTrue(longer.startswith(sent['document']))
        self.assertLessEqual(len(json.dumps(sent['document'], ensure_ascii=False)), DOCUMENT_CHARS + 2)  # escaped line breaks count
        self.assertIn('읽지 않았습니다', sent['omitted'])

    def test_only_new_items_with_stated_numbers_and_wording_are_kept(self):
        text = '작성: 홍길동 책임. 2023년부터 반응기 수율을 12.5% 높였다. 기술연구소 공정팀에서 분석 담당으로 일했다.'
        card = {**CARD, 'skills': ['DOE'], 'careers': [{'title': '기존 과제', 'period': ''}]}
        career = {'organization': '', 'period': '', 'role': '', 'description': '반응기를 다뤘다.'}
        value = {'summary': ' 수율 개선 기록 ', 'bio_addition': '수율을 40% 높였습니다.',
                 'skills': ['doe', 'PatchCore', 'patchcore', ''], 'interests': ['반응기'],
                 'careers': [{'title': '반응기 수율 개선', 'organization': '기술연구소 공정팀', 'period': '2021-2022', 'role': '분석 담당',
                              'description': '수율을 12.5% 높였다.'},
                             {**career, 'title': '없는 성과', 'description': '수율을 40% 높였다.'},
                             {**career, 'title': '기존 과제'},
                             {**career, 'title': '역할 추측', 'period': '2023', 'role': '개발 총괄'},
                             {**career, 'title': '저자 표기', 'role': '홍길동 책임'}]}
        result = finish_digest(value, text, card)
        self.assertEqual((result['summary'], result['bio_addition']), ('수율 개선 기록', ''))  # an invented metric drops the sentence
        self.assertEqual((result['skills'], result['interests']), (['PatchCore'], ['반응기']))
        listed = {**card, 'skills': ['Taichi Lang 기반 GPU 수치 해석'], 'interests': ['베이지안 다목적 최적화']}
        repeated = finish_digest({'skills': ['Taichi Lang 수치 해석', '베이지안 다목적 최적화', 'Taichi Lang 메시 생성']}, text, listed)
        self.assertEqual(repeated['skills'], ['Taichi Lang 메시 생성'])  # every word already in one entry: not new
        self.assertEqual([c['title'] for c in result['careers']], ['반응기 수율 개선', '역할 추측', '저자 표기'])
        first, guessed, byline = result['careers']
        self.assertEqual((first['organization'], first['period'], first['role']), ('기술연구소 공정팀', '', '분석 담당'))
        self.assertEqual((guessed['period'], guessed['role']), ('2023', ''))  # "총괄" is not in the document
        self.assertEqual(byline['role'], '')  # the author line names the card owner, not a role
        numbered = finish_digest({'careers': [{**career, 'title': '사번 표기', 'role': '책임 (C18408)'}]}, text + ' C18408', card)
        self.assertEqual(numbered['careers'][0]['role'], '')  # nor is an employee number
        self.assertEqual(finish_digest({'bio_addition': '수율을 12.5% 높였습니다.'}, text, card)['bio_addition'], '수율을 12.5% 높였습니다.')
        said = {**card, 'bio': '반응기 수율을 12.5% 높였습니다.'}
        self.assertEqual(finish_digest({'bio_addition': '수율을 12.5% 높였습니다.'}, text, said)['bio_addition'], '')  # already in the biography

    def test_an_unpublished_profile_app_falls_back_to_the_chat_app(self):
        models = DigestModels(reject={AIU_PROFILE_APP})
        model_id, _ = ProfileReader(models).digest('cv.txt', document(5), CARD)
        self.assertEqual((model_id, [c[0] for c in models.calls]), ('aiu', [AIU_PROFILE_APP, 'aiu']))
        with self.assertRaises(ReadingError):
            ProfileReader(DigestModels(reject={AIU_PROFILE_APP, 'aiu'})).digest('cv.txt', document(5), CARD)

    def test_the_profile_app_is_not_a_chat_choice(self):
        models = ChatModels({'RNDPLZ_AIU_API_KEY': 'fixture-a', 'RNDPLZ_AIU_URL': 'https://api.aiu.gscaltex.com/ext/v1/workflows/run',
                             'RNDPLZ_AIU_PROFILE_API_KEY': 'fixture-b', 'RNDPLZ_OLLAMA_URL': 'http://127.0.0.1:9'})
        self.assertNotIn(AIU_PROFILE_APP, [m['id'] for m in models.catalog()['models']])
        self.assertEqual(models.get(AIU_PROFILE_APP)['provider'], 'aiu')
        self.assertEqual(ProfileReader(models).digest_models(), [AIU_PROFILE_APP, 'aiu'])
        without = ChatModels({'RNDPLZ_OLLAMA_URL': 'http://127.0.0.1:9'})
        with self.assertRaises(ReadingError):
            ProfileReader(without).digest('cv.txt', 'text', CARD)


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
        self.models = DigestModels()
        self.profiles = Profiles(self.store, public=True, reader=ProfileReader(self.models))

    def request(self, **payload):
        return {**payload, 'base_version': self.profiles.read()['profile']['version'], 'request_id': 'req-' + uuid.uuid4().hex}

    def upload(self, text=None):
        view = self.profiles.upload(self.request(name='cv.txt', data=base64.b64encode((text or document()).encode()).decode()))
        return view['operation']['source_id']

    def test_a_proposal_is_cached_and_changes_nothing_until_saved(self):
        identifier = self.upload()
        before = self.profiles.read()['profile']
        result = self.profiles.digest({'source_id': identifier})
        self.assertEqual((result['cached'], result['base_version'], result['name']), (False, before['version'], 'cv.txt'))
        self.assertEqual(result['proposal']['skills'], ['베이지안 최적화', '운전 데이터 분석'])
        self.assertEqual(self.profiles.read()['profile'], before)
        self.assertTrue(self.profiles.digest({'source_id': identifier})['cached'])
        self.assertEqual(len(self.models.calls), 1)
        self.profiles.save(self.request(fields={'skills': '베이지안 최적화'}))  # the card changed: read again
        again = self.profiles.digest({'source_id': identifier})
        self.assertEqual((again['cached'], again['proposal']['skills']), (False, ['운전 데이터 분석']))
        self.assertEqual(self.models.calls[-1][1]['current_card']['skills'], ['베이지안 최적화'])

    def test_deleting_a_document_removes_its_proposal(self):
        identifier = self.upload()
        self.profiles.digest({'source_id': identifier})
        cached = Path(self.tmp.name) / 'self-profile' / 'digests' / (identifier + '.json')
        self.assertTrue(cached.exists())
        self.profiles.source_action(self.request(id=identifier, action='delete'))
        self.assertFalse(cached.exists())
        with self.assertRaises(ProfileError):
            self.profiles.digest({'source_id': identifier})

    def test_without_a_reader_there_is_no_reading(self):
        profiles = Profiles(self.store, public=True)
        identifier = self.upload()
        with self.assertRaises(ProfileError) as caught:
            profiles.digest({'source_id': identifier})
        self.assertEqual(caught.exception.code, 'model_unavailable')
        self.assertEqual(profiles.read()['limits']['extraction'], 'paragraph_rules')
        self.assertEqual(self.profiles.read()['limits']['extraction'], 'ai_digest')

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

    def test_a_document_is_read_through_the_route(self):
        self.cookies, self.token = {}, ''
        self.token = self.call('GET', '/api/chat/bootstrap')[1]['token']
        context = list(self.app.contexts.values())[-1]  # this visitor (the newest context)
        context['profile'].reader = ProfileReader(DigestModels())
        body = {'action': 'upload', 'turn_id': 'turn-upload-000000001',
                'payload': {'name': 'cv.txt', 'data': base64.b64encode(document(40).encode()).decode(), 'base_version': 0,
                            'request_id': 'upload-0000001'}}
        status, view = self.call('POST', '/api/self-profile/chat', body)
        self.assertEqual(status, 200, view)
        source = view['profile_view']['sources'][0]
        self.assertEqual(view['profile_view']['limits']['extraction'], 'ai_digest')
        status, result = self.call('POST', '/api/self-profile/digest', {'source_id': source['id']})
        self.assertEqual((status, result['proposal']['careers'][0]['title']), (200, '촉매 반응기 최적화'))
        status, _ = self.call('POST', '/api/self-profile/digest', {'source_id': 'a' * 32})
        self.assertEqual(status, 404)
        status, _ = self.call('POST', '/api/self-profile/read-part', {'source_id': source['id'], 'part': 1, 'model_id': 'bridge'})
        self.assertEqual(status, 404)  # the part reading is gone

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
