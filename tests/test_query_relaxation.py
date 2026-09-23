"""Rarest-term retry and Korean compound-noun containment in the lexical search.

After PR #23-#25, gemma4:e4b replays still missed a one-line career record
containing "증류" when it wrote "증류 기술" (the generic "기술" is absent) or
"진공증류" (a compound noun the record does not contain). Both fallbacks mark
the weaker match so the assessment stage can rate it accordingly.
"""
import unittest
from types import SimpleNamespace

from rndplz.domain import Contribution, Person, Record
from rndplz.engine import Engine
from rndplz.evidence_search import PublicEvidenceSearch, _query_hit, _rarest_term_hits


def record(rid, pid, name, title, text):
    return Record(id=rid, kind="career_record", title=title, text=text, date="2020",
                  people=[Contribution(person_id=pid, name=name, role="recorded_role")], tags=[],
                  field="process_engineering", scope="self_reported", source_system="user_provided_resume",
                  source_id=rid, source_url="", checked_at="2026-09-23", evidence_kind="career_experience")


def corpus():
    people = {"P-MW": Person(id="P-MW", name="Manwoo Son", org="GS"),
              "P-CAT": Person(id="P-CAT", name="Catalyst Person", org="GS")}
    records = {
        "R-MONO": record("R-MONO", "P-MW", "Manwoo Son", "모노머 공정 모델링 및 증류·추출 실험",
                         "모노머 공정 모델링 및 최적화, 증류 및 추출 실험 수행."),
        "R-BIO": record("R-BIO", "P-MW", "Manwoo Son", "Diols 탈색·탈취 공정 개발",
                        "증류, 흡착, 수소화반응 등을 활용한 Diols 탈색·탈취 공정 개발."),
        "R-CAT": record("R-CAT", "P-CAT", "Catalyst Person", "촉매 반응기 설계",
                        "고정층 촉매 반응기 설계와 실험."),
    }
    by_person = {}
    for row in records.values():
        for contribution in row.people:
            by_person.setdefault(contribution.person_id, []).append(row)
    return SimpleNamespace(people=people, records=records, by_person=by_person, topics=[],
                           topic_by_id={}, questions=[], errors=[])


def plan(*groups):
    return {"reply": "조회", "intent": "search", "lookup_action": "execute", "summary": "",
            "interpretations": [{"label": "t", "groups": [{"topic_ids": [], "queries": list(queries)}
                                                            for queries in groups]}],
            "person_names": [], "conditions": [], "record_ids": []}


class QueryRelaxationTests(unittest.TestCase):
    def setUp(self):
        self.corpus = corpus()
        self.search = PublicEvidenceSearch(Engine(self.corpus))

    def run_search(self, *groups):
        return self.search.search(plan(*groups), request_revision="test")

    def hit_modes(self, result, pid):
        card = next(c for c in result["candidates"] if c["id"] == pid)
        return sorted({hit["match_mode"] for item in card["matching_interpretations"]
                       for group in item["groups"] for match in group["matches"] for hit in match["queries"]})

    def test_exact_and_all_terms_matches_are_unchanged(self):
        self.assertEqual(_query_hit(self.corpus.records["R-MONO"], "증류")["match_mode"], "exact_phrase")
        self.assertEqual(_query_hit(self.corpus.records["R-MONO"], "증류 실험")["match_mode"], "all_terms")
        result = self.run_search(["증류 실험"])
        self.assertEqual([c["id"] for c in result["candidates"]], ["P-MW"])
        self.assertNotIn("query_relaxation", result["candidates"][0])

    def test_generic_modifier_falls_back_to_the_rarest_term(self):
        # "기술" appears nowhere, "증류" in two records: retry with "증류".
        self.assertIsNone(_query_hit(self.corpus.records["R-MONO"], "증류 기술"))
        hits = _rarest_term_hits("증류 기술", self.corpus.records)
        self.assertEqual({rid for rid, _ in hits}, {"R-MONO", "R-BIO"})
        self.assertEqual(hits[0][1]["relaxed_term"], "증류")
        result = self.run_search(["증류 기술"])
        self.assertEqual([c["id"] for c in result["candidates"]], ["P-MW"])
        self.assertEqual(self.hit_modes(result, "P-MW"), ["rarest_term"])
        self.assertEqual(result["candidates"][0]["query_relaxation"], ["rarest_term"])
        self.assertIn("정확한 표현 일치는 아닙니다", result["candidates"][0]["reason"])

    def test_rarest_term_prefers_the_less_common_term(self):
        # "촉매" is in one record, "증류" in two: the rarer term wins.
        hits = _rarest_term_hits("증류 촉매", self.corpus.records)
        self.assertEqual([rid for rid, _ in hits], ["R-CAT"])

    def test_fallback_needs_a_term_present_somewhere_and_two_terms(self):
        self.assertEqual(_rarest_term_hits("용매 정제", self.corpus.records), [])
        self.assertEqual(_rarest_term_hits("잔존물", self.corpus.records), [])
        self.assertEqual(self.run_search(["용매 정제"])["candidates"], [])

    def test_compound_noun_contains_a_record_word(self):
        hit = _query_hit(self.corpus.records["R-MONO"], "진공증류")
        self.assertEqual(hit["match_mode"], "all_terms_compound")
        self.assertEqual(hit["relaxed_terms"], ["진공증류"])
        result = self.run_search(["진공증류"])
        self.assertEqual([c["id"] for c in result["candidates"]], ["P-MW"])
        self.assertEqual(result["candidates"][0]["query_relaxation"], ["all_terms_compound"])

    def test_compound_containment_limits(self):
        # Two-syllable terms and words shorter than half the term never qualify.
        self.assertIsNone(_query_hit(self.corpus.records["R-MONO"], "증류탑설계공정"))
        self.assertIsNone(_query_hit(self.corpus.records["R-CAT"], "진공증류"))
        self.assertIsNone(_query_hit(self.corpus.records["R-MONO"], "정제"))

    def test_rarest_term_ranks_below_a_complete_match(self):
        result = self.run_search(["증류 기술"])
        full = self.run_search(["증류"])
        self.assertGreater(full["candidates"][0]["score_internal"], result["candidates"][0]["score_internal"])


if __name__ == "__main__":
    unittest.main()
