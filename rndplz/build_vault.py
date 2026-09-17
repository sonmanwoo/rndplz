from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
import uuid
import re
import sys
from collections import Counter
from pathlib import Path
from urllib.parse import quote
if __package__ in (None,""):
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from rndplz.data import ROOT
from rndplz.service import Service


def short(identifier):
    return identifier.rsplit("/",1)[-1]


def text(value):
    return str(value or "").replace("[[","［［").replace("]]","］］").replace("<","&lt;")


def note(meta,body):
    return "---\n"+"\n".join(k+": "+json.dumps(v,ensure_ascii=False) for k,v in meta.items())+"\n---\n\n"+body+"\n"



def atomic_write(path,content):
    temporary=path.with_name(path.name+"."+uuid.uuid4().hex+".tmp")
    try:
        with temporary.open("wb") as f:
            f.write(content.encode("utf-8"));f.flush();os.fsync(f.fileno())
        os.replace(temporary,path)
    finally:
        temporary.unlink(missing_ok=True)


def export_vault(service,target=None):
    target=Path(target or ROOT/"out"/"vault").resolve()
    target.mkdir(parents=True,exist_ok=True)
    lockfile=target/".rndplz-export.lock"
    deadline=time.monotonic()+3
    while True:
        try:
            fd=os.open(lockfile,os.O_CREAT|os.O_EXCL|os.O_WRONLY)
            os.close(fd);break
        except FileExistsError:
            if time.monotonic()>deadline:
                raise ValueError("다른 볼트 내보내기가 진행 중입니다. 잠시 후 다시 시도해 주세요.")
            time.sleep(.03)
    try:
        return _export_vault(service,target)
    finally:
        lockfile.unlink(missing_ok=True)

def _export_vault(service,target=None):
    target=Path(target or ROOT/"out"/"vault").resolve()
    target.mkdir(parents=True,exist_ok=True)
    corpus=service.corpus
    state=service.store.read()
    admin=service.admin(state)
    notes={}
    def link(folder,identifier):
        label=None
        if folder=="Researchers":
            person=corpus.people.get(identifier)
            label=person.name if person else None
        elif folder=="Topics":
            topic=corpus.topic_by_id.get(identifier)
            label=topic["name"] if topic else None
        elif folder in ("Papers","SiteRecords","CareerRecords"):
            record=corpus.records.get(identifier)
            label=record.title if record else None
        alias="|"+str(label).replace("|"," ").replace("]"," ").replace("["," ") if label else ""
        return "[["+folder+"/"+short(identifier)+alias+"]]"
    for p in corpus.people.values():
        records=corpus.by_person[p.id]
        prefix="시연용 가상 인물\n\n" if p.virtual else ""
        body="# "+text(p.name)+"\n\n"+prefix+"개인 수행·본인 확인·연락 의향: 미확인\n\n"+"".join("- "+link("SiteRecords" if r.virtual else "CareerRecords" if r.kind == "career_record" else "Papers",r.id)+"\n" for r in records)
        received=[x for x in state["proposals"] if x["recipient_id"]==p.id]
        body+="\n## 시연 제안\n"+"".join("- "+link("Proposals",x["id"])+"\n" for x in received)
        notes["Researchers/"+short(p.id)+".md"]=note({"type":"researcher","name":p.name,"aliases":[p.name],"institution_type":p.org_type,"virtual":p.virtual,"works_in_corpus":len(records),"works_count":p.profile.get("works_count"),"person_confirmed":False},body)
    for r in corpus.records.values():
        folder="SiteRecords" if r.virtual else "CareerRecords" if r.kind == "career_record" else "Papers"
        body=("시연용 가상 기록\n\n" if r.virtual else "")+"# "+text(r.title)+"\n\n"
        if r.source_url:
            body+="[출처 기록]("+r.source_url+")\n\n"
        body+=text(r.text)+"\n\n## 참여 기록\n"
        body+="".join("- "+(link("Researchers",c.person_id) if c.person_id else text(c.name)+" — 프로필 미등록")+" · "+c.role+" · 개인 수행 미확인\n" for c in r.people)
        body+="\n## 관련 주제\n"+" ".join(link("Topics",t) for t in r.tags)
        notes[folder+"/"+short(r.id)+".md"]=note({"type":"site_record" if r.virtual else "career_record" if r.kind == "career_record" else "paper","scope":r.scope,"field":r.field,"virtual":r.virtual,"evidence_kind":r.evidence_kind,"checked_at":r.checked_at},body)
    for row in admin["topics"]:
        tid=row["id"]
        records=[r for r in corpus.records.values() if tid in r.tags]
        body="# "+row["name"]+"\n\n"+admin["note"]+"\n\n"+"".join("- "+link("SiteRecords" if r.virtual else "CareerRecords" if r.kind == "career_record" else "Papers",r.id)+"\n" for r in records)
        notes["Topics/"+tid+".md"]=note({"type":"topic","name":row["name"],"demand":row["demand"],"supply_records":row["people"],"virtual_people":row["virtual_people"],"confirmed":0,"strategy":row["strategy"]},body)
    for q in corpus.questions:
        result=service.engine.recommend(q["question"]+" "+q.get("ai_answer",""),q.get("mode"))
        body="# "+q["id"]+"\n\n"+text(q["question"])+"\n\n"
        if q.get("ai_answer"):
            body+="## 검증 대상 · 가상의 AI 답\n\n> "+text(q["ai_answer"])+"\n\n"
        body+="## 후보\n"+"".join("- "+link("Researchers",c["id"])+" · "+c["reason"]+"\n" for c in result["candidates"])
        body+="\n## 주제\n"+" ".join(link("Topics",t) for t in result["topic_ids"])
        notes["Questions/"+q["id"]+".md"]=note({"type":"question","field":result["field"],"candidates":[link("Researchers",c["id"]) for c in result["candidates"]]},body)
    for session in state["sessions"]:
        body="# 대화 기록\n\n"+text(session["original"])+"\n\n"
        if session["mode"]=="verify":
            body="# 검증 대상이 포함된 대화\n\n"+body
        body+="\n".join("**"+m["role"]+"** "+text(m["text"])+"\n" for m in session["messages"])
        body+="\n## 제안\n"+"".join("- "+link("Proposals",p["id"])+"\n" for p in state["proposals"] if p["session_id"]==session["id"])
        notes["Requests/"+session["id"]+".md"]=note({"type":"request","request_kind":session["mode"],"created":session["created"]},body)
    for p in state["proposals"]:
        body="# 시연 제안 · "+p["state"]+"\n\n"+("가상 현장 기록\n\n" if p["virtual"] else "")+text(p["body"])+"\n\n수신: "+link("Researchers",p["recipient_id"])+"\n\n대화: "+link("Requests",p["session_id"])+"\n\n"
        body+="## 근거\n"+"".join("- "+link("SiteRecords" if e["virtual"] else "Papers",e["id"])+"\n" for e in p["evidence"])
        notes["Proposals/"+p["id"]+".md"]=note({"type":"proposal","status":p["state"],"direction":p["direction"],"virtual":p["virtual"],"simulated":True,"copy_to_proposer":True,"to":link("Researchers",p["recipient_id"]),"created":p["created"]},body)
    notes["00-START.md"]=note({"type":"start"},"# 수소문 · 연구 경험으로 연결\n\n공개 논문·본인 제공 경력·가상 현장 기록을 이용한 시연입니다. 개별 수행 능력과 현재 연락 의향은 미확인입니다.\n\n"+ "\n".join("- "+link("Questions",q["id"]) for q in corpus.questions)+"\n\n[[00-ADMIN]]\n\n![[bases/후보.base]]")
    notes["00-ADMIN.md"]=note({"type":"admin"},"# 기록 분포와 시연 제안\n\n"+admin["note"]+"\n\n"+ "\n".join("- "+link("Topics",t["id"]) for t in corpus.topics)+"\n\n![[bases/관리자.base]]")
    notes["bases/후보.base"]="filters:\n  or:\n    - 'type == \"researcher\"'\n    - 'type == \"question\"'\nviews:\n  - type: table\n    name: 질문별 후보\n    filters: 'type == \"question\"'\n    order: [file.name, candidates]\n  - type: table\n    name: 산업체 저자\n    filters: 'type == \"researcher\" && institution_type == \"company\"'\n    order: [name, works_in_corpus, works_count]\n  - type: table\n    name: 개인 수행 미확인\n    filters: 'type == \"researcher\" && person_confirmed == false'\n    order: [name, works_in_corpus, person_confirmed]\n"
    notes["bases/관리자.base"]="views:\n  - type: table\n    name: 기록 분포\n    filters: 'type == \"topic\"'\n    order: [name, supply_records, virtual_people]\n  - type: table\n    name: 추가 확인 영역\n    filters: 'type == \"topic\"'\n    order: [name, demand, confirmed, strategy]\n  - type: table\n    name: 제안 상태\n    filters: 'type == \"proposal\"'\n    order: [file.name, status, to]\n  - type: table\n    name: 연구소와 현장\n    filters: 'type == \"proposal\"'\n    order: [file.name, direction, virtual]\n"
    manifest_path=target/".rndplz-manifest.json"
    previous=json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    manifest=dict(previous)
    conflicts=[]
    for name,content in notes.items():
        path=target/name
        digest=hashlib.sha256(content.encode()).hexdigest()
        if path.exists():
            current=hashlib.sha256(path.read_bytes()).hexdigest()
            if current==digest:
                manifest[name]=digest
                continue
            logical=hashlib.sha256(path.read_text(encoding="utf-8").encode()).hexdigest()
            if previous.get(name) not in (current,logical):
                conflicts.append(name)
                continue
        path.parent.mkdir(parents=True,exist_ok=True)
        atomic_write(path,content)
        manifest[name]=digest
    atomic_write(manifest_path,json.dumps(manifest,ensure_ascii=False,indent=2))
    config=target/".obsidian"
    config.mkdir(exist_ok=True)
    colors={"Researchers":"3cd4ff","Papers":"f7c243","Topics":"34ee6a","Questions":"aa66f4","Proposals":"ff8c42","SiteRecords":"b9c7cc"}
    graph_path=config/"graph.json"
    graph=json.loads(graph_path.read_text(encoding="utf-8")) if graph_path.exists() else {}
    groups=graph.setdefault("colorGroups",[])
    for folder,color in colors.items():
        query="path:"+folder
        if not any(x.get("query")==query for x in groups):
            groups.append({"query":query,"color":{"a":1,"rgb":int(color,16)}})
    atomic_write(graph_path,json.dumps(graph,indent=2))
    css="\n".join('.nav-folder-title[data-path="'+folder+'"], .nav-file-title[data-path^="'+folder+'/"] { color: #'+color+'; }' for folder,color in colors.items())
    snippets=config/"snippets";snippets.mkdir(exist_ok=True)
    atomic_write(snippets/"rndplz-colors.css",css)
    appearance_path=config/"appearance.json"
    appearance=json.loads(appearance_path.read_text(encoding="utf-8")) if appearance_path.exists() else {}
    enabled=appearance.setdefault("enabledCssSnippets",[])
    if "rndplz-colors" not in enabled:
        enabled.append("rndplz-colors")
    atomic_write(appearance_path,json.dumps(appearance,indent=2))
    unresolved=[]
    for name in notes:
        if not name.endswith(".md"):
            continue
        content=(target/name).read_text(encoding="utf-8")
        for target_link in re.findall(r"\[\[([^\]|#]+)",content):
            link_path=target/target_link
            if not link_path.exists() and not link_path.with_suffix(".md").exists():
                unresolved.append({"file":name,"link":target_link})
    return {"path":str(target),"uri":"obsidian://open?path="+quote(str(target/"00-START.md"),safe=""),"note_count":sum(n.endswith(".md") for n in notes),"by_folder":dict(Counter(n.split("/")[0] if "/" in n else "root" for n in notes if n.endswith(".md"))),"unresolved":unresolved,"conflicts":conflicts,"views":7}


if __name__=="__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    parser=argparse.ArgumentParser()
    parser.add_argument("--out",default=str(ROOT/"out"/"vault"))
    args=parser.parse_args()
    result=export_vault(Service(),args.out)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    raise SystemExit(bool(result["unresolved"] or result["conflicts"]))
