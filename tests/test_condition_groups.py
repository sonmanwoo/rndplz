"""Condition groups in the public evidence search (2026-10-13).

On 2026-10-13 the fast consultation model turned "증류 전문가" + "실험실 공정의 스케일업 및 설비 설계" into
[증류 | distillation] AND [스케일업 | 설계 | design]. Nobody had 스케일업, but one researcher whose record leads with
crystallization had the word 설계, so he alone passed and two distillation researchers were dropped. A group the
model marks role=condition now never drops anyone: field groups decide who is found, and a person without a record
for the condition is admitted with it unmatched, for the assessment to judge.
"""
import unittest
from types import SimpleNamespace

from rndplz import model_dialogue
from rndplz.domain import Contribution, Person, Record
from rndplz.engine import Engine
from rndplz.evidence_search import PublicEvidenceSearch


def record(rid, pid, name, title, text):
    # The same record shape as tests/test_group_relaxation.py.
    return Record(id=rid, kind="career_record", title=title, text=text, date="2026",
                  people=[Contribution(person_id=pid, name=name, role="recorded_role")], tags=[],
                  field="process_engineering", scope="self_reported", source_system="user_provided_resume",
                  source_id=rid, source_url="", checked_at="2026-10-13", evidence_kind="career_experience")


def corpus():
    people = {pid: Person(id=pid, name=name, org="org") for pid, name in
              (("P-KISS", "Kiss"), ("P-MW", "Manwoo Son"), ("P-DOH", "Doherty"), ("P-CAT", "Catalyst Person"))}
    records = {
        "R-KISS": record("R-KISS", "P-KISS", "Kiss", "Reactive distillation and process intensification",
                         "Reactive distillation, dividing-wall columns and heat-integrated distillation."),
        "R-MW": record("R-MW", "P-MW", "Manwoo Son", "모노머 공정 모델링 및 증류·추출 실험",
                       "모노머 공정 모델링 및 최적화, 증류 및 추출 실험 수행."),
        "R-DOH": record("R-DOH", "P-DOH", "Doherty", "유기물 결정화의 결정형 선택과 반응분리 공정 설계 연구",
                        "결정형·형상 선택 연구. 반응증류, 반응추출과 잔류곡선 기반 분리 공정 설계도 다룬다."),
        "R-CAT": record("R-CAT", "P-CAT", "Catalyst Person", "촉매 반응기 설계",
                        "고정층 촉매 반응기 설계와 Pilot Scale 설비 구축."),
    }
    by_person = {}
    for row in records.values():
        for contribution in row.people:
            by_person.setdefault(contribution.person_id, []).append(row)
    return SimpleNamespace(people=people, records=records, by_person=by_person, topics=[],
                           topic_by_id={}, questions=[], errors=[])


def plan(*groups):
    return {"reply": "조회", "intent": "search", "lookup_action": "execute", "summary": "",
            "interpretations": [{"label": "t", "groups": [dict(group) for group in groups]}],
            "person_names": [], "conditions": [], "record_ids": []}


DISTILL = {"topic_ids": [], "queries": ["증류", "distillation"]}
SCALE_UP = {"topic_ids": [], "queries": ["스케일업", "설계", "design"]}


class ConditionGroupTests(unittest.TestCase):
    def setUp(self):
        self.search = PublicEvidenceSearch(Engine(corpus()))

    def run_search(self, *groups):
        return self.search.search(plan(*groups), request_revision="test")

    def test_the_2026_10_13_request_keeps_every_distillation_researcher(self):
        # As the model wrote it (no role): AND lets one coincidental 설계 decide the candidates.
        before = self.run_search(DISTILL, SCALE_UP)
        self.assertEqual([c["id"] for c in before["candidates"]], ["P-DOH"])
        # With the added experience marked as a condition, everyone with distillation records is found.
        after = self.run_search({**DISTILL, "role": "field"}, {**SCALE_UP, "role": "condition"})
        cards = {c["id"]: c for c in after["candidates"]}
        field = {pid for pid, card in cards.items() if not card.get("condition_side")}
        self.assertEqual(field, {"P-KISS", "P-MW", "P-DOH"})
        # 설계 alone never makes someone a field candidate; at most a condition-side one after them, for the assessment.
        self.assertTrue(cards["P-CAT"]["condition_side"])
        self.assertEqual(after["candidates"][-1]["id"], "P-CAT")
        # Linked to the condition ranks first; the others carry it as unverified for the assessment.
        self.assertEqual(after["candidates"][0]["id"], "P-DOH")
        self.assertFalse(cards["P-DOH"].get("group_relaxation"))
        for pid in ("P-KISS", "P-MW"):
            self.assertTrue(cards[pid]["group_relaxation"])
            self.assertIn("미확인", cards[pid]["reason"])
            interpretation = cards[pid]["matching_interpretations"][0]
            self.assertEqual(interpretation["unmatched_group_indexes"], [1])
            self.assertEqual((interpretation["matched_group_count"], interpretation["required_group_count"]), (1, 2))
        self.assertTrue(after["interpretations"][0]["group_relaxation"])
        self.assertEqual(after["interpretations"][0]["groups"][1]["role"], "condition")

    def test_condition_side_adds_the_closest_people_beside_the_field(self):
        # P-CAT has no distillation record but links to both conditions (Pilot Scale 설비 · 설계): a condition-side
        # candidate after the field's people, the field unmatched for the assessment to judge.
        result = self.run_search({**DISTILL, "role": "field"},
                                 {"topic_ids": [], "queries": ["스케일업", "pilot"], "role": "condition"},
                                 {"topic_ids": [], "queries": ["설비", "설계"], "role": "condition"})
        ids = [c["id"] for c in result["candidates"]]
        self.assertEqual(ids[-1], "P-CAT")
        self.assertEqual(set(ids[:-1]), {"P-KISS", "P-MW", "P-DOH"})
        side = result["candidates"][-1]
        self.assertTrue(side["condition_side"])
        self.assertIn("덧붙인 조건과 연결된", side["reason"])
        self.assertEqual(side["matching_interpretations"][0]["unmatched_group_indexes"], [0])
        self.assertFalse(any(c.get("condition_side") for c in result["candidates"][:-1]))

    def test_condition_side_order_follows_an_engine_ranker(self):
        seen = {}
        def ranker(sentence, records_by_person):
            seen["sentence"] = sentence
            return {pid: (1.0 if pid == "P-CAT" else 0.0) for pid in records_by_person}
        self.search.engine.meaning = ranker
        plan_ = plan({**DISTILL, "role": "field"}, {"topic_ids": [], "queries": ["설계"], "role": "condition"})
        plan_["conditions"] = [{"kind": "required", "text": "설비 설계 경험", "source_turn_id": "t", "source_quote": "설비 설계"}]
        result = self.search.search(plan_, request_revision="test")
        self.assertEqual(seen["sentence"], "설비 설계")
        self.assertEqual([c["id"] for c in result["candidates"] if c.get("condition_side")], ["P-CAT"])

    def test_cards_carry_the_meaning_rank_and_similarity(self):
        # A ranker scores every shown person against the user's condition words; the condition side also gets its
        # rank among everyone linked to the conditions without the field (2026-10-13, shown on the cards).
        self.search.engine.meaning = lambda sentence, own: {pid: {"P-CAT": .7, "P-DOH": .6}.get(pid, .5) for pid in own}
        plan_ = plan({**DISTILL, "role": "field"}, {"topic_ids": [], "queries": ["설계"], "role": "condition"})
        plan_["conditions"] = [{"kind": "required", "text": "설비 설계 경험", "source_turn_id": "t", "source_quote": "설비 설계"}]
        result = self.search.search(plan_, request_revision="test")
        cards = {c["id"]: c for c in result["candidates"]}
        self.assertEqual(cards["P-CAT"]["meaning"], {"score": 0.7, "rank": 1, "pool": 1})
        self.assertEqual(cards["P-DOH"]["meaning"], {"score": 0.6})
        self.assertEqual(cards["P-KISS"]["meaning"], {"score": 0.5})
        self.assertEqual(result["meaning_sentence"], "설비 설계")

    def test_no_meaning_without_a_ranker(self):
        result = self.run_search({**DISTILL, "role": "field"}, {"topic_ids": [], "queries": ["설계"], "role": "condition"})
        self.assertFalse(any("meaning" in c for c in result["candidates"]))
        self.assertNotIn("meaning_sentence", result)

    def test_projection_passes_only_a_well_formed_meaning(self):
        from rndplz.scout_projection import _candidate
        shown = _candidate({"id": "P", "name": "n", "condition_side": True, "meaning": {"score": 0.67591, "rank": 1, "pool": 6}})
        self.assertEqual(shown["meaning"], {"score": 0.676, "rank": 1, "pool": 6})
        self.assertTrue(shown["condition_side"])
        self.assertEqual(_candidate({"id": "P", "name": "n", "meaning": {"score": 0.5, "rank": 7, "pool": 6}})["meaning"], {"score": 0.5})
        self.assertNotIn("meaning", _candidate({"id": "P", "name": "n", "meaning": {"score": 5}}))
        self.assertNotIn("condition_side", _candidate({"id": "P", "name": "n", "condition_side": "yes"}))

    def test_cards_show_the_line(self):
        from pathlib import Path
        web = Path(__file__).resolve().parents[1] / "rndplz" / "web"
        chat, draw = (web / "chat.js").read_text(encoding="utf-8"), (web / "draw.js").read_text(encoding="utf-8")
        self.assertIn("meaning:candidateMeaning(c)}", chat)
        self.assertIn("if (record.purpose_relation === 'adjacent' || record.meaning) {", draw)
        self.assertIn("'조건 쪽 후보 ' + meaning.pool + '명 중 ' + meaning.rank + '위 · '", draw)
        self.assertIn("'덧붙인 조건과의 의미 유사도 ' + meaning.score.toFixed(3)", draw)
        rmap = (web / "recommendation-map.js").read_text(encoding="utf-8")
        self.assertIn("(side ? '조건 쪽 ' + meaning.pool + '명 중 ' + meaning.rank + '위 · ' : '조건 유사도 ') + meaning.score.toFixed(3)", rmap)
        # the person dialog's "왜 이 사람인가" carries the same line
        self.assertIn("+meaningHtml(candidate)+'</section>')", chat)
        self.assertIn("'덧붙인 조건과의 의미 유사도 '+m.score.toFixed(3)", chat)

    def test_no_condition_side_without_a_field_match(self):
        result = self.run_search({"topic_ids": [], "queries": ["없는말"], "role": "field"},
                                 {"topic_ids": [], "queries": ["설계"], "role": "condition"})
        self.assertFalse(any(c.get("condition_side") for c in result["candidates"]))

    def test_field_groups_still_intersect(self):
        result = self.run_search({**DISTILL, "role": "field"}, {"topic_ids": [], "queries": ["모노머"], "role": "field"})
        self.assertEqual([c["id"] for c in result["candidates"]], ["P-MW"])

    def test_only_conditions_fall_back_to_every_group(self):
        # A plan with no field group behaves as before: its groups decide together.
        result = self.run_search({**DISTILL, "role": "condition"}, {"topic_ids": [], "queries": ["모노머"], "role": "condition"})
        self.assertEqual([c["id"] for c in result["candidates"]], ["P-MW"])

    def test_role_is_validated(self):
        with self.assertRaises(ValueError):
            self.run_search({**DISTILL, "role": "maybe"})

    def test_plan_schema_takes_a_group_with_or_without_role(self):
        schema = model_dialogue._GROUP_SCHEMA
        model_dialogue._validate_shape({"topic_ids": [], "queries": ["증류"]}, schema)
        model_dialogue._validate_shape({"topic_ids": [], "queries": ["증류"], "role": "condition"}, schema)
        with self.assertRaises(model_dialogue.PlanValidationError):
            model_dialogue._validate_shape({"topic_ids": [], "queries": ["증류"], "role": "other"}, schema)


if __name__ == "__main__":
    unittest.main()
