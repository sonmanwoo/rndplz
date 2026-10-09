"""Read-only HTTP entry for other agents (an AiU external tool): /api/agent/v1/*.

The same public tools as the command line and MCP server (`agent_tools`), behind a Bearer key
(RNDPLZ_AGENT_API_KEY, read from _keys at start). No visitor cookie, no session, no model call,
no write: a draft is text the caller hands to a person. The OpenAPI schema is served without a key
so a tool registry can import it; it carries no secret.
"""
import hmac
import json
import threading
import time
from urllib.parse import parse_qs, unquote

from .agent_tools import AgentTools

PREFIX = '/api/agent/v1/'
RATE_PER_MINUTE = 60
MAX_BODY = 8192
STATUS = {'invalid_argument': 400, 'not_found': 404, 'draft_unavailable': 422, 'configuration_error': 503}


class AgentHTTP:
    def __init__(self, env, origin):
        self.key = (env.get('RNDPLZ_AGENT_API_KEY') or '').strip()
        self.origin = origin
        self.env = env
        self.lock = threading.Lock()
        self.calls = []
        self._tools = None

    @property
    def enabled(self):
        return len(self.key) >= 32

    def tools(self):
        with self.lock:
            if self._tools is None:
                self._tools = AgentTools(self.env)
            return self._tools

    def _admitted(self, environ):
        given = environ.get('HTTP_AUTHORIZATION', '')
        return given.startswith('Bearer ') and hmac.compare_digest(given[7:].strip().encode(), self.key.encode())

    def _within_rate(self):
        now = time.monotonic()
        with self.lock:
            self.calls = [moment for moment in self.calls if now - moment < 60]
            if len(self.calls) >= RATE_PER_MINUTE:
                return False
            self.calls.append(now)
            return True

    def handle(self, environ, path, method, send):
        if not self.enabled:
            return send(404, {'error': '찾을 수 없는 주소입니다.'})
        route = path[len(PREFIX):]
        if route == 'openapi.json' and method == 'GET':
            return send(200, self.schema())
        if not self._admitted(environ):
            return send(401, {'error': '인증 키가 필요합니다.'})
        if not self._within_rate():
            return send(429, {'error': '요청이 너무 많습니다. 잠시 후 다시 시도해 주세요.'})
        query = {key: values[0] for key, values in parse_qs(environ.get('QUERY_STRING', '')).items()}
        tools = self.tools()
        if method == 'GET' and route == 'find-people':
            try:
                limit = int(query.get('limit', '5'))
            except ValueError:
                limit = 0
            result = tools.find_people(query.get('query', ''), limit)
        elif method == 'GET' and route == 'capabilities':
            result = tools.list_capabilities()
        elif method == 'GET' and route.startswith(('person/', 'record/', 'capability/')):
            kind, _, ident = route.partition('/')
            ident = unquote(ident)
            result = {'person': tools.get_person, 'record': tools.get_record,
                      'capability': tools.people_for_capability}[kind](ident)
        elif method == 'POST' and route == 'draft':
            try:
                size = int(environ.get('CONTENT_LENGTH') or 0)
            except ValueError:
                size = -1
            if not 0 < size <= MAX_BODY:
                return send(413 if size > MAX_BODY else 400, {'error': '요청 본문을 확인해 주세요.'})
            try:
                body = json.loads(environ['wsgi.input'].read(size).decode('utf-8'))
            except (ValueError, UnicodeDecodeError):
                return send(400, {'error': 'JSON 본문이 필요합니다.'})
            if not isinstance(body, dict):
                return send(400, {'error': 'JSON 객체가 필요합니다.'})
            result = tools.draft_request(body.get('person_ids'), body.get('need', ''), body.get('requester_note', ''))
        else:
            return send(404, {'error': '찾을 수 없는 주소입니다.'})
        code = (result.get('error') or {}).get('code') if result.get('status') == 'error' else None
        return send(STATUS.get(code, 400) if code else 200, result)

    def schema(self):
        """OpenAPI 3.0 for a tool registry: every operation is read-only and public-scope only."""
        def ok(description):
            return {'200': {'description': description, 'content': {'application/json': {'schema': {'type': 'object'}}}}}

        def path_param(name, description):
            return [{'name': name, 'in': 'path', 'required': True, 'description': description, 'schema': {'type': 'string'}}]

        note = ' 공개 근거만 다루며 연락 가능성·협업 의사는 확인하지 않았습니다.'
        return {
            'openapi': '3.0.1',
            'info': {'title': '수소문 연구자 찾기', 'version': '1.0',
                     'description': '사내 연구 문제를 함께 풀 사람을 공개 근거(논문·경력·프로젝트 기록)로 찾는 읽기 전용 도구.' + note},
            'servers': [{'url': self.origin.rstrip('/') + '/api/agent/v1'}],
            'components': {'securitySchemes': {'bearer': {'type': 'http', 'scheme': 'bearer'}}},
            'security': [{'bearer': []}],
            'paths': {
                '/find-people': {'get': {
                    'operationId': 'find_people', 'summary': '문제로 사람 찾기',
                    'description': '연구 문제·조건 문장으로 연결 근거가 있는 사람과 근거 기록을 찾는다. 결과가 없거나 모호하면 그 상태와 안내를 돌려준다.' + note,
                    'parameters': [
                        {'name': 'query', 'in': 'query', 'required': True, 'description': '연구 문제나 찾는 조건(한국어·영어)', 'schema': {'type': 'string'}},
                        {'name': 'limit', 'in': 'query', 'required': False, 'description': '최대 사람 수(1~10, 기본 5)', 'schema': {'type': 'integer', 'default': 5}}],
                    'responses': ok('사람·근거 기록·안내')}},
                '/person/{person_id}': {'get': {
                    'operationId': 'get_person', 'summary': '사람 카드 보기',
                    'description': 'find_people 결과의 id로 공개 카드(소속·기술·경력·근거 목록)를 본다.',
                    'parameters': path_param('person_id', '사람 id(find_people 결과)'), 'responses': ok('공개 카드')}},
                '/record/{record_id}': {'get': {
                    'operationId': 'get_record', 'summary': '근거 기록 보기',
                    'description': '근거 기록(논문·경력·프로젝트)의 상세와 출처.',
                    'parameters': path_param('record_id', '근거 기록 id'), 'responses': ok('근거 기록')}},
                '/capabilities': {'get': {
                    'operationId': 'list_capabilities', 'summary': '연구 분야 목록',
                    'description': '연구 맵의 역량(분야) 목록과 사람 수.', 'responses': ok('역량 목록')}},
                '/capability/{capability_id}': {'get': {
                    'operationId': 'people_for_capability', 'summary': '분야별 사람',
                    'description': '역량 id에 연결된 사람.',
                    'parameters': path_param('capability_id', '역량 id(list_capabilities 결과)'), 'responses': ok('사람 목록')}},
                '/draft': {'post': {
                    'operationId': 'draft_request', 'summary': '의뢰서 초안 만들기',
                    'description': '찾은 사람에게 보낼 의뢰서 초안(글)만 만든다. 보내기·저장은 하지 않으며 사람이 수소문 화면에서 확인·발송한다.',
                    'requestBody': {'required': True, 'content': {'application/json': {'schema': {
                        'type': 'object', 'required': ['person_ids', 'need'],
                        'properties': {'person_ids': {'type': 'array', 'items': {'type': 'string'}, 'description': '받을 사람 id 목록'},
                                       'need': {'type': 'string', 'description': '필요한 도움'},
                                       'requester_note': {'type': 'string', 'description': '덧붙일 말(선택)'}}}}}},
                    'responses': ok('초안 제목·본문')}},
            },
        }
