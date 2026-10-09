"""Opt-in landing views; the ordinary home and its source assets stay untouched."""
from __future__ import annotations

import hashlib
import html
import json
import re
from urllib.parse import parse_qs

from .people_map import build_capabilities
from .static_assets import StaticAsset


LANDING_ASSETS = {
    **{'/' + name: (name, 'text/css' if name.endswith('.css') else 'text/javascript')
       for name in ('landing.css', 'landing.js', 'landing-boot.js', 'landing-map-link.js', 'landing-map-preview.js')},
    '/landing-home.js': ('home-cosmos.js', 'text/javascript'),
    '/landing-chat.js': ('chat.js', 'text/javascript'),
    **{'/landing-assets/' + name + '.webp': ('landing-assets/' + name + '.webp', 'image/webp')
       for name in ('chat', 'evidence', 'map', 'letter', 'profile')},
}
MAP_SCRIPTS = ('people-map-model.js', 'people-map-layout.js', 'people-map-graph.js', 'people-map.js')
DEFERRED_ASSETS = ('landing.js', 'landing-map-preview.js', 'recommendation-map.js', *MAP_SCRIPTS)


def landing_variant(query_string):
    """Only the two explicitly requested query values enable the prototype."""
    values = parse_qs(query_string, keep_blank_values=True).get('landing')
    return 'people' if values == [''] else 'map' if values == ['map'] else None


def _asset(path, body, mime):
    return StaticAsset(path, body, body, mime, hashlib.sha256(body).hexdigest()[:10])


def home_script_variant(asset):
    """Disable just the old downward-navigation gesture for opt-in documents."""
    old = b'const ownScroll = target => !isHome()'
    if asset.body.count(old) != 1:
        raise ValueError('Home scroll hook changed; review the opt-in landing variant')
    body = asset.body.replace(old, b'const ownScroll = target => Boolean(body.dataset.landing) || !isHome()', 1)
    return _asset('/landing-home.js', body, asset.mime)


def chat_script_variant(asset):
    """Await the deferred graph factories before the existing recommendation import, and keep the
    welcome page at its top: the chat's follow-the-thread scroll would otherwise jump to the landing's end."""
    old = b"import('/recommendation-map.js')"
    follow = b'if(autoScroll&&!briefEditor)window.scrollTo'
    if asset.body.count(old) != 1 or asset.body.count(follow) != 1:
        raise ValueError('Recommendation import or thread scroll changed; review the opt-in landing variant')
    body = asset.body.replace(old, b'window.Landing.loadRecommendation()', 1)
    body = body.replace(follow, b'if(autoScroll&&!briefEditor&&!document.body.classList.contains("home-welcome"))window.scrollTo', 1)
    return _asset('/landing-chat.js', body, asset.mime)


def landing_document(asset, variant, web, static_assets):
    """Compose from current home bytes without writing or rewriting its source."""
    source = asset.body.decode('utf-8')
    newline = '\r\n' if b'\r\n' in asset.body else '\n'
    home_script = home_script_variant(static_assets.read('/home-cosmos.js'))
    home_url = '/landing-home.js?v=' + home_script.version
    source, count = re.subn(r'(<script\b[^>]*\bsrc=")/home-cosmos\.js(?:\?[^"<>]*)?("[^>]*></script>)',
                            lambda match: match[1] + home_url + match[2], source, count=1)
    if count != 1:
        raise ValueError('Home script registration changed; review landing composition')
    chat_script = chat_script_variant(static_assets.read('/chat.js'))
    chat_url = '/landing-chat.js?v=' + chat_script.version
    boot = html.escape(static_assets.versioned_url('/landing-boot.js', '/'), quote=True)
    source, count = re.subn(r'(<script\b[^>]*\bsrc=")/chat\.js(?:\?[^"<>]*)?("[^>]*></script>)',
                            lambda match: '<script src="' + boot + '" defer></script>' + match[1] + chat_url + match[2], source, count=1)
    if count != 1:
        raise ValueError('Chat script registration changed; review landing composition')
    for name in MAP_SCRIPTS:
        source = re.sub(r'<script\b[^>]*\bsrc="/' + re.escape(name) + r'(?:\?[^"<>]*)?"[^>]*></script>', '', source)
    urls = {'/' + name: static_assets.versioned_url('/' + name, '/') for name in DEFERRED_ASSETS}
    attrs = ' data-landing="' + variant + '" data-landing-assets="' + html.escape(json.dumps(urls), quote=True) + '"'
    source = source.replace('<body class="', '<body' + attrs + ' class="home-landing ', 1)
    css = html.escape(static_assets.versioned_url('/landing.css', '/'), quote=True)
    source = source.replace('</head>', '<link rel="stylesheet" href="' + css + '"></head>', 1)
    down = ('<a id="landingDown" class="landing-down" href="#landingFeatures" aria-label="소개 보기">'
            '<span aria-hidden="true">⌄</span></a>')
    fragment = (web / 'landing.html').read_bytes().decode('utf-8')
    if variant == 'map':
        fragment = fragment.replace('id="landingPeople"', 'id="landingPeople" hidden', 1)
        fragment = fragment.replace('aria-labelledby="landingMapTitle" hidden', 'aria-labelledby="landingMapTitle"', 1)
    # HTML remains in source order: welcome, introduction, and existing dialogs.
    source = source.replace('</main></div>', down + newline + '</main></div>' + newline + fragment, 1)
    return _asset('/?landing=' + variant, source.encode('utf-8'), asset.mime)


def capability_document(asset, static_assets):
    """Register an address-to-existing-map adapter only on a capability link."""
    url = html.escape(static_assets.versioned_url('/landing-map-link.js', '/explore'), quote=True)
    body = asset.body.replace(b'</head>', ('<script src="' + url + '" defer></script></head>').encode(), 1)
    return _asset('/explore?capability', body, asset.mime)


def build_landing_people_map(engine):
    """Small public-person projection, requested only after the introduction enters view."""
    corpus = engine.corpus
    categories = build_capabilities(corpus)
    people = []
    for person in corpus.people.values():
        profile = person.profile
        portrait = profile.get('portrait') or {}
        if (person.id.startswith('LOCAL-') or person.virtual or not profile.get('curated')
                or profile.get('source_type') in ('self_reported', 'provided_resume')
                or not isinstance(portrait.get('path'), str)
                or not re.fullmatch(r'/portraits/[A-Za-z0-9_-]+\.(?:png|jpe?g|webp)', portrait['path'])):
            continue
        public_profile = {key: profile[key] for key in ('display_name',) if key in profile}
        public_profile['portrait'] = {'path': portrait['path']}
        field = profile.get('field_label') or profile.get('research_field')
        if not isinstance(field, str) or not field.strip():
            field = next((category['label'] for category in categories
                          if any(link['id'] == person.id for link in category['people'])), '')
        people.append({'id': person.id, 'name': person.name, 'profile': public_profile, 'field_label': field})
    public_ids = {person['id'] for person in people}
    return {
        'schema_version': 'people-map-landing-v1',
        'people': people,
        'capabilities': [
            {'id': category['id'], 'label': category['label'],
             'people': [{'id': link['id']} for link in category['people'] if link['id'] in public_ids]}
            for category in categories
        ],
    }
