"""Same-meaning words for the research map's search box (map_synonyms.py, /api/people-map/expand)."""
import io
import json
import tempfile
import unittest
from pathlib import Path
from urllib.parse import urlencode

from rndplz.map_synonyms import CALLS_PER_MINUTE, MapSynonyms, usable


class FakeOllama:
    def __init__(self, terms=(), fail=False):
        self.terms, self.fail, self.bodies = list(terms), fail, []

    def __call__(self, request, timeout=None):
        self.bodies.append(json.loads(request.data))
        if self.fail:
            raise OSError('model down')
        return io.BytesIO(json.dumps({'message': {'content': json.dumps({'terms': self.terms}, ensure_ascii=False)}}).encode())


class MapSynonymsTests(unittest.TestCase):
    def test_short_or_markup_words_are_dropped(self):
        # Seen in the 2026-10-12 measurement: 'H', 'cat', '막' matched inside unrelated words.
        for word in ('H', 'H2', 'PC', '막', '$\\text{CO}_2$'):
            self.assertFalse(usable(word), word)
        for word in ('증류', 'CO2', 'distill', 'catalysis'):
            self.assertTrue(usable(word), word)

    def test_terms_are_filtered_deduplicated_and_cached(self):
        model = FakeOllama(['distillation', 'Distillation', '증류', 'H', 'distill', '증 류'])
        synonyms = MapSynonyms('http://127.0.0.1:11434', 'gemma4:e4b', opener=model)
        first = synonyms.expand('  증류 ')
        self.assertEqual(first, {'query': '증류', 'terms': ['distillation', 'distill'], 'available': True})
        self.assertEqual(model.bodies[0]['model'], 'gemma4:e4b')
        self.assertFalse(model.bodies[0]['think'])
        self.assertTrue(model.bodies[0]['messages'][0]['content'].endswith('검색어: 증류'))
        self.assertEqual(synonyms.expand('증류')['terms'], ['distillation', 'distill'])
        self.assertEqual(len(model.bodies), 1, 'the second search is served from memory')

    def test_failures_and_limits_answer_without_words(self):
        down = MapSynonyms('http://127.0.0.1:11434', 'gemma4:e4b', opener=FakeOllama(fail=True))
        self.assertEqual(down.expand('촉매'), {'query': '촉매', 'terms': [], 'available': False})
        self.assertNotIn('촉매', down.cache, 'a failure is tried again next time')
        off = MapSynonyms('http://127.0.0.1:11434', 'off', opener=FakeOllama(['x']))
        self.assertFalse(off.expand('촉매')['available'])
        now = [0.0]
        busy = MapSynonyms('http://127.0.0.1:11434', 'gemma4:e4b', opener=FakeOllama(['catalyst']), clock=lambda: now[0])
        for n in range(CALLS_PER_MINUTE):
            busy.expand('word%d' % n)
        self.assertFalse(busy.expand('another')['available'])
        self.assertTrue(busy.expand('word0')['available'], 'remembered searches still answer')
        now[0] = 61.0
        self.assertTrue(busy.expand('another')['available'])

    def test_query_length(self):
        synonyms = MapSynonyms('http://127.0.0.1:11434', 'gemma4:e4b', opener=FakeOllama())
        for bad in ('', '   ', 'x' * 61, None):
            with self.assertRaises(ValueError):
                synonyms.expand(bad)


class ExpandEndpointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from rndplz.public_web import PublicApp
        cls.tmp = tempfile.TemporaryDirectory()
        cls.app = PublicApp(state_dir=Path(cls.tmp.name) / 'state', env={
            'RNDPLZ_LOCAL_PREVIEW': '1', 'RNDPLZ_SESSION_SECRET': 's' * 64, 'RNDPLZ_MAP_SYNONYM_MODEL': 'off',
            'RNDPLZ_PUBLIC_PERSON_IDS': 'LOCAL-MANWOO,LOCAL-JINHO,LOCAL-DASOL,LOCAL-HONG'})

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def get(self, words, cookie=''):
        captured = {}
        def start_response(status, headers):
            captured['status'], captured['headers'] = int(status.split()[0]), headers
        body = b''.join(self.app({'REQUEST_METHOD': 'GET', 'PATH_INFO': '/api/people-map/expand', 'QUERY_STRING': urlencode({'q': words}),
                                  'HTTP_HOST': '127.0.0.1', 'wsgi.url_scheme': 'http', 'wsgi.input': io.BytesIO(b''),
                                  'CONTENT_LENGTH': '0', 'HTTP_COOKIE': cookie}, start_response))
        cookie = '; '.join(v.split(';')[0] for k, v in captured['headers'] if k.lower() == 'set-cookie') or cookie
        return captured['status'], json.loads(body), cookie

    def test_answers_and_limits_a_visitor(self):
        status, body, cookie = self.get('증류')
        self.assertEqual((status, body), (200, {'query': '증류', 'terms': [], 'available': False}))
        self.app.map_synonyms = MapSynonyms('http://127.0.0.1:11434', 'gemma4:e4b', opener=FakeOllama(['distillation']))
        status, body, cookie = self.get('증류', cookie)
        self.assertEqual((status, body['terms']), (200, ['distillation']))
        self.assertEqual(self.get('', cookie)[0], 400)
        for _ in range(37):
            self.assertEqual(self.get('증류', cookie)[0], 200)
        self.assertEqual(self.get('증류', cookie)[0], 429, 'forty searches a minute per visitor')


if __name__ == '__main__':
    unittest.main()
