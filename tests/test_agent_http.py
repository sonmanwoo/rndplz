"""The read-only HTTP entry for other agents (an AiU external tool): key, schema, routes, limits."""
import io
import json
from urllib.parse import urlsplit

import pytest

import rndplz.agent_http as agent_http
import rndplz.public_web as public_web

KEY = 'k' * 40


def call(app, url, *, method='GET', key=KEY, payload=None):
    parsed = urlsplit(url)
    raw = json.dumps(payload, ensure_ascii=False).encode() if payload is not None else b''
    environ = {'REQUEST_METHOD': method, 'PATH_INFO': parsed.path, 'QUERY_STRING': parsed.query,
               'HTTP_HOST': '127.0.0.1', 'wsgi.url_scheme': 'http', 'wsgi.input': io.BytesIO(raw),
               'CONTENT_LENGTH': str(len(raw)), 'HTTP_COOKIE': ''}
    if key:
        environ['HTTP_AUTHORIZATION'] = 'Bearer ' + key
    if method == 'POST':
        environ['CONTENT_TYPE'] = 'application/json'
    result = {}

    def start_response(status, headers):
        result['status'] = int(status.split()[0])
        result['headers'] = dict(headers)

    result['body'] = b''.join(app(environ, start_response))
    result['json'] = json.loads(result['body']) if result['body'] else None
    return result


def make_app(tmp_path, **extra):
    return public_web.PublicApp(state_dir=tmp_path / 'state', env={
        'RNDPLZ_LOCAL_PREVIEW': '1', 'RNDPLZ_SESSION_SECRET': 's' * 64, 'RNDPLZ_PROVIDER': 'none',
        'RNDPLZ_MODEL_CALL_LIMIT': '0', 'RNDPLZ_PUBLIC_ORIGIN': 'https://example.test:8443', **extra})


@pytest.fixture
def app(tmp_path):
    return make_app(tmp_path, RNDPLZ_AGENT_API_KEY=KEY)


def test_without_a_configured_key_the_entry_does_not_exist(tmp_path):
    bare = make_app(tmp_path)
    assert call(bare, '/api/agent/v1/openapi.json')['status'] == 404
    assert call(bare, '/api/agent/v1/capabilities')['status'] == 404


def test_schema_is_public_and_names_every_read_only_operation(app):
    response = call(app, '/api/agent/v1/openapi.json', key='')
    assert response['status'] == 200
    schema = response['json']
    assert schema['servers'] == [{'url': 'https://example.test:8443/api/agent/v1'}]
    operations = {op['operationId'] for path in schema['paths'].values() for op in path.values()}
    assert operations == {'find_people', 'get_person', 'get_record', 'list_capabilities', 'people_for_capability', 'draft_request'}
    assert KEY not in response['body'].decode()


def test_calls_need_the_key(app):
    assert call(app, '/api/agent/v1/capabilities', key='')['status'] == 401
    assert call(app, '/api/agent/v1/capabilities', key='w' * 40)['status'] == 401
    assert call(app, '/api/agent/v1/capabilities')['status'] == 200


def test_find_inspect_and_draft_without_a_visitor_session(app):
    found = call(app, '/api/agent/v1/find-people?query=MPC%20%EC%97%B0%EA%B5%AC%EC%9E%90&limit=2')
    assert found['status'] == 200 and 'Set-Cookie' not in found['headers']
    people = found['json']['people']
    assert people and len(people) <= 2
    person = call(app, '/api/agent/v1/person/' + people[0]['id'])
    assert person['status'] == 200 and person['json']['status'] == 'ok'
    capabilities = call(app, '/api/agent/v1/capabilities')['json']['capabilities']
    assert call(app, '/api/agent/v1/capability/' + capabilities[0]['id'])['status'] == 200
    draft = call(app, '/api/agent/v1/draft', method='POST', payload={'person_ids': [people[0]['id']], 'need': '공정 제어 자문'})
    assert draft['status'] == 200 and draft['json']['drafts']
    assert call(app, '/api/agent/v1/person/NOT-A-PERSON')['status'] == 404
    assert call(app, '/api/agent/v1/draft', method='POST', payload=['x'])['status'] == 400
    assert call(app, '/api/agent/v1/unknown')['status'] == 404


def test_rate_limit(app, monkeypatch):
    monkeypatch.setattr(agent_http, 'RATE_PER_MINUTE', 3)
    statuses = [call(app, '/api/agent/v1/capabilities')['status'] for _ in range(4)]
    assert statuses == [200, 200, 200, 429]
