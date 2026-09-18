from __future__ import annotations

import re
import unicodedata
from collections import Counter
from .data import Corpus, matches

SCOPE = {"public_research_case":"공개 연구 사례","provided_resume":"제공된 직무 경력","self_reported":"본인 제공 경력","ai_foundations":"AI 기초 연구 · 공개 사례","direct":"직접 관련","adjacent_ev":"인접 분야 · 전기차","adjacent_transformer":"인접 분야 · 변압기","other":"적용 범위 추가 확인","other_field":"다른 연구 분야","virtual_site":"가상 현장 기록"}
KIND = {"career_experience":"제공된 직무 경력","experiment":"실험 문헌","simulation":"시뮬레이션 문헌","review":"리뷰 문헌","theory":"이론 문헌","mixed":"복합 문헌","unknown":"종류 미확인","site_experience":"가상 현장 경험"}
MODE = {"advice":"자문","verify":"검증 요청","member":"프로젝트 멤버","site_request":"현장 의뢰","resource_request":"자원 요청"}
ROLE = {"first":"1저자","middle":"공저자","last":"마지막 저자","unknown":"저자","recorded_role":"기록상 담당"}


class Engine:
    def __init__(self, corpus=None):
        self.corpus = corpus or Corpus()
        self.public_fields = {t["field"] for t in self.corpus.topics} - {
            "site", "immersion_cooling", "cpn_n2o_oxidation", "crystallization_kinetics",
            "ai_foundations", "process_engineering", "energy_catalysis"}

    @staticmethod
    def _profile_mentions(text):
        """Explicit control concepts, with local negation; never record evidence."""
        value = unicodedata.normalize("NFKC", str(text or ""))
        patterns = {
            "process_control": r"공정\s*제어|process\s+control",
            "apc": r"apc|advanced\s+process\s+control|고급\s*공정\s*제어",
            "pid": r"pid(?:\s+(?:control|제어))?|proportional[\s-]+integral[\s-]+derivative(?:\s+control)?|비례\s*적분\s*미분(?:\s*제어)?",
            "mpc": r"mpc(?:\s+(?:control|제어))?|model\s+predictive\s+control|모델\s*예측\s*제어",
        }
        found = []
        for concept, pattern in patterns.items():
            bounded = r"(?<![a-z0-9])(?:" + pattern + r")(?![a-z0-9])"
            found.extend({"concept": concept, "start": m.start(), "end": m.end(),
                          "query_term": m.group(), "negated": False}
                         for m in re.finditer(bounded, value, re.I))
        # Advanced process control is APC, not a second broad parent occurrence.
        found = [m for m in found if not any(n["start"] <= m["start"] and n["end"] >= m["end"]
                 and n["end"] - n["start"] > m["end"] - m["start"] for n in found)]
        found.sort(key=lambda m: (m["start"], m["end"]))
        noun = r"(?:(?:관련(?:된)?|경험|기술|관심|전문가|연구자|사람|분야|제어)\s*)*"
        particle = r"(?:은|는|을|를|이|가|도)?\s*"
        negative = r"(?:말고|제외(?!하지\s*(?:말|않))|빼(?:고|줘|주세요)|아니(?:라|고|야|에요)|아닌|필요\s*없|관심\s*없|안\s*(?:찾|원)|(?:not|excluded|unwanted)\b)"
        suffix = r"^\s*" + noun + particle + r"(?:(?:찾지|추천하지|보여주지|포함하지)\s*)?" + negative
        connector = r"[\s,·/&]*(?:(?:및|와|과|하고|나|또는|and|or)[\s,·/&]*)?"
        for i, item in enumerate(found):
            end = found[i + 1]["start"] if i + 1 < len(found) else len(value)
            right = value[item["end"]:end]
            left = value[found[i - 1]["end"] if i else 0:item["start"]]
            item["negated"] = bool(re.match(suffix, right, re.I) or
                re.search(r"\b(?:not|without|excluding|exclude|except)\s+(?:(?:a|an|the)\s+)?$", left, re.I))
            if item["negated"]:
                # A coordinated list before '말고' is one excluded clause.
                prior = i - 1
                while prior >= 0 and re.fullmatch(connector, value[found[prior]["end"]:found[prior + 1]["start"]], re.I):
                    found[prior]["negated"] = True
                    prior -= 1
        return found

    def profile_query_terms(self, text):
        """Return positive concept IDs in query order, without broadening children."""
        mentions = self._profile_mentions(text)
        latest = {m["concept"]: m["negated"] for m in mentions}
        return list(dict.fromkeys(m["concept"] for m in mentions
                    if not m["negated"] and not latest[m["concept"]]))

    def profile_matches(self, text, person_ids=None):
        """Find declared skills/interests in the already-visible corpus only.

        Matches describe profile text, not performance, availability or eligibility.
        This helper deliberately does not change recommend(), records or their tags.
        """
        mentions = self._profile_mentions(text)
        positive = self.profile_query_terms(text)
        if not positive:
            return []
        latest = {m["concept"]: m["negated"] for m in mentions}
        excluded = {concept for concept, negated in latest.items() if negated}
        query_terms = {concept: next(m["query_term"] for m in mentions
                      if m["concept"] == concept and not m["negated"]) for concept in positive}
        # A specific PID/MPC/APC request must not match an unrelated sibling
        # merely because the query also says 'process control'.
        concepts = [c for c in positive if c != "process_control"] or positive
        requested = None if person_ids is None else ({person_ids} if isinstance(person_ids, str) else set(person_ids))
        results = []
        for pid, person in self.corpus.people.items():
            if requested is not None and pid not in requested:
                continue
            profile = person.profile or {}
            entries = []
            for field, basis in (("skills", "등록 기술"), ("interests", "등록 관심")):
                values = profile.get(field, [])
                if isinstance(values, list):
                    entries.extend((field, f"{field}[{i}]", value, basis) for i, value in enumerate(values) if isinstance(value, str))
            groups = profile.get("skill_groups", [])
            if isinstance(groups, list):
                for i, group in enumerate(groups):
                    items = group.get("items", []) if isinstance(group, dict) else []
                    if isinstance(items, list):
                        entries.extend(("skill_groups", f"skill_groups[{i}].items[{j}]", value, "등록 기술")
                                       for j, value in enumerate(items) if isinstance(value, str))
            matches_found = []
            for field, path, value, basis in entries:
                declared = set(self.profile_query_terms(value)) - excluded
                for concept in concepts:
                    supported = bool(declared) if concept == "process_control" else concept in declared
                    if supported:
                        matches_found.append({"field": field, "path": path, "value": value,
                                              "basis": basis, "concept": concept, "query_term": query_terms[concept]})
            if matches_found:
                results.append({"person_id": pid, "matches": matches_found})
        return results

    def topics_for(self, text):
        scores = {t["id"]:sum(matches(text,k) for k in t["keywords"]) for t in self.corpus.topics}
        has_ai_topic = any(v for k,v in scores.items() if k.startswith(("AI-", "PE-", "CE-")) or self.corpus.topic_by_id[k]["field"] in self.public_fields)
        for person in self.corpus.people.values():
            if not has_ai_topic and person.profile.get("curated") and any(matches(text, a) for a in person.profile.get("aliases", [])):
                for record in self.corpus.by_person[person.id]:
                    for tag in record.tags:
                        scores[tag] = max(scores.get(tag, 0), 2)
        return {k:v for k,v in scores.items() if v}

    def mode_for(self, text, mode=None):
        if mode in MODE:
            return mode
        if re.search(r"AI.*(답|말|제안)|검증 대상|맞는지", text, re.I):
            return "verify"
        if re.search(r"소분|벌크|[0-9]+\s*kg|자원|구매|시료.*(필요|구해)", text, re.I):
            return "resource_request"
        if re.search(r"탱크|거품|누유|현장|공장", text):
            return "site_request"
        if re.search(r"팀|멤버|프로젝트.*함께", text):
            return "member"
        return "advice"

    def field_for(self, topics, mode, text=""):
        if "T07" in topics and any(matches(text,k) for k in ("사이클로펜텐","사이클로펜타논","cpn","cyclopentene","cyclopentanone","산화","oxidation")):
            return "cpn_n2o_oxidation"
        if "T08" in topics and any(matches(text,k) for k in ("결정","핵생성","crystall","nucleation")):
            return "crystallization_kinetics"
        if mode == "resource_request":
            return "site" if any(t.startswith("T_") for t in topics) else "unknown"
        # Broad words like AI, lifespan, material, water, and flow cannot establish
        # that an unrelated question belongs to this narrowly curated corpus.
        anchors=("액침","냉각","서버","데이터센터","데이터 센터","회로기판","pcb","fkm","fr-4","절연유","변압기","윤활유","기유","pao","poe","에스테르","전기차","배터리","immersion","coolant","cooling","data center","datacenter","transformer","dielectric fluid","lubricant","thermal management","heat transfer")
        if any(t in topics for t in ("T01","T02","T03","T04","T05","T06")) and any(matches(text,k) for k in anchors):
            return "immersion_cooling"
        extra_fields = {self.corpus.topic_by_id[t]["field"] for t in topics
                        if self.corpus.topic_by_id[t]["field"] in self.public_fields}
        if extra_fields:
            return next(iter(extra_fields)) if len(extra_fields) == 1 else "unknown"
        if any(t.startswith("CE-") for t in topics):
            return "energy_catalysis"
        if any(t.startswith("PE-") for t in topics):
            return "process_engineering"
        return "ai_foundations" if any(t.startswith("AI-") for t in topics) else "unknown"

    def claims(self, text):
        parts = re.split(r"(?<=[.!?。])\s+|\n+|(?<=이며),?\s+",text)
        return [p.strip() for p in parts if p.strip() and re.search(r"\d|변하지|안전|이하|이상|미만",p)][:5]

    def explain_record(self, record, contribution=None):
        boundary = {"adjacent_ev":"전기차 연구이며 서버 조건으로의 적용은 별도 검토가 필요합니다.","adjacent_transformer":"변압기 절연유 연구이며 서버 소재·운전 조건과 구분해야 합니다.","other":"대상·운전 조건의 일치 여부를 추가 확인해야 합니다.","other_field":"다른 연구 분야입니다. 이 코퍼스의 자료 범위 안에서만 판단합니다."}.get(record.scope,"개인의 실험 수행 역할·현재 소속·연락 의향은 확인되지 않았습니다.")
        if record.virtual:
            boundary = "시연용 가상 현장 기록입니다. 실제 인물·사업장·승인 절차가 아닙니다."
        elif not record.text:
            boundary += " 초록이 없어 제목·메타데이터에 근거합니다."
        if record.scope == "ai_foundations":
            boundary = "공개 AI 연구 사례입니다. 사내 재직·협업 가능 여부나 정유·냉각 분야 수행 경험을 뜻하지 않습니다."
        if record.scope == "public_research_case":
            boundary = "공식 프로필·논문에 근거한 공개 연구 사례입니다. 사내 재직·개인 수행·현재 협업 가능 여부는 확인하지 않았습니다."
            boundary += " " + " ".join(record.details.get(k, "") for k in ("contribution_note", "boundary_note") if record.details.get(k))
        if record.kind == "career_record":
            boundary = "본인 제공 경력 자료입니다. 회사 HR 검증·수행 수준·현재 협업 가능 여부는 확인하지 않았습니다."
        if record.scope == "provided_resume":
            boundary = "사용자가 제공한 직무 경력입니다. 회사 HR 검증·수행 수준·협업 가능 여부는 별도 확인이 필요합니다."
        if record.kind == "preprint":
            boundary += " 프리프린트이며 심사 완료 논문으로 간주하지 않습니다."
        return {"id":record.id,"kind":record.kind,"title":record.title,"date":record.date,"url":record.source_url,"scope":SCOPE.get(record.scope,record.scope),"scope_key":record.scope,"evidence_kind":record.evidence_kind,"evidence_label":KIND[record.evidence_kind],"classification_basis":record.classification_basis,"checked_at":record.checked_at,"virtual":record.virtual,"boundary":boundary,"role":ROLE.get(contribution.role,"저자") if contribution else "기록","corresponding":bool(contribution and contribution.corresponding),"access":"제공된 직무 이력" if record.scope == "provided_resume" else "본인 제공 이력·경력 보완" if record.kind == "career_record" else "서지·편집 요약 (초록 원문 아님)" if record.details.get("text_kind") == "editorial_summary" else "가상 기록" if record.virtual else "메타데이터·초록" if record.text else "메타데이터","tags":record.tags}

    def record_scores(self, text, topics, field, mode):
        scored=[]
        for record in self.corpus.records.values():
            if record.virtual:
                if mode not in ("site_request","resource_request"):
                    continue
            elif field != record.field or mode == "resource_request":
                continue
            overlap=set(topics)&set(record.tags)
            if not overlap:
                continue
            score=0.0
            for tid in overlap:
                terms=self.corpus.topic_by_id[tid]["keywords"]
                title_hits=sum(matches(record.title,k) for k in terms)
                abstract_hits=sum(matches(record.text,k) for k in terms)
                score+=topics[tid]*(.15+min(title_hits,4)*.14+min(abstract_hits,6)*.025)
            aliases={"pcb":"회로기판","fkm":"고무","n2o":"아산화질소","cyclopentanone":"사이클로펜타논","crystallization":"결정화"}
            for entity in ("pcb","fkm","pao","poe","fr-4","n2o","cyclopentanone","crystallization"):
                if (matches(text,entity) or (entity in aliases and aliases[entity] in text)) and matches(record.title+" "+record.text,entity):
                    score+=.6
            if record.field in self.public_fields or record.field in ("ai_foundations", "process_engineering", "energy_catalysis"):
                if any(c.person_id and any(matches(text, a) for a in self.corpus.people[c.person_id].profile.get("aliases", [])) for c in record.people):
                    score += 2
            if record.scope.startswith("adjacent"):
                score*=.75
            if mode=="verify":
                score*={"experiment":1.15,"mixed":1,"review":.5,"simulation":.7,"unknown":.6}.get(record.evidence_kind,.75)
            if not record.text and not record.virtual:
                score*=.85
            scored.append((record,round(score,6)))
        return sorted(scored,key=lambda pair:(-pair[1],pair[0].id))

    def candidate(self, person, scored, query_topics, query_text=""):
        best,best_score=scored[0]
        contribution=next(c for c in best.people if c.person_id==person.id)
        evidence=[self.explain_record(r,next(c for c in r.people if c.person_id==person.id)) for r,_ in scored[:3]]
        own=self.corpus.by_person[person.id]
        names=[t.get("name","") for t in person.profile.get("topics",[])[:3]]
        overlap=set(query_topics)&set(self.topics_for(" ".join(names)))
        orgs=contribution.institutions
        org=" / ".join(i.get("name","") for i in orgs) or person.org
        org_type="company" if any(i.get("type")=="company" for i in orgs) else orgs[0].get("type","unknown") if orgs else person.org_type
        shared = [self.corpus.topic_by_id[t] for t in query_topics if t in best.tags]
        question_terms = [k for t in shared for k in t["keywords"] if matches(query_text, k)]
        # Synonyms share a topic; participation is evidence, not proof of hands-on work.
        topic_name = shared[0]["name"] if shared else self.corpus.topic_by_id[best.tags[0]]["name"]
        focus = " · ".join(dict.fromkeys(question_terms[:2])) or topic_name
        reason = f'요청의 「{focus}」와 연결된 「{best.title}」에 {ROLE.get(contribution.role, "저자")}로 참여한 기록이 있습니다.'
        if best.kind == "career_record":
            reason = f'요청의 「{focus}」와 연결된 「{best.title}」 경험이 제공된 직무 경력에 기록되어 있습니다.'
        role = topic_name
        if person.virtual:
            reason = f'요청의 「{focus}」와 연결된 「{best.title}」 경험이 시연용 가상 현장 기록에 있습니다.'
            role=best.details["role"]
        return {"id":person.id,"name":person.name,"profile":person.profile if person.profile.get("curated") else {},"org":org,"org_type":org_type,"role":role,"reason":reason,"experience":best.details["role"] if person.virtual else best.title,"virtual":person.virtual,"kind":person.kind,"evidence":evidence,"topics":sorted({t for r,_ in scored for t in r.tags}),"evidence_counts":dict(Counter(r.evidence_kind for r in own)),"works_count":person.profile.get("works_count"),"works_in_corpus":len(own),"relevant_records":len(scored),"profile_topics":names,"portfolio":"관련 주제 확인" if overlap else "참여 문헌에서 확인 · 전체 이력은 추가 확인","record_confirmed":True,"individual_performance_verified":False,"person_confirmed":False,"availability":"미확인","details":best.details if person.virtual else {},"score_internal":round(best_score+min(sum(s for _,s in scored[1:3])*.06,.2),6)}

    def recommend(self,text,mode=None,limit=7):
        mode=self.mode_for(text,mode)
        topics=self.topics_for(text)
        field=self.field_for(topics,mode,text)
        if field=="unknown":
            topics={}
        scores=self.record_scores(text,topics,field,mode) if topics else []
        grouped={}
        named = {p.id for p in self.corpus.people.values() if p.profile.get("curated") and any(matches(text, a) for a in p.profile.get("aliases", []))}
        for record,score in scores:
            for contribution in record.people:
                if named and (field in self.public_fields or field in ("ai_foundations", "process_engineering", "energy_catalysis")) and contribution.person_id not in named:
                    continue
                if contribution.person_id and score>=.2:
                    grouped.setdefault(contribution.person_id,[]).append((record,score))
        candidates=[self.candidate(self.corpus.people[pid],records,topics,text) for pid,records in grouped.items()]
        candidates.sort(key=lambda c:(-c["score_internal"],c["id"]))
        if mode=="resource_request":
            route=[]
            for label,patterns in [("취급·소분 경험",("소분",)),("구매·이관 경로",("이관","분할 승인")),("반출 절차 확인",("반출 승인",))]:
                found=next((c for c in candidates if c not in route and any(p in " ".join(c["details"].get("can_help_with",[])) for p in patterns)),None)
                if found:
                    found["route_role"]=label
                    route.append(found)
            candidates=route
            for i,c in enumerate(candidates):
                c.update(route_order=i+1,route_total=len(candidates),previous=candidates[i-1]["name"] if i else None,next=candidates[i+1]["name"] if i+1<len(candidates) else None)
        elif mode=="site_request":
            site=[c for c in candidates if c["virtual"]][:2]
            candidates=site+[c for c in candidates if not c["virtual"]][:max(0,limit-len(site))]
        else:
            candidates=candidates[:limit]
        for c in candidates:
            c.pop("score_internal",None)
        strip=[]
        if scores and not scores[0][0].virtual:
            for c in scores[0][0].people:
                strip.append({"name":c.name,"id":c.person_id,"role":ROLE.get(c.role,"저자"),"corresponding":c.corresponding,"profile_status":"프로필 연결" if c.person_id else "프로필 미등록","individual_performance_verified":False})
        return {"mode":mode,"mode_label":MODE[mode],"field":field,"topic_ids":list(topics),"candidates":candidates,"author_strip":strip,"author_strip_record":self.explain_record(scores[0][0]) if strip else None,"closest_topics":[t["name"] for t in self.corpus.topics[:3]] if not candidates else [],"empty_message":"이 코퍼스에서 충분한 근거를 갖춘 후보를 찾지 못했습니다." if not candidates else "","record_count":len(scores),"model_calls":0,"ranking_source":"규칙","claims":self.claims(text) if mode=="verify" else []}

    def clarify(self,text,mode,turns):
        if turns>=2 or not self.topics_for(text):
            return None
        if mode=="verify":
            return "검증할 주장 중 무엇을 먼저 확인하고 싶나요? 대상 소재나 조건을 함께 적어 주세요."
        if mode=="resource_request":
            return "필요한 물질의 종류와 수량·기한을 알려 주세요."
        if mode=="site_request":
            return "어떤 설비에서, 어떤 운전 조건일 때 현상이 나타나나요?"
        if "T02" in self.topics_for(text):
            return "회로기판과 고무 씰 중 무엇을 먼저 검토하고 싶나요?"
        return "검토하려는 대상과 가장 중요한 조건을 한 가지 알려 주세요."
