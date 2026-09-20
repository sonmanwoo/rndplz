"""Public WSGI entrypoint with isolated visitor state and server-owned models."""
from __future__ import annotations

import hashlib
import hmac
import itertools
import json
import os
import re
import secrets
import threading
import time
import uuid
from http import HTTPStatus
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.parse import parse_qs

from .chat_models import ChatModels
from .gemma_bridge import GemmaRelay
from .conversation import Conversation
from .discovery import DiscoveryError
from .data import Corpus, ROOT
from .engine import Engine
from .models import ExternalModel
from .service import Service
from .people_map import build_people_map
from .diagnostics import DiagnosticAuth, Diagnostics, scope as diagnostic_scope
from .profiles import Profiles, ProfileError
from .profile_chat import ProfileChat

WEB = Path(__file__).with_name('web')
# Public comparison artifacts are explicit, immutable files; never resolve arbitrary paths.
PREVIEW_PREFIX = '/ui-previews/UI-MAIN-001/r1/'
PREVIEW_FILES = {
    '': ('index.html', 'text/html; charset=utf-8'),
    'index.html': ('index.html', 'text/html; charset=utf-8'),
    'review.css': ('review.css', 'text/css; charset=utf-8'),
    'review.js': ('review.js', 'text/javascript; charset=utf-8'),
    **{f'images/{name}-{size}.png': (f'images/{name}-{size}.png', 'image/png')
       for name in ('fan', 'evidence') for size in ('desktop', 'mobile')},
}


# Previews use fixed reviewed packages, never filesystem path discovery.
PREVIEW_PACKAGES = {
    '/ui-previews/CAPABILITY-PROPOSALS/r1/': {
        '': ('index.html', 'text/html; charset=utf-8'),
        'app.js': ('app.js', 'text/javascript; charset=utf-8'),
        'assets/gs-ignacio-e-grossmann.png': ('assets/gs-ignacio-e-grossmann.png', 'image/png'),
        'assets/gs-jens-kehlet-norskov.png': ('assets/gs-jens-kehlet-norskov.png', 'image/png'),
        'assets/gs-sankar-nair.png': ('assets/gs-sankar-nair.png', 'image/png'),
        'assets/jinho-illustration.png': ('assets/jinho-illustration.png', 'image/png'),
        'assets/manwoo-illustration.png': ('assets/manwoo-illustration.png', 'image/png'),
        'assets/pool-ian-wilson.png': ('assets/pool-ian-wilson.png', 'image/png'),
        'assets/pool-issam-mudawar.png': ('assets/pool-issam-mudawar.png', 'image/png'),
        'assets/pool-james-rawlings.png': ('assets/pool-james-rawlings.png', 'image/png'),
        'assets/pool-joshua-heyne.png': ('assets/pool-joshua-heyne.png', 'image/png'),
        'assets/pool-manfred-morari.png': ('assets/pool-manfred-morari.png', 'image/png'),
        'assets/pool-oussama-khatib.png': ('assets/pool-oussama-khatib.png', 'image/png'),
        'assets/pool-robert-mccormick.png': ('assets/pool-robert-mccormick.png', 'image/png'),
        'assets/pool-sandro-macchietto.png': ('assets/pool-sandro-macchietto.png', 'image/png'),
        'assets/pool-yogendra-joshi.png': ('assets/pool-yogendra-joshi.png', 'image/png'),
        'data.js': ('data.js', 'text/javascript; charset=utf-8'),
        'index.html': ('index.html', 'text/html; charset=utf-8'),
        'map.css': ('map.css', 'text/css; charset=utf-8'),
        'map.js': ('map.js', 'text/javascript; charset=utf-8'),
        'proposals.css': ('proposals.css', 'text/css; charset=utf-8'),
        'proposals.js': ('proposals.js', 'text/javascript; charset=utf-8'),
        'styles.css': ('styles.css', 'text/css; charset=utf-8'),
    },
    '/ui-previews/PEOPLE-MAP/r2/': {
        '': ('index.html', 'text/html; charset=utf-8'),
        'app.js': ('app.js', 'text/javascript; charset=utf-8'),
        'data.js': ('data.js', 'text/javascript; charset=utf-8'),
        'index.html': ('index.html', 'text/html; charset=utf-8'),
        'mark.svg': ('mark.svg', 'image/svg+xml'),
        'model.js': ('model.js', 'text/javascript; charset=utf-8'),
        'styles.css': ('styles.css', 'text/css; charset=utf-8'),
        'views/desktop.png': ('views/desktop.png', 'image/png'),
        'views/desktop.svg': ('views/desktop.svg', 'image/svg+xml'),
        'views/mobile.png': ('views/mobile.png', 'image/png'),
        'views/mobile.svg': ('views/mobile.svg', 'image/svg+xml'),
    },
    '/ui-previews/PEOPLE-MAP/r1/': {
        '': ('index.html', 'text/html; charset=utf-8'),
        'app.js': ('app.js', 'text/javascript; charset=utf-8'),
        'index.html': ('index.html', 'text/html; charset=utf-8'),
        'mark.svg': ('mark.svg', 'image/svg+xml'),
        'model.js': ('model.js', 'text/javascript; charset=utf-8'),
        'styles.css': ('styles.css', 'text/css; charset=utf-8'),
        'views/desktop.png': ('views/desktop.png', 'image/png'),
        'views/desktop.svg': ('views/desktop.svg', 'image/svg+xml'),
        'views/mobile.png': ('views/mobile.png', 'image/png'),
        'views/mobile.svg': ('views/mobile.svg', 'image/svg+xml'),
    },
    '/ui-previews/KNOWLEDGE-MAP/r1/': {
        '': ('index.html', 'text/html; charset=utf-8'),
        'assets/hinton.png': ('assets/hinton.png', 'image/png'),
        'dataset.json': ('dataset.json', 'application/json; charset=utf-8'),
        'index.html': ('index.html', 'text/html; charset=utf-8'),
        'styles.css': ('styles.css', 'text/css; charset=utf-8'),
        'views/a-desktop.png': ('views/a-desktop.png', 'image/png'),
        'views/a-desktop.svg': ('views/a-desktop.svg', 'image/svg+xml'),
        'views/a-mobile-cross.png': ('views/a-mobile-cross.png', 'image/png'),
        'views/a-mobile-cross.svg': ('views/a-mobile-cross.svg', 'image/svg+xml'),
        'views/a-mobile-empty.png': ('views/a-mobile-empty.png', 'image/png'),
        'views/a-mobile-empty.svg': ('views/a-mobile-empty.svg', 'image/svg+xml'),
        'views/a-mobile-one.png': ('views/a-mobile-one.png', 'image/png'),
        'views/a-mobile-one.svg': ('views/a-mobile-one.svg', 'image/svg+xml'),
        'views/b-desktop.png': ('views/b-desktop.png', 'image/png'),
        'views/b-desktop.svg': ('views/b-desktop.svg', 'image/svg+xml'),
        'views/c-desktop.png': ('views/c-desktop.png', 'image/png'),
        'views/c-desktop.svg': ('views/c-desktop.svg', 'image/svg+xml'),
    },
    PREVIEW_PREFIX: PREVIEW_FILES,
    '/ui-previews/CARD-FLIP/r1/': {
        '': ('index.html', 'text/html; charset=utf-8'),
        'index.html': ('index.html', 'text/html; charset=utf-8'),
        'review.css': ('review.css', 'text/css; charset=utf-8'),
        **{name: (name, 'text/javascript; charset=utf-8') for name in ('review.js', 'data.js')},
        **{f'images/{name}.png': (f'images/{name}.png', 'image/png') for name in ('manwoo', 'hinton')},
    },
    '/ui-previews/LAUREATE/r3/': {
        '': ('index.html', 'text/html; charset=utf-8'),
        'index.html': ('index.html', 'text/html; charset=utf-8'),
        'review.css': ('review.css', 'text/css; charset=utf-8'),
        **{name: (name, 'text/javascript; charset=utf-8') for name in ('review.js', 'data.js')},
        **{f'images/{name}.png': (f'images/{name}.png', 'image/png') for name in
           ('hinton', 'arnold', 'bertozzi', 'strickland', 'kariko', 'baker')},
    },
    '/ui-previews/LAUREATE/r2/': {
        '': ('index.html', 'text/html; charset=utf-8'),
        'index.html': ('index.html', 'text/html; charset=utf-8'),
        'review.css': ('review.css', 'text/css; charset=utf-8'),
        **{name: (name, 'text/javascript; charset=utf-8') for name in ('review.js', 'data.js')},
        **{f'images/{name}.png': (f'images/{name}.png', 'image/png') for name in ('hinton', 'arnold')},
    },
    '/ui-previews/LAUREATE/r1/': {
        '': ('index.html', 'text/html; charset=utf-8'),
        'index.html': ('index.html', 'text/html; charset=utf-8'),
        'review.css': ('review.css', 'text/css; charset=utf-8'),
        **{name: (name, 'text/javascript; charset=utf-8') for name in ('review.js', 'data.js')},
        **{f'images/{name}.jpg': (f'images/{name}.jpg', 'image/jpeg') for name in
           ('arnold', 'baker', 'bertozzi', 'hinton', 'kariko', 'strickland')},
    },
    '/ui-previews/M8/r1/': {
        '': ('index.html', 'text/html; charset=utf-8'),
        'index.html': ('index.html', 'text/html; charset=utf-8'),
        **{name: (name, 'text/css; charset=utf-8') for name in
           ('review.css', 'vendor/app.css', 'vendor/holo.css', 'vendor/envelope.css')},
        **{name: (name, 'text/javascript; charset=utf-8') for name in
           ('review.js', 'data.js', 'vendor/holo.js', 'vendor/envelope.js')},
    },
}
PREVIEW_ROUTES = {
    prefix + suffix: (prefix.strip('/') + '/' + name, mime)
    for prefix, files in PREVIEW_PACKAGES.items()
    for suffix, (name, mime) in files.items()
}


class PublicModels(ChatModels):
    """No local Ollama probing or visitor changes to shared API credentials."""
    def __init__(self, env=None):
        super().__init__(env)
        self.bridge=GemmaRelay(self.env.get('RNDPLZ_BRIDGE_TOKEN',''),self.env.get('RNDPLZ_BRIDGE_MODEL','gemma4:e4b'),
                               models=self.env.get('RNDPLZ_BRIDGE_MODELS'))

    def catalog(self, refresh=False):
        if self.env.get('RNDPLZ_PUBLIC_MODEL')=='bridge':
            status=self.bridge.control('status');available=set(status['models'])
            items=[]
            for model in self.bridge.allowed_models:
                ready=model in available and not status['draining']
                suffix='' if ready else ' · 점검 중' if status['draining'] else ' · 연결 대기'
                items.append({'id':'bridge' if model==self.bridge.model else 'bridge:'+model,
                              'provider':'bridge','model':model,'name':model+' · 운영자 PC'+suffix,
                              'enabled':ready,'local':False,'vision':False})
            items.append({'id':'guide','provider':'guide','name':'기록 탐색 안내 · AI 미사용','enabled':True,'local':False,'vision':False})
            return {'models':items,'default':'bridge' if items[0]['enabled'] else 'guide','public':True}
        items = [{'id': p, 'provider': p, 'name': label + ' · ' + c['model'],
                  'enabled': True, 'local': False, 'vision': False}
                 for p, label in [('openai', 'OpenAI API'), ('claude', 'Claude API')]
                 if (c := self.configs.get(p))]
        if not items:
            items = [{'id': 'guide', 'provider': 'guide', 'name': '기록 탐색 안내 · AI 미사용',
                      'enabled': True, 'local': False, 'vision': False}]
        return {'models': items, 'default': items[0]['id'], 'public': True}

    def configure(self, payload):
        raise ValueError('공개 서비스 모델은 운영자가 서버에서 설정합니다.')

    def stream(self, identifier, messages, *, contract=None):
        option=self.get(identifier)
        stream_options={} if contract is None else {'contract':contract}
        if option['provider']=='bridge':
            yield from self.bridge.stream(messages,model=option['model'],**stream_options)
            return
        if identifier != 'guide':
            yield from super().stream(identifier, messages,**stream_options)
            return
        if contract is not None:raise ValueError('기록 탐색 안내는 모델 대화 생성 계약을 지원하지 않습니다.')
        users = [m for m in messages if m['role'] == 'user']
        if len(users) == 1:
            yield '기록 탐색 안내를 선택하셨습니다. 이 모드는 AI 기술 답변을 생성하지 않고 등록된 기록에서 사람을 찾도록 돕습니다. 찾으려는 사람과 하려는 일을 말씀해 주세요. 등록 기록에서 범위가 좁혀지면 «현재 정보로 수소문»이 나타납니다.'
        else:
            yield '이 모드는 기술 답변을 생성하지 않는 기록 탐색 안내입니다. 어떤 경험이 있는 사람을 찾는지 말씀해 주세요. 등록 기록에서 범위가 좁혀졌을 때만 «현재 정보로 수소문»으로 이어집니다.'


class PublicApp:
    def __init__(self, state_dir=None, env=None, include_personal=None):
        self.env = dict(os.environ if env is None else env)
        self.directory = Path(state_dir or self.env.get('RNDPLZ_STATE_DIR', ROOT / 'out' / 'public-state'))
        self.directory.mkdir(parents=True, exist_ok=True)
        self.secret = self.env.get('RNDPLZ_SESSION_SECRET', '').encode() or secrets.token_bytes(32)
        self.secure = self.env.get('RNDPLZ_LOCAL_PREVIEW') != '1'
        self.allowed_hosts = set(filter(None, self.env.get('RNDPLZ_ALLOWED_HOSTS', '').split(',')))
        if self.env.get('RENDER_EXTERNAL_HOSTNAME'):
            self.allowed_hosts.add(self.env['RENDER_EXTERNAL_HOSTNAME'])
        self.allowed_hosts.update({'127.0.0.1', 'localhost'})
        self.origin = self.env.get('RNDPLZ_PUBLIC_ORIGIN', '').rstrip('/')
        corpus = Corpus()
        approved = self.env.get('RNDPLZ_PUBLISH_PERSONAL') == '1' if include_personal is None else include_personal
        if not approved:
            hidden = {p.id for p in corpus.people.values() if p.profile.get('source_type') in ('self_reported', 'provided_resume')}
            corpus.people = {k: p for k, p in corpus.people.items() if k not in hidden}
            corpus.records = {k: r for k, r in corpus.records.items() if not any(c.person_id in hidden for c in r.people)}
            corpus.by_person = {k: [r for r in v if r.id in corpus.records] for k, v in corpus.by_person.items() if k not in hidden}
        from .demo_pool import project_corpus
        corpus = project_corpus(corpus, allow_personal_omission=not approved)
        self.engine = Engine(corpus)
        self.models = PublicModels(self.env)
        self.diagnostic_auth=DiagnosticAuth(self.env,Path(__file__).with_name('diagnostic_auth.json'))
        self.diagnostics=Diagnostics(self.directory/'diagnostics') if self.diagnostic_auth.enabled else None
        if self.diagnostics is not None:self.diagnostics.mark_interrupted()
        # A startup file fingerprint is provenance metadata, not a memory attestation.
        tracked=('conversation.py','public_web.py','gemma_bridge.py','chat_models.py','chat_actions.py','discovery.py','diagnostics.py',
                 'model_dialogue.py','evidence_search.py','model_conversation.py')
        fingerprint=hashlib.sha256()
        for name in tracked:
            fingerprint.update(name.encode());fingerprint.update(Path(__file__).with_name(name).read_bytes())
        revision=self.env.get('RENDER_GIT_COMMIT','')
        self.diagnostic_runtime={'code_fingerprint':fingerprint.hexdigest(),
                                 'deployment_revision':revision if re.fullmatch(r'[a-f0-9]{40}',revision) else None,
                                 'raw_state_retention':'existing_state_unchanged',
                                 'storage_lifetime':'ephemeral_platform_storage; export_before_deploy'}
        self.contexts = {}
        self.lock = threading.RLock()
        self.request_slots = threading.BoundedSemaphore(4)
        self.images = {p.profile['portrait']['path'] for p in corpus.people.values() if p.profile.get('portrait')}
        self.images.update(p.profile['portrait']['background'] for p in corpus.people.values() if p.profile.get('portrait', {}).get('background'))

    def signature(self, value):
        return hmac.new(self.secret, value.encode(), hashlib.sha256).hexdigest()

    def visitor(self, environ):
        cookie = SimpleCookie()
        try:
            cookie.load(environ.get('HTTP_COOKIE', ''))
            value = cookie.get('rndplz_visitor').value if cookie.get('rndplz_visitor') else ''
        except Exception:
            value = ''
        parts = value.split('.')
        valid = len(parts) == 3 and re.fullmatch('[a-f0-9]{32}', parts[0]) and parts[1].isdigit()
        valid = valid and 0 <= time.time() - int(parts[1]) < 86400 and hmac.compare_digest(parts[2], self.signature('.'.join(parts[:2])))
        if not valid:
            value = secrets.token_hex(16) + '.' + str(int(time.time()))
            value += '.' + self.signature(value)
        sid = value.split('.')[0]
        with self.lock:
            now = time.monotonic()
            if sid not in self.contexts:
                # Only discard idle in-memory handles; never touch another visitor's files.
                for key, item in list(self.contexts.items()):
                    if now - item['used'] > 3600 and item['active'] == 0:
                        del self.contexts[key]
                if len(self.contexts) >= 128:
                    raise ValueError('현재 접속자가 많습니다. 잠시 후 다시 시도해 주세요.')
                service = Service(self.engine, self.directory / sid, ExternalModel(env={}))
                self.contexts[sid] = {'service': service, 'chat': Conversation(service, self.models), 'profile': Profiles(service.store, public=True),
                                      'token': self.signature('csrf:' + sid), 'used': now, 'active': 0, 'requests': [],
                                      'visitor_ref':self.signature('diagnostic:' + sid)}
            context = self.contexts[sid]
            context['used'] = now
        return context, 'rndplz_visitor=' + value + '; Path=/; HttpOnly; SameSite=Lax; Max-Age=86400' + ('; Secure' if self.secure else '')

    def _diagnostic_observe(self, metadata, content=None):
        if self.diagnostics is None:return
        try:self.diagnostics.record(metadata,content)
        except Exception:
            try:
                with self.diagnostics.lock:self.diagnostics._problem('write_errors','diagnostic_callback_failed')
            except Exception:pass

    def _operator(self,environ,path,method,send):
        if not self.diagnostic_auth.enabled:return send(404,{'error':'경로를 찾을 수 없습니다.'})
        if not self.diagnostic_auth.authorized(environ.get('HTTP_X_RNDPLZ_DIAGNOSTIC','')):
            try:self.diagnostics._audit('authentication_rejected','unauthenticated')
            except Exception:pass
            return send(403,{'error':'운영자 인증이 필요합니다.'})
        origin=environ.get('HTTP_ORIGIN','')
        expected=self.origin or ('https://' if self.secure else 'http://')+environ.get('HTTP_HOST','')
        if origin and origin!=expected:return send(403,{'error':'허용되지 않는 요청입니다.'})
        actor=self.diagnostic_auth.credential_id
        try:
            query=parse_qs(environ.get('QUERY_STRING',''),keep_blank_values=True)
            if any(len(v)!=1 for v in query.values()):raise ValueError()
            if path=='/api/operator/diagnostics/recent' and method=='GET':
                if set(query)-{'since','model','status','limit'}:raise ValueError()
                args={k:v[0] for k,v in query.items()};args['limit']=int(args.get('limit','50'))
                data=self.diagnostics.recent(**args,actor=actor)
            elif path=='/api/operator/diagnostics/session' and method=='GET':
                if set(query)-{'id','turn'} or 'id' not in query:raise ValueError()
                data=self.diagnostics.session(query['id'][0],turn_id=query.get('turn',[None])[0],actor=actor)
            elif path=='/api/operator/diagnostics/snapshot' and method=='POST':
                if query:raise ValueError()
                length=int(environ.get('CONTENT_LENGTH') or '0')
                if not 0<length<=16000:return send(413,{'error':'요청 범위 초과'})
                payload=json.loads(environ['wsgi.input'].read(length))
                if not isinstance(payload,dict) or set(payload)-{'session_ref','turn_ids','include_content'}:raise ValueError()
                data=self.diagnostics.snapshot(payload.get('session_ref'),turn_ids=payload.get('turn_ids'),include_content=payload.get('include_content',False),actor=actor)
            else:return send(404,{'error':'경로를 찾을 수 없습니다.'})
            response={**data,'runtime':self.diagnostic_runtime}
            if len(json.dumps(response,ensure_ascii=False).encode())>5*1024*1024:
                return send(413,{'error':'진단 응답 크기를 넘었습니다. 턴 범위를 줄여 주세요.'})
            return send(200,response)
        except (ValueError,TypeError,KeyError):return send(400,{'error':'진단 조회 범위를 확인해 주세요.'})
        except Exception:return send(503,{'error':'진단 기록을 현재 읽을 수 없습니다.'})

    def __call__(self, environ, start_response):
        headers = [('Cache-Control', 'no-store'), ('X-Content-Type-Options', 'nosniff'),
                   ('Referrer-Policy', 'same-origin'),
                   ('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")]
        diagnostic_request=None;diagnostic_content=None;diagnostic_error='request_rejected';received=time.monotonic()
        def send(status, value, mime='application/json; charset=utf-8'):
            if status>=400 and diagnostic_request is not None:
                self._diagnostic_observe({**diagnostic_request,'event_type':'request_rejected','status':'rejected',
                    'route':'reject','route_reason':'request_validation','http_status':status,'error_kind':diagnostic_error,
                    'failure_stage':'request','elapsed_ms':round((time.monotonic()-received)*1000),'model_called':False},diagnostic_content)
            raw = json.dumps(value, ensure_ascii=False).encode() if isinstance(value, (dict, list)) else value
            start_response(f'{status} {HTTPStatus(status).phrase}', headers + [('Content-Type', mime), ('Content-Length', str(len(raw)))])
            return [raw]
        host = environ.get('HTTP_HOST', '').split(':')[0].lower()
        if host not in self.allowed_hosts:
            return send(421, {'error': '허용되지 않은 서비스 주소입니다.'})
        path, method = environ.get('PATH_INFO', '/'), environ.get('REQUEST_METHOD', 'GET')
        if path == '/healthz':
            return send(200, {'status': 'ok'})
        if method not in ('GET', 'POST'):
            return send(405, {'error': '지원하지 않는 요청입니다.'})
        if path.startswith('/api/operator/diagnostics/'):
            return self._operator(environ,path,method,send)
        if path.startswith('/ui-previews/'):
            if method != 'GET': return send(405, {'error': '읽기 전용 비교 페이지입니다.'})
            entry = PREVIEW_ROUTES.get(path)
            if entry is None: return send(404, {'error': '비교 페이지를 찾을 수 없습니다.'})
            name, mime = entry
            try: raw = (WEB / name).read_bytes()
            except FileNotFoundError: return send(404, {'error': '비교 페이지를 찾을 수 없습니다.'})
            return send(200, raw, mime)
        if path.startswith('/portraits/'):
            if method != 'GET': return send(405, {'error': '읽기 전용 이미지입니다.'})
            if path not in self.images: return send(404, {'error': '이미지를 찾을 수 없습니다.'})
            try: raw = (WEB / path.lstrip('/')).read_bytes()
            except FileNotFoundError: return send(404, {'error': '이미지를 찾을 수 없습니다.'})
            return send(200, raw, 'image/png' if path.endswith('.png') else 'image/jpeg')
        if path in ('/api/worker/poll','/api/worker/result'):
            if method!='POST': return send(405,{'error':'지원하지 않는 요청입니다.'})
            if not self.models.bridge.authorized(environ.get('HTTP_X_RNDPLZ_BRIDGE','')):
                return send(403,{'error':'연결 인증이 필요합니다.'})
            try:
                length=int(environ.get('CONTENT_LENGTH','0'))
                if not 0<length<=262144: return send(413,{'error':'요청 범위 초과'})
                payload=json.loads(environ['wsgi.input'].read(length))
                if not isinstance(payload,dict): raise ValueError()
                if path.endswith('/poll'):
                    if 'control' in payload:return send(200,self.models.bridge.control(payload['control']))
                    if 'models' in payload and not isinstance(payload['models'],list):raise ValueError()
                    if 'capabilities' in payload and not isinstance(payload['capabilities'],list):raise ValueError()
                    return send(200,{'job':self.models.bridge.poll(payload.get('models'),capabilities=payload.get('capabilities'))})
                self.models.bridge.deliver(payload)
                return send(200,{'ok':True})
            except (ValueError,KeyError,TypeError): return send(400,{'error':'연결 요청 형식을 확인해 주세요.'})
        try:
            context, cookie = self.visitor(environ)
            headers.append(('Set-Cookie', cookie))
            service, chat, profile = context['service'], context['chat'], context['profile']
            token = context['token']
            query = parse_qs(environ.get('QUERY_STRING', ''))
            identifier = query.get('id', [''])[0]
            if method=='POST' and path in ('/api/chat','/api/chat/prepare','/api/attachments'):
                request_id=uuid.uuid4().hex
                diagnostic_request={'visitor_ref':context['visitor_ref'],'request_id':request_id,'attempt_id':uuid.uuid4().hex,
                                    'trace_id':uuid.uuid4().hex,'session_id':'request-'+request_id,
                                    'code_fingerprint':self.diagnostic_runtime['code_fingerprint']}
                marker=environ.get('HTTP_X_RNDPLZ_DIAGNOSTIC_RUN','')
                if isinstance(marker,str) and re.fullmatch(r'[a-f0-9]{32}',marker):diagnostic_request['diagnostic_run']=marker
            if method == 'GET':
                if path == '/api/self-profile': return send(200, {'token':token, **profile.read()})
                if path == '/api/self-profile/source': return send(200, profile.source(identifier))
                if path == '/api/chat/bootstrap': return send(200, {'token': token, 'history': chat.history(), **self.models.catalog()})
                if path == '/api/chat/models': return send(200, self.models.catalog())
                if path == '/api/chat/session': return send(200, chat.get(identifier))
                if path == '/api/bootstrap': return send(200, {**service.bootstrap(), 'token': token, 'public': True})
                if path == '/api/people-map': return send(200, build_people_map(service.engine))
                if path == '/api/admin': return send(200, service.admin())
                if path == '/api/person': return send(200, service.person(identifier))
                if path == '/api/proposals': return send(200, service.store.read()['proposals'])
                if path == '/api/attachment':
                    item = chat.attachments.load(identifier)
                    return send(200, {**chat.attachments.public(item), 'text': item['text'], 'image': item['image'], 'mime': item['mime']})
                if path == '/api/record':
                    record = self.engine.corpus.records.get(identifier)
                    if not record: return send(404, {'error': '기록을 찾을 수 없습니다.'})
                    return send(200, {**self.engine.explain_record(record), 'text': record.text, 'details': record.details})
                files = {'/': ('index.html', 'text/html'), '/explore': ('explore.html', 'text/html'), '/profile': ('profile.html', 'text/html')}
                for name in ('people-map.css', 'people-map-model.js', 'people-map.js', 'craft.css', 'chat.css', 'style.css', 'craft.js', 'chat.js', 'app.js', 'profile.css', 'profile.js', 'profile-chat.js'):
                    files['/' + name] = (name, 'text/css' if name.endswith('.css') else 'text/javascript')
                if path in files:
                    name, mime = files[path]
                    return send(200, (WEB / name).read_bytes(), mime + '; charset=utf-8')
                return send(404, {'error': '페이지를 찾을 수 없습니다.'})
            if not hmac.compare_digest(environ.get('HTTP_X_RNDPLZ_TOKEN', ''), token):
                return send(403, {'error': '화면을 새로고침한 뒤 다시 시도해 주세요.'})
            origin = environ.get('HTTP_ORIGIN', '')
            expected = self.origin or ('https://' if self.secure else 'http://') + environ.get('HTTP_HOST', '')
            if origin != expected:
                return send(403, {'error': '허용되지 않는 요청입니다.'})
            if path in ('/api/chat/configure', '/api/export', '/api/ai/structure', '/api/ai/draft'):
                return send(403, {'error': '공개 시연에서 제공하지 않는 관리 기능입니다.'})
            length = int(environ.get('CONTENT_LENGTH') or '0')
            if not 0 < length <= (1500000 if path in ('/api/attachments','/api/self-profile/upload','/api/self-profile/chat') else 200000):
                return send(413, {'error': '요청 크기가 허용 범위를 넘었습니다. 공개 시연 첨부는 약 1MB까지입니다.'})
            payload = json.loads(environ['wsgi.input'].read(length).decode('utf-8'))
            if not isinstance(payload, dict): raise ValueError('요청 형식이 올바르지 않습니다.')
            if diagnostic_request is not None:
                for key in ('session_id','turn_id'):
                    if isinstance(payload.get(key),str) and re.fullmatch(r'[A-Za-z0-9-]{16,80}',payload[key]):diagnostic_request[key]=payload[key]
                diagnostic_request['model_selected']=payload.get('model_id')
                if path!='/api/attachments':
                    text=payload.get('text','')
                    diagnostic_content={'user_text':text[:16000] if isinstance(text,str) else ''}
                    diagnostic_request['input_chars']=len(text) if isinstance(text,str) else 0
                    diagnostic_request['attachment_count']=len(payload.get('attachments',[])) if isinstance(payload.get('attachments'),list) else 0
            with self.lock:
                now = time.monotonic()
                context['requests'] = [t for t in context['requests'] if now - t < 60]
                if len(context['requests']) >= 20:
                    diagnostic_error='rate_limit';return send(429, {'error': '요청이 많습니다. 잠시 후 다시 시도해 주세요.'})
                context['requests'].append(now)
            if path == '/api/chat':
                state = service.store.read()
                if sum(s.get('turns', 0) for s in state['sessions']) >= 40:
                    diagnostic_error='message_limit';return send(429, {'error': '이 방문자의 공개 시연 메시지 한도에 도달했습니다.'})
                if not self.request_slots.acquire(blocking=False):
                    diagnostic_error='busy';return send(429, {'error': '응답 중인 방문자가 많습니다. 잠시 후 다시 시도해 주세요.'})
                def observed_iterator():
                    with diagnostic_scope(self.diagnostics,diagnostic_request or {}):
                        yield from chat.stream(payload)
                iterator = observed_iterator()
                try:
                    first = next(iterator)
                except Exception:
                    self.request_slots.release()
                    raise
                with self.lock: context['active'] += 1
                def stream():
                    try:
                        for event in itertools.chain([first], iterator):
                            yield (json.dumps(event, ensure_ascii=False) + '\n').encode()
                    finally:
                        iterator.close()
                        with self.lock: context['active'] -= 1
                        self.request_slots.release()
                start_response('200 OK', headers + [('Content-Type', 'application/x-ndjson; charset=utf-8')])
                return stream()
            if path == '/api/chat/prepare':
                # Preparing may now generate an answer, so it shares chat admission.
                if not self.request_slots.acquire(blocking=False):
                    diagnostic_error='busy';return send(429, {'error': '응답 중인 방문자가 많습니다. 잠시 후 다시 시도해 주세요.'})
                with self.lock:context['active']+=1
                try:
                    if diagnostic_request is not None:
                        with diagnostic_scope(self.diagnostics,diagnostic_request):
                            return send(200,chat.prepare(payload))
                    return send(200,chat.prepare(payload))
                finally:
                    with self.lock:context['active']-=1
                    self.request_slots.release()
            if path == '/api/attachments' and len(list(chat.attachments.directory.glob('*.json'))) >= 12:
                return send(429, {'error': '공개 시연의 첨부 개수 한도에 도달했습니다.'})
            routes = {
                '/api/self-profile/chat': lambda: ProfileChat(service, profile).handle(payload),
                '/api/self-profile/save': lambda: profile.save(payload),
                '/api/self-profile/upload': lambda: profile.upload(payload),
                '/api/self-profile/suggest': lambda: profile.suggest(payload),
                '/api/self-profile/source-action': lambda: profile.source_action(payload),
                '/api/attachments': lambda: chat.attachments.upload(payload),
                '/api/converse': lambda: service.converse(payload),
                '/api/slots': lambda: service.update_slots(payload),
                '/api/draft': lambda: service.draft(payload.get('session_id'), payload.get('candidate_id')),
                '/api/proposals': lambda: service.save_proposal(payload),
                '/api/transition': lambda: service.transition(payload.get('id'), payload.get('state')),
            }
            if path not in routes: return send(404, {'error': '경로를 찾을 수 없습니다.'})
            if diagnostic_request is not None:
                with diagnostic_scope(self.diagnostics,diagnostic_request):
                    return send(200,routes[path]())
            return send(200, routes[path]())
        except DiscoveryError as exc:
            diagnostic_error='discovery_not_ready'
            return send(409, {'error':str(exc), 'code':exc.code})
        except ProfileError as exc:
            return send(exc.status, {'error':str(exc), 'code':exc.code, **({'profile_command': exc.profile_command} if hasattr(exc, 'profile_command') else {})})
        except ValueError as exc:
            # Only fixed, user-actionable validation messages may cross this boundary.
            safe_messages = {
                '선택한 모델은 이미지를 읽지 못합니다. 이미지 지원 모델을 선택하거나 문서로 첨부해 주세요.',
                '이 대화에는 이미지가 있습니다. 이미지 지원 모델을 선택하거나 새 대화를 시작해 주세요.',
            }
            message = str(exc)
            diagnostic_error='unsupported_image' if message in safe_messages else 'validation'
            return send(400, {'error': message if message in safe_messages else
                             '요청을 처리하지 못했습니다. 현재 방문자의 대화·첨부를 확인해 주세요.'})
        except (KeyError, TypeError):
            diagnostic_error='validation'
            return send(400, {'error': '요청을 처리하지 못했습니다. 현재 방문자의 대화·첨부를 확인해 주세요.'})
        except Exception:
            diagnostic_error='server_error'
            return send(500, {'error': '처리 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.'})


application = PublicApp()

if __name__ == '__main__':
    from socketserver import ThreadingMixIn
    from wsgiref.simple_server import make_server, WSGIServer
    class ThreadedServer(ThreadingMixIn, WSGIServer):
        daemon_threads = True
    port = int(os.environ.get('PORT', '8878'))
    with make_server('127.0.0.1', port, application, server_class=ThreadedServer) as server:
        print(f'Public deployment preview: http://127.0.0.1:{port}/', flush=True)
        server.serve_forever()
