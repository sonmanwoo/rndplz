from __future__ import annotations

import copy
import hashlib
import json
import re
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from .data import ROOT
from .engine import Engine, MODE
from .demo_pool import present_session, require_proposal_boundary
from .storage import StateStore
from .models import ExternalModel


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def validate_text(value, limit=20000, empty=False):
    if not isinstance(value,str) or len(value)>limit or (not empty and not value.strip()):
        raise ValueError("내용이 비어 있거나 허용 길이를 넘었습니다.")
    return value.strip()


class Service:
    def __init__(self, engine=None, state_dir=None, model=None):
        self.engine=engine or Engine()
        self.corpus=self.engine.corpus
        self.store=StateStore(state_dir or ROOT/"out"/"state")
        self.model=model or ExternalModel(audit_path=self.store.directory/"model-events.jsonl")

    def present_session(self, session):
        return present_session(session, self.corpus)

    def bootstrap(self):
        state=self.store.read()
        return {"version":"0.1.0","stats":self.corpus.stats(),"questions":self.corpus.questions,"topics":self.corpus.topics,"session":self.present_session(state["sessions"][-1]) if state["sessions"] else None,"proposal_count":len(state["proposals"]),"model":self.model.status()}

    def converse(self, payload):
        text=validate_text(payload.get("text",""),empty=bool(payload.get("session_id")))
        explicit_mode=payload.get("mode")
        if explicit_mode and explicit_mode not in MODE:
            raise ValueError("알 수 없는 의뢰 종류입니다.")
        def update(state):
            sid=payload.get("session_id")
            if sid:
                session=next((s for s in state["sessions"] if s["id"]==sid),None)
                if session is None:
                    raise ValueError("대화를 찾을 수 없습니다.")
                if session.get("kind") == "chat":
                    raise ValueError("채팅에서 시작한 요청은 대화창에 새 조건을 입력해 이어가 주세요.")
                if session["turns"]>=3:
                    raise ValueError("이 대화는 이미 구체화를 마쳤습니다. 조건을 수정하거나 새 질문을 시작해 주세요.")
                session["turns"]+=1
                session["messages"].append({"role":"user","text":text or "추가 조건 없음"})
                if text and not session["slots"]["conditions"]:
                    session["slots"]["conditions"]=text
            else:
                if not text:
                    raise ValueError("질문을 입력해 주세요.")
                mode=self.engine.mode_for(text,explicit_mode)
                session={"id":uuid.uuid4().hex,"created":now(),"updated":now(),"original":text,"messages":[{"role":"user","text":text}],"turns":1,"mode":mode,"asker":"site" if mode=="site_request" else "lab","slots":{"target":"","conditions":"","resources":"","deadline":"","goal":text},"result":None}
                state["sessions"].append(session)
            if explicit_mode:
                session["mode"]=explicit_mode
            patch=payload.get("slots") or {}
            if not isinstance(patch,dict):
                raise ValueError("조건 카드 형식이 올바르지 않습니다.")
            for k,v in patch.items():
                if k in session["slots"]:
                    value=validate_text(v,20000,True)
                    if k=="goal" and not sid and not value:
                        continue
                    session["slots"][k]=value
            if sid and text and not session["slots"]["conditions"]:
                session["slots"]["conditions"]=text
            session["asker"]="site" if session["mode"]=="site_request" else "lab"
            self.refresh(session)
            followup=None if payload.get("skip") else self.engine.clarify(session["original"],session["mode"],session["turns"])
            session["followup"]=followup
            session["ready"]=not bool(followup)
            response=followup or ("근거가 있는 후보를 살펴보세요. 개인의 수행 역할은 별도 확인이 필요합니다." if session["result"]["candidates"] else session["result"]["empty_message"])
            session["messages"].append({"role":"assistant","text":response})
            session["updated"]=now()
            return self.present_session(session)
        return self.store.transaction(update)

    def refresh(self,session):
        query=session["original"]
        query+=" "+" ".join(str(v) for k,v in session["slots"].items() if v and str(v) not in query)
        session["result"]=self.engine.recommend(query,session["mode"])

    def update_slots(self,payload):
        def update(state):
            session=next((s for s in state["sessions"] if s["id"]==payload.get("session_id")),None)
            if not session:
                raise ValueError("대화를 찾을 수 없습니다.")
            if session.get("kind") == "chat":
                raise ValueError("채팅에서 시작한 요청은 대화창에 새 조건을 입력해 이어가 주세요.")
            patch=payload.get("slots") or {}
            if not isinstance(patch,dict):
                raise ValueError("조건 카드 형식이 올바르지 않습니다.")
            for k,v in patch.items():
                if k in session["slots"]:
                    session["slots"][k]=validate_text(v,20000,True)
            if payload.get("mode") in MODE:
                session["mode"]=payload["mode"]
            session["asker"]="site" if session["mode"]=="site_request" else "lab"
            self.refresh(session)
            session["ready"]=True
            session["followup"]=None
            session["updated"]=now()
            return self.present_session(session)
        return self.store.transaction(update)

    def session(self,sid):
        session=next((s for s in self.store.read()["sessions"] if s["id"]==sid),None)
        if not session:
            raise ValueError("대화를 찾을 수 없습니다.")
        return self.present_session(session)

    def draft(self,sid,cid):
        session=self.session(sid)
        c=next((c for c in (session.get("result") or {}).get("candidates",[]) if c["id"]==cid),None)
        if not c:
            raise ValueError("이 질문의 근거 있는 후보를 선택해 주세요.")
        if c.get("lookup_only"):
            raise ValueError("지금은 인물 이력 조회입니다. 도움받을 일과 조건을 입력해 관련 근거로 사람을 찾아 주세요.")
        require_proposal_boundary(self.corpus, cid, c.get("evidence"))
        slots=session["slots"]
        request_scope={"advice":"15분 자문 또는 문서 의견", "verify":"인용 주장과 전제·검증 방법 검토", "member":"프로젝트에 참여 가능한 역할·기간 협의", "site_request":"현상·운전 조건 검토와 조사 방법 자문", "resource_request":"취급·이관 가능 여부와 담당 경로 확인"}[session["mode"]]
        refs="\n".join("- "+e["title"]+" ("+e["date"]+")"+(" · 가상 현장 기록" if e["virtual"] else "") for e in c["evidence"])
        body=f'{c["name"]}님께,\n\n[막힌 현상]\n{session.get("proposal_context",session["original"])}\n\n[목표]\n{slots["goal"] or "추가 협의"}\n\n[검토 대상]\n{slots["target"] or "추가 협의"}\n\n[가진 자료·조건]\n{slots["resources"] or "추가 협의"} / {slots["conditions"] or "조건 확인 필요"}\n\n[요청 범위]\n{MODE[session["mode"]]} · {request_scope}\n\n[연결 근거]\n{refs}\n\n[기한]\n{slots["deadline"] or "협의 가능"}\n\n감사합니다.\n— 시연 제안자'
        if session["mode"]=="verify":
            claims="\n".join("> "+x for x in session["result"]["claims"])
            body=f'[검증 대상 · AI가 제안한 내용이며 사실로 확인되지 않음]\n{claims}\n\n[확인하고 싶은 점]\n{slots["target"] or "위 주장에 필요한 조건과 검증 방법"}\n\n'+body
        if c["virtual"]:
            body="[시연용 가상 현장 기록에 기반한 제안]\n\n"+body
        if c.get("route_order"):
            body=f'[가상 자원 요청 경로 {c["route_order"]}/{c["route_total"]} · {c["route_role"]}]\n\n'+body
        return {"body":body,"candidate":c,"session_id":sid,"request_kind":session["mode"],"evidence":c["evidence"]}

    def save_proposal(self,payload):
        key=validate_text(payload.get("idempotency_key",""),100)
        sid=validate_text(payload.get("session_id",""),100)
        ids=payload.get("candidate_ids")
        if not isinstance(ids,list) or not 1<=len(ids)<=7 or not all(isinstance(x,str) for x in ids) or len(set(ids))!=len(ids):
            raise ValueError("수신 후보를 1~7명 선택해 주세요.")
        state_name=payload.get("state","sent")
        if state_name not in ("draft","sent"):
            raise ValueError("초안 또는 시연 보냄만 생성할 수 있습니다.")
        bodies=payload.get("bodies") or {}
        if not isinstance(bodies,dict):
            raise ValueError("제안문 형식이 올바르지 않습니다.")
        digest=hashlib.sha256(json.dumps([sid,ids,state_name,bodies],ensure_ascii=False,sort_keys=True).encode()).hexdigest()
        def update(state):
            if key in state["idempotency"]:
                prior=state["idempotency"][key]
                if prior["digest"]!=digest:
                    raise ValueError("이미 다른 요청에 사용한 저장 식별자입니다.")
                return [p for p in state["proposals"] if p["id"] in prior["ids"]]
            session=next((s for s in state["sessions"] if s["id"]==sid),None)
            if not session:
                raise ValueError("대화를 찾을 수 없습니다.")
            created=[]
            group=uuid.uuid4().hex
            for cid in ids:
                c=next((c for c in (session.get("result") or {}).get("candidates",[]) if c["id"]==cid),None)
                if not c:
                    raise ValueError("추천 근거가 없는 수신자입니다.")
                draft=self.draft(sid,cid)
                body=validate_text(bodies.get(cid,draft["body"]),30000)
                if session["mode"]=="verify" and "검증 대상" not in body:
                    raise ValueError("검증 요청에는 '검증 대상' 표시가 필요합니다.")
                if c["virtual"] and "가상" not in body:
                    raise ValueError("현장 제안에는 '가상' 표시가 필요합니다.")
                stamp=now()
                p={"id":uuid.uuid4().hex,"group_id":group,"session_id":sid,"recipient_id":cid,"recipient_name":c["name"],"request_kind":session["mode"],"direction":session["asker"]+"→"+("site" if c["virtual"] else "lab"),"body":body,"evidence":c["evidence"],"topics":session["result"]["topic_ids"],"state":state_name,"simulated":True,"virtual":c["virtual"],"route_order":c.get("route_order"),"route_total":c.get("route_total"),"copy_to_proposer":True,"created":stamp,"updated":stamp,"history":[{"state":state_name,"at":stamp,"simulated":True}]}
                created.append(p)
            state["proposals"].extend(created)
            state["idempotency"][key]={"digest":digest,"ids":[p["id"] for p in created]}
            return created
        return self.store.transaction(update)

    def transition(self,pid,target):
        allowed={"draft":{"sent","cancelled"},"sent":{"accepted","declined","closed","cancelled"},"accepted":{"closed"},"declined":{"closed"},"closed":set(),"cancelled":set()}
        def update(state):
            p=next((p for p in state["proposals"] if p["id"]==pid),None)
            if not p or target not in allowed[p["state"]]:
                raise ValueError("허용되지 않는 상태 변경입니다.")
            if p["state"] == "draft" and target == "sent":
                require_proposal_boundary(self.corpus, p.get("recipient_id"), p.get("evidence"))
            p["state"]=target;p["updated"]=now()
            p["history"].append({"state":target,"at":p["updated"],"simulated":True})
            return p
        return self.store.transaction(update)


    def ai_structure(self,payload):
        if payload.get("consent") is not True:
            raise ValueError("설정에서 외부 AI 전송 범위를 확인해 주세요.")
        text=validate_text(payload.get("text",""),20000)
        return self.model.structure(text)

    def ai_draft(self,payload):
        if payload.get("consent") is not True:
            raise ValueError("설정에서 외부 AI 전송 범위를 확인해 주세요.")
        draft=self.draft(payload.get("session_id"),payload.get("candidate_id"))
        body=validate_text(payload.get("body",draft["body"]),20000)
        return self.model.draft(body,draft["candidate"],self.session(draft["session_id"])["original"])

    def admin(self,state=None):
        state=self.store.read() if state is None else state
        nodes=[]
        for person in self.corpus.people.values():
            records=self.corpus.by_person[person.id]
            nodes.append({"id":person.id,"name":person.name,"aliases":person.profile.get("aliases",[]),"virtual":person.virtual,"org_type":person.org_type,"record_count":len(records),"topics":sorted({t for r in records for t in r.tags})})
        rows=[]
        for topic in self.corpus.topics:
            tid=topic["id"]
            matching=[n for n in nodes if tid in n["topics"]]
            demand=len({s["id"] for s in state["sessions"] if s["result"] and tid in s["result"]["topic_ids"]})
            papers=[r for r in self.corpus.records.values() if tid in r.tags]
            rows.append({"id":tid,"name":topic["name"],"demand":demand,"people":len(matching),"researchers":sum(not n["virtual"] for n in matching),"virtual_people":sum(n["virtual"] for n in matching),"records":len(papers),"confirmed":0,"ratio":round(demand/len(matching),4) if matching else None,"strategy":"이 자료에서 확인 못함" if not matching else "개인 수행·본인 확인 필요" if demand else "요청이 생기면 관련 근거 확인"})
        return {"featured":[self.person(p.id) for p in self.corpus.people.values() if p.profile.get("curated")],"nodes":nodes,"topics":rows,"proposals":len(state["proposals"]),"states":dict(Counter(p["state"] for p in state["proposals"])),"directions":dict(Counter(p["direction"] for p in state["proposals"])),"requests":len(state["sessions"]),"note":"공개 문헌·본인 제공 경력·가상 현장 기록의 분포입니다. 회사 역량·가용 인원 평가가 아닙니다."}

    def person(self,pid):
        person=self.corpus.people.get(pid)
        if not person:
            raise ValueError("인물 기록을 찾을 수 없습니다.")
        records=self.corpus.by_person[pid]
        return {"id":pid,"name":person.name,"profile":person.profile if person.profile.get("curated") else {},"virtual":person.virtual,"org":person.org,"record_count":len(records),"evidence":[self.engine.explain_record(r,next(c for c in r.people if c.person_id==pid)) for r in records],"profile_topics":[t.get("name","") for t in person.profile.get("topics",[])[:3]],"person_confirmed":False}
