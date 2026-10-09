"""Offline WSGI and projection checks; no listening server or browser is used."""
import gzip
import hashlib
import html
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
    ('', None), ('landing', 'people'), ('landing=', 'people'), ('landing=map', 'map'),
    ('x=1&landing', 'people'), ('landing=people', None), ('landing=1', None),
    ('landing=MAP', None), ('landing=map&landing=', None), ('landing=&landing=', None),
])
def test_exact_opt_in_variants(query, expected):
    assert landing_variant(query) == expected


@pytest.mark.parametrize('query', ['', '?x=1', '?landing=1', '?landing=people', '?landing=map&landing='])
def test_default_home_keeps_identical_served_bytes_and_assets(app, query):
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
    people_section = re.search(r'<section\b[^>]*id="landingPeople"[^>]*>', body)[0]
    map_section = re.search(r'<section\b[^>]*id="landingMap"[^>]*>', body)[0]
    assert (' hidden' in people_section) is (variant == 'map')
    assert (' hidden' in map_section) is (variant == 'people')
    assert 'id="landingDown"' in body and 'href="#landingFeatures"' in body
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
    assert request(app, '/')['body'] == original
    compressed = request(app, '/' + query, encoding='gzip')
    assert gzip.decompress(compressed['body']) == response['body']
    assert response['headers']['Cache-Control'] == 'no-store'


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


def test_landing_projection_filters_private_profiles_and_detailed_fields(monkeypatch):
    def person(identifier, **profile):
        return Person(id=identifier, name=identifier, profile={
            'curated': True, 'display_name': '공개 연구자',
            'portrait': {'path': '/portraits/public.png', 'background': '/private.png'},
            'biography': 'not in the lightweight projection', 'csrf_token': 'private',
            **profile,
        })
    people = [
        person('public-a', field_label='공정 제어'),
        person('public-b', field_label=['invalid'], research_field='unsupported fallback'),
        person('LOCAL-private'), person('resume', source_type='provided_resume'),
        person('self', source_type='self_reported'), person('uncurated', curated=False),
        person('bad-path', portrait={'path': 'https://example.test/private.png'}),
        person('no-portrait', portrait={}), person('virtual'),
    ]
    people[-1].virtual = True
    corpus = SimpleNamespace(people={person.id: person for person in people})
    categories = [
        {'id': 'second', 'label': '두 번째 역량', 'description': 'omit',
         'people': [{'id': 'public-b', 'recordIds': ['hidden']}, {'id': 'LOCAL-private'}]},
        {'id': 'first', 'label': '첫 번째 역량', 'description': 'omit',
         'people': [{'id': 'public-a'}, {'id': 'self'}]},
    ]
    monkeypatch.setattr('rndplz.landing.build_capabilities', lambda current: categories)
    result = build_landing_people_map(SimpleNamespace(corpus=corpus))
    assert result['schema_version'] == 'people-map-landing-v1'
    assert [person['id'] for person in result['people']] == ['public-a', 'public-b']
    assert [person['field_label'] for person in result['people']] == ['공정 제어', '두 번째 역량']
    assert result['people'][0] == {
        'id': 'public-a', 'name': 'public-a', 'field_label': '공정 제어',
        'profile': {'display_name': '공개 연구자', 'portrait': {'path': '/portraits/public.png'}},
    }
    assert result['capabilities'] == [
        {'id': 'second', 'label': '두 번째 역량', 'people': [{'id': 'public-b'}]},
        {'id': 'first', 'label': '첫 번째 역량', 'people': [{'id': 'public-a'}]},
    ]


def test_home_api_contract_is_unchanged_and_landing_reuses_category_order(app):
    home = request(app, '/api/people-map?view=home')
    expected = build_home_people_map(app.engine)
    assert json.loads(home['body']) == expected
    landing = request(app, '/api/people-map?view=home&landing=1')
    assert landing['status'] == 200
    data = json.loads(landing['body'])
    assert data == build_landing_people_map(app.engine)
    assert [category['id'] for category in data['capabilities']] == [category['id'] for category in expected['capabilities']]
    assert [category['label'] for category in data['capabilities']] == [category['label'] for category in build_capabilities(app.engine.corpus)]
    assert data['people']
    assert not any(person['id'].startswith('LOCAL-') for person in data['people'])
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
        baseline = size('/', encoding)
        assert size('/?landing', encoding) < baseline
        assert size('/?landing=map', encoding) < baseline
