from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections import Counter
from pathlib import Path

from .domain import Contribution, Person, Record

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA = ROOT / "pack" / "data"


def normalize(value):
    return unicodedata.normalize("NFKC", value or "").lower()


def matches(text, term):
    text, term = normalize(text), normalize(term)
    if re.fullmatch(r"[a-z0-9-]+", term) and len(term) <= 4:
        return bool(re.search(r"(?<![a-z0-9])" + re.escape(term) + r"(?![a-z0-9])", text))
    return term in text


def source_url(work):
    doi = (work.get("doi") or "").strip()
    if doi.startswith("10."):
        return "https://doi.org/" + doi
    for value in (doi, work.get("landing_page"), work.get("id")):
        if isinstance(value, str) and value.startswith(("https://", "http://")):
            return value
    return ""


def classify(title, abstract, source_type):
    text = normalize(title + " " + abstract)
    if source_type == "review" or re.search(r"\b(review|survey|overview)\b", normalize(title)):
        return "review", ["제목·문헌 유형의 리뷰 표현"]
    hints = []
    for kind, pattern in [
        ("experiment", r"\b(experimental|experimentally|experiments|measured|accelerated thermal|fabricated|testing)\b"),
        ("simulation", r"\b(simulation|numerical|cfd|computational fluid)\b"),
        ("theory", r"\b(theoretical|analytical solution|theorem)\b"),
    ]:
        if re.search(pattern, text):
            hints.append(kind)
    return (hints[0] if len(hints) == 1 else "mixed" if hints else "unknown"), hints


class Corpus:
    def __init__(self, data_dir=DEFAULT_DATA):
        self.data_dir = Path(data_dir)
        self.topics = json.loads((Path(__file__).with_name("topics.json")).read_text(encoding="utf-8"))
        self.topic_by_id = {t["id"]: t for t in self.topics}
        self.people: dict[str, Person] = {}
        self.records: dict[str, Record] = {}
        self.errors = []
        self.hashes = {}
        self.load()
        self.by_person = {pid: [] for pid in self.people}
        for record in self.records.values():
            for contribution in record.people:
                if contribution.person_id in self.by_person:
                    self.by_person[contribution.person_id].append(record)

    def read(self, name):
        raw = (self.data_dir / name).read_bytes()
        self.hashes[name] = hashlib.sha256(raw).hexdigest()
        return json.loads(raw.decode("utf-8"))

    def add(self, collection, obj):
        if not obj.id or obj.id in collection:
            self.errors.append("식별자 누락 또는 중복: " + str(obj.id))
            return
        collection[obj.id] = obj

    def load(self):
        snapshot = self.read("openalex_snapshot.json")
        self.checked_at = snapshot["checked_at"]
        for author in snapshot["authors"]:
            orgs = author.get("last_known_institutions") or []
            org = orgs[0] if orgs else {}
            self.add(self.people, Person(author["id"], author["name"], org=org.get("name", org.get("display_name", "소속 미확인")), org_type=org.get("type", "unknown"), profile=author))
        for work in snapshot["works"]:
            abstract = work.get("abstract") or ""
            kind, basis = classify(work["title"], abstract, work.get("type"))
            contributions = [Contribution(x.get("author_id"), x["name"], x.get("position", "unknown"), bool(x.get("is_corresponding")), x.get("institutions", [])) for x in work["authorships"]]
            for item in contributions:
                if item.person_id and item.person_id not in self.people:
                    self.errors.append("미해결 저자 참조: " + item.person_id)
            text = work["title"] + " " + abstract
            tags = [t["id"] for t in self.topics if t["field"] == work["field"] and any(matches(text, term) for term in t["keywords"])]
            record = Record(work["id"], "preprint" if work.get("type") == "preprint" else "paper", work["title"], abstract, str(work.get("date") or work.get("year") or ""), contributions, tags, work["field"], work["scope"], "openalex", work["id"], source_url(work), self.checked_at, kind, basis, details={"doi": work.get("doi"), "source_type": work.get("type"), "abstract_available": bool(abstract)})
            self.add(self.records, record)
        site = self.read("site_records_seed.json")
        for raw in site["records"]:
            info = raw["person"]
            site_name = "가상 지원센터" if info["site"] == "본사" else "가상 사업장 A" if info["site"] == "여수공장" else "가상 사업장 B"
            details = {key: raw.get(key) for key in ["handles", "equipment", "quantity_scale", "procurement", "experiences", "evidence", "can_help_with"]}
            details.update(site=site_name, dept="가상 " + info["dept"], role=info["role"])
            self.add(self.people, Person(info["id"], info["name"], "site", site_name, "site", {"role": info["role"]}, virtual=True))
            for topic in raw["topics"]:
                if topic not in self.topic_by_id:
                    self.errors.append("현장 주제 미등록: " + topic)
            text = " ".join(raw["handles"] + raw["equipment"] + raw["can_help_with"]) + " " + str(raw["procurement"]) + " " + " ".join(x["what"] + " " + x["outcome"] for x in raw["experiences"])
            dates = [x["date"] for x in raw["experiences"]]
            self.add(self.records, Record(raw["id"], "site_record", info["role"] + " 경험 기록 (가상)", text, max(dates), [Contribution(info["id"], info["name"], "recorded_role")], raw["topics"], "site", "virtual_site", "virtual_seed", raw["id"], "", site["checked_at"], "site_experience", ["시연용 가상 기록"], "virtual_demo", True, details))
        featured = json.loads(Path(__file__).with_name("featured_people.json").read_text(encoding="utf-8"))
        self.checked_at = max(self.checked_at, featured["checked_at"])
        for raw in featured["people"]:
            self.add(self.people, Person(raw["id"], raw["name"], org=raw["org"], org_type=raw["org_type"], profile=raw))
        for raw in featured["papers"]:
            contributions = [Contribution(a["person_id"], a["name"], a["role"], a.get("corresponding", False)) for a in raw["authors"]]
            for c in contributions:
                if c.person_id and c.person_id not in self.people:
                    self.errors.append("미해결 저자 참조: " + c.person_id)
            for tag in raw["tags"]:
                if tag not in self.topic_by_id:
                    self.errors.append("미해결 주제 참조: " + tag)
            details = {"text_kind": "editorial_summary", "abstract_available": False,
                       "author_coverage": "selected_curated_profiles", "all_authors": [a["name"] for a in raw["authors"]]}
            for key in ("contribution_note", "boundary_note", "metadata_sources", "venue", "doi", "publication_type", "source_access_note"):
                if key in raw: details[key] = raw[key]
            self.add(self.records, Record(raw["id"], raw["kind"], raw["title"], raw["summary"], raw["date"],
                contributions, raw["tags"], raw.get("field", "ai_foundations"), raw.get("scope", "ai_foundations"), "curated_primary_sources", raw["id"],
                raw["url"], raw.get("checked_at", featured["checked_at"]), raw["evidence_kind"],
                raw.get("classification_basis", ["원문 서지·초록을 확인한 편집 요약"]), details=details))
        for raw in featured.get("experience_records", []):
            person = self.people[raw["person_id"]]
            self.add(self.records, Record(raw["id"], "career_record", raw["title"], raw["summary"], raw["date"],
                [Contribution(person.id, person.name, "recorded_role")], raw["tags"], raw.get("field", "process_engineering"), raw.get("scope", "self_reported"),
                "user_provided_resume", raw["id"], "", featured["checked_at"], "career_experience",
                ["제공된 이력과 경력 보완"], "local_self_reported", False, {"text_kind": "self_reported", "abstract_available": False}))
        questions = self.read("questions.json")["questions"]
        # Runtime receives user-visible prompts only. Evaluation labels and stage notes stay out.
        self.questions = [{k: q[k] for k in ("id", "question", "ai_answer", "mode") if k in q} for q in questions]
        for record in self.records.values():
            if not record.title or not record.people:
                self.errors.append("기록 필수 정보 누락: " + record.id)

    def stats(self):
        papers = [r for r in self.records.values() if r.kind in ("paper", "preprint")]
        company = {c.person_id for r in papers for c in r.people if c.person_id and any(i.get("type") == "company" for i in c.institutions)}
        return {"papers": len(papers), "career_records": sum(r.kind == "career_record" for r in self.records.values()), "researchers": sum(not p.virtual for p in self.people.values()), "site_records": sum(r.virtual for r in self.records.values()), "people": len(self.people), "company_authors": len(company), "missing_author_occurrences": sum(not c.person_id for r in papers for c in r.people), "missing_abstracts": sum(not r.details.get("abstract_available", bool(r.text)) for r in papers), "fields": dict(Counter(r.field for r in papers)), "classification": dict(Counter(r.evidence_kind for r in papers)), "questions": len(self.questions), "checked_at": self.checked_at, "errors": self.errors}
