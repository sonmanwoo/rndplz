"""Side-effect-free public corpus, card and request views shared by web and agents."""
from .data import Corpus
from .engine import Engine
from .demo_pool import project_corpus, proposal_boundary
from .public_profiles import restrict_personal_publication, selected_public_people
from .request_letter import ASK, letter_key, rule_text

SOURCE_NOTE = '공개 논문·제공 경력·가상 현장 기록이며 사내 실명부가 아닙니다.'
AVAILABILITY_NOTE = '현재 소속·가용 시간·연락 의향은 미확인'


class PickError(ValueError):
    """Fixed, user-facing reasons a person picked on the map cannot receive this request."""
    code = 'pick_unavailable'


def build_public_engine(env, include_personal=None, *, corpus=None):
    """Use precisely the public web publication gate before building an engine."""
    corpus = Corpus() if corpus is None else corpus
    approved = env.get('RNDPLZ_PUBLISH_PERSONAL') == '1' if include_personal is None else include_personal
    if not approved:
        selected = selected_public_people(env) if include_personal is None else frozenset()
        restrict_personal_publication(corpus, selected)
    corpus = project_corpus(corpus, allow_personal_omission=not approved)
    return Engine(corpus)


def record_payload(engine, identifier):
    record = engine.corpus.records.get(identifier)
    if not record:
        raise ValueError('기록을 찾을 수 없습니다.')
    return {**engine.explain_record(record), 'text': record.text, 'details': record.details}


def person_payload(engine,pid):
    person=engine.corpus.people.get(pid)
    if not person:
        raise ValueError("인물 기록을 찾을 수 없습니다.")
    records=engine.corpus.by_person[pid]
    return {"id":pid,"name":person.name,"profile":person.profile if person.profile.get("curated") else {},"virtual":person.virtual,"org":person.org,"record_count":len(records),"evidence":[engine.explain_record(r,next(c for c in r.people if c.person_id==pid)) for r in records],"profile_topics":[t.get("name","") for t in person.profile.get("topics",[])[:3]],"person_confirmed":False}


def picked_candidate(engine,session,cid):
    """Someone the requester chose on the map instead of a recommendation. The same request
    goes to them, marked as the requester's own choice; their records are listed, not judged."""
    result=session.get("result")
    policy=getattr(engine.corpus,"demo_pool",None)
    if (not isinstance(result,dict) or not result.get("candidates") or result.get("inspection_only")
            or any(c.get("lookup_only") for c in result["candidates"])
            or (policy and result.get("pool_version")!=policy["version"])):
        raise PickError("현재 요청으로 사람을 찾은 대화에서만 다른 분께 의뢰를 보낼 수 있어요.")
    if any(c["id"]==cid for c in result["candidates"]):
        raise PickError("추천된 분은 후보 카드에서 의뢰를 보내 주세요.")
    person=engine.corpus.people.get(cid)
    if not person:
        raise PickError("현재 명단에 없는 인물이에요.")
    records=sorted(engine.corpus.by_person.get(cid,[]),key=lambda r:r.date or "",reverse=True)[:5]
    if not records:
        raise PickError("등록된 이력이 없는 분이라 의뢰를 보낼 수 없어요.")
    evidence=[engine.explain_record(r,next(c for c in r.people if c.person_id==cid)) for r in records]
    reason=proposal_boundary(engine.corpus,cid,evidence)
    if reason:
        raise PickError(reason)
    profile=person.profile if person.profile.get("curated") else {}
    name=profile.get("display_name") if isinstance(profile.get("display_name"),str) and profile["display_name"].strip() else person.name
    return {"id":cid,"name":name,"virtual":person.virtual,"evidence":evidence,"selection":"user_pick"}

def request_text(session):
    """The request in a letter: the company AI's paragraph written for this exact brief, else the brief laid
    out plainly; a session without an approved brief keeps its request text."""
    from .model_conversation import request_spec_content
    spec=request_spec_content(session.get("request_spec"))
    if spec is not None and spec["has_content"] is True:
        written=session.get("request_letter") or {}
        if written.get("key")==letter_key(spec,session["mode"]) and isinstance(written.get("body"),str) and written["body"].strip():
            return written["body"]
        return rule_text(spec)
    slots=session["slots"]
    lines=["지금 이런 일로 도움이 필요합니다.\n"+session.get("proposal_context",session["original"])]
    lines+=[label+": "+slots[key] for label,key in (("검토 대상","target"),("가진 자료","resources"),("조건","conditions")) if slots.get(key)]
    return "\n\n".join(lines)

def render_draft(corpus, session, c):
    """Private text template; each caller must validate its own authority."""
    sid = session["id"]
    person = corpus.people.get(c["id"])
    display_name = (person.profile or {}).get("display_name") if person else None
    name = display_name.strip() if isinstance(display_name, str) and display_name.strip() else person.name if person else c["name"]
    c = {**c, "profile": {**(c.get("profile") or {}), "display_name": name}}
    slots=session["slots"]
    # A letter to a colleague (2026-10-14): greeting, why this person, the request in sentences, the ask and
    # thanks, then the records it rests on. It was the brief under bracket headings, read like a form.
    titles=[e["title"] for e in c["evidence"]]
    seen=("「"+titles[0]+"」"+(" 외 "+str(len(titles)-1)+"건의 기록" if len(titles)>1 else "" if titles[0].endswith("기록") else " 기록")) if titles else "기록"
    picked=c.get("selection")=="user_pick"
    if picked:
        why=f"수소문 추천 목록에는 없었지만, {name}님의 {seen}을 보고 제가 직접 골라 연락드립니다. 이번 일과 맞닿아 있는지는 아직 확인하지 못했습니다."
    else:
        why=f"수소문에서 {name}님의 {seen}을 보고 연락드립니다."
        if c.get("purpose_relation")=="adjacent":
            why+=" 이번 일과 같은 분야는 아닐 수 있지만, 가까운 주제의 기록이라 의견을 여쭙고 싶었습니다."
    parts=[f"{name}님, 안녕하세요.", why]
    if session["mode"]=="verify":
        claims="\n".join("> "+x for x in session["result"]["claims"])
        parts.append(f'검증 대상 (AI가 제안한 내용이며 아직 사실로 확인되지 않았습니다)\n{claims}\n\n확인하고 싶은 점: {slots["target"] or "위 주장에 필요한 조건과 검증 방법"}')
    parts.append(request_text(session))
    when=(f"기한은 {slots['deadline']}입니다만, 일정은 {name}님 편하신 때에 최대한 맞추겠습니다." if slots["deadline"]
          else f"일정은 {name}님 편하신 때에 맞추겠습니다.")
    parts+=[ASK[session["mode"]]+" "+when, "바쁘신 중에 읽어 주셔서 감사합니다.\n— 시연 제안자"]
    refs="\n".join("- "+e["title"]+(" ("+e["date"]+")" if e.get("date") else "")+(" · 가상 현장 기록" if e["virtual"] else "") for e in c["evidence"])
    parts.append("참고한 기록\n"+refs)
    body="\n\n".join(part for part in parts if part)
    if c["virtual"]:
        body="[시연용 가상 현장 기록에 기반한 제안]\n\n"+body
    if c.get("route_order"):
        body=f'[가상 자원 요청 경로 {c["route_order"]}/{c["route_total"]} · {c["route_role"]}]\n\n'+body
    return {"body":body,"candidate":c,"session_id":sid,"request_kind":session["mode"],"evidence":c["evidence"]}
