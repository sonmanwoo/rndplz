"""Meaning ranker for condition-side candidates (2026-10-13, experiment): EmbeddingGemma on a local llama.cpp
server (an OpenAI-style /v1/embeddings URL, e.g. 16_SemanticSearch's http://127.0.0.1:8090/v1/embeddings).
Records are embedded once and cached by content; the search falls back to lexical order when this raises."""
import hashlib
import json
import math
import urllib.request


class EmbeddingRanker:
    def __init__(self, url, timeout=4.0):
        self.url, self.timeout, self.vectors = url, timeout, {}

    def _embed(self, texts):
        out = []
        for start in range(0, len(texts), 16):
            body = json.dumps({"input": texts[start:start + 16]}).encode("utf-8")
            request = urllib.request.Request(self.url, body, {"Content-Type": "application/json"})
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                rows = sorted(json.load(response)["data"], key=lambda row: row["index"])
            for row in rows:
                norm = math.sqrt(sum(x * x for x in row["embedding"])) or 1.0
                out.append([x / norm for x in row["embedding"]])
        return out

    @staticmethod
    def _key(record):
        return record.id + ":" + hashlib.sha256((record.title + "\n" + (record.text or "")).encode("utf-8")).hexdigest()[:16]

    def __call__(self, sentence, records_by_person):
        missing = {}
        for records in records_by_person.values():
            for record in records:
                if self._key(record) not in self.vectors:
                    missing[self._key(record)] = f"title: {record.title} | text: {(record.text or '')[:1200]}"
        if missing:
            self.vectors.update(zip(missing, self._embed(list(missing.values()))))
        query = self._embed([f"task: search result | query: {sentence}"])[0]
        dot = lambda vector: sum(a * b for a, b in zip(query, vector))
        return {pid: max((dot(self.vectors[self._key(record)]) for record in records), default=-1.0)
                for pid, records in records_by_person.items()}
