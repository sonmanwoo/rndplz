"""Same-meaning words for a search typed into the research map (2026-10-12).

The map filters on the device by characters, so '증류' misses a record titled 'distillation'. When typing pauses the
page sends only the typed words here; the local Gemma returns translations, word forms and common synonyms, and the
page searches its own data again with them. Nothing is kept beyond a small in-memory cache.

Measured 2026-10-12 (_work/tools/map-search-bench, 17 concepts in Korean and English over the public map): characters
alone F1 0.85, this expansion with gemma4:e4b 0.93 at 0.22 s per new search on this PC; an EmbeddingGemma 2 search
was faster (0.01 s) but less accurate (0.79), the company AI as accurate (0.94) but 3.4 s.
"""
from __future__ import annotations

import json
import re
import threading
import time
import unicodedata
import urllib.request
from collections import OrderedDict

PROMPT = """연구자 검색창에 사람이 입력한 검색어입니다. 연구 기록(논문 제목·요약, 경력, 기술 목록)에서 이 검색어와 같은 뜻으로 쓰였을 말을 돌려주세요.
- 반드시 한국어와 영어를 모두 넣습니다(검색어가 영어면 한국어 번역, 한국어면 영어 번역).
- 영어 어형(예: catalyst, catalysis, catalytic)과 흔한 동의어·표기 차이를 넣습니다.
- 넣지 않을 것: 상위 분야, 단순히 관련된 다른 개념, 너무 넓은 말(예: oil, cell, system), 한 글자 낱말, 3글자 미만 영문 약어, 수식 표기.
- 예: '부식'이면 corrosion, corrode, 녹은 넣고 '도장'·'재료 열화'는 넣지 않습니다.
- 최대 8개, 검색어 자체는 빼고, JSON만: {"terms": ["..."]}
검색어: """
MAX_QUERY = 60
MAX_TERMS = 8
CACHE_SIZE = 512
# The whole service: model calls per minute (cached searches are free) and at most two at a time.
CALLS_PER_MINUTE = 120
# The first call after the model left memory loads it (4-6 s on this PC); later calls take about 0.2 s.
TIMEOUT_SECONDS = 8
SCHEMA = {'type': 'object', 'properties': {'terms': {'type': 'array', 'items': {'type': 'string'}}}, 'required': ['terms']}


def key(text):
    """The map's own search key (people-map-model.js): NFKC, no spaces, lower case."""
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', text)).lower()


def usable(term, query_key=''):
    """A word the map's character match can carry: two Hangul syllables or three Latin letters, no markup.
    Shorter words ('H', 'cat', '막') match inside unrelated words and flood the results."""
    found = key(term)
    if not found or found == query_key or re.search(r'[$\\{}^_<>]', term):
        return False
    return len(found) >= (2 if re.search('[가-힣]', found) else 3)


class MapSynonyms:
    def __init__(self, base_url, model, *, opener=None, clock=time.monotonic):
        self.url = base_url.rstrip('/') + '/api/chat'
        self.model = model if model and model != 'off' else ''
        self.open = opener or urllib.request.build_opener(urllib.request.ProxyHandler({})).open
        self.clock = clock
        self.lock = threading.Lock()
        self.cache = OrderedDict()
        self.calls = []
        self.slots = threading.BoundedSemaphore(2)

    def expand(self, query):
        words = ' '.join(query.split()) if isinstance(query, str) else ''
        if not words or len(words) > MAX_QUERY:
            raise ValueError('검색어는 1~60자로 보내 주세요.')
        cache_key = key(words)
        with self.lock:
            if cache_key in self.cache:
                self.cache.move_to_end(cache_key)
                return {'query': words, 'terms': list(self.cache[cache_key]), 'available': True}
            now = self.clock()
            self.calls = [t for t in self.calls if now - t < 60]
            if not self.model or len(self.calls) >= CALLS_PER_MINUTE:
                return {'query': words, 'terms': [], 'available': False}
            self.calls.append(now)
        if not self.slots.acquire(timeout=TIMEOUT_SECONDS):
            return {'query': words, 'terms': [], 'available': False}
        try:
            terms = self._ask(words, cache_key)
        except Exception:
            # The map keeps its character results; a failed model call is simply not shown.
            return {'query': words, 'terms': [], 'available': False}
        finally:
            self.slots.release()
        with self.lock:
            self.cache[cache_key] = terms
            while len(self.cache) > CACHE_SIZE:
                self.cache.popitem(last=False)
        return {'query': words, 'terms': list(terms), 'available': True}

    def _ask(self, words, cache_key):
        body = {'model': self.model, 'stream': False, 'think': False, 'keep_alive': '24h', 'format': SCHEMA,
                'options': {'temperature': 0, 'num_predict': 200}, 'messages': [{'role': 'user', 'content': PROMPT + words}]}
        request = urllib.request.Request(self.url, json.dumps(body, ensure_ascii=False).encode(), {'Content-Type': 'application/json'})
        with self.open(request, timeout=TIMEOUT_SECONDS) as response:
            content = json.load(response)['message']['content']
        value = json.loads(re.search(r'\{.*\}', content, re.S)[0])
        terms, seen = [], {cache_key}
        for term in value.get('terms', []):
            if isinstance(term, str) and usable(term, cache_key) and key(term) not in seen:
                seen.add(key(term))
                terms.append(term.strip()[:40])
        return terms[:MAX_TERMS]
