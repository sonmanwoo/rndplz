"""Meaning-level matching of a search expression to record text, with a local multilingual embedding model.

A request written in another language or wording ("ethylene oligomerization", "마찰 시험") finds
records that say it differently ("올레핀 올리고머화", "tribology"). Embeddings come from a local
Ollama model (bge-m3 by default) on the CPU, so they never take GPU memory from Gemma. Record
vectors are cached by content, so a record changed in 내 프로필 is embedded again. When the
model is unreachable the search simply stays lexical; nothing here is required for a lookup.
A record is compared by its title and by its title with text, and the closer one counts: a short
title ("올레핀 올리고머화 방법") matches a short query far more clearly than a long abstract does.
"""
from __future__ import annotations

import hashlib
import json
import math
import threading
import time
import urllib.request

RECORD_CHARS = 2000
QUERY_CACHE = 256
RETRY_AFTER = 60.0


def _unit(vector):
    norm = math.sqrt(sum(value * value for value in vector)) or 1.0
    return [value / norm for value in vector]


def _record_text(record):
    return ((record.title or '') + '\n' + (record.text or ''))[:RECORD_CHARS]


class RecordEmbeddings:
    def __init__(self, url='http://127.0.0.1:11434', model='bge-m3', *, timeout=20.0, gpu=False, embed=None):
        self.url, self.model, self.timeout, self.gpu = url.rstrip('/'), model, timeout, gpu
        self._embed_call = embed or self._ollama
        self.lock = threading.Lock()
        self.records = {}   # record id -> (content digest, title vector, title+text vector)
        self.queries = {}   # query -> unit vector (insertion order = age)
        self.failed_at = 0.0

    @classmethod
    def from_env(cls, env):
        """RNDPLZ_EMBED_MODEL turns it on (e.g. bge-m3); RNDPLZ_EMBED_URL defaults to the local Ollama."""
        model = (env.get('RNDPLZ_EMBED_MODEL') or '').strip()
        if not model:
            return None
        return cls(env.get('RNDPLZ_EMBED_URL') or env.get('RNDPLZ_OLLAMA_URL') or 'http://127.0.0.1:11434', model,
                   gpu=env.get('RNDPLZ_EMBED_GPU') == '1')

    def _ollama(self, texts):
        body = {'model': self.model, 'input': texts, 'keep_alive': '24h', 'truncate': True}
        if not self.gpu:
            body['options'] = {'num_gpu': 0}
        request = urllib.request.Request(self.url + '/api/embed', data=json.dumps(body).encode('utf-8'),
                                         headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            vectors = json.loads(response.read().decode('utf-8'))['embeddings']
        if len(vectors) != len(texts):
            raise ValueError('embedding_count_mismatch')
        return vectors

    def _embed(self, texts):
        if not texts:
            return []
        if time.monotonic() - self.failed_at < RETRY_AFTER:
            raise ConnectionError('embedding_backoff')
        try:
            return [_unit(vector) for vector in self._embed_call(texts)]
        except Exception:
            self.failed_at = time.monotonic()
            raise

    def _record_vectors(self, records):
        wanted = {}
        for record in records:
            digest = hashlib.sha256(_record_text(record).encode('utf-8')).hexdigest()
            cached = self.records.get(record.id)
            if not cached or cached[0] != digest:
                wanted[record.id] = (digest, (record.title or '')[:RECORD_CHARS], _record_text(record))
        if wanted:
            ids = list(wanted)
            vectors = self._embed([wanted[rid][1] for rid in ids] + [wanted[rid][2] for rid in ids])
            with self.lock:
                for index, rid in enumerate(ids):
                    self.records[rid] = (wanted[rid][0], vectors[index], vectors[len(ids) + index])
        return {record.id: self.records[record.id][1:] for record in records}

    def _query_vector(self, query):
        vector = self.queries.get(query)
        if vector is None:
            vector = self._embed([query])[0]
            with self.lock:
                self.queries[query] = vector
                while len(self.queries) > QUERY_CACHE:
                    self.queries.pop(next(iter(self.queries)))
        return vector

    def similarities(self, query, records):
        """{record id: cosine similarity} for every record, or {} when the model cannot be reached."""
        records = list(records)
        try:
            vectors = self._record_vectors(records)
            target = self._query_vector(query)
        except Exception:
            return {}
        return {rid: max(sum(a * b for a, b in zip(target, vector)) for vector in pair) for rid, pair in vectors.items()}

    def warm(self, records):
        """Embed the records ahead of the first lookup (called in a background thread)."""
        try:
            self._record_vectors(list(records))
        except Exception:
            pass
