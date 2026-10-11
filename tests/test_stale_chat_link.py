"""2026-10-11: a phone kept /?chat=<id> of an account conversation after its login ended. Reading it as a
signed-out visitor showed the generic 'check the current visitor's conversation' error on the home."""
import json
import re
from pathlib import Path

from tests.test_public_performance import app, request  # noqa: F401  (fixture)


def test_a_conversation_this_visitor_cannot_open_is_a_quiet_404(app):
    response = request(app, '/api/chat/session?id=' + 'e' * 32)
    assert response['status'] == 404
    body = json.loads(response['body'])
    assert body['code'] == 'session_unavailable'
    assert '다시 로그인' in body['error'] and '현재 방문자의 대화' not in body['error']


def test_the_home_drops_the_stale_address_and_notes_it_quietly():
    chat = (Path(__file__).resolve().parents[1] / 'rndplz/web/chat.js').read_text(encoding='utf-8')
    boot = chat[chat.index('const id=new URLSearchParams(location.search).get("chat");'):]
    boot = boot[:boot.index('render();resizeInput();')]
    assert 'e.code!=="session_unavailable"' in boot and 'searchParams.delete("chat")' in boot and 'note(e.message)' in boot
    assert re.search(r'function note\(message\)\{error\(message\);', chat)
