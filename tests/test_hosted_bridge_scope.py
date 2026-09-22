"""Offline scope integration: actual Service/Conversation and selected UI functions.

Only in-memory corpus, store, attachments and model catalog/stream are synthetic.
No application constructor, full Corpus load, credentials, HTTP or model execution.
"""
import copy
import json
from pathlib import Path
import shutil
import socket
import subprocess
import sys
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch
import urllib.request

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def forbidden(*args, **kwargs):
    raise AssertionError('Network is forbidden in hosted bridge scope tests')


class MemoryStore:
    def __init__(self, sessions=()):
        self.state = {'sessions': copy.deepcopy(list(sessions))}

    def read(self):
        return copy.deepcopy(self.state)

    def transaction(self, mutate):
        working = copy.deepcopy(self.state)
        result = mutate(working)
        self.state = working
        return copy.deepcopy(result)


class FakeModels:
    scoped_bridge = True

    def __init__(self, *, scoped=True, unavailable=False):
        self.scoped_bridge = scoped
        self.unavailable = unavailable
        self.calls = []
        self.runtime = NS(config=NS(provider='codex_oauth'))

    def catalog(self):
        self.calls.append(('catalog',))
        return {'default': 'runtime', 'models': []}

    def get(self, identifier):
        self.calls.append(('get', identifier))
        if self.unavailable:
            raise ValueError('Synthetic unavailable model')
        providers = {'bridge': 'bridge', 'runtime': 'codex_oauth', 'gemini:test': 'gemini'}
        if identifier not in providers:
            raise ValueError('Synthetic unknown model')
        return {'id': identifier, 'provider': providers[identifier], 'name': identifier,
                'model': 'gemma4:e4b' if identifier == 'bridge' else identifier,
                'enabled': True, 'vision': identifier != 'bridge',
                'public_scope': identifier == 'bridge' and self.scoped_bridge}

    def stream(self, identifier, messages, *, contract=None):
        self.calls.append(('stream', identifier, contract))
        yield 'synthetic-result'


def fixture(models=None, sessions=()):
    person = lambda pid: NS(id=pid, name=pid, virtual=False, profile={'private_marker': 'excluded'})
    record = lambda rid, pid, kind='paper': NS(id=rid, kind=kind, virtual=False,
        source_system='curated_primary_sources', people=[NS(person_id=pid)], tags=[])
    corpus = NS(people={pid: person(pid) for pid in ('PUB-SYNTHETIC', 'LOCAL-SYNTHETIC')},
        records={'PUBLIC-PAPER': record('PUBLIC-PAPER', 'PUB-SYNTHETIC'),
                 'PERSONAL-PAPER': record('PERSONAL-PAPER', 'LOCAL-SYNTHETIC'),
                 'PERSONAL-CAREER': record('PERSONAL-CAREER', 'LOCAL-SYNTHETIC', 'career_record')},
        topics=[], topic_by_id={}, demo_pool={'version': 'synthetic', 'personal_person_ids': ['LOCAL-SYNTHETIC']})
    service = Service.__new__(Service)
    service.corpus, service.engine, service.store = corpus, Engine(corpus), MemoryStore(sessions)
    chat = Conversation.__new__(Conversation)
    chat.service, chat.store, chat.models = service, service.store, models or FakeModels()
    chat.actions, chat.discovery = ChatActions(service), None
    items = {'document': {'id': 'document', 'image': None, 'text': 'Explicit synthetic document'},
             'image': {'id': 'image', 'image': 'synthetic-image', 'text': ''}}
    chat.attachments = NS(load=lambda key: copy.deepcopy(items[key]))
    return chat


def scope(provider='bridge', identifier='bridge'):
    return {'id': RUNTIME_DOCUMENT_SCOPE_ID, 'provider': provider, 'model_id': identifier}


def request(identifier='bridge', **extra):
    return {'model_id': identifier, 'model_selection_origin': 'explicit',
            'text': 'Synthetic question', 'turn_id': 'synthetic-turn-0001', **extra}


def session(policy=None, identifier='bridge'):
    policy = policy or scope()
    return {'id': 'synthetic-session', 'kind': 'chat', 'provider_scope': policy,
            'model_id': identifier,
            'execution_binding': {'model_id': identifier,
                                  'provider': 'bridge' if identifier == 'bridge' else 'codex_oauth'},
            'messages': []}


class HostedBridgeScopeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.guards = [patch.object(socket, 'socket', forbidden),
                      patch.object(socket, 'create_connection', forbidden),
                      patch.object(urllib.request.OpenerDirector, 'open', forbidden)]
        for guard in cls.guards:
            guard.start()
            cls.addClassCleanup(guard.stop)
        global Service, Engine, Conversation, ChatActions, provider_scope
        global ProviderScopeError, RUNTIME_DOCUMENT_SCOPE_ID, RUNTIME_SCOPE_PROVIDERS
        from rndplz.service import Service, provider_scope, ProviderScopeError
        from rndplz.service import RUNTIME_DOCUMENT_SCOPE_ID, RUNTIME_SCOPE_PROVIDERS
        from rndplz.engine import Engine
        from rndplz.conversation import Conversation
        from rndplz.chat_actions import ChatActions

    def test_exact_scope_schema_and_existing_routes(self):
        self.assertEqual(provider_scope({'provider_scope': scope()}), scope())
        self.assertEqual(RUNTIME_SCOPE_PROVIDERS, ('codex_oauth', 'openai_api'))
        for change in ({'id': 'runtime_public_papers.v1'}, {'model_id': 'runtime'},
                       {'provider': 'ollama'}, {'unexpected': True}):
            with self.subTest(change=change), self.assertRaises(ProviderScopeError):
                provider_scope({'provider_scope': {**scope(), **change}})
        for identifier, provider, expected_id in (
                ('runtime', 'codex_oauth', RUNTIME_DOCUMENT_SCOPE_ID),
                ('gemini:test', 'gemini', 'gemini_public_papers.v2')):
            view = fixture()._for_provider_request(request(identifier))
            self.assertEqual(view._provider_scope, {'id': expected_id, 'provider': provider, 'model_id': identifier})

    def test_new_bridge_projects_real_service_corpus_and_stop_is_offline(self):
        chat = fixture()
        view = chat._for_provider_request(request())
        self.assertIsNot(view, chat)
        self.assertIs(view.store, chat.store)
        self.assertEqual(view._provider_scope, scope())
        self.assertEqual(set(view.service.corpus.people), {'PUB-SYNTHETIC'})
        self.assertEqual(set(view.service.corpus.records), {'PUBLIC-PAPER'})
        self.assertEqual(view.service.corpus.people['PUB-SYNTHETIC'].profile, {})
        self.assertIn('LOCAL-SYNTHETIC', chat.service.corpus.people)
        models = FakeModels(unavailable=True)
        stopped = fixture(models)._for_provider_request(request(text='stop', model_selection_origin='automatic'))
        self.assertEqual(stopped._provider_scope, scope())
        self.assertEqual(models.calls, [])
        legacy = fixture(FakeModels(scoped=False))
        self.assertIs(legacy._for_provider_request(request()), legacy)
        self.assertEqual(legacy.models.calls, [])

    def test_existing_policy_and_explicit_model_binding_preserved(self):
        for old, new in (('runtime', 'bridge'), ('bridge', 'runtime')):
            policy = scope('codex_oauth', 'runtime') if old == 'runtime' else scope()
            saved = session(policy, old)
            chat = fixture(sessions=[saved])
            payload = request(new, session_id=saved['id'])
            view = chat._for_provider_request(payload)
            self.assertEqual(view._provider_scope, policy)
            view._bind_execution(saved, payload)
            self.assertEqual(saved['provider_scope'], policy)
            self.assertEqual(saved['model_id'], new)
            self.assertEqual(saved['model_selection_origin'], 'explicit')
            with self.assertRaises(ProviderScopeError):
                chat._for_provider_request({**payload, 'model_selection_origin': 'automatic'})
        with self.assertRaises(ValueError):
            fixture(FakeModels(unavailable=True))._for_provider_request(request())
        with self.assertRaises(ProviderScopeError):
            fixture(sessions=[{'id': 'legacy', 'model_id': 'bridge'}])._for_provider_request(request(session_id='legacy'))

    def test_attachment_profile_and_client_scope_boundaries(self):
        chat = fixture()
        view = chat._for_provider_request(request(attachments=['document']))
        self.assertEqual(view._scoped_attachment_items(['document'])[0]['text'], 'Explicit synthetic document')
        with self.assertRaises(ProviderScopeError):
            chat._for_provider_request(request(attachments=['image']))
        for key in ('provider_scope', 'execution_binding'):
            with self.subTest(key=key), self.assertRaises(ProviderScopeError):
                chat._for_provider_request(request(**{key: scope()}))
        with self.assertRaises(ProviderScopeError):
            chat._for_provider_request(request(person_id='LOCAL-SYNTHETIC'))
        saved = session()
        chat = fixture(sessions=[saved])
        with self.assertRaises(ProviderScopeError):
            chat.require_profile_context(saved['id'])
        saved['messages'] = [{'kind': 'self_profile'}]
        with self.assertRaises(ProviderScopeError):
            fixture(sessions=[saved])._for_provider_request(request(session_id=saved['id']))
        # Existing image-capable scope cannot switch to non-vision bridge.
        saved = session(scope('codex_oauth', 'runtime'), 'runtime')
        saved['messages'] = [{'role': 'user', 'attachments': [{'id': 'image'}]}]
        with self.assertRaises(ProviderScopeError):
            fixture(sessions=[saved])._for_provider_request(request(session_id=saved['id']))

    def test_dispatch_rechecks_stored_explicit_attachments_and_scope(self):
        saved = session()
        saved['messages'] = [{'role': 'user', 'model_selection_origin': 'explicit',
                              'attachments': [{'id': 'document'}], 'explicit_attachment_ids': ['document']}]
        chat = fixture(sessions=[saved])
        view = chat._for_provider_request(request(session_id=saved['id']))
        messages = [{'role': 'user', 'content': 'Explicit synthetic document'}]
        self.assertEqual(list(view.models.stream('bridge', messages, contract='dialogue_answer.v1')), ['synthetic-result'])
        self.assertEqual(sum(row[0] == 'stream' for row in chat.models.calls), 1)
        chat.store.state['sessions'][0]['messages'][0].pop('explicit_attachment_ids')
        with self.assertRaises(ProviderScopeError):
            list(view.models.stream('bridge', messages, contract='dialogue_answer.v1'))
        self.assertEqual(sum(row[0] == 'stream' for row in chat.models.calls), 1)

    def test_fresh_begin_browser_projection_preserves_document_scope(self):
        from rndplz.scout_projection import project_session
        chat = fixture()
        self.assertEqual(chat.store.read()['sessions'], [])
        # Exercise real new-session begin/store/presentation; replace only the
        # downstream generation preparation, without dispatching a model.
        with patch.object(Conversation, 'reserve_model_turn', return_value=[]) as reserve:
            presented, messages, cached, selected = chat.begin(request())
        reserve.assert_called_once()
        self.assertFalse(cached)
        self.assertEqual(messages, [])
        self.assertEqual(selected['id'], 'bridge')
        stored = chat.store.read()['sessions'][0]
        self.assertEqual(stored['provider_scope'], scope())
        self.assertEqual(presented['provider_scope'], scope())
        wire = project_session(presented)
        self.assertEqual(wire.get('provider_scope'), stored['provider_scope'])
        self.assertEqual(wire.get('execution_binding'), stored['execution_binding'])
        for invalid in ({'id': 'runtime_public_papers.v1'}, {'model_id': 'bridge:other'},
                        {'provider': 'ollama'}, {'unexpected': True}):
            malformed = copy.deepcopy(presented)
            malformed['provider_scope'].update(invalid)
            self.assertNotIn('provider_scope', project_session(malformed))
        node = shutil.which('node')
        if not node:
            self.skipTest('Node unavailable; browser projection UI connection not executed')
        source = (ROOT / 'rndplz/web/chat.js').read_text(encoding='utf-8')
        names = ['isGeminiModel', 'hasGeminiScope', 'isRuntimeModel', 'isScopedBridgeModel',
                 'hasRuntimeScope', 'hasPublicPaperScope', 'isPublicPaperModel',
                 'isPublicPaperContext', 'allowsScopedImages', 'allowsScopedDocuments']
        functions = []
        for name in names:
            start = source.index('function ' + name + '(')
            functions.append(source[start:source.index('\nfunction ', start + 1)].strip())
        program = '\n'.join([
            "const assert=require('node:assert/strict');",
            "const GEMINI_ID='gemini:test',selectedModel='bridge';",
            "const catalog=[{id:'bridge',provider:'bridge',public_scope:true,enabled:true,vision:false}];",
            'const session=' + json.dumps(wire, ensure_ascii=False) + ';',
            *functions,
            "assert.equal(hasPublicPaperScope(session),true);",
            "assert.equal(allowsScopedDocuments(),true); assert.equal(allowsScopedImages(),false);"
        ])
        completed = subprocess.run([node, '-e', program], capture_output=True, text=True, timeout=15)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertFalse(any(row[0] == 'stream' for row in chat.models.calls))

    def test_actual_ui_scope_functions_without_browser(self):
        node = shutil.which('node')
        if not node:
            self.skipTest('Node unavailable; UI pure functions not executed')
        source = (ROOT / 'rndplz/web/chat.js').read_text(encoding='utf-8')
        names = ['isGeminiModel', 'hasGeminiScope', 'isRuntimeModel', 'isScopedBridgeModel',
                 'hasRuntimeScope', 'hasPublicPaperScope', 'isPublicPaperModel',
                 'isPublicPaperContext', 'allowsScopedImages', 'allowsScopedDocuments',
                 'modelBoundaryMessage', 'selectionOrigin', 'resolveModelSelection']
        functions = []
        for name in names:
            start = source.index('function ' + name + '(')
            end = source.index('\nfunction ', start + 1)
            functions.append(source[start:end].strip())
        program = '\n'.join([
            "const assert=require('node:assert/strict');",
            "const GEMINI_ID='gemini:test'; let selectedModel='bridge',session=null,files=[];",
            "let catalog=[{id:'bridge',provider:'bridge',public_scope:true,enabled:true,vision:false}];",
            *functions,
            "assert.equal(isPublicPaperModel(),true); assert.equal(allowsScopedDocuments(),true); assert.equal(allowsScopedImages(),false);",
            "assert.equal(modelBoundaryMessage('bridge',[],{id:'old',model_id:'guide'}).length>0,true);",
            "session={id:'saved',model_id:'bridge',provider_scope:{id:'runtime_public_papers.v2',provider:'bridge',model_id:'bridge'}};",
            "assert.equal(hasPublicPaperScope(session),true); assert.equal(allowsScopedDocuments(),true); assert.equal(allowsScopedImages(),false);",
            "assert.deepEqual(resolveModelSelection(catalog,'runtime','bridge','explicit'),{id:'bridge',origin:'explicit'});",
            "catalog=[{id:'runtime',provider:'codex_oauth',enabled:true,vision:true}]; selectedModel='runtime'; assert.equal(allowsScopedImages(),false);",
            "selectedModel='bridge'; catalog=[{id:'bridge',provider:'bridge',public_scope:false,enabled:true,vision:false}]; session=null; assert.equal(isPublicPaperModel(),false);",
            "catalog=[{id:'runtime',provider:'codex_oauth',enabled:true,vision:true}]; selectedModel='runtime'; assert.equal(isPublicPaperModel(),true); assert.equal(allowsScopedImages(),true);",
            "catalog=[{id:'gemini:test',provider:'gemini',enabled:true,vision:true}]; selectedModel='gemini:test'; assert.equal(isPublicPaperModel(),true);",
            "console.log(JSON.stringify({status:'PASS',browser:0,network:0}));"
        ])
        completed = subprocess.run([node, '-e', program], capture_output=True, text=True, timeout=15)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(json.loads(completed.stdout)['status'], 'PASS')


if __name__ == '__main__':
    unittest.main(verbosity=2)
