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
from .attachments import AttachmentError, MAX_UPLOAD_BODY, MAX_HTTPS_BODY
from .https_documents import FetchError
from .gemma_bridge import GemmaRelay
from .conversation import Conversation
from .model_conversation import ModelResponseUnavailable, ModelResponseBudgetExhausted, ScoutSourceChanged
from .discovery import DiscoveryError
from .data import Corpus, ROOT
from .engine import Engine
from .models import ExternalModel
from .hosted_demo import HostedDemoPolicy
from .llm_runtime import RuntimeLegacyModel
from .model_conversation import ObservedRuntimeChatModels
from .service import Service, ProviderScopeError
from .storage import StateStore
from .people_map import build_people_map
from .diagnostics import DiagnosticAuth, Diagnostics, OperationalDiagnostics, attachment_client_metadata, scope as diagnostic_scope
from .profiles import Profiles, ProfileError
from .auth_service import AuthService, AuthError, AUTHORIZATION, strict_json
from .profile_chat import ProfileChat
from .scout_projection import project_session

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
    '/ui-previews/CAPABILITY-GRAPH/r1/': {
        '': ('index.html', 'text/html; charset=utf-8'),
        'assets/arnold.png': ('assets/arnold.png', 'image/png'),
        'assets/gs-ali-erdemir.png': ('assets/gs-ali-erdemir.png', 'image/png'),
        'assets/gs-geoffrey-w-coates.png': ('assets/gs-geoffrey-w-coates.png', 'image/png'),
        'assets/gs-gerhard-ertl.png': ('assets/gs-gerhard-ertl.png', 'image/png'),
        'assets/gs-hugh-spikes.png': ('assets/gs-hugh-spikes.png', 'image/png'),
        'assets/gs-ignacio-e-grossmann.png': ('assets/gs-ignacio-e-grossmann.png', 'image/png'),
        'assets/gs-jens-kehlet-norskov.png': ('assets/gs-jens-kehlet-norskov.png', 'image/png'),
        'assets/gs-jeong-young-park.png': ('assets/gs-jeong-young-park.png', 'image/png'),
        'assets/gs-john-f-hartwig.png': ('assets/gs-john-f-hartwig.png', 'image/png'),
        'assets/gs-krzysztof-matyjaszewski.png': ('assets/gs-krzysztof-matyjaszewski.png', 'image/png'),
        'assets/gs-omar-m-yaghi.png': ('assets/gs-omar-m-yaghi.png', 'image/png'),
        'assets/gs-robert-h-grubbs.png': ('assets/gs-robert-h-grubbs.png', 'image/png'),
        'assets/gs-ryong-ryoo.png': ('assets/gs-ryong-ryoo.png', 'image/png'),
        'assets/gs-sankar-nair.png': ('assets/gs-sankar-nair.png', 'image/png'),
        'assets/gs-susumu-kitagawa.png': ('assets/gs-susumu-kitagawa.png', 'image/png'),
        'assets/gs-venkat-venkatasubramanian.png': ('assets/gs-venkat-venkatasubramanian.png', 'image/png'),
        'assets/gs-yang-shao-horn.png': ('assets/gs-yang-shao-horn.png', 'image/png'),
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
        'graph.js': ('graph.js', 'text/javascript; charset=utf-8'),
        'index.html': ('index.html', 'text/html; charset=utf-8'),
        'model.js': ('model.js', 'text/javascript; charset=utf-8'),
        'styles.css': ('styles.css', 'text/css; charset=utf-8'),
    },
    '/ui-previews/CAPABILITY-PROPOSALS/r2/': {
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
    '/ui-previews/CI-FONTS/r1/': {
        '': ('index.html', 'text/html; charset=utf-8'),
        'app.js': ('app.js', 'text/javascript; charset=utf-8'),
        'credits.html': ('credits.html', 'text/html; charset=utf-8'),
        'fonts.css': ('fonts.css', 'text/css; charset=utf-8'),
        'fonts/a-en.woff2': ('fonts/a-en.woff2', 'font/woff2'),
        'fonts/a-ko.woff2': ('fonts/a-ko.woff2', 'font/woff2'),
        'fonts/b-en.woff2': ('fonts/b-en.woff2', 'font/woff2'),
        'fonts/b-ko.woff2': ('fonts/b-ko.woff2', 'font/woff2'),
        'fonts/c-en.woff2': ('fonts/c-en.woff2', 'font/woff2'),
        'fonts/c-ko.woff2': ('fonts/c-ko.woff2', 'font/woff2'),
        'fonts/d-en.woff2': ('fonts/d-en.woff2', 'font/woff2'),
        'fonts/d-ko.woff2': ('fonts/d-ko.woff2', 'font/woff2'),
        'fonts/e-en.woff2': ('fonts/e-en.woff2', 'font/woff2'),
        'fonts/e-ko.woff2': ('fonts/e-ko.woff2', 'font/woff2'),
        'fonts/f-en.woff2': ('fonts/f-en.woff2', 'font/woff2'),
        'fonts/f-ko.woff2': ('fonts/f-ko.woff2', 'font/woff2'),
        'index.html': ('index.html', 'text/html; charset=utf-8'),
        'licenses/archivo-OFL.txt': ('licenses/archivo-OFL.txt', 'text/plain; charset=utf-8'),
        'licenses/blackhansans-OFL.txt': ('licenses/blackhansans-OFL.txt', 'text/plain; charset=utf-8'),
        'licenses/cormorantgaramond-OFL.txt': ('licenses/cormorantgaramond-OFL.txt', 'text/plain; charset=utf-8'),
        'licenses/dmsans-OFL.txt': ('licenses/dmsans-OFL.txt', 'text/plain; charset=utf-8'),
        'licenses/gothica1-OFL.txt': ('licenses/gothica1-OFL.txt', 'text/plain; charset=utf-8'),
        'licenses/gowunbatang-OFL.txt': ('licenses/gowunbatang-OFL.txt', 'text/plain; charset=utf-8'),
        'licenses/gowundodum-OFL.txt': ('licenses/gowundodum-OFL.txt', 'text/plain; charset=utf-8'),
        'licenses/ibmplexsans-OFL.txt': ('licenses/ibmplexsans-OFL.txt', 'text/plain; charset=utf-8'),
        'licenses/ibmplexsanskr-OFL.txt': ('licenses/ibmplexsanskr-OFL.txt', 'text/plain; charset=utf-8'),
        'licenses/librebaskerville-OFL.txt': ('licenses/librebaskerville-OFL.txt', 'text/plain; charset=utf-8'),
        'licenses/notoserifkr-OFL.txt': ('licenses/notoserifkr-OFL.txt', 'text/plain; charset=utf-8'),
        'licenses/spacegrotesk-OFL.txt': ('licenses/spacegrotesk-OFL.txt', 'text/plain; charset=utf-8'),
        'mark.svg': ('mark.svg', 'image/svg+xml'),
        'orbit.css': ('orbit.css', 'text/css; charset=utf-8'),
        'orbit.html': ('orbit.html', 'text/html; charset=utf-8'),
        'orbit.js': ('orbit.js', 'text/javascript; charset=utf-8'),
        'style.css': ('style.css', 'text/css; charset=utf-8'),
    },
    '/ui-previews/CI-FONTS/r2/': {
        '': ('index.html', 'text/html; charset=utf-8'),
        'app.js': ('app.js', 'text/javascript; charset=utf-8'),
        'fonts/c-en.woff2': ('fonts/c-en.woff2', 'font/woff2'),
        'fonts/c-ko.woff2': ('fonts/c-ko.woff2', 'font/woff2'),
        'fonts/h1.woff2': ('fonts/h1.woff2', 'font/woff2'),
        'fonts/h2.woff2': ('fonts/h2.woff2', 'font/woff2'),
        'fonts/h3.woff2': ('fonts/h3.woff2', 'font/woff2'),
        'fonts/h4.woff2': ('fonts/h4.woff2', 'font/woff2'),
        'fonts/h5.woff2': ('fonts/h5.woff2', 'font/woff2'),
        'fonts.css': ('fonts.css', 'text/css; charset=utf-8'),
        'index.html': ('index.html', 'text/html; charset=utf-8'),
        'licenses/bodonimoda-OFL.txt': ('licenses/bodonimoda-OFL.txt', 'text/plain; charset=utf-8'),
        'licenses/cormorantgaramond-OFL.txt': ('licenses/cormorantgaramond-OFL.txt', 'text/plain; charset=utf-8'),
        'licenses/ebgaramond-OFL.txt': ('licenses/ebgaramond-OFL.txt', 'text/plain; charset=utf-8'),
        'licenses/gowunbatang-OFL.txt': ('licenses/gowunbatang-OFL.txt', 'text/plain; charset=utf-8'),
        'licenses/librebaskerville-OFL.txt': ('licenses/librebaskerville-OFL.txt', 'text/plain; charset=utf-8'),
        'licenses/spacegrotesk-OFL.txt': ('licenses/spacegrotesk-OFL.txt', 'text/plain; charset=utf-8'),
        'mark.svg': ('mark.svg', 'image/svg+xml'),
        'motion.js': ('motion.js', 'text/javascript; charset=utf-8'),
        'style.css': ('style.css', 'text/css; charset=utf-8'),
    },
    '/ui-previews/CI-FONTS/r3/': {
        '': ('index.html', 'text/html; charset=utf-8'),
        'app.js': ('app.js', 'text/javascript; charset=utf-8'),
        'fonts/c-en.woff2': ('fonts/c-en.woff2', 'font/woff2'),
        'fonts/c-ko.woff2': ('fonts/c-ko.woff2', 'font/woff2'),
        'fonts/h5.woff2': ('fonts/h5.woff2', 'font/woff2'),
        'fonts.css': ('fonts.css', 'text/css; charset=utf-8'),
        'index.html': ('index.html', 'text/html; charset=utf-8'),
        'licenses/gowunbatang-OFL.txt': ('licenses/gowunbatang-OFL.txt', 'text/plain; charset=utf-8'),
        'licenses/librebaskerville-OFL.txt': ('licenses/librebaskerville-OFL.txt', 'text/plain; charset=utf-8'),
        'licenses/spacegrotesk-OFL.txt': ('licenses/spacegrotesk-OFL.txt', 'text/plain; charset=utf-8'),
        'mark.svg': ('mark.svg', 'image/svg+xml'),
        'motion.js': ('motion.js', 'text/javascript; charset=utf-8'),
        'style.css': ('style.css', 'text/css; charset=utf-8'),
    },
    '/ui-previews/CI-FONTS/r4/': {
        '': ('index.html', 'text/html; charset=utf-8'),
        'app.js': ('app.js', 'text/javascript; charset=utf-8'),
        'fonts/c-en.woff2': ('fonts/c-en.woff2', 'font/woff2'),
        'fonts/c-ko.woff2': ('fonts/c-ko.woff2', 'font/woff2'),
        'fonts/h5.woff2': ('fonts/h5.woff2', 'font/woff2'),
        'fonts.css': ('fonts.css', 'text/css; charset=utf-8'),
        'index.html': ('index.html', 'text/html; charset=utf-8'),
        'licenses/gowunbatang-OFL.txt': ('licenses/gowunbatang-OFL.txt', 'text/plain; charset=utf-8'),
        'licenses/librebaskerville-OFL.txt': ('licenses/librebaskerville-OFL.txt', 'text/plain; charset=utf-8'),
        'licenses/spacegrotesk-OFL.txt': ('licenses/spacegrotesk-OFL.txt', 'text/plain; charset=utf-8'),
        'mark.svg': ('mark.svg', 'image/svg+xml'),
        'motion.js': ('motion.js', 'text/javascript; charset=utf-8'),
        'orbit.css': ('orbit.css', 'text/css; charset=utf-8'),
        'orbit.html': ('orbit.html', 'text/html; charset=utf-8'),
        'orbit.js': ('orbit.js', 'text/javascript; charset=utf-8'),
        'style.css': ('style.css', 'text/css; charset=utf-8'),
        'theme.css': ('theme.css', 'text/css; charset=utf-8'),
        'theme.js': ('theme.js', 'text/javascript; charset=utf-8'),
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
            option = self.gemini_option()
            if option: items.append(option)
            return {'models':items,'default':option['id'] if option else ('bridge' if items[0]['enabled'] else 'guide'),'public':True}
        items = [{'id': p, 'provider': p, 'name': label + ' · ' + c['model'],
                  'enabled': True, 'local': False, 'vision': False}
                 for p, label in [('openai', 'OpenAI API'), ('claude', 'Claude API')]
                 if (c := self.configs.get(p))]
        if not items:
            items = [{'id': 'guide', 'provider': 'guide', 'name': '기록 탐색 안내 · AI 미사용',
                      'enabled': True, 'local': False, 'vision': False}]
        default = items[0]['id']
        option = self.gemini_option()
        if option: items.append(option)
        return {'models': items, 'default': option['id'] if option else default, 'public': True}

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


class _VisitorStream:
    """Release admission once; lifecycle metadata is not a delivery acknowledgement."""
    def __init__(self, iterator, first, release, *, observe=None, request_id=None):
        self.iterator=iterator
        self.events=itertools.chain([first],iterator)
        self.release=release
        self.observe=observe
        self.request_id=request_id
        self.closed=False
        self.started=time.monotonic()
        self.terminal_yielded=False
        self.first_delta=False
        self.phase=None
        self.close_reason='closed'

    def _emit(self, kind, **metadata):
        if self.observe is not None:
            try:self.observe({'event_type':kind,'elapsed_ms':round((time.monotonic()-self.started)*1000),**metadata})
            except Exception:pass

    def __iter__(self):return self

    def __next__(self):
        if self.closed:raise StopIteration
        try:
            event=next(self.events)
            if isinstance(event,dict) and 'session' in event:
                event={**event,'session':project_session(event['session'])}
            if isinstance(event,dict) and event.get('type')=='start' and self.request_id:
                event={**event,'request_id':self.request_id}
            raw=(json.dumps(event,ensure_ascii=False)+'\n').encode()
            if isinstance(event,dict):
                session=event.get('session') or {}
                identity={'session_id':session.get('id')} if isinstance(session,dict) else {}
                kind=event.get('type')
                if kind=='start':self._emit('stream_started',**identity)
                elif kind=='phase' and event.get('phase')!=self.phase:
                    self.phase=event.get('phase');self._emit('stream_phase',phase=self.phase)
                elif kind=='delta' and not self.first_delta:
                    self.first_delta=True;self._emit('stream_first_delta')
                elif kind in ('done','error'):
                    self.terminal_yielded=True
                    self._emit('stream_terminal_yielded',terminal_type=kind,terminal_yielded=True,**identity)
            return raw
        except StopIteration:
            self.close_reason='eof'
            self._emit('stream_eof',eof=True,terminal_yielded=self.terminal_yielded)
            self.close()
            raise
        except BaseException:
            self.close_reason='iteration_error'
            self._emit('stream_error',error_kind='stream_iteration_failed',failure_stage='stream')
            self.close()
            raise

    def close(self):
        if not self.closed:
            self.closed=True
            try:self.iterator.close()
            except BaseException:
                self.close_reason='cleanup_error'
                self._emit('stream_error',error_kind='stream_cleanup_failed',failure_stage='stream')
                raise
            finally:
                try:self.release()
                finally:self._emit('stream_closed',close_reason=self.close_reason,terminal_yielded=self.terminal_yielded)


class PublicApp:
    def __init__(self, state_dir=None, env=None, include_personal=None):
        self.env = dict(os.environ if env is None else env)
        self.hosted_demo_policy = HostedDemoPolicy(self.env) if self.env.get('APP_RUNTIME') == 'hosted_demo' else None
        self.directory = Path(state_dir or self.env.get('RNDPLZ_STATE_DIR', ROOT / 'out' / 'public-state'))
        self.directory.mkdir(parents=True, exist_ok=True)
        self.secret = self.env.get('RNDPLZ_SESSION_SECRET', '').encode() or secrets.token_bytes(32)
        self.secure = self.hosted_demo_policy is not None or self.env.get('RNDPLZ_LOCAL_PREVIEW') != '1'
        self.allowed_hosts = set(filter(None, self.env.get('RNDPLZ_ALLOWED_HOSTS', '').split(',')))
        if self.env.get('RENDER_EXTERNAL_HOSTNAME'):
            self.allowed_hosts.add(self.env['RENDER_EXTERNAL_HOSTNAME'])
        self.allowed_hosts.update({'127.0.0.1', 'localhost'})
        self.origin = self.hosted_demo_policy.origin if self.hosted_demo_policy is not None else self.env.get('RNDPLZ_PUBLIC_ORIGIN', '').rstrip('/')
        if self.hosted_demo_policy is not None:
            self.allowed_hosts.add(self.hosted_demo_policy.authority.split(':')[0])
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
        self.models = ObservedRuntimeChatModels(self.env) if self.env.get('APP_RUNTIME') in ('hosted_demo', 'hosted_public') else PublicModels(self.env)
        self.diagnostic_auth=DiagnosticAuth({}, None) if self.hosted_demo_policy is not None else DiagnosticAuth(self.env,Path(__file__).with_name('diagnostic_auth.json'))
        self.diagnostics=Diagnostics(self.directory/'diagnostics') if self.diagnostic_auth.enabled else None
        if self.diagnostics is not None:self.diagnostics.mark_interrupted()
        self.observation = (OperationalDiagnostics(self.diagnostics, provider=self.models.runtime.config.provider,
                            model=self.models.runtime.config.model) if self.env.get('APP_RUNTIME') in ('hosted_public','hosted_demo') else self.diagnostics)
        # A startup file fingerprint is provenance metadata, not a memory attestation.
        tracked=('conversation.py','public_web.py','gemma_bridge.py','chat_models.py','chat_actions.py','discovery.py','diagnostics.py',
                 'model_dialogue.py','evidence_search.py','model_conversation.py','scout_projection.py',
                 'auth_service.py','account_storage.py','profiles.py','service.py','gemini_native.py','llm_runtime.py','responses_stream.py','llm_budget.py','owner_budget_gate.py')
        if self.hosted_demo_policy is not None:
            tracked += ('hosted_demo.py',)
        fingerprint=hashlib.sha256()
        for name in tracked:
            fingerprint.update(name.encode());fingerprint.update(Path(__file__).with_name(name).read_bytes())
        revision=self.env.get('RENDER_GIT_COMMIT','')
        self.diagnostic_runtime={'code_fingerprint':fingerprint.hexdigest(),
                                 'deployment_revision':revision if re.fullmatch(r'[a-f0-9]{40}',revision) else None,
                                 'raw_state_retention':'existing_state_unchanged',
                                 'storage_lifetime':'ephemeral_platform_storage; export_before_deploy'}
        self.auth = AuthService(reason='hosted_demo_disabled') if self.hosted_demo_policy is not None else AuthService.from_env(self.env)
        self.contexts = {}
        self.lock = threading.RLock()
        self.request_slots = threading.BoundedSemaphore(4)
        self.images = {p.profile['portrait']['path'] for p in corpus.people.values() if p.profile.get('portrait')}
        self.images.update(p.profile['portrait']['background'] for p in corpus.people.values() if p.profile.get('portrait', {}).get('background'))
        # Derivatives come only from a scoped person's portrait, never a background.
        for person in corpus.people.values():
            asset = person.profile.get('portrait', {}).get('path')
            if isinstance(asset, str) and re.fullmatch(r'/portraits/[A-Za-z0-9_.-]+\.(?:png|jpe?g|webp)', asset):
                stem = asset.rsplit('.', 1)[0]
                self.images.update(stem + '-' + size + '.webp' for size in ('thumb', 'detail'))

    def _runtime_legacy_model(self, directory):
        if self.env.get('APP_RUNTIME') in ('hosted_demo', 'hosted_public'):
            return RuntimeLegacyModel(self.models.runtime, audit_path=directory / 'model-events.jsonl')
        return ExternalModel(env={})

    def signature(self, value):
        return hmac.new(self.secret, value.encode(), hashlib.sha256).hexdigest()

    def _revoked(self, sid):
        # The signed cookie identifies one existing visitor directory. Keeping a
        # tombstone prevents an old cookie from restoring that visitor on restart.
        return StateStore(self.directory / sid, env=self.env).is_revoked()

    def _expired_cookie(self):
        return ('rndplz_visitor=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0; '
                'Expires=Thu, 01 Jan 1970 00:00:00 GMT' + ('; Secure' if self.secure else ''))

    def _logout(self, context):
        with self.lock:
            if context['inflight'] != 1 or context['active']:
                return False
            if context.get('session_mode') == 'account':
                # Account store and logout serialize against the same session row.
                self.auth.logout(context['_account_cookie'], context['token'])
                context['revoked'] = True
                self.contexts.pop(context['sid'], None)
                return True
            if not context['service'].store.revoke():
                return False
            context['revoked'] = True
            self.contexts.pop(context['sid'], None)
        return True

    @staticmethod
    def _account_cookie(environ, name):
        raw = environ.get('HTTP_COOKIE', '')
        # Reject ambiguous same-name cookies rather than choosing client order.
        entries = [piece.strip() for piece in raw.split(';')
                   if piece.strip().split('=', 1)[0] == name]
        if len(entries) > 1:
            raise AuthError('account_cookie_ambiguous', 401)
        if not entries:
            return None
        cookie = SimpleCookie()
        try:
            cookie.load(entries[0])
            value = cookie[name].value
        except Exception:
            raise AuthError('account_cookie_invalid', 401) from None
        if not value or len(value) > 2048:
            raise AuthError('account_cookie_invalid', 401)
        return value

    @staticmethod
    def _account_cookie_header(name, value='', max_age=0):
        # Only opaque server-issued values enter Set-Cookie, never query data.
        if value and not re.fullmatch(r'[A-Za-z0-9_-]{20,200}', value):
            raise AuthError('account_cookie_shape', 503)
        result = name + '=' + value + '; Path=/; Secure; HttpOnly; SameSite=Lax; Max-Age=' + str(max_age)
        if not value:
            result += '; Expires=Thu, 01 Jan 1970 00:00:00 GMT'
        return result

    @staticmethod
    def _public_account(account):
        return {key: account[key] for key in ('id', 'display_name', 'email')}

    def _account_status(self, context, environ):
        account = context.get('account')
        login_available = self.auth.login_available
        # An expired account cookie never supplies a new visitor CSRF for writes.
        try:
            has_account_cookie = self._account_cookie(environ, self.auth.SESSION_COOKIE_NAME) is not None
        except AuthError:
            has_account_cookie = True
        return {'enabled': self.auth.enabled, 'authenticated': account is not None,
                'account': self._public_account(account) if account else None,
                'login_url': '/auth/google/start' if login_available else None,
                'enrollment_enabled': self.auth.enabled and self.auth.enrollment_enabled,
                'enrollment_url': '/auth/google/enroll' if self.auth.enabled and self.auth.enrollment_enabled else None,
                'disabled_reason': ('Google 로그인이 아직 설정되지 않았습니다. 방문자로 계속 이용할 수 있습니다.' if not self.auth.enabled else
                                    '초대 코드를 받아 최초 가입 화면에서 먼저 가입해 주세요.' if not login_available else None),
                'token': context['token'] if account or not has_account_cookie else None}

    def _account_context(self, environ):
        if self.hosted_demo_policy is not None:
            return None
        protected = (environ.get('REQUEST_METHOD') == 'POST' or
                     environ.get('PATH_INFO', '').startswith('/api/self-profile') or
                     environ.get('PATH_INFO', '') == '/api/account/mole')
        try:
            cookie = self._account_cookie(environ, self.auth.SESSION_COOKIE_NAME)
        except AuthError:
            if protected:
                raise
            return None
        if cookie is None:
            return None
        principal = self.auth.authenticate(cookie)
        if principal is None:
            if protected:
                raise AuthError('account_session_expired', 401)
            return None
        account = principal['account']
        # The key identifies this opaque login session, not every login to the account.
        sid = 'account-' + hashlib.sha256(cookie.encode('utf-8')).hexdigest()
        with self.lock:
            now = time.monotonic()
            if sid not in self.contexts:
                for key, item in list(self.contexts.items()):
                    if now - item['used'] > 3600 and item['active'] == 0 and item['inflight'] == 0:
                        del self.contexts[key]
                if len(self.contexts) >= 128:
                    raise AuthError('account_busy', 429)
                service = Service(self.engine, self.directory / sid, self._runtime_legacy_model(self.directory / sid), state_env=self.env)
                store = self.auth.profile_store(account['id'], session_cookie=cookie)
                profile = Profiles(store, public=True, account={key: account[key]
                    for key in ('id', 'verified', 'storage_lifetime')})
                self.contexts[sid] = {'service': service, 'chat': Conversation(service, self.models),
                    'profile': profile, 'account': account, 'session_mode': 'account',
                    '_account_cookie': cookie, 'token': principal['csrf'], 'used': now,
                    'active': 0, 'requests': [], 'sid': sid, 'inflight': 0, 'revoked': False,
                    'visitor_ref': self.signature('diagnostic:' + sid)}
            context = self.contexts[sid]
            context.update(account=account, token=principal['csrf'], used=now)
        return context

    def _google_login(self, environ, path, method, send, headers):
        if method != 'GET':
            return send(405, {'error': '로그인 이동은 GET 요청으로만 처리합니다.'})
        try:
            query = parse_qs(environ.get('QUERY_STRING', ''), keep_blank_values=True)
            if any(len(value) != 1 for value in query.values()):
                raise AuthError('login_query_ambiguous', 400)
            if path == '/auth/google/start':
                if query:
                    raise AuthError('login_query_invalid', 400)
                # Normal same-site menu navigation has no X-CSRF or Origin header.
                flow = self.auth.begin_login('/')
                if not flow['authorization_url'].startswith(AUTHORIZATION + '?'):
                    raise AuthError('login_destination_invalid', 503)
                headers.append(('Set-Cookie', self._account_cookie_header(
                    self.auth.LOGIN_COOKIE_NAME, flow['login_cookie'], flow['cookie_max_age'])))
                headers.append(('Location', flow['authorization_url']))
                return send(303, b'', 'text/plain; charset=utf-8')
            if 'error' in query:
                if query.get('state', [''])[0]:
                    self.auth.cancel_login(query['state'][0], self._account_cookie(environ, self.auth.LOGIN_COOKIE_NAME))
                raise AuthError('google_login_not_completed', 403)
            if not query.get('code', [''])[0] or not query.get('state', [''])[0]:
                raise AuthError('login_query_invalid', 400)
            login_cookie = self._account_cookie(environ, self.auth.LOGIN_COOKIE_NAME)
            try:
                previous_cookie = self._account_cookie(environ, self.auth.SESSION_COOKIE_NAME)
            except AuthError:
                previous_cookie = None
            # A malformed/expired prior cookie cannot prevent a fresh valid login.
            if previous_cookie and self.auth.authenticate(previous_cookie) is None:
                previous_cookie = None
            result = self.auth.finish(query['code'][0], query['state'][0], login_cookie, previous_cookie)
            if previous_cookie:
                old_key = 'account-' + hashlib.sha256(previous_cookie.encode('utf-8')).hexdigest()
                with self.lock:
                    previous = self.contexts.pop(old_key, None)
                    if previous is not None:
                        previous['revoked'] = True
            headers.append(('Set-Cookie', self._account_cookie_header(
                self.auth.SESSION_COOKIE_NAME, result['session_cookie'], 86400)))
            headers.append(('Set-Cookie', self._account_cookie_header(self.auth.LOGIN_COOKIE_NAME)))
            headers.append(('Set-Cookie', self._expired_cookie()))
            headers.append(('Location', '/?account_changed=1'))
            return send(303, b'', 'text/plain; charset=utf-8')
        except AuthError as exc:
            headers.append(('Set-Cookie', self._account_cookie_header(self.auth.LOGIN_COOKIE_NAME)))
            return send(exc.status, {'error': str(exc), 'code': exc.code})
        except Exception:
            headers.append(('Set-Cookie', self._account_cookie_header(self.auth.LOGIN_COOKIE_NAME)))
            return send(503, {'error': '계정 인증을 지금 처리할 수 없습니다. 잠시 후 다시 시도해 주세요.', 'code': 'account_service_unavailable'})

    def visitor(self, environ):
        account = self._account_context(environ)
        if account is not None:
            return account, None
        cookie = SimpleCookie()
        try:
            cookie.load(environ.get('HTTP_COOKIE', ''))
            value = cookie.get('rndplz_visitor').value if cookie.get('rndplz_visitor') else ''
        except Exception:
            value = ''
        parts = value.split('.')
        valid = len(parts) == 3 and re.fullmatch('[a-f0-9]{32}', parts[0]) and parts[1].isdigit()
        valid = valid and 0 <= time.time() - int(parts[1]) < 86400 and hmac.compare_digest(parts[2], self.signature('.'.join(parts[:2])))
        with self.lock:
            if not valid or self._revoked(parts[0]):
                value = secrets.token_hex(16) + '.' + str(int(time.time()))
                value += '.' + self.signature(value)
            sid = value.split('.')[0]
            now = time.monotonic()
            if sid not in self.contexts:
                # Only discard idle in-memory handles; never touch another visitor's files.
                for key, item in list(self.contexts.items()):
                    if now - item['used'] > 3600 and item['active'] == 0 and item['inflight'] == 0:
                        del self.contexts[key]
                if len(self.contexts) >= 128:
                    raise ValueError('현재 접속자가 많습니다. 잠시 후 다시 시도해 주세요.')
                service = Service(self.engine, self.directory / sid, self._runtime_legacy_model(self.directory / sid), state_env=self.env)
                self.contexts[sid] = {'service': service, 'chat': Conversation(service, self.models), 'profile': Profiles(service.store, public=True),
                                      'token': self.signature('csrf:' + sid), 'used': now, 'active': 0, 'requests': [],
                                      'sid': sid, 'inflight': 0, 'revoked': False,
                                      'visitor_ref':self.signature('diagnostic:' + sid)}
            context = self.contexts[sid]
            context['used'] = now
        return context, 'rndplz_visitor=' + value + '; Path=/; HttpOnly; SameSite=Lax; Max-Age=86400' + ('; Secure' if self.secure else '')

    def _diagnostic_observe(self, metadata, content=None):
        if self.observation is None:return
        try:self.observation.record(metadata,content)
        except Exception:
            try:
                with self.diagnostics.lock:self.diagnostics._problem('write_errors','diagnostic_callback_failed')
            except Exception:pass

    def _recovery_report(self, context, chat, payload, send, probe):
        allowed={'session_id','turn_id','request_id','outcome','error_kind','http_status','elapsed_ms','poll_count'}
        if (set(payload)-allowed or not {'session_id','turn_id','outcome'}<=set(payload)
                or any(not isinstance(payload.get(k),str) or not re.fullmatch(r'[A-Za-z0-9-]{16,80}',payload[k]) for k in ('session_id','turn_id'))
                or payload['outcome'] not in ('stream_interrupted','recovered','pending','unavailable')):
            return send(400,{'error':'회복 관측 형식을 확인해 주세요.','code':'recovery_report_invalid'})
        if 'error_kind' in payload and payload['error_kind'] not in ('eof','aborted','stream_error','http','network','timeout','invalid_response'):
            return send(400,{'error':'회복 관측 형식을 확인해 주세요.','code':'recovery_report_invalid'})
        for key,lower,upper in (('elapsed_ms',0,3600000),('poll_count',0,100),('http_status',100,599)):
            if key in payload and (type(payload[key]) is not int or not lower<=payload[key]<=upper):
                return send(400,{'error':'회복 관측 형식을 확인해 주세요.','code':'recovery_report_invalid'})
        request_id=payload.get('request_id')
        if request_id is not None and (not isinstance(request_id,str) or not re.fullmatch('[a-f0-9]{32}',request_id)):
            return send(400,{'error':'회복 관측 형식을 확인해 주세요.','code':'recovery_report_invalid'})
        session=chat.get(payload['session_id'])
        if not any(m.get('role')=='user' and m.get('turn_id')==payload['turn_id'] for m in session.get('messages',[])):
            return send(403,{'error':'현재 방문자의 요청만 확인할 수 있습니다.','code':'recovery_report_scope'})
        probe['session_verified']=True
        with self.lock:
            now=time.monotonic()
            reports=[t for t in context.get('recovery_reports',[]) if now-t<60]
            if len(reports)>=6:return send(429,{'error':'상태 확인 보고가 많습니다. 잠시 후 확인해 주세요.','code':'recovery_report_rate'})
            if request_id is not None and context.get('request_refs',{}).get(request_id)!=(payload['session_id'],payload['turn_id']):
                return send(400,{'error':'회복 관측의 요청 연결을 확인해 주세요.','code':'recovery_report_request'})
            probe['request_verified']=request_id is not None
            context['recovery_reports']=[*reports,now]
        meta={k:payload[k] for k in ('outcome','elapsed_ms','poll_count','http_status') if k in payload}
        if 'error_kind' in payload:meta['client_error_kind']=payload['error_kind']
        self._diagnostic_observe({**probe,**meta,'event_type':'client_recovery_report'})
        return send(200,{'ok':True})

    def _attachment_client_report(self, context, payload, send, request_id):
        # The existing visitor/CSRF/Origin and global POST budget run before this method.
        # Share the six-per-minute report allowance with recovery reports, including invalid attempts.
        with self.lock:
            now=time.monotonic()
            reports=[t for t in context.get('recovery_reports',[]) if now-t<60]
            if len(reports)>=6:
                return send(429,{'error':'상태 확인 보고가 많습니다. 잠시 후 확인해 주세요.','code':'attachment_client_report_rate'})
            context['recovery_reports']=[*reports,now]
        try:metadata=attachment_client_metadata(payload)
        except ValueError:
            return send(400,{'error':'첨부 관측 형식을 확인해 주세요.','code':'attachment_client_report_invalid'})
        self._diagnostic_observe({**metadata,'event_type':'attachment_client_rejected',
            'request_id':request_id,'visitor_ref':context['visitor_ref'],
            'code_fingerprint':self.diagnostic_runtime['code_fingerprint'],
            'deployment_revision':self.diagnostic_runtime['deployment_revision']})
        return send(200,{'ok':True})

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
        if self.hosted_demo_policy is not None:
            handled = self.hosted_demo_policy.admit(environ, start_response)
            if handled is not None:
                return handled
        headers = [('Cache-Control', 'no-store'), ('X-Content-Type-Options', 'nosniff'),
                   ('Referrer-Policy', 'same-origin'),
                   ('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")]
        diagnostic_request=None;diagnostic_content=None;diagnostic_error='request_rejected';received=time.monotonic()
        diagnostic_model_called=False
        diagnostic_probe=None
        attachment_report_request_id=None
        https_observation=None;https_failure_stage='request';https_upstream_status=None
        def send(status, value, mime='application/json; charset=utf-8'):
            if https_observation is not None:
                metadata={**https_observation,'event_type':'attachment_https_finished',
                    'status':'error' if status>=400 else 'complete','http_status':status,
                    'elapsed_ms':round((time.monotonic()-received)*1000)}
                if status>=400:
                    metadata.update(error_kind=value.get('code',diagnostic_error) if isinstance(value,dict) else diagnostic_error,
                        failure_stage=https_failure_stage,upstream_http_status=https_upstream_status)
                self._diagnostic_observe(metadata)
            if status>=400 and diagnostic_probe is not None:
                self._diagnostic_observe({**diagnostic_probe,'http_status':status,'error_kind':diagnostic_error,
                    'elapsed_ms':round((time.monotonic()-received)*1000)})
            if status>=400 and diagnostic_request is not None:
                self._diagnostic_observe({**diagnostic_request,'event_type':'request_rejected','status':'rejected',
                    'route':'reject','route_reason':'model_response_failure' if diagnostic_model_called else 'request_validation','http_status':status,'error_kind':diagnostic_error,
                    'failure_stage':'model_response' if diagnostic_model_called else 'request','elapsed_ms':round((time.monotonic()-received)*1000),'model_called':diagnostic_model_called},diagnostic_content)
            if (isinstance(value, dict) and 'session' in value
                    and not environ.get('PATH_INFO', '').startswith('/api/operator/diagnostics/')):
                value = {**value, 'session': project_session(value['session'])}
            raw = json.dumps(value, ensure_ascii=False).encode() if isinstance(value, (dict, list)) else value
            start_response(f'{status} {HTTPStatus(status).phrase}', headers + [('Content-Type', mime), ('Content-Length', str(len(raw)))])
            return [raw]
        host = environ.get('HTTP_HOST', '').split(':')[0].lower()
        if host not in self.allowed_hosts:
            return send(421, {'error': '허용되지 않은 서비스 주소입니다.'})
        path, method = environ.get('PATH_INFO', '/'), environ.get('REQUEST_METHOD', 'GET')
        if path in ('/auth/google/start', '/auth/google/callback'):
            return self._google_login(environ, path, method, send, headers)
        if path == '/auth/google/enroll':
            headers[:] = [(name, value) for name, value in headers if name.lower() != 'referrer-policy']
            headers.append(('Referrer-Policy', 'no-referrer'))
            if environ.get('QUERY_STRING', ''):
                return send(400, {'error': '초대 코드는 주소에 넣지 말고 입력란에 입력해 주세요.'})
        if path == '/healthz':
            return send(200, {'status': 'ok'})
        if method not in ('GET', 'POST'):
            return send(405, {'error': '지원하지 않는 요청입니다.'})
        if path == '/api/logout' and method != 'POST':
            return send(405, {'error': '방문자 세션 종료는 POST 요청으로만 처리합니다.'})
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
            return send(200, raw, 'image/webp' if path.endswith('.webp') else 'image/png' if path.endswith('.png') else 'image/jpeg')
        if path in ('/api/worker/poll','/api/worker/result'):
            if self.env.get('APP_RUNTIME') == 'hosted_public':
                return send(404, {'error': '이 연결 경로는 현재 사용할 수 없습니다.', 'code': 'runtime_worker_unavailable'})
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
        lease = None
        streaming = False
        try:
            context, cookie = self.visitor(environ)
            with self.lock:
                if context['revoked'] or self._revoked(context['sid']):
                    headers.append(('Set-Cookie', self._expired_cookie()))
                    return send(403, {'error': '종료된 방문자 세션입니다. 화면을 새로고침해 주세요.'})
                context['inflight'] += 1
                lease = context
            if cookie is not None:
                headers.append(('Set-Cookie', cookie))
            service, chat, profile = context['service'], context['chat'], context['profile']
            token = context['token']
            query = parse_qs(environ.get('QUERY_STRING', ''))
            identifier = query.get('id', [''])[0]
            if (method,path) in (('GET','/api/chat/session'),('POST','/api/chat/recovery-report')):
                probe_id=uuid.uuid4().hex
                diagnostic_probe={'event_type':'session_read_failed' if method=='GET' else 'recovery_report_rejected',
                    'request_id':probe_id,'visitor_ref':context['visitor_ref'],
                    'session_verified':False,'request_verified':False,
                    'code_fingerprint':self.diagnostic_runtime['code_fingerprint'],
                    'deployment_revision':self.diagnostic_runtime['deployment_revision']}
                if method=='GET':diagnostic_probe['claimed_session_id']=identifier
                headers.append(('X-RNDPLZ-Request-Id',probe_id))
            if method=='POST' and path=='/api/attachments/https':
                https_id=uuid.uuid4().hex
                https_observation={'request_id':https_id,'visitor_ref':context['visitor_ref'],
                    'code_fingerprint':self.diagnostic_runtime['code_fingerprint'],
                    'deployment_revision':self.diagnostic_runtime['deployment_revision']}
                headers.append(('X-RNDPLZ-Request-Id',https_id))
                self._diagnostic_observe({**https_observation,'event_type':'attachment_https_started','status':'started'})
            if method=='POST' and path=='/api/attachments/client-report':
                attachment_report_request_id=uuid.uuid4().hex
                headers.append(('X-RNDPLZ-Request-Id',attachment_report_request_id))
            if method=='POST' and path in ('/api/chat','/api/chat/prepare','/api/attachments'):
                request_id=uuid.uuid4().hex
                diagnostic_request={'visitor_ref':context['visitor_ref'],'request_id':request_id,'attempt_id':uuid.uuid4().hex,
                                    'trace_id':uuid.uuid4().hex,'session_id':'request-'+request_id,
                                    'code_fingerprint':self.diagnostic_runtime['code_fingerprint'],
                                    'deployment_revision':self.diagnostic_runtime['deployment_revision']}
                headers.append(('X-RNDPLZ-Request-Id',request_id))
                marker=environ.get('HTTP_X_RNDPLZ_DIAGNOSTIC_RUN','')
                if isinstance(marker,str) and re.fullmatch(r'[a-f0-9]{32}',marker):diagnostic_request['diagnostic_run']=marker
            session_mode = context.get('session_mode', 'visitor')
            account_view = {'account': self._public_account(context['account'])} if context.get('account') else {}
            if method == 'GET':
                if path == '/api/account/session': return send(200, self._account_status(context, environ))
                if path == '/api/account/mole':
                    if not context.get('account'):
                        return send(401, {'error': '로그인 후 참여 포인트를 확인할 수 있습니다.', 'code': 'account_required'})
                    if environ.get('QUERY_STRING', ''):
                        return send(400, {'error': '참여 포인트 조회에는 추가 조건을 넣지 마세요.', 'code': 'mole_query_not_allowed'})
                    return send(200, profile.store.mole_summary())
                if path == '/api/self-profile': return send(200, {'token':token, **profile.read()})
                if path == '/api/self-profile/source': return send(200, profile.source(identifier))
                if path == '/api/chat/bootstrap': return send(200, {'token': token, 'history': chat.history(), **self.models.catalog(), 'public': True, 'session_mode': session_mode, 'logout_supported': True, **account_view})
                if path == '/api/chat/models': return send(200, {**self.models.catalog(), 'public': True})
                if path == '/api/chat/session':
                    session=chat.get(identifier)
                    self._diagnostic_observe({**diagnostic_probe,'event_type':'session_read_completed',
                        'session_verified':True,'pending_present':bool(session.get('pending')),
                        'http_status':200,'elapsed_ms':round((time.monotonic()-received)*1000)})
                    return send(200,project_session(session))
                if path == '/api/bootstrap': return send(200, {**service.bootstrap(), 'token': token, 'public': True, 'session_mode': session_mode, 'logout_supported': True, **account_view})
                if path == '/api/people-map': return send(200, build_people_map(service.engine))
                if path == '/api/admin': return send(200, service.admin())
                if path == '/api/person': return send(200, service.person(identifier))
                if path == '/api/proposals': return send(200, service.store.read()['proposals'])
                if path == '/api/attachment':
                    return send(200, chat.attachments.source(identifier))
                if path == '/api/record':
                    record = self.engine.corpus.records.get(identifier)
                    if not record: return send(404, {'error': '기록을 찾을 수 없습니다.'})
                    return send(200, {**self.engine.explain_record(record), 'text': record.text, 'details': record.details})
                files = {'/': ('index.html', 'text/html'), '/explore': ('explore.html', 'text/html'), '/profile': ('profile.html', 'text/html'), '/auth/google/enroll': ('account-enroll.html', 'text/html')}
                for name in ('people-map.css', 'people-map-model.js', 'people-map-layout.js', 'people-map-graph.js', 'people-map.js', 'theme.js', 'theme.css', 'craft.css', 'chat.css', 'style.css', 'craft.js', 'chat.js', 'app.js', 'profile.css', 'profile.js', 'profile-chat.js', 'account-menu.js', 'account-enroll.js', 'draw.js', 'draw.css', 'recommendation-map.js', 'recommendation-map.css'):
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
            if path == '/auth/google/enroll' and not 0 < length <= 4096:
                return send(413, {'error': '초대 입력의 크기를 확인해 주세요.'})
            body_limit = 2048 if path in ('/api/chat/recovery-report','/api/attachments/client-report') else MAX_HTTPS_BODY if path == '/api/attachments/https' else MAX_UPLOAD_BODY if path == '/api/attachments' else (1500000 if path in ('/api/self-profile/upload','/api/self-profile/chat') else 200000)
            if not 0 < length <= body_limit:
                if path=='/api/attachments/client-report':
                    return send(413,{'error':'첨부 관측 크기를 확인해 주세요.','code':'attachment_client_report_invalid'})
                if path == '/api/attachments/https':
                    return send(413, {'error':'링크 주소의 크기를 확인해 주세요.', 'code':'https_request_too_large'})
                if path == '/api/attachments':
                    return send(413, {'error':str(AttachmentError('too_large')), 'code':'attachment_too_large'})
                return send(413, {'error': '요청 크기가 허용 범위를 넘었습니다. 공개 시연 첨부는 약 1MB까지입니다.'})
            raw_payload = environ['wsgi.input'].read(length).decode('utf-8')
            try:
                payload = strict_json(raw_payload) if path in ('/auth/google/enroll','/api/attachments/https','/api/chat/recovery-report','/api/attachments/client-report') else json.loads(raw_payload)
            except AuthError:
                if path=='/api/attachments/client-report':
                    return send(400,{'error':'첨부 관측 형식을 확인해 주세요.','code':'attachment_client_report_invalid'})
                if path == '/api/chat/recovery-report':
                    return send(400,{'error':'회복 관측 형식을 확인해 주세요.','code':'recovery_report_invalid'})
                raise
            if not isinstance(payload, dict): raise ValueError('요청 형식이 올바르지 않습니다.')
            if diagnostic_probe is not None:
                for original,claimed in (('session_id','claimed_session_id'),('turn_id','claimed_turn_id'),('request_id','client_request_id')):
                    if isinstance(payload.get(original),str):diagnostic_probe[claimed]=payload[original]
            if path == '/api/logout':
                if payload:
                    return send(400, {'error': '방문자 세션 종료 요청에는 추가 항목을 넣지 마세요.'})
                if not self._logout(context):
                    return send(409, {'error': '현재 요청이 끝난 뒤 방문자 세션을 종료해 주세요.', 'code': 'logout_busy'})
                headers[:] = [(name, value) for name, value in headers if name.lower() != 'set-cookie']
                headers.append(('Set-Cookie', self._expired_cookie()))
                headers.append(('Set-Cookie', self._account_cookie_header(self.auth.LOGIN_COOKIE_NAME)))
                if session_mode == 'account':
                    headers.append(('Set-Cookie', self._account_cookie_header(self.auth.SESSION_COOKIE_NAME)))
                return send(200, {'ok': True, 'logged_out': True, 'session_mode': 'visitor'})
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
            if path=='/api/attachments/client-report':
                if environ.get('QUERY_STRING',''):
                    return send(400,{'error':'첨부 관측에는 추가 주소 조건을 넣지 마세요.','code':'attachment_client_report_invalid'})
                return self._attachment_client_report(context,payload,send,attachment_report_request_id)
            if path == '/api/chat/recovery-report':
                if environ.get('QUERY_STRING',''):return send(400,{'error':'회복 관측에는 추가 주소 조건을 넣지 마세요.','code':'recovery_report_invalid'})
                return self._recovery_report(context,chat,payload,send,diagnostic_probe)
            if path == '/auth/google/enroll':
                if set(payload) != {'invitation'} or not isinstance(payload.get('invitation'), str) or not re.fullmatch(r'[A-Za-z0-9_-]{43}', payload['invitation']):
                    return send(400, {'error': '받은 초대 코드를 확인해 주세요.'})
                if context.get('account') is not None:
                    return send(409, {'error': '현재 계정에서 로그아웃한 뒤 초대로 가입해 주세요.'})
                with self.lock:
                    if context['active'] or context['inflight'] != 1:
                        return send(409, {'error': '진행 중인 요청이 끝난 뒤 다시 시도해 주세요.'})
                flow = self.auth.begin_enrollment(payload['invitation'], '/')
                if not flow['authorization_url'].startswith(AUTHORIZATION + '?'):
                    raise AuthError('login_destination_invalid', 503)
                headers.append(('Set-Cookie', self._account_cookie_header(
                    self.auth.LOGIN_COOKIE_NAME, flow['login_cookie'], flow['cookie_max_age'])))
                return send(200, {'authorization_url': flow['authorization_url']})
            if path == '/api/chat':
                state = service.store.read()
                if sum(s.get('turns', 0) for s in state['sessions']) >= 40:
                    diagnostic_error='message_limit';return send(429, {'error': '이 방문자의 공개 시연 메시지 한도에 도달했습니다.'})
                if not self.request_slots.acquire(blocking=False):
                    diagnostic_error='busy';return send(429, {'error': '응답 중인 방문자가 많습니다. 잠시 후 다시 시도해 주세요.'})
                def observed_iterator():
                    with diagnostic_scope(self.observation,diagnostic_request or {}):
                        yield from chat.stream(payload)
                self._diagnostic_observe({**(diagnostic_request or {}),'event_type':'request_received'})
                iterator = observed_iterator()
                try:
                    first = next(iterator)
                except Exception:
                    self.request_slots.release()
                    raise
                with self.lock: context['active'] += 1
                def release_stream():
                    try:
                        with self.lock:
                            context['active'] -= 1
                            context['inflight'] -= 1
                    finally:
                        self.request_slots.release()
                def observe_stream(meta):
                    if meta.get('session_id') and diagnostic_request is not None:
                        diagnostic_request['session_id']=meta['session_id']
                        with self.lock:
                            refs=context.setdefault('request_refs',{})
                            refs[diagnostic_request['request_id']]=(meta['session_id'],diagnostic_request.get('turn_id'))
                            while len(refs)>16:refs.pop(next(iter(refs)))
                    self._diagnostic_observe({**(diagnostic_request or {}),**meta})
                response = _VisitorStream(iterator, first, release_stream, observe=observe_stream,
                                          request_id=(diagnostic_request or {}).get('request_id'))
                streaming = True
                try:
                    start_response('200 OK', headers + [('Content-Type', 'application/x-ndjson; charset=utf-8')])
                except BaseException:
                    response.close()
                    raise
                return response
            if path == '/api/chat/prepare':
                # Preparing may now generate an answer, so it shares chat admission.
                if not self.request_slots.acquire(blocking=False):
                    diagnostic_error='busy';return send(429, {'error': '응답 중인 방문자가 많습니다. 잠시 후 다시 시도해 주세요.'})
                with self.lock:context['active']+=1
                try:
                    if diagnostic_request is not None:
                        with diagnostic_scope(self.observation,diagnostic_request):
                            return send(200,service.prepared_draft_response(chat.prepare(payload)))
                    return send(200,service.prepared_draft_response(chat.prepare(payload)))
                finally:
                    with self.lock:context['active']-=1
                    self.request_slots.release()
            if path in ('/api/attachments','/api/attachments/https'):
                # Serialize a visitor's attachment commits and retain logout's active/inflight guard.
                with self.lock:
                    if context['active'] or context['inflight'] != 1:
                        return send(409, {'error':'진행 중인 요청이 끝난 뒤 자료를 추가해 주세요.', 'code':'attachment_context_busy'})
                    if len(list(chat.attachments.directory.glob('*.json'))) >= 12:
                        return send(429, {'error':'공개 시연의 첨부 개수 한도에 도달했습니다.'})
                    context['active']+=1
                try:
                    if path == '/api/attachments/https':
                        https_failure_stage='attachment_ingest'
                        return send(200, chat.attachments.upload_url(payload))
                    if diagnostic_request is not None:
                        with diagnostic_scope(self.observation,diagnostic_request):
                            return send(200,chat.attachments.upload(payload))
                    return send(200,chat.attachments.upload(payload))
                finally:
                    with self.lock:context['active']-=1
            if path == '/api/self-profile/chat':
                chat.require_profile_context(payload.get('session_id'))
            routes = {
                '/api/self-profile/chat': lambda: ProfileChat(service, profile).handle(payload),
                '/api/self-profile/save': lambda: profile.save(payload),
                '/api/self-profile/upload': lambda: profile.upload(payload),
                '/api/self-profile/suggest': lambda: profile.suggest(payload),
                '/api/self-profile/source-action': lambda: profile.source_action(payload),
                '/api/converse': lambda: project_session(service.converse(payload)),
                '/api/slots': lambda: project_session(service.update_slots(payload)),
                '/api/draft': lambda: service.draft(payload.get('session_id'), payload.get('candidate_id')),
                '/api/proposals': lambda: service.save_proposal(payload),
                '/api/transition': lambda: service.transition(payload.get('id'), payload.get('state')),
            }
            if path not in routes: return send(404, {'error': '경로를 찾을 수 없습니다.'})
            if diagnostic_request is not None:
                with diagnostic_scope(self.observation,diagnostic_request):
                    return send(200,routes[path]())
            return send(200, routes[path]())
        except ProviderScopeError as exc:
            diagnostic_error = exc.code
            return send(409, {'error': str(exc), 'code': exc.code, 'request_preserved': True})
        except AuthError as exc:
            return send(exc.status, {'error': str(exc), 'code': exc.code})
        except ModelResponseBudgetExhausted as exc:
            diagnostic_error=exc.code
            return send(409, {'error':str(exc), 'code':exc.code,
                              'request_preserved':True, 'retry_available':False})
        except ModelResponseUnavailable as exc:
            diagnostic_error=exc.code
            diagnostic_model_called=True
            message = (str(exc) + ' 잠시 후 버튼으로 다시 시도할 수 있습니다.' if exc.retry_available else
                       str(exc) + ' 지금 이 요청을 다시 처리할 수 없습니다. 의뢰서는 유지되며, 이 오류 때문에 조건을 바꾸실 필요는 없습니다.')
            return send(503, {'error':message, 'code':exc.code,
                              'request_preserved':exc.request_preserved, 'retry_available':exc.retry_available})
        except ScoutSourceChanged as exc:
            diagnostic_error=exc.code
            return send(409, {'error':str(exc), 'code':exc.code, 'request_preserved':True,
                              'session':exc.session})
        except DiscoveryError as exc:
            diagnostic_error='discovery_not_ready'
            return send(409, {'error':str(exc), 'code':exc.code})
        except ProfileError as exc:
            return send(exc.status, {'error':str(exc), 'code':exc.code, **({'profile_command': exc.profile_command} if hasattr(exc, 'profile_command') else {})})
        except FetchError as exc:
            diagnostic_error=exc.code
            https_failure_stage=exc.observation['failure_stage']
            https_upstream_status=exc.observation.get('upstream_http_status')
            return send(exc.status, {'error':str(exc), 'code':exc.code})
        except AttachmentError as exc:
            diagnostic_error=exc.code
            return send(exc.status, {'error':str(exc), 'code':exc.code})
        except ValueError as exc:
            # Only fixed, user-actionable validation messages may cross this boundary.
            safe_messages = {
                '선택한 모델은 이미지를 읽지 못합니다. 이미지 지원 모델을 선택하거나 문서로 첨부해 주세요.',
                '이 대화에는 이미지가 있습니다. 이미지 지원 모델을 선택하거나 새 대화를 시작해 주세요.',
            }
            message = str(exc)
            if path == '/api/draft' and message == '대화를 찾을 수 없습니다.':
                diagnostic_error = 'draft_session_unavailable'
                return send(409, {'error': '이 대화의 저장된 후보를 현재 서버에서 찾을 수 없어요. 새 대화에서 수소문한 뒤 편지를 작성해 주세요.', 'code': 'draft_session_unavailable'})
            if message in (
                    '이 대화의 모델 입력 범위를 넘었습니다. 첨부를 줄이거나 필요한 부분을 새 대화에 넣어 주세요.',
                    '대화와 생성 계약이 모델 입력 범위를 넘었습니다. 사용할 자료 범위를 줄여 주세요.'):
                diagnostic_error='context_input_too_large'
                return send(400, {'error':message, 'code':diagnostic_error})
            diagnostic_error='unsupported_image' if message in safe_messages else 'validation'
            return send(400, {'error': message if message in safe_messages else
                             '요청을 처리하지 못했습니다. 현재 방문자의 대화·첨부를 확인해 주세요.'})
        except (KeyError, TypeError):
            diagnostic_error='validation'
            return send(400, {'error': '요청을 처리하지 못했습니다. 현재 방문자의 대화·첨부를 확인해 주세요.'})
        except Exception:
            diagnostic_error='server_error'
            return send(500, {'error': '처리 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.'})
        finally:
            if lease is not None and not streaming:
                with self.lock:
                    lease['inflight'] -= 1


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
