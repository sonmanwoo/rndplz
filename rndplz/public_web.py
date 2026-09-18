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
from http import HTTPStatus
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.parse import parse_qs

from .chat_models import ChatModels
from .gemma_bridge import GemmaRelay
from .conversation import Conversation
from .data import Corpus, ROOT
from .engine import Engine
from .models import ExternalModel
from .service import Service

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



class PublicModels(ChatModels):
    """No local Ollama probing or visitor changes to shared API credentials."""
    def __init__(self, env=None):
        super().__init__(env)
        self.bridge=GemmaRelay(self.env.get('RNDPLZ_BRIDGE_TOKEN',''),self.env.get('RNDPLZ_BRIDGE_MODEL','gemma4:e4b'))

    def catalog(self, refresh=False):
        if self.env.get('RNDPLZ_PUBLIC_MODEL')=='bridge':
            ready=self.bridge.online
            return {'models':[
                {'id':'bridge','provider':'bridge','name':self.bridge.model+' · 운영자 PC'+('' if ready else ' · 연결 대기'),
                 'enabled':ready,'local':False,'vision':False},
                {'id':'guide','provider':'guide','name':'기록 탐색 안내 · AI 미사용','enabled':True,'local':False,'vision':False}],
                'default':'bridge' if ready else 'guide','public':True}
        items = [{'id': p, 'provider': p, 'name': label + ' · ' + c['model'],
                  'enabled': True, 'local': False, 'vision': False}
                 for p, label in [('openai', 'OpenAI API'), ('claude', 'Claude API')]
                 if (c := self.configs.get(p))]
        if not items:
            items = [{'id': 'guide', 'provider': 'guide', 'name': '기록 탐색 안내 · AI 미연결',
                      'enabled': True, 'local': False, 'vision': False}]
        return {'models': items, 'default': items[0]['id'], 'public': True}

    def configure(self, payload):
        raise ValueError('공개 서비스 모델은 운영자가 서버에서 설정합니다.')

    def stream(self, identifier, messages):
        if identifier=='bridge':
            yield from self.bridge.stream(messages)
            return
        if identifier != 'guide':
            yield from super().stream(identifier, messages)
            return
        users = [m for m in messages if m['role'] == 'user']
        if len(users) == 1:
            yield '기록 탐색 안내입니다. 현재 공개 서버에 AI 모델이 연결되지 않아 기술 답변은 생성하지 않습니다. 찾으려는 사람의 연구 주제와 필요한 경험·조건을 한 번 더 적어 주세요.'
        else:
            yield '입력한 내용을 함께 검색할 준비가 됐습니다. 아래 «이 내용으로 사람 찾기»를 누르면 공개된 인물·논문·경력 기록에서 관련 근거를 찾아 보여드립니다.'


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
        self.engine = Engine(corpus)
        self.models = PublicModels(self.env)
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
                self.contexts[sid] = {'service': service, 'chat': Conversation(service, self.models),
                                      'token': self.signature('csrf:' + sid), 'used': now, 'active': 0, 'requests': []}
            context = self.contexts[sid]
            context['used'] = now
        return context, 'rndplz_visitor=' + value + '; Path=/; HttpOnly; SameSite=Lax; Max-Age=86400' + ('; Secure' if self.secure else '')

    def __call__(self, environ, start_response):
        headers = [('Cache-Control', 'no-store'), ('X-Content-Type-Options', 'nosniff'),
                   ('Referrer-Policy', 'same-origin'),
                   ('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")]
        def send(status, value, mime='application/json; charset=utf-8'):
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
        if path.startswith('/ui-previews/'):
            if method != 'GET': return send(405, {'error': '읽기 전용 비교 페이지입니다.'})
            entry = PREVIEW_FILES.get(path[len(PREVIEW_PREFIX):]) if path.startswith(PREVIEW_PREFIX) else None
            if entry is None: return send(404, {'error': '비교 페이지를 찾을 수 없습니다.'})
            name, mime = entry
            try: raw = (WEB / PREVIEW_PREFIX.strip('/') / name).read_bytes()
            except FileNotFoundError: return send(404, {'error': '비교 페이지를 찾을 수 없습니다.'})
            return send(200, raw, mime)
        if path in ('/api/worker/poll','/api/worker/result'):
            if method!='POST': return send(405,{'error':'지원하지 않는 요청입니다.'})
            if not self.models.bridge.authorized(environ.get('HTTP_X_RNDPLZ_BRIDGE','')):
                return send(403,{'error':'연결 인증이 필요합니다.'})
            try:
                length=int(environ.get('CONTENT_LENGTH','0'))
                if not 0<length<=262144: return send(413,{'error':'요청 범위 초과'})
                payload=json.loads(environ['wsgi.input'].read(length))
                if not isinstance(payload,dict): raise ValueError()
                if path.endswith('/poll'): return send(200,{'job':self.models.bridge.poll()})
                self.models.bridge.deliver(payload)
                return send(200,{'ok':True})
            except (ValueError,KeyError,TypeError): return send(400,{'error':'연결 요청 형식을 확인해 주세요.'})
        try:
            context, cookie = self.visitor(environ)
            headers.append(('Set-Cookie', cookie))
            service, chat = context['service'], context['chat']
            token = context['token']
            query = parse_qs(environ.get('QUERY_STRING', ''))
            identifier = query.get('id', [''])[0]
            if method == 'GET':
                if path == '/api/chat/bootstrap': return send(200, {'token': token, 'history': chat.history(), **self.models.catalog()})
                if path == '/api/chat/models': return send(200, self.models.catalog())
                if path == '/api/chat/session': return send(200, chat.get(identifier))
                if path == '/api/bootstrap': return send(200, {**service.bootstrap(), 'token': token, 'public': True})
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
                files = {'/': ('index.html', 'text/html'), '/explore': ('explore.html', 'text/html')}
                for name in ('craft.css', 'chat.css', 'style.css', 'craft.js', 'chat.js', 'app.js'):
                    files['/' + name] = (name, 'text/css' if name.endswith('.css') else 'text/javascript')
                if path in files:
                    name, mime = files[path]
                    return send(200, (WEB / name).read_bytes(), mime + '; charset=utf-8')
                if path in self.images:
                    return send(200, (WEB / path.lstrip('/')).read_bytes(), 'image/png' if path.endswith('.png') else 'image/jpeg')
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
            if not 0 < length <= (1500000 if path == '/api/attachments' else 200000):
                return send(413, {'error': '요청 크기가 허용 범위를 넘었습니다. 공개 시연 첨부는 약 1MB까지입니다.'})
            payload = json.loads(environ['wsgi.input'].read(length).decode('utf-8'))
            if not isinstance(payload, dict): raise ValueError('요청 형식이 올바르지 않습니다.')
            with self.lock:
                now = time.monotonic()
                context['requests'] = [t for t in context['requests'] if now - t < 60]
                if len(context['requests']) >= 20:
                    return send(429, {'error': '요청이 많습니다. 잠시 후 다시 시도해 주세요.'})
                context['requests'].append(now)
            if path == '/api/chat':
                state = service.store.read()
                if sum(s.get('turns', 0) for s in state['sessions']) >= 40:
                    return send(429, {'error': '이 방문자의 공개 시연 메시지 한도에 도달했습니다.'})
                if not self.request_slots.acquire(blocking=False):
                    return send(429, {'error': '응답 중인 방문자가 많습니다. 잠시 후 다시 시도해 주세요.'})
                iterator = chat.stream(payload)
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
            if path == '/api/attachments' and len(list(chat.attachments.directory.glob('*.json'))) >= 12:
                return send(429, {'error': '공개 시연의 첨부 개수 한도에 도달했습니다.'})
            routes = {
                '/api/attachments': lambda: chat.attachments.upload(payload),
                '/api/chat/prepare': lambda: chat.prepare(payload),
                '/api/converse': lambda: service.converse(payload),
                '/api/slots': lambda: service.update_slots(payload),
                '/api/draft': lambda: service.draft(payload.get('session_id'), payload.get('candidate_id')),
                '/api/proposals': lambda: service.save_proposal(payload),
                '/api/transition': lambda: service.transition(payload.get('id'), payload.get('state')),
            }
            if path not in routes: return send(404, {'error': '경로를 찾을 수 없습니다.'})
            return send(200, routes[path]())
        except (ValueError, KeyError, TypeError):
            return send(400, {'error': '요청을 처리하지 못했습니다. 현재 방문자의 대화·첨부를 확인해 주세요.'})
        except Exception:
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
