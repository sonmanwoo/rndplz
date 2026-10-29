"""2026-10-29: a person asked to delete a conversation from the list on the left."""
import json
from pathlib import Path

import pytest

from rndplz.connection_metrics import collect
from tests.test_public_performance import app, request  # noqa: F401  (fixture)

A, B = 'a' * 32, 'b' * 32
FILE, SHARED = 'c' * 32, 'd' * 32


def _visitor(app):
    first = request(app, '/api/chat/bootstrap')
    cookie = first['headers']['Set-Cookie'].split(';', 1)[0]
    return cookie, next(iter(app.contexts.values()))


def _seed(context, **first):
    attachments = context['chat'].attachments.directory
    for identifier in (FILE, SHARED):
        (attachments / (identifier + '.json')).write_text('{}', encoding='utf-8')

    def chat(sid, refs, **extra):
        return {'id': sid, 'kind': 'chat', 'original': '증류탑 범람 문의 ' + sid[:4], 'created': '2026-10-29T01:00:00+00:00',
                'updated': '2026-10-29T01:00:00+00:00', 'turns': 3,
                'messages': [{'role': 'user', 'text': '증류탑 범람을 아는 분', 'attachments': [{'id': r} for r in refs]}],
                'scout': {'disclosed': True}, 'result': {'candidates': [{'id': 'LOCAL-MANWOO'}]}, **extra}

    def apply(state):
        state['sessions'] += [chat(A, [FILE, SHARED], **first), chat(B, [SHARED])]
    context['service'].store.transaction(apply)
    return attachments


def _delete(app, cookie, context, payload):
    response = request(app, '/api/chat/delete', cookie=cookie, method='POST', payload=payload, token=context['token'])
    return response['status'], json.loads(response['body'])


def test_a_deleted_conversation_leaves_the_list_and_takes_its_own_files(app):
    cookie, context = _visitor(app)
    attachments = _seed(context)
    status, body = _delete(app, cookie, context, {'session_id': A})
    assert (status, body) == (200, {'deleted': A})
    history = json.loads(request(app, '/api/chat/bootstrap', cookie=cookie)['body'])['history']
    assert [row['id'] for row in history] == [B]
    assert request(app, '/api/chat/session?id=' + A, cookie=cookie)['status'] == 404
    assert not (attachments / (FILE + '.json')).exists()
    assert (attachments / (SHARED + '.json')).exists()  # the other conversation still shows it
    state = context['service'].store.read()
    assert state['deleted_sessions'] == [{'id': A, 'created': '2026-10-29T01:00:00+00:00',
                                          'deleted': state['deleted_sessions'][0]['deleted'], 'turns': 3,
                                          'started': True, 'searched': True, 'cards': ['LOCAL-MANWOO']}]
    assert '증류탑' not in json.dumps(state['deleted_sessions'], ensure_ascii=False)
    assert _delete(app, cookie, context, {'session_id': A}) == (404, {
        'error': '이미 지웠거나 열 수 없는 대화예요.', 'code': 'session_unavailable'})


def test_a_conversation_still_answering_is_not_deleted(app):
    cookie, context = _visitor(app)
    _seed(context, pending='turn-1')
    status, body = _delete(app, cookie, context, {'session_id': A})
    assert status == 409 and body['code'] == 'delete_busy'
    assert any(s['id'] == A for s in context['service'].store.read()['sessions'])


@pytest.mark.parametrize('payload', [{}, {'session_id': 3}, {'session_id': A, 'extra': 1}])
def test_a_malformed_delete_is_refused(app, payload):
    cookie, context = _visitor(app)
    _seed(context)
    status, body = _delete(app, cookie, context, payload)
    assert status == 400 and body['code'] == 'delete_invalid'
    assert len(context['service'].store.read()['sessions']) == 2


def test_another_visitor_cannot_delete_it(app):
    cookie, context = _visitor(app)
    _seed(context)
    app.contexts.clear()
    other_cookie, other = _visitor(app)
    assert other is not context
    assert _delete(app, other_cookie, other, {'session_id': A})[0] == 404


def test_deleting_does_not_reset_the_message_limit(app):
    cookie, context = _visitor(app)

    def apply(state):
        state['sessions'].append({'id': A, 'kind': 'chat', 'original': 'x', 'created': 'x', 'updated': 'x', 'turns': 40, 'messages': []})
    context['service'].store.transaction(apply)
    assert _delete(app, cookie, context, {'session_id': A})[0] == 200
    response = request(app, '/api/chat', cookie=cookie, method='POST', payload={'text': 'hi'}, token=context['token'])
    assert response['status'] == 429


def test_connection_counts_keep_a_deleted_conversation(app):
    cookie, context = _visitor(app)
    _seed(context)

    def letter(state):
        state['proposals'].append({'session_id': A, 'recipient_id': 'LOCAL-MANWOO', 'state': 'sent',
                                   'created': '2026-10-29T01:00:00+00:00'})
    context['service'].store.transaction(letter)
    root = Path(context['service'].store.directory).parent
    before = collect(root)['periods']['all']
    assert _delete(app, cookie, context, {'session_id': A})[0] == 200
    after = collect(root)['periods']['all']
    assert after == before
    assert (after['started'], after['searched'], after['sent'], after['choice']['first']) == (2, 2, 1, 1)


def test_each_listed_conversation_has_its_own_delete_button():
    chat = (Path(__file__).resolve().parents[1] / 'rndplz/web/chat.js').read_text(encoding='utf-8')
    listed = chat[chat.index('function historyHtml(){'):]
    listed = listed[:listed.index('\n')]
    assert 'data-action="history-delete"' in listed and 'aria-label="' in listed
    assert 'api("/api/chat/delete",{session_id:id})' in chat
