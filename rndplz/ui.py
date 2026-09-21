from __future__ import annotations

import argparse
import json
import secrets
import re
import itertools
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs
if __package__ in (None,""):
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from rndplz.service import Service
from rndplz.people_map import build_people_map
from rndplz.conversation import Conversation
from rndplz.build_vault import export_vault
from rndplz.profiles import Profiles, ProfileError
from rndplz.profile_chat import ProfileChat
from rndplz.scout_projection import project_session
from rndplz.model_conversation import ScoutSourceChanged, ModelResponseUnavailable, ModelResponseBudgetExhausted
from rndplz.discovery import DiscoveryError

WEB=Path(__file__).with_name("web")


def make_server(host="127.0.0.1",port=8877,state_dir=None):
    service=Service(state_dir=state_dir)
    chat=Conversation(service)
    profiles=Profiles(service.store)
    token=secrets.token_urlsafe(32)
    # Only active portrait assets in the local corpus are served; no directory scan.
    portraits={}
    image_mimes={'.png':'image/png','.jpg':'image/jpeg','.jpeg':'image/jpeg','.webp':'image/webp'}
    for person in service.corpus.people.values():
        for key in ('path','background'):
            asset=person.profile.get('portrait',{}).get(key)
            if isinstance(asset,str) and re.fullmatch(r'/portraits/[A-Za-z0-9_.-]+\.(?:png|jpe?g|webp)',asset):
                portraits[asset]=(asset.lstrip('/'),image_mimes[Path(asset).suffix])
                if key == 'path':
                    stem = asset.rsplit('.', 1)[0]
                    for size in ('thumb', 'detail'):
                        derived = stem + '-' + size + '.webp'
                        portraits[derived] = (derived.lstrip('/'), image_mimes['.webp'])
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,format,*args):
            # Avoid logging arbitrary question text or environment values.
            pass
        def send(self,status,data,content_type="application/json; charset=utf-8"):
            if isinstance(data,dict):
                if data.get('kind')=='chat':data=project_session(data)
                elif isinstance(data.get('session'),dict):data={**data,'session':project_session(data['session'])}
            raw=json.dumps(data,ensure_ascii=False).encode() if isinstance(data,(dict,list)) else data
            self.send_response(status)
            self.send_header("Content-Type",content_type)
            self.send_header("Content-Length",str(len(raw)))
            self.send_header("Cache-Control","no-store")
            self.send_header("X-Content-Type-Options","nosniff")
            self.send_header("Content-Security-Policy","default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
            self.end_headers()
            self.wfile.write(raw)
        def valid_host(self):
            allowed={"127.0.0.1:"+str(self.server.server_port),"localhost:"+str(self.server.server_port)}
            return self.headers.get("Host") in allowed
        def do_GET(self):
            if not self.valid_host():
                return self.send(421,{"error":"로컬 주소로 접속해 주세요."})
            parsed=urlparse(self.path)
            query=parse_qs(parsed.query)
            try:
                if parsed.path=="/api/self-profile":
                    return self.send(200,{"token":token,**profiles.read()})
                if parsed.path=="/api/self-profile/source":
                    return self.send(200,profiles.source(query.get("id",[""])[0]))
                if parsed.path=="/api/chat/bootstrap":
                    return self.send(200,{"token":token,"history":chat.history(),"session_mode":"local_single_user","logout_supported":False,**chat.models.catalog()})
                if parsed.path=="/api/chat/session":
                    return self.send(200,project_session(chat.get(query.get("id",[""])[0])))
                if parsed.path=="/api/chat/models":
                    return self.send(200,chat.models.catalog(refresh=query.get("refresh")==["1"]))
                if parsed.path=="/api/attachment":
                    item=chat.attachments.load(query.get("id",[""])[0])
                    return self.send(200,{**chat.attachments.public(item),"text":item["text"],"image":item["image"],"mime":item["mime"]})
                if parsed.path=="/api/bootstrap":
                    return self.send(200,{**service.bootstrap(),"token":token})
                if parsed.path=="/api/people-map":
                    return self.send(200,build_people_map(service.engine))
                if parsed.path=="/api/admin":
                    return self.send(200,service.admin())
                if parsed.path=="/api/proposals":
                    return self.send(200,service.store.read()["proposals"])
                if parsed.path=="/api/person":
                    return self.send(200,service.person(query.get("id",[""])[0]))
                if parsed.path=="/api/record":
                    record=service.corpus.records.get(query.get("id",[""])[0])
                    if not record:
                        return self.send(404,{"error":"기록을 찾을 수 없습니다."})
                    return self.send(200,{**service.engine.explain_record(record),"text":record.text,"details":record.details})
                static={"/craft.css":("craft.css","text/css; charset=utf-8"),"/craft.js":("craft.js","text/javascript; charset=utf-8"),"/":("index.html","text/html; charset=utf-8"),"/explore":("explore.html","text/html; charset=utf-8"),"/chat.js":("chat.js","text/javascript; charset=utf-8"),"/chat.css":("chat.css","text/css; charset=utf-8"),"/app.js":("app.js","text/javascript; charset=utf-8"),"/style.css":("style.css","text/css; charset=utf-8")}
                static["/profile-chat.js"]=("profile-chat.js","text/javascript; charset=utf-8")
                static["/account-menu.js"]=("account-menu.js","text/javascript; charset=utf-8")
                static["/draw.js"]=("draw.js","text/javascript; charset=utf-8")
                static["/draw.css"]=("draw.css","text/css; charset=utf-8")
                static.update({"/profile":("profile.html","text/html; charset=utf-8"),"/profile.js":("profile.js","text/javascript; charset=utf-8"),"/profile.css":("profile.css","text/css; charset=utf-8")})
                static.update({"/"+name:(name,"text/css; charset=utf-8" if name.endswith(".css") else "text/javascript; charset=utf-8") for name in ("people-map.css","people-map-model.js","people-map-layout.js","people-map-graph.js","people-map.js")})
                static.update(portraits)
                if parsed.path in static:
                    name,mime=static[parsed.path]
                    return self.send(200,(WEB/name).read_bytes(),mime)
                return self.send(404,{"error":"페이지를 찾을 수 없습니다."})
            except ProfileError as exc:
                self.send(exc.status,{"error":str(exc),"code":exc.code})
            except (ValueError,KeyError) as exc:
                self.send(400,{"error":str(exc)})
            except Exception:
                self.send(500,{"error":"로컬 데이터 처리에 실패했습니다. 저장 파일은 보존됩니다."})
        def do_POST(self):
            if not self.valid_host() or self.headers.get("X-RnDplz-Token")!=token:
                return self.send(403,{"error":"화면을 새로고침한 뒤 다시 시도해 주세요."})
            origin=self.headers.get("Origin")
            if origin and origin not in ("http://127.0.0.1:"+str(self.server.server_port),"http://localhost:"+str(self.server.server_port)):
                return self.send(403,{"error":"허용되지 않는 요청입니다."})
            try:
                path=urlparse(self.path).path
                length=int(self.headers.get("Content-Length","0"))
                if length<1 or length>(12*1024*1024 if path in ("/api/attachments","/api/self-profile/upload","/api/self-profile/chat") else 200000):
                    return self.send(413,{"error":"요청 크기가 허용 범위를 넘었습니다."})
                payload=json.loads(self.rfile.read(length).decode("utf-8"))
                if not isinstance(payload,dict):
                    raise ValueError("요청 형식이 올바르지 않습니다.")
                if path=="/api/chat":
                    iterator=chat.stream(payload)
                    first=next(iterator)
                    self.send_response(200)
                    self.send_header("Content-Type","application/x-ndjson; charset=utf-8")
                    self.send_header("Cache-Control","no-store")
                    self.send_header("X-Content-Type-Options","nosniff")
                    self.send_header("Connection","close")
                    self.end_headers();self.close_connection=True
                    try:
                        for event in itertools.chain([first],iterator):
                            if isinstance(event.get('session'),dict):event={**event,'session':project_session(event['session'])}
                            self.wfile.write((json.dumps(event,ensure_ascii=False)+"\n").encode())
                            self.wfile.flush()
                    except (BrokenPipeError,ConnectionResetError,OSError):
                        pass
                    finally:
                        iterator.close()
                    return
                routes={"/api/attachments":lambda:chat.attachments.upload(payload),"/api/chat/configure":lambda:chat.models.configure(payload),"/api/chat/prepare":lambda:project_session(chat.prepare(payload)),"/api/converse":lambda:service.converse(payload),"/api/ai/structure":lambda:service.ai_structure(payload),"/api/ai/draft":lambda:service.ai_draft(payload),"/api/slots":lambda:service.update_slots(payload),"/api/draft":lambda:service.draft(payload.get("session_id"),payload.get("candidate_id")),"/api/proposals":lambda:service.save_proposal(payload),"/api/transition":lambda:service.transition(payload.get("id"),payload.get("state")),"/api/export":lambda:export_vault(service)}
                routes.update({"/api/self-profile/chat":lambda:ProfileChat(service,profiles).handle(payload),"/api/self-profile/save":lambda:profiles.save(payload),"/api/self-profile/upload":lambda:profiles.upload(payload),"/api/self-profile/suggest":lambda:profiles.suggest(payload),"/api/self-profile/source-action":lambda:profiles.source_action(payload)})
                path=urlparse(self.path).path
                if path not in routes:
                    return self.send(404,{"error":"경로를 찾을 수 없습니다."})
                self.send(200,routes[path]())
            except ProfileError as exc:
                self.send(exc.status,{"error":str(exc),"code":exc.code, **({'profile_command': exc.profile_command} if hasattr(exc, 'profile_command') else {})})
            except ScoutSourceChanged as exc:
                self.send(409,{"error":str(exc),"code":exc.code,"request_preserved":True,"session":project_session(exc.session)})
            except ModelResponseBudgetExhausted as exc:
                self.send(409,{"error":str(exc),"code":exc.code,"request_preserved":True,"retry_available":False})
            except ModelResponseUnavailable as exc:
                self.send(503,{"error":str(exc),"code":exc.code,"request_preserved":exc.request_preserved,"retry_available":exc.retry_available})
            except DiscoveryError as exc:
                self.send(409,{"error":str(exc),"code":exc.code})
            except (ValueError,KeyError,TypeError) as exc:
                self.send(400,{"error":str(exc)})
            except Exception:
                self.send(500,{"error":"저장에 실패했습니다. 입력을 유지하고 다시 시도해 주세요."})
    server=ThreadingHTTPServer((host,port),Handler)
    server.service=service
    server.chat=chat
    server.profiles=profiles
    return server


if __name__=="__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    parser=argparse.ArgumentParser()
    parser.add_argument("--port",type=int,default=8877)
    parser.add_argument("--state-dir")
    args=parser.parse_args()
    server=make_server(port=args.port,state_dir=args.state_dir)
    print("수소문 · http://127.0.0.1:"+str(server.server_port)+"/",flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
