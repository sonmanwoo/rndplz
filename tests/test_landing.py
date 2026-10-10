"""Offline WSGI and projection checks; no listening server or browser is used."""
import gzip
import hashlib
import html
import io
import json
import re
from types import SimpleNamespace

import pytest

from rndplz.domain import Person
from rndplz.landing import (
    LANDING_ASSETS, MAP_SCRIPTS, build_landing_people_map,
    chat_script_variant, home_script_variant, landing_variant,
)
from rndplz.people_map import build_capabilities, build_home_people_map
from rndplz.static_assets import StaticAssets
from tests.test_public_performance import app, request


@pytest.mark.parametrize('query, expected', [
    ('', 'people'), ('x=1', 'people'), ('landing=off', None), ('landing', 'people'), ('landing=', 'people'), ('landing=map', 'map'),
    ('x=1&landing', 'people'), ('landing=people', None), ('landing=1', None),
    ('landing=MAP', None), ('landing=map&landing=', None), ('landing=&landing=', None),
])
def test_exact_opt_in_variants(query, expected):
    assert landing_variant(query) == expected


@pytest.mark.parametrize('query', ['?landing=off', '?landing=1', '?landing=people', '?landing=map&landing='])
def test_bare_home_keeps_identical_served_bytes_and_assets(app, query):
    baseline = StaticAssets(lambda path: None if path in LANDING_ASSETS else app._static_file(path), origin=app.origin)
    original = baseline.read('/')
    response = request(app, '/' + query)
    assert response['status'] == 200
    assert response['body'] == original.body
    assert b'data-landing' not in response['body']
    assert b'landing-boot.js' not in response['body']
    for name in ('home-cosmos.js', 'chat.js', *MAP_SCRIPTS):
        assert ('/' + name + '?v=').encode() in response['body']
        assert request(app, '/' + name)['body'] == baseline.read('/' + name).body


@pytest.mark.parametrize('query, variant', [('?landing', 'people'), ('?landing=map', 'map')])
def test_landing_composes_only_opt_in_document_and_defers_map(app, query, variant):
    original = app.static_assets.read('/').body
    response = request(app, '/' + query)
    assert response['status'] == 200
    body = response['body'].decode()
    assert 'data-landing="' + variant + '"' in body
    assert 'landingPeople' not in body
    map_section = re.search(r'<section\b[^>]*id="landingMap"[^>]*>', body)[0]
    assert ' hidden' not in map_section
    assert '<h2 id="landingMapTitle">' in body
    assert '전체 연구 맵 열기' in body
    assert '<h2 id="landingSourcesTitle">어떤 자료로 찾나요</h2>' in body
    assert 'id="landingCounts"' in body
    assert body.index('id="landingMap"') < body.index('id="landingSources"') < body.index('class="landing-closing"')
    principles = re.search(r'<ul class="landing-principles">(.*?)</ul>', body, re.S)[1]
    assert re.findall(r'<li>(.*?)</li>', principles) == [
        '공개 논문·제공 경력·프로젝트 기록을 근거로 찾아요.',
        '대화는 사내 AI(AiU) 또는 운영자 PC의 로컬 모델이 처리해요.',
    ]
    closing = body[body.index('class="landing-closing-actions"'):body.index('<nav class="landing-links"')]
    assert 'data-landing-ask>질문하기</button>' in closing
    assert 'data-landing-login>로그인</button>' in closing
    assert re.search(r'<a\b[^>]*href="/profile"[^>]*>내 이력 올리기</a>', closing)
    assert 'id="landingDown"' in body and 'href="#landingFeatures"' in body
    # 2026-10-10: the cosmos.so chevron (stroked SVG), not a text glyph that sits off-centre in the circle.
    down = body[body.index('id="landingDown"'):body.index('</a>', body.index('id="landingDown"'))]
    assert 'd="M4.25 9.25 12 17l7.75-7.75"' in down and '⌄' not in down
    assert '<h2 id="landingClosingTitle">당신이 멈춘 지점,<br>같이 풀 사람을<br>찾아요</h2>' in body
    assert body.index('id="landingDown"') < body.index('</main></div>') < body.index('id="landingFeatures"')
    assert re.search(r'<script[^>]+src="/landing-boot\.js\?v=[a-f0-9]{10}"[^>]*defer', body)
    assert re.search(r'<link[^>]+href="/landing\.css\?v=[a-f0-9]{10}"', body)
    assert re.search(r'<script[^>]+src="/landing-home\.js\?v=[a-f0-9]{10}"', body)
    assert re.search(r'<script[^>]+src="/landing-chat\.js\?v=[a-f0-9]{10}"', body)
    assert body.index('src="/landing-boot.js') < body.index('src="/landing-chat.js')
    assert '<script src="/home-cosmos.js' not in body
    assert '<script src="/chat.js' not in body
    for name in (*MAP_SCRIPTS, 'landing.js'):
        assert not re.search(r'<script[^>]+src="/' + re.escape(name), body)
    manifest = json.loads(html.unescape(re.search(r'data-landing-assets="([^"]+)"', body)[1]))
    assert set('/' + name for name in MAP_SCRIPTS).issubset(manifest)
    assert '/landing.js' in manifest
    assert '/recommendation-map.js' in manifest
    for path, url in manifest.items():
        assert url == app.static_assets.versioned_url(path, '/')
    assert app.static_assets.read('/').body == original
    assert request(app, '/?landing=off')['body'] == original
    assert request(app, '/')['body'] == request(app, '/?landing')['body']  # the home opens with the introduction (2026-10-10)
    compressed = request(app, '/' + query, encoding='gzip')
    assert gzip.decompress(compressed['body']) == response['body']
    assert response['headers']['Cache-Control'] == 'no-store'


def test_landing_map_alias_has_the_same_document(app):
    default = request(app, '/?landing')['body']
    alias = request(app, '/?landing=map')['body']
    assert default.replace(b'data-landing="people"', b'data-landing="map"', 1) == alias


def test_derived_home_script_keeps_original_and_hashes_transmitted_bytes(app):
    original = app.static_assets.read('/home-cosmos.js')
    derived = home_script_variant(original)
    assert derived.body == original.body.replace(
        b'const ownScroll = target => !isHome()',
        b'const ownScroll = target => Boolean(body.dataset.landing) || !isHome()', 1)
    assert derived.version == hashlib.sha256(derived.body).hexdigest()[:10]
    response = request(app, '/landing-home.js?v=' + derived.version)
    assert response['status'] == 200
    assert response['body'] == derived.body
    assert response['headers']['Cache-Control'] == 'public, max-age=31536000, immutable'
    assert 'Set-Cookie' not in response['headers']
    assert request(app, '/landing-home.js?v=' + original.version)['status'] == 404
    assert request(app, '/home-cosmos.js')['body'] == original.body
    compressed = request(app, '/landing-home.js?v=' + derived.version, encoding='gzip')
    assert gzip.decompress(compressed['body']) == derived.body


def test_derived_chat_awaits_graph_dependencies_without_changing_normal_chat(app):
    original = app.static_assets.read('/chat.js')
    derived = chat_script_variant(original)
    assert derived.body == original.body.replace(
        b"import('/recommendation-map.js')", b'window.Landing.loadRecommendation()', 1).replace(
        b'if(autoScroll&&!briefEditor)window.scrollTo',
        b'if(autoScroll&&!briefEditor&&!document.body.classList.contains("home-welcome"))window.scrollTo', 1)
    assert derived.version == hashlib.sha256(derived.body).hexdigest()[:10]
    response = request(app, '/landing-chat.js?v=' + derived.version)
    assert response['status'] == 200
    assert response['body'] == derived.body
    assert response['headers']['Cache-Control'] == 'public, max-age=31536000, immutable'
    assert 'Set-Cookie' not in response['headers']
    assert request(app, '/landing-chat.js?v=' + original.version)['status'] == 404
    assert request(app, '/chat.js')['body'] == original.body
    compressed = request(app, '/landing-chat.js?v=' + derived.version, encoding='gzip')
    assert gzip.decompress(compressed['body']) == derived.body


def test_capability_adapter_is_only_registered_for_addressed_explore(app):
    baseline = app.static_assets.read('/explore').body
    assert request(app, '/explore#map')['body'] == baseline
    response = request(app, '/explore?capability=process-control#map')
    assert response['status'] == 200
    addition = re.search(rb'<script src="/landing-map-link\.js\?v=[a-f0-9]{10}" defer></script>', response['body'])
    assert addition is not None
    assert response['body'].replace(addition[0], b'') == baseline
    # User-controlled query values are never interpolated into the HTML.
    injected = request(app, '/explore?capability=%3Cscript%3Ebad%3C/script%3E')
    assert injected['body'] == response['body']


def test_landing_projection_counts_scoped_data_without_people_or_details(monkeypatch):
    # Already-public provided profiles count too; neither portraits nor curated
    # status determine whether a researcher is part of the published corpus.
    people = [
        Person(id='public-a', name='public-a', profile={'curated': True, 'portrait': {'path': '/portraits/a.png'}}),
        Person(id='public-b', name='public-b'),
        Person(id='LOCAL-approved', name='LOCAL-approved', profile={'source_type': 'provided_resume'}),
        Person(id='virtual', name='virtual', virtual=True),
    ]
    shared = SimpleNamespace(id='shared-paper', virtual=False)
    provided = SimpleNamespace(id='approved-career', virtual=False)
    virtual = SimpleNamespace(id='virtual-record', virtual=True)
    corpus = SimpleNamespace(
        people={person.id: person for person in people},
        records={record.id: record for record in (shared, provided, virtual)},
        by_person={'public-a': [shared], 'public-b': [shared], 'LOCAL-approved': [provided], 'virtual': [virtual]},
    )
    categories = [
        {'id': 'second', 'label': '두 번째 분야', 'description': 'omit',
         'people': [{'id': 'public-b', 'recordIds': ['shared-paper']}, {'id': 'LOCAL-approved'}]},
        {'id': 'first', 'label': '첫 번째 분야', 'description': 'omit', 'people': [{'id': 'public-a'}]},
    ]
    monkeypatch.setattr('rndplz.landing.build_capabilities', lambda current: categories)
    result = build_landing_people_map(SimpleNamespace(corpus=corpus))
    assert result == {
        'schema_version': 'people-map-landing-v1',
        'counts': {'people': 3, 'capabilities': 2, 'records': 2},
        'capabilities': [{'id': 'second', 'label': '두 번째 분야'}, {'id': 'first', 'label': '첫 번째 분야'}],
    }
    # A shared paper counts once, and totals follow the current scoped data.
    corpus.people.pop('public-b')
    corpus.records.pop('approved-career')
    categories.pop()
    assert build_landing_people_map(SimpleNamespace(corpus=corpus))['counts'] == {
        'people': 2, 'capabilities': 1, 'records': 1,
    }


def test_landing_projection_has_zero_counts_for_an_empty_corpus(monkeypatch):
    monkeypatch.setattr('rndplz.landing.build_capabilities', lambda current: [])
    data = build_landing_people_map(SimpleNamespace(corpus=SimpleNamespace(people={}, records={})))
    assert data['counts'] == {'people': 0, 'capabilities': 0, 'records': 0}
    assert data['capabilities'] == []
    assert 'people' not in data


def test_home_api_contract_is_unchanged_and_landing_reuses_category_order(app, monkeypatch):
    def no_details(*args, **kwargs):
        pytest.fail('The lightweight endpoint must not materialize record details')

    monkeypatch.setattr(app.engine, 'explain_record', no_details)
    home = request(app, '/api/people-map?view=home')
    expected = build_home_people_map(app.engine)
    assert json.loads(home['body']) == expected
    landing = request(app, '/api/people-map?view=home&landing=1')
    assert landing['status'] == 200
    data = json.loads(landing['body'])
    assert data == build_landing_people_map(app.engine)
    assert [category['id'] for category in data['capabilities']] == [category['id'] for category in expected['capabilities']]
    assert [category['label'] for category in data['capabilities']] == [category['label'] for category in build_capabilities(app.engine.corpus)]
    assert 'people' not in data
    assert all(set(category) == {'id', 'label'} for category in data['capabilities'])
    assert data['counts'] == {
        'people': sum(not person.virtual for person in app.engine.corpus.people.values()),
        'capabilities': len(expected['capabilities']),
        'records': sum(not record.virtual for record in app.engine.corpus.records.values()),
    }
    assert len(landing['body']) < len(home['body'])
    assert request(app, '/api/people-map?view=home')['body'] == home['body']
    assert request(app, '/api/people-map?view=home&landing=no')['body'] == home['body']
    compressed = request(app, '/api/people-map?view=home&landing=1', encoding='gzip')
    assert gzip.decompress(compressed['body']) == landing['body']


def test_landing_files_are_explicitly_allowlisted_and_fragment_is_not_public(app):
    for path in LANDING_ASSETS:
        response = request(app, path)
        assert response['status'] == 200, path
        assert 'Set-Cookie' not in response['headers']
    assert request(app, '/landing.html')['status'] == 404
    assert request(app, '/landing-assets/unreviewed.png')['status'] == 404


def test_landing_first_document_and_eager_assets_stay_within_home_byte_budget(app):
    """Compare actual WSGI representations; no browser or listening socket."""
    from html.parser import HTMLParser

    class EagerAssets(HTMLParser):
        def __init__(self):
            super().__init__()
            self.urls = set()

        def handle_starttag(self, tag, attributes):
            attributes = dict(attributes)
            if tag == 'script' and attributes.get('src'):
                self.urls.add(attributes['src'])
            elif tag == 'link' and attributes.get('rel') == 'stylesheet':
                self.urls.add(attributes['href'])

    def size(url, encoding):
        document = request(app, url, encoding=encoding)
        assert document['status'] == 200
        source = document['body']
        if document['headers'].get('Content-Encoding') == 'gzip':
            source = gzip.decompress(source)
        parser = EagerAssets()
        parser.feed(source.decode('utf-8'))
        total = len(document['body'])
        for asset_url in parser.urls:
            asset = request(app, asset_url, encoding=encoding)
            assert asset['status'] == 200
            total += len(asset['body'])
        return total

    for encoding in (None, 'gzip'):
        baseline = size('/?landing=off', encoding)
        assert size('/?landing', encoding) < baseline
        assert size('/?landing=map', encoding) < baseline


def test_scene_rail_plays_recorded_service_clips(app):
    """2026-10-10: the feature rail shows five scenes recorded from the real service; the old crops are gone."""
    body = request(app, '/')['body'].decode('utf-8')
    start = body.index('id="landingFeatureRail"')
    rail = body[start:body.index('</ul>', start)]
    videos = re.findall(r'<video\b[^>]*>', rail)
    assert len(videos) == 5
    for n, tag in enumerate(videos, 1):
        assert 'muted' in tag and 'playsinline' in tag and 'preload="none"' in tag and 'autoplay' not in tag
        assert re.search(rf'data-src="/landing-assets/scene-{n}\.mp4\?v=[a-f0-9]{{10}}"', tag), tag
        assert re.search(rf'data-poster="/landing-assets/scene-{n}\.jpg\?v=[a-f0-9]{{10}}"', tag), tag
    assert re.search(r'data-src="/landing-assets/profile\.webp\?v=[a-f0-9]{10}"', rail) and '연구 맵으로 둘러봐요' not in rail
    # A versioned clip is cached for a year and still answers byte ranges.
    versioned = re.search(r'data-src="(/landing-assets/scene-1\.mp4\?v=[a-f0-9]{10})"', rail)[1]
    cached = request(app, versioned)
    assert cached['status'] == 200 and 'immutable' in cached['headers']['Cache-Control']
    for name in ('chat', 'evidence', 'map', 'letter'):
        assert request(app, f'/landing-assets/{name}.webp')['status'] == 404
    clip = request(app, '/landing-assets/scene-1.mp4')
    assert clip['status'] == 200 and clip['headers']['Content-Type'] == 'video/mp4'
    # iOS Safari plays a clip only through byte ranges.
    environ = {'REQUEST_METHOD': 'GET', 'PATH_INFO': '/landing-assets/scene-1.mp4', 'QUERY_STRING': '', 'HTTP_HOST': '127.0.0.1',
               'wsgi.url_scheme': 'http', 'wsgi.input': io.BytesIO(b''), 'CONTENT_LENGTH': '0', 'HTTP_COOKIE': '', 'HTTP_RANGE': 'bytes=0-99'}
    status = {}
    part = b''.join(app(environ, lambda code, headers: status.update(code=code, headers=dict(headers))))
    assert status['code'].startswith('206') and len(part) == 100
    assert status['headers']['Content-Range'].startswith('bytes 0-99/')
