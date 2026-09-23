"""Group-level relaxation of AND groups in the public evidence search.

On 2026-09-23 gemma4:e4b split a request into the groups
[["잔존 물질 제거", "미세 물질"]] AND [["증류"]]. The only matching person had
records for "증류" but nothing for the problem description, so the lookup
returned nothing. With relaxation, a person who matches every group but one
is admitted with that group marked unmatched; query terms are never relaxed.
"""
import unittest
from types import SimpleNamespace

from rndplz.domain import Contribution, Person, Record
from rndplz.engine import Engine
from rndplz.evidence_search import PublicEvidenceSearch


def record(rid, pid, name, title, text):
    # Field values mirror the real self-reported career records in the corpus.
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
                        "고정층 촉매 반응기 설계와 잔존 물질 제거 실험."),
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


class GroupRelaxationTests(unittest.TestCase):
    def setUp(self):
        self.search = PublicEvidenceSearch(Engine(corpus()))

    def run_search(self, *groups):
        return self.search.search(plan(*groups), request_revision="test")

    def test_full_and_match_is_unchanged(self):
        result = self.run_search(["증류"])
        self.assertEqual([c["id"] for c in result["candidates"]], ["P-MW"])
        self.assertFalse(result["candidates"][0].get("group_relaxation"))
        self.assertFalse(result["interpretations"][0]["group_relaxation"])
        self.assertEqual(result["lookup_resolution"], "matched")

    def test_one_unmatched_group_is_waived_and_marked(self):
        result = self.run_search(["잔존 물질 제거", "미세 물질"], ["증류"])
        # Each person matches exactly one of the two groups; both are admitted as partial.
        cards = {c["id"]: c for c in result["candidates"]}
        self.assertEqual(set(cards), {"P-MW", "P-CAT"})
        for card in cards.values():
            self.assertTrue(card["group_relaxation"])
            self.assertIn("미확인", card["reason"])
        self.assertEqual([g["matched"] for g in cards["P-MW"]["matching_interpretations"][0]["groups"]], [False, True])
        self.assertEqual(cards["P-MW"]["matching_interpretations"][0]["unmatched_group_indexes"], [0])
        self.assertEqual([g["matched"] for g in cards["P-CAT"]["matching_interpretations"][0]["groups"]], [True, False])
        self.assertTrue(result["interpretations"][0]["group_relaxation"])
        self.assertEqual(result["lookup_resolution"], "matched")

    def test_terms_inside_a_query_are_not_relaxed(self):
        # Every whitespace-separated term still has to match one record.
        result = self.run_search(["증류 잔존 미세"])
        self.assertEqual(result["candidates"], [])
        self.assertEqual(result["lookup_resolution"], "no_linked_evidence")

    def test_two_unmatched_groups_still_return_nothing(self):
        result = self.run_search(["잔존 미세 물질"], ["용매 정제"], ["증류"])
        self.assertEqual(result["candidates"], [])
        self.assertFalse(result["interpretations"][0]["group_relaxation"])

    def test_complete_match_ranks_above_partial_match(self):
        result = self.run_search(["잔존 물질 제거"], ["증류"])
        # P-CAT matches only the first group and P-MW only the second: both partial.
        self.assertEqual({c["id"] for c in result["candidates"]}, {"P-MW", "P-CAT"})
        self.assertTrue(all(c["group_relaxation"] for c in result["candidates"]))
        full = self.run_search(["촉매 반응기"])
        self.assertEqual([c["id"] for c in full["candidates"]], ["P-CAT"])
        self.assertGreater(full["candidates"][0]["score_internal"], result["candidates"][0]["score_internal"])


if __name__ == "__main__":
    unittest.main()
