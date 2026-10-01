"""Meaning-level fallback for a search expression that matches no record word.

Feedback (2026-10-01): "에틸렌 oligomerization 전문가" did not find the person whose record says
"올레핀 올리고머화". A query with no lexical hit now falls back to records with the same meaning
(multilingual embeddings) before its rarest term; without a reachable model the search stays lexical.
"""
import dataclasses
import unittest
from types import SimpleNamespace

from rndplz.domain import Contribution, Person, Record
from rndplz.engine import Engine
from rndplz.evidence_search import PublicEvidenceSearch
from rndplz.semantic_search import RecordEmbeddings


def record(rid, pid, name, title, text):
    return Record(id=rid, kind="career_record", title=title, text=text, date="2020",
                  people=[Contribution(person_id=pid, name=name, role="recorded_role")], tags=[],
                  field="process_engineering", scope="self_reported", source_system="user_provided_resume",
                  source_id=rid, source_url="", checked_at="2026-09-23", evidence_kind="career_experience")


def corpus():
    people = {"P-HONG": Person(id="P-HONG", name="Hong", org="GS"),
              "P-JO": Person(id="P-JO", name="Jo", org="GS")}
    records = {
        "R-OLIGO": record("R-OLIGO", "P-HONG", "Hong", "올레핀 올리고머화 촉매", "에틸렌을 올리고머화하는 촉매 조성물."),
        "R-ETH": record("R-ETH", "P-JO", "Jo", "에틸렌 생산 공정 운전", "에틸렌 분해로 운전과 수율 관리."),
    }
    by_person = {}
    for row in records.values():
        for contribution in row.people:
            by_person.setdefault(contribution.person_id, []).append(row)
    return SimpleNamespace(people=people, records=records, by_person=by_person, topics=[],
                           topic_by_id={}, questions=[], errors=[])


# Toy vectors standing in for the model: oligomerization texts point one way, ethylene operation another.
VECTORS = {"oligo": [1.0, 0.1, 0.0], "eth": [0.1, 1.0, 0.0], "other": [0.0, 0.0, 1.0]}


def fake_embed(calls):
    def embed(texts):
        calls.append(list(texts))
        return [VECTORS["oligo" if ("올리고머" in t or "oligomer" in t) else "eth" if "에틸렌" in t else "other"]
                for t in texts]
    return embed


def plan(*queries):
    return {"reply": "조회", "intent": "search", "lookup_action": "execute", "summary": "",
            "interpretations": [{"label": "t", "groups": [{"topic_ids": [], "queries": list(queries)}]}],
            "person_names": [], "conditions": [], "record_ids": []}


class SemanticSearchTests(unittest.TestCase):
    def search(self, embed, *queries):
        engine = Engine(corpus())
        engine.semantic = RecordEmbeddings(embed=embed) if embed else None
        return PublicEvidenceSearch(engine).search(plan(*queries), request_revision="test")

    def modes(self, result, pid):
        card = next(c for c in result["candidates"] if c["id"] == pid)
        return sorted({hit["match_mode"] for item in card["matching_interpretations"]
                       for group in item["groups"] for match in group["matches"] for hit in match["queries"]})

    def test_a_foreign_term_finds_the_record_by_meaning(self):
        calls = []
        result = self.search(fake_embed(calls), "oligomerization")
        self.assertEqual([c["id"] for c in result["candidates"]], ["P-HONG"])
        self.assertEqual(self.modes(result, "P-HONG"), ["semantic"])
        self.assertIn("같은 뜻의 다른 표현", result["candidates"][0]["reason"])

    def test_meaning_comes_before_the_rarest_term(self):
        # Lexically only "에틸렌" exists, which would admit the ethylene operator too.
        result = self.search(fake_embed([]), "에틸렌 oligomerization")
        self.assertEqual([c["id"] for c in result["candidates"]], ["P-HONG"])

    def test_a_lexical_hit_does_not_ask_the_model(self):
        calls = []
        result = self.search(fake_embed(calls), "올리고머화")
        self.assertEqual([c["id"] for c in result["candidates"]], ["P-HONG"])
        self.assertEqual(calls, [])

    def test_an_unreachable_model_leaves_the_lexical_fallback(self):
        def down(texts):
            raise ConnectionError("no ollama")
        result = self.search(down, "에틸렌 oligomerization")
        self.assertEqual(self.modes(result, "P-JO"), ["rarest_term"])
        self.assertEqual(self.search(None, "oligomerization")["candidates"], [])

    def test_record_vectors_are_cached_by_content(self):
        calls = []
        embeddings = RecordEmbeddings(embed=fake_embed(calls))
        rows = list(corpus().records.values())
        embeddings.similarities("oligomerization", rows)
        embeddings.similarities("oligomerization", rows)
        self.assertEqual([len(batch) for batch in calls], [4, 1])  # each record's title and text once, the query once
        changed = dataclasses.replace(rows[0], text="바뀐 설명")
        embeddings.similarities("oligomerization", [changed, rows[1]])
        self.assertEqual(len(calls[-1]), 2)  # only the changed record is embedded again


if __name__ == "__main__":
    unittest.main()
