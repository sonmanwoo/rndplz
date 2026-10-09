"""Side-effect-free public corpus, card and request views shared by web and agents."""
from .data import Corpus
from .engine import Engine, MODE
from .demo_pool import project_corpus, proposal_boundary
from .public_profiles import restrict_personal_publication, selected_public_people

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

def render_draft(corpus, session, c):
    """Private text template; each caller must validate its own authority."""
    sid = session["id"]
    person = corpus.people.get(c["id"])
    display_name = (person.profile or {}).get("display_name") if person else None
    name = display_name.strip() if isinstance(display_name, str) and display_name.strip() else person.name if person else c["name"]
    c = {**c, "profile": {**(c.get("profile") or {}), "display_name": name}}
    slots=session["slots"]
    request_scope={"advice":"15분 자문 또는 문서 의견", "verify":"인용 주장과 전제·검증 방법 검토", "member":"프로젝트에 참여 가능한 역할·기간 협의", "site_request":"현상·운전 조건 검토와 조사 방법 자문", "resource_request":"취급·이관 가능 여부와 담당 경로 확인"}[session["mode"]]
    refs="\n".join("- "+e["title"]+" ("+e["date"]+")"+(" · 가상 현장 기록" if e["virtual"] else "") for e in c["evidence"])
    basis="[연결 근거]\n"+refs
    if c.get("selection")=="user_pick":
        basis="[직접 선택]\n추천 목록 밖에서 요청자가 직접 고른 분입니다. 이번 요청과의 관련성은 아직 확인되지 않았습니다.\n\n[등록 이력]\n"+refs
    body=f'{name}님께,\n\n[막힌 현상]\n{session.get("proposal_context",session["original"])}\n\n[목표]\n{slots["goal"] or "추가 협의"}\n\n[검토 대상]\n{slots["target"] or "추가 협의"}\n\n[가진 자료·조건]\n{slots["resources"] or "추가 협의"} / {slots["conditions"] or "조건 확인 필요"}\n\n[요청 범위]\n{MODE[session["mode"]]} · {request_scope}\n\n{basis}\n\n[기한]\n{slots["deadline"] or "협의 가능"}\n\n감사합니다.\n— 시연 제안자'
    if session["mode"]=="verify":
        claims="\n".join("> "+x for x in session["result"]["claims"])
        body=f'[검증 대상 · AI가 제안한 내용이며 사실로 확인되지 않음]\n{claims}\n\n[확인하고 싶은 점]\n{slots["target"] or "위 주장에 필요한 조건과 검증 방법"}\n\n'+body
    if c["virtual"]:
        body="[시연용 가상 현장 기록에 기반한 제안]\n\n"+body
    if c.get("route_order"):
        body=f'[가상 자원 요청 경로 {c["route_order"]}/{c["route_total"]} · {c["route_role"]}]\n\n'+body
    return {"body":body,"candidate":c,"session_id":sid,"request_kind":session["mode"],"evidence":c["evidence"]}
