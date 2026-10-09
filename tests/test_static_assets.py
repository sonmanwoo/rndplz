"""Offline checks for content addresses and public-only gzip helpers."""
import gzip
import hashlib
from unittest.mock import patch

import pytest

from rndplz.static_assets import StaticAssets, is_compressible, prefers_gzip


@pytest.mark.parametrize('header, expected', [
    ('', False), ('br', False), ('gzip', True), ('GZIP', True),
    ('gzip;q=0', False), ('*;q=0.7', True), ('gzip;q=0,*;q=1', False),
    ('gzip;q=0.8, identity;q=0.9', False), ('gzip;q=1, identity;q=0.5', True),
    ('gzip;q=0.5', True), ('gzip;q=wrong', False), ('gzip;q=nan', False),
    ('gzip;q=2', False), ('gzip;q=0,gzip', False),
])
def test_encoding_negotiation(header, expected):
    assert prefers_gzip(header) is expected


@pytest.fixture
def assets(tmp_path):
    allowed = {}

    def add(path, data, mime):
        target = tmp_path / (path.lstrip('/') or 'index.html')
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        allowed[path] = (target, mime)
        return target

    return StaticAssets(allowed.get, origin='https://example.test'), add


def test_html_and_transitive_css_versions_follow_content(assets):
    store, add = assets
    font = add('/fonts/main.woff2', b'font original', 'font/woff2')
    add('/css/main.css', b'@font-face { src: url("../fonts/main.woff2#font"); }\r\n', 'text/css')
    script = add('/app.js', b'console.log("original");', 'text/javascript')
    source = b'<!doctype html>\r\n<link rel="stylesheet" href="/css/main.css">\r\n<script src="/app.js"></script>\r\n'
    add('/', source, 'text/html')
    first = store.read('/')
    css = store.read('/css/main.css')
    assert first.raw == source
    assert b'/css/main.css?v=' + css.version.encode() in first.body
    assert b'../fonts/main.woff2?v=' + store.read('/fonts/main.woff2').version.encode() + b'#font' in css.body
    assert first.body.count(b'\r\n') == source.count(b'\r\n')
    font.write_bytes(b'font replaced')
    second = store.read('/')
    assert second.body != first.body
    assert store.read('/css/main.css').version != css.version
    # Same length replacements are invalidated even without a stat-size change.
    script.write_bytes(b'console.log("modified");')
    assert store.read('/').body != second.body


def test_existing_query_fragment_and_origin_are_preserved(assets):
    store, add = assets
    add('/app.js', b'console.log(1);', 'text/javascript')
    version = store.read('/app.js').version
    assert store.versioned_url('../app.js?x=a%20b&v=old#section', '/nested/index.html') == '../app.js?x=a%20b&v=' + version + '#section'
    assert store.versioned_url('https://example.test/app.js', '/') == 'https://example.test/app.js?v=' + version
    assert store.versioned_url('https://example.test:443/app.js', '/') == 'https://example.test:443/app.js?v=' + version
    assert store.versioned_url('//example.test/app.js', '/') == '//example.test/app.js?v=' + version
    for url in ('https://other.test/app.js', 'http://example.test/app.js', '//other.test/app.js',
                'https://example.test:0/app.js', 'https://example.test:bad/app.js', 'https://[invalid/app.js',
                'data:text/javascript,hello', '#id', '/private.js', '/missing.js'):
        assert store.versioned_url(url, '/') == url


def test_html_only_changes_actual_asset_attributes_and_accepts_new_allowlist_entries(assets):
    store, add = assets
    add('/person-view.js', b'console.log(1);', 'text/javascript')
    add('/person-view.css', b'body {}', 'text/css')
    add('/fonts/new.woff2', b'font', 'font/woff2')
    source = '''<!-- <script src="/person-view.js"></script> -->
<script>const example = '<script src="/person-view.js">';</script>
<script defer src='/person-view.js?x=1&amp;y=2'></script>
<link rel=stylesheet href=/person-view.css>
<link rel="preload" as="font" href="/fonts/new.woff2">
<a href="/person-view.js">keep</a>'''
    add('/', source.encode(), 'text/html')
    body = store.read('/').body.decode()
    assert '<!-- <script src="/person-view.js"></script> -->' in body
    assert 'const example = \'<script src="/person-view.js">\';' in body
    assert 'x=1&amp;y=2&amp;v=' in body
    assert 'href="/person-view.css?v=' in body
    assert '/fonts/new.woff2?v=' in body
    assert '<a href="/person-view.js">keep</a>' in body


def test_css_preserves_comments_data_urls_and_strings_and_versions_imports(assets):
    store, add = assets
    add('/img/a.svg', b'<svg/>', 'image/svg+xml')
    add('/nested.css', b'.nested {}', 'text/css')
    source = b'''/* url(/img/a.svg) */
.a { content: "url(/img/a.svg)"; background: url(data:image/svg+xml;base64,aabb); }
.b { background: url( '/img/a.svg?x=1#icon' ); }
@import "nested.css" screen;
'''
    add('/style.css', source, 'text/css')
    body = store.read('/style.css').body
    assert b'/* url(/img/a.svg) */' in body
    assert b'content: "url(/img/a.svg)"' in body
    assert b'url(data:image/svg+xml;base64,aabb)' in body
    assert b"url( '/img/a.svg?x=1&v=" in body
    assert b"#icon' )" in body
    assert b'@import "nested.css?v=' in body


def test_cyclic_css_remains_no_store_addressable_without_recursion(assets):
    store, add = assets
    add('/a.css', b'@import "b.css";', 'text/css')
    add('/b.css', b'@import "a.css";', 'text/css')
    add('/', b'<link rel="stylesheet" href="/a.css">', 'text/html')
    assert store.read('/a.css').body == b'@import "b.css";'
    assert store.read('/').body == b'<link rel="stylesheet" href="/a.css">'


def test_gzip_cache_reuses_encoding_and_invalidates_in_place(assets):
    store, add = assets
    file = add('/app.js', b'const example = "a";\n' * 200, 'text/javascript')
    asset = store.read('/app.js')
    assert store.gzip_body(asset, '') is None
    with patch('rndplz.static_assets.gzip.compress', wraps=gzip.compress) as compress:
        encoded = store.gzip_body(asset, 'gzip')
        assert gzip.decompress(encoded) == asset.body
        assert store.gzip_body(store.read('/app.js'), 'gzip') is encoded
        assert compress.call_count == 1
        file.write_bytes(b'const example = "b";\n' * 200)
        changed = store.gzip_body(store.read('/app.js'), 'gzip')
        assert changed != encoded
        assert compress.call_count == 2
        assert len(store._gzip_cache) == 1


def test_gzip_excludes_small_binary_and_stream_data():
    assert not is_compressible('application/json', b'a' * 1023)
    assert is_compressible('application/json; charset=utf-8', b'a' * 1024)
    for mime in ('image/webp', 'font/woff2', 'application/x-ndjson', 'application/octet-stream'):
        assert not is_compressible(mime, b'a' * 2048)


def test_gzip_cache_is_bounded_by_entry_count_and_bytes():
    store = StaticAssets(lambda path: None, max_cache_entries=2, max_cache_bytes=100)
    for index in range(10):
        store.gzip_bytes(b'a' * 2048, 'application/json', 'gzip', cache_key=str(index))
    assert len(store._gzip_cache) <= 2
    assert store._gzip_cache_bytes <= 100


def test_version_is_the_transmitted_identity_representation(assets):
    store, add = assets
    add('/f.woff2', b'font', 'font/woff2')
    add('/x.css', b'@font-face {src:url(/f.woff2)}', 'text/css')
    asset = store.read('/x.css')
    assert asset.version == hashlib.sha256(asset.body).hexdigest()[:10]
    assert asset.version != hashlib.sha256(asset.raw).hexdigest()[:10]
