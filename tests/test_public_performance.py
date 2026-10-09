"""Direct WSGI checks for public compression, asset versions and the home projection.

No listening socket, preview server, browser or external provider is started.
"""
import gzip
import hashlib
import io
import json
import os
import re
import time
from urllib.parse import urlsplit
from unittest.mock import Mock

import pytest

import rndplz.public_web as public_web


def request(app, url, *, encoding=None, cookie='', method='GET', payload=None, token=''):
    parsed = urlsplit(url)
    raw = json.dumps(payload).encode() if payload is not None else b''
    environ = {
        'REQUEST_METHOD': method, 'PATH_INFO': parsed.path, 'QUERY_STRING': parsed.query,
        'HTTP_HOST': '127.0.0.1', 'wsgi.url_scheme': 'http', 'wsgi.input': io.BytesIO(raw),
        'CONTENT_LENGTH': str(len(raw)), 'HTTP_COOKIE': cookie,
    }
    if encoding is not None:
        environ['HTTP_ACCEPT_ENCODING'] = encoding
    if method == 'POST':
        environ.update(CONTENT_TYPE='application/json', HTTP_ORIGIN='http://127.0.0.1',
                       HTTP_X_RNDPLZ_TOKEN=token)
    result = {}

    def start_response(status, headers):
        result['status'] = int(status.split()[0])
        result['headers'] = dict(headers)

    iterable = app(environ, start_response)
    try:
        result['body'] = b''.join(iterable)
    finally:
        if hasattr(iterable, 'close'):
            iterable.close()
    return result


@pytest.fixture
def app(tmp_path, monkeypatch):
    result = public_web.PublicApp(state_dir=tmp_path / 'state', env={
        'RNDPLZ_LOCAL_PREVIEW': '1', 'RNDPLZ_SESSION_SECRET': 's' * 64,
        'RNDPLZ_PROVIDER': 'none', 'RNDPLZ_MODEL_CALL_LIMIT': '0',
        'RNDPLZ_PUBLIC_PERSON_IDS': 'LOCAL-MANWOO,LOCAL-JINHO,LOCAL-DASOL,LOCAL-HONG',
    })
    monkeypatch.setattr(result.models, 'catalog', lambda: {'models': []})
    return result


@pytest.fixture
def static_web(app, tmp_path, monkeypatch):
    web = tmp_path / 'web'
    web.mkdir()
    files = {
        'person-view.js': (b'window.fixturePerson = true;\r\n' * 90, 'text/javascript'),
        'person-view.css': (
            b'@font-face{font-family:fixture;src:url("/fixture-font.woff2")}\r\n'
            b'.fixture{background:url(/fixture.svg)}\r\n' + b'.fixture{color:navy}\r\n' * 90,
            'text/css'),
        'tiny.js': (b'void 0;\r\n', 'text/javascript'),
        'fixture.svg': (b'<svg xmlns="http://www.w3.org/2000/svg"><desc>' + b'art ' * 400 + b'</desc></svg>',
                        'image/svg+xml'),
        'fixture.json': (json.dumps({'public': ['data'] * 300}).encode(), 'application/json'),
        'fixture-font.woff2': (b'wOF2' + b'font' * 500, 'font/woff2'),
        'fixture.webp': (b'RIFF' + b'image' * 500, 'image/webp'),
    }
    page = (b'<!doctype html>\r\n<link rel="stylesheet" href="/person-view.css">\r\n'
            b'<script src="/person-view.js" defer></script>\r\n' + b'<!-- fixture -->\r\n' * 100)
    for name in ('index.html', 'explore.html', 'profile.html'):
        (web / name).write_bytes(page)
    allowed = dict(public_web.STATIC_FILES)
    for name, (body, mime) in files.items():
        (web / name).write_bytes(body)
        allowed['/' + name] = (name, mime)
    monkeypatch.setattr(public_web, 'WEB', web)
    monkeypatch.setattr(public_web, 'STATIC_FILES', allowed)
    return web


def version_url(body, filename):
    found = re.search(rb'/' + re.escape(filename.encode()) + rb'\?v=[a-f0-9]{10}', body)
    assert found is not None, filename
    return found.group().decode()


def assert_length(response):
    assert response['headers']['Content-Length'] == str(len(response['body']))


@pytest.mark.parametrize('url', [
    '/person-view.js', '/person-view.css', '/', '/fixture.svg', '/fixture.json',
    '/api/people-map?view=home',
])
def test_public_text_gzip_has_exact_length_and_vary(app, static_web, url):
    original = request(app, url)
    compressed = request(app, url, encoding='gzip, br')
    assert original['status'] == compressed['status'] == 200
    assert len(original['body']) >= 1024
    assert 'Content-Encoding' not in original['headers']
    assert compressed['headers']['Content-Encoding'] == 'gzip'
    assert gzip.decompress(compressed['body']) == original['body']
    assert len(compressed['body']) < len(original['body'])
    for response in (original, compressed):
        assert response['headers']['Vary'] == 'Accept-Encoding'
        assert response['headers']['Cache-Control'] == 'no-store'
        assert "script-src 'self'" in response['headers']['Content-Security-Policy']
        assert_length(response)


@pytest.mark.parametrize('encoding', [None, '', 'br', 'gzip;q=0', '*;q=0',
                                      '*;q=1, gzip;q=0', 'gzip;q=0.2, identity;q=0.8'])
def test_gzip_negotiation_preserves_identity_when_not_accepted(app, static_web, encoding):
    response = request(app, '/person-view.js', encoding=encoding)
    assert response['status'] == 200
    assert response['body'] == (static_web / 'person-view.js').read_bytes()
    assert 'Content-Encoding' not in response['headers']
    assert response['headers']['Vary'] == 'Accept-Encoding'
    assert_length(response)


@pytest.mark.parametrize('encoding', ['gzip', 'GZIP;q=0.8', '*;q=1'])
def test_gzip_negotiation_accepts_explicit_or_wildcard(app, static_web, encoding):
    response = request(app, '/person-view.js', encoding=encoding)
    assert response['headers']['Content-Encoding'] == 'gzip'
    assert gzip.decompress(response['body']) == (static_web / 'person-view.js').read_bytes()
    assert_length(response)


@pytest.mark.parametrize('filename', ['tiny.js', 'fixture-font.woff2', 'fixture.webp'])
def test_tiny_text_and_precompressed_formats_are_not_compressed(app, static_web, filename):
    response = request(app, '/' + filename, encoding='gzip')
    assert response['status'] == 200
    assert response['body'] == (static_web / filename).read_bytes()
    assert 'Content-Encoding' not in response['headers']
    assert_length(response)


def test_versions_apply_to_new_allowlisted_files_and_css_dependencies(app, static_web):
    page = request(app, '/')
    script_url = version_url(page['body'], 'person-view.js')
    css_url = version_url(page['body'], 'person-view.css')
    assert script_url.endswith(hashlib.sha256((static_web / 'person-view.js').read_bytes()).hexdigest()[:10])
    css = request(app, css_url)
    font_url = version_url(css['body'], 'fixture-font.woff2')
    image_url = version_url(css['body'], 'fixture.svg')
    for url in (script_url, css_url, font_url, image_url):
        for encoding in (None, 'gzip'):
            response = request(app, url, encoding=encoding)
            assert response['status'] == 200
            assert response['headers']['Cache-Control'] == 'public, max-age=31536000, immutable'
            assert 'Set-Cookie' not in response['headers']
            assert_length(response)
        plain = request(app, url.split('?')[0])
        assert plain['headers']['Cache-Control'] == 'no-store'
    assert page['headers']['Cache-Control'] == 'no-store'
    assert request(app, '/?v=0123456789')['headers']['Cache-Control'] == 'no-store'
    assert request(app, '/api/people-map?view=home&v=0123456789')['headers']['Cache-Control'] == 'no-store'


def test_modified_bytes_invalidate_html_css_and_old_immutable_urls(app, static_web):
    original = request(app, '/')['body']
    old_script = version_url(original, 'person-view.js')
    old_css = version_url(original, 'person-view.css')
    old_css_body = request(app, old_css)['body']
    old_font = version_url(old_css_body, 'fixture-font.woff2')
    # Same byte count and mtime still invalidate a content-based version.
    script = static_web / 'person-view.js'
    before = script.stat()
    script.write_bytes(script.read_bytes().replace(b'true', b'null'))
    os.utime(script, ns=(before.st_atime_ns, before.st_mtime_ns))
    changed_script = request(app, '/')['body']
    assert version_url(changed_script, 'person-view.js') != old_script
    assert version_url(changed_script, 'person-view.css') == old_css
    font = static_web / 'fixture-font.woff2'
    before = font.stat()
    font.write_bytes(font.read_bytes().replace(b'font', b'FONT'))
    os.utime(font, ns=(before.st_atime_ns, before.st_mtime_ns))
    changed_font = request(app, '/')['body']
    new_css = version_url(changed_font, 'person-view.css')
    assert new_css != old_css
    assert version_url(request(app, new_css)['body'], 'fixture-font.woff2') != old_font
    for url in (old_script, old_css, old_font):
        stale = request(app, url, encoding='gzip')
        assert stale['status'] == 404
        assert stale['headers']['Cache-Control'] == 'no-store'
        assert 'Content-Encoding' not in stale['headers']
        assert_length(stale)


@pytest.mark.parametrize('query', ['v=fake', 'v=', 'v=0123456789&v=0123456789'])
def test_invalid_versions_cannot_publish_current_bytes_as_immutable(app, static_web, query):
    response = request(app, '/person-view.js?' + query, encoding='gzip')
    assert response['status'] == 404
    assert response['headers']['Cache-Control'] == 'no-store'
    assert 'Content-Encoding' not in response['headers']
    assert_length(response)


def test_duplicate_valid_version_is_rejected(app, static_web):
    url = version_url(request(app, '/')['body'], 'person-view.js')
    response = request(app, url + '&' + url.split('?')[1])
    assert response['status'] == 404
    assert response['headers']['Cache-Control'] == 'no-store'


def test_static_assets_skip_visitor_auth_and_inflight_even_with_full_contexts(app, static_web, monkeypatch):
    assert app.contexts == {}
    first = request(app, '/person-view.js')
    assert first['status'] == 200 and 'Set-Cookie' not in first['headers']
    assert app.contexts == {}
    saturated = {str(index): {'used': time.monotonic(), 'active': 1, 'inflight': 17}
                 for index in range(128)}
    app.contexts.update(saturated)
    before = {key: dict(value) for key, value in app.contexts.items()}
    hooks = []
    for owner, name in ((app, 'visitor'), (app, '_account_context'), (app, '_revoked'),
                        (app.auth, 'authenticate')):
        hook = Mock(side_effect=AssertionError('static asset entered visitor handling'))
        monkeypatch.setattr(owner, name, hook)
        hooks.append(hook)
    before_files = sorted(str(path) for path in app.directory.rglob('*'))
    for url in ('/person-view.js', '/person-view.css', '/fixture.svg', '/fixture-font.woff2'):
        response = request(app, url, encoding='gzip', cookie='rndplz_visitor=invalid')
        assert response['status'] == 200
        assert 'Set-Cookie' not in response['headers']
    assert app.contexts == before
    assert sorted(str(path) for path in app.directory.rglob('*')) == before_files
    for hook in hooks:
        hook.assert_not_called()


@pytest.mark.parametrize('page', ['/', '/explore', '/profile'])
def test_entry_document_seeds_one_cookie_for_parallel_api_bootstrap(app, static_web, page):
    document = request(app, page, encoding='gzip')
    assert document['status'] == 200
    assert document['headers']['Cache-Control'] == 'no-store'
    cookie = document['headers']['Set-Cookie'].split(';', 1)[0]
    assert len(app.contexts) == 1
    context = next(iter(app.contexts.values()))
    for url in ('/api/chat/bootstrap', '/api/self-profile', '/api/bootstrap'):
        response = request(app, url, cookie=cookie, encoding='gzip')
        assert response['status'] == 200
        assert json.loads(response['body'])['token'] == context['token']
        assert response['headers']['Set-Cookie'].split(';', 1)[0] == cookie
        assert 'Content-Encoding' not in response['headers']
    account = request(app, '/api/account/session', cookie=cookie)
    assert account['status'] == 200
    assert account['headers']['Set-Cookie'].split(';', 1)[0] == cookie
    assert len(app.contexts) == 1
    assert context['inflight'] == 0


def test_large_secret_and_personal_responses_never_opt_into_compression(app, monkeypatch):
    initial = request(app, '/api/chat/bootstrap')
    cookie = initial['headers']['Set-Cookie'].split(';', 1)[0]
    context = next(iter(app.contexts.values()))
    reflected = 'synthetic visitor input ' * 150
    monkeypatch.setattr(context['chat'], 'history', lambda: [{'text': reflected}])
    monkeypatch.setattr(context['profile'], 'read', lambda: {'profile': {'text': reflected}})
    monkeypatch.setattr(context['service'], 'bootstrap', lambda: {'text': reflected})
    monkeypatch.setattr(context['service'], 'person', lambda identifier: {'id': identifier, 'text': reflected})
    monkeypatch.setattr(app, '_account_status', lambda ctx, env: {'token': ctx['token'], 'text': reflected})
    for url in ('/api/chat/bootstrap', '/api/self-profile', '/api/bootstrap',
                '/api/account/session', '/api/person?id=fixture'):
        response = request(app, url, cookie=cookie, encoding='gzip')
        assert response['status'] == 200
        assert len(response['body']) > 1024
        assert 'Content-Encoding' not in response['headers']
        assert 'Vary' not in response['headers']
        assert response['headers']['Cache-Control'] == 'no-store'
        assert_length(response)


def test_ndjson_chat_stream_remains_uncompressed(app, monkeypatch):
    initial = request(app, '/api/chat/bootstrap')
    cookie = initial['headers']['Set-Cookie'].split(';', 1)[0]
    context = next(iter(app.contexts.values()))
    events = [{'type': 'delta', 'text': 'synthetic ' * 300}, {'type': 'done'}]
    monkeypatch.setattr(context['chat'], 'stream', lambda payload: iter(events))
    response = request(app, '/api/chat', encoding='gzip', cookie=cookie, method='POST',
                       payload={'text': 'fixture'}, token=context['token'])
    assert response['status'] == 200
    assert response['headers']['Content-Type'] == 'application/x-ndjson; charset=utf-8'
    assert 'Content-Encoding' not in response['headers']
    assert 'Content-Length' not in response['headers']
    assert 'Vary' not in response['headers']
    assert [json.loads(line) for line in response['body'].splitlines()] == events
    assert context['inflight'] == context['active'] == 0


def test_home_endpoint_equals_full_map_public_presentation_projection(app):
    full_response = request(app, '/api/people-map')
    cookie = full_response['headers']['Set-Cookie'].split(';', 1)[0]
    full = json.loads(full_response['body'])
    home_response = request(app, '/api/people-map?view=home', cookie=cookie, encoding='gzip')
    home = json.loads(gzip.decompress(home_response['body']))
    assert full_response['status'] == home_response['status'] == 200
    assert full['schema_version'] == 'people-map-existing-v1' and full['complete'] is True
    assert home['schema_version'] == 'people-map-home-v1'
    expected = []
    for person in full['people']:
        profile = person['profile']
        projected = {key: profile[key] for key in ('display_name',) if key in profile}
        if 'path' in (profile.get('portrait') or {}):
            projected['portrait'] = {'path': profile['portrait']['path']}
        expected.append({'id': person['id'], 'name': person['name'], 'profile': projected})
    assert home['people'] == expected
    assert home['capabilities'] == [
        {'id': category['id'], 'people': [{'id': link['id']} for link in category['people']]}
        for category in full['capabilities']
    ]
    assert home_response['headers']['Cache-Control'] == 'no-store'
    assert len(home_response['body']) < len(full_response['body']) // 10


def test_full_people_map_gzip_preserves_existing_contract(app):
    original = request(app, '/api/people-map')
    cookie = original['headers']['Set-Cookie'].split(';', 1)[0]
    compressed = request(app, '/api/people-map', encoding='gzip', cookie=cookie)
    assert original['status'] == compressed['status'] == 200
    assert 'Content-Encoding' not in original['headers']
    assert compressed['headers']['Content-Encoding'] == 'gzip'
    plain_data = json.loads(original['body'])
    gzip_data = json.loads(gzip.decompress(compressed['body']))
    for data in (plain_data, gzip_data):
        assert data['schema_version'] == 'people-map-existing-v1'
        assert data['complete'] is True
        assert data['source'].pop('generated_at')
    # The generation timestamp is the sole request-specific map field.
    assert gzip_data == plain_data
    assert len(compressed['body']) < len(original['body'])
    for response in (original, compressed):
        assert response['headers']['Vary'] == 'Accept-Encoding'
        assert response['headers']['Cache-Control'] == 'no-store'
        assert_length(response)
