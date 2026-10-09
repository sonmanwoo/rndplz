"""로컬 CLI의 JSON 계약과 실제 하위 프로세스 MCP 입출력을 검증한다."""
import io
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
from unittest.mock import patch

import pytest

from rndplz import agent


ROOT = Path(__file__).resolve().parents[1]


def child_env():
    return {**os.environ, 'PYTHONIOENCODING': 'utf-8', 'PYTHONDONTWRITEBYTECODE': '1',
            'RNDPLZ_PROVIDER': 'none', 'RNDPLZ_MODEL_CALL_LIMIT': '0',
            'RNDPLZ_PUBLISH_PERSONAL': '', 'RNDPLZ_PUBLIC_PERSON_IDS': ''}


def run_cli(*args):
    return subprocess.run([sys.executable, '-B', '-m', 'rndplz.agent', *args], cwd=ROOT,
                          env=child_env(), capture_output=True, encoding='utf-8', timeout=60)


def initialize(version=agent.PROTOCOL_VERSIONS[0]):
    return {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize',
            'params': {'protocolVersion': version, 'capabilities': {},
                       'clientInfo': {'name': '수소문 시험', 'version': '1'}}}


def ready_server():
    server = agent.MCPServer()
    server.handle(initialize())
    server.handle({'jsonrpc': '2.0', 'method': 'notifications/initialized'})
    return server


def test_cli_utf8_json_and_korean_text_in_subprocess():
    result = run_cli('capabilities')
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data['status'] == 'ok'
    assert data['capabilities']
    assert set(('schema_version', 'pool_version', 'generated_at')) <= data.keys()
    assert any('\uac00' <= char <= '\ud7a3' for char in result.stdout)
    assert '\\u' not in result.stdout
    result = run_cli('capabilities', '--text')
    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith('수소문 결과\n')
    assert '역량 목록:' in result.stdout
    assert '공개 풀 버전:' in result.stdout


@pytest.mark.parametrize('args', [[], ['unknown'], ['person'], ['find-people', '촉매', '--limit', 'abc'],
                                  ['find-people', '촉매', '--limit', '0'], ['draft', '--to', '', '--need', '촉매'],
                                  ['--text', 'person', 'NOT-A-PUBLIC-ID']])
def test_cli_invalid_inputs_return_nonzero_json(args):
    result = run_cli(*args)
    assert result.returncode != 0
    data = json.loads(result.stdout)
    assert data['status'] == 'error'
    assert data['error']
    assert set(('schema_version', 'pool_version', 'generated_at')) <= data.keys()
    assert 'Traceback' not in result.stderr


@pytest.mark.parametrize(('args', 'name', 'arguments'), [
    (['find-people', '촉매 문제', '--limit', '3'], 'find_people', {'query': '촉매 문제', 'limit': 3}),
    (['person', 'P1'], 'get_person', {'person_id': 'P1'}),
    (['record', 'R1'], 'get_record', {'record_id': 'R1'}),
    (['capabilities'], 'list_capabilities', {}),
    (['capability', 'C1'], 'people_for_capability', {'capability_id': 'C1'}),
    (['draft', '--to', 'P1, P2', '--need', '촉매 문제', '--requester-note', '검토 부탁드립니다'],
     'draft_request', {'person_ids': ['P1', 'P2'], 'need': '촉매 문제', 'requester_note': '검토 부탁드립니다'}),
])
def test_cli_routes_each_command_to_shared_tool(args, name, arguments):
    with patch.object(agent, 'call_tool', return_value={'status': 'ok'}) as call, patch('sys.stdout', new_callable=io.StringIO):
        assert agent.main(args) == 0
    call.assert_called_once_with(name, arguments)


@pytest.mark.parametrize('args', [['--text', 'capabilities'], ['capabilities', '--text']])
def test_cli_text_flag_works_before_or_after_command(args):
    with patch.object(agent, 'call_tool', return_value={'status': 'ok'}), patch('sys.stdout', new_callable=io.StringIO) as output:
        assert agent.main(args) == 0
        assert output.getvalue() == '수소문 결과\n상태: 완료\n'


@pytest.mark.parametrize(('name', 'arguments'), [
    ('find_people', {'query': '촉매', 'limit': True}),
    ('find_people', {'query': '촉매', 'limit': 2.5}),
    ('find_people', {'query': '촉매', 'limit': 51}),
    ('find_people', {'query': 1}),
    ('find_people', {'query': ' '}),
    ('find_people', {'query': '가' * 20001}),
    ('get_person', {'person_id': None}),
    ('get_person', {'person_id': 'x' * 301}),
    ('get_record', {}),
    ('list_capabilities', {'private': True}),
    ('people_for_capability', []),
    ('draft_request', {'person_ids': 'P1', 'need': '촉매'}),
    ('draft_request', {'person_ids': [], 'need': '촉매'}),
    ('draft_request', {'person_ids': [1], 'need': '촉매'}),
    ('draft_request', {'person_ids': ['P1', 'P1'], 'need': '촉매'}),
    ('draft_request', {'person_ids': ['P1', ' P1'], 'need': '촉매'}),
    ('draft_request', {'person_ids': ['P' + str(i) for i in range(8)], 'need': '촉매'}),
    ('draft_request', {'person_ids': ['P1'], 'need': '촉매', 'requester_note': None}),
])
def test_mcp_bad_tool_arguments_are_tool_errors_without_calling_tool(name, arguments):
    server = ready_server()
    # Error construction is allowed; invoking a corpus tool is not.
    with patch.object(agent, '_error', return_value={'status': 'error', 'error': {'code': 'invalid_arguments'}}), \
            patch.object(agent, '_tools') as tools:
        response = server.handle({'jsonrpc': '2.0', 'id': 4, 'method': 'tools/call',
                                  'params': {'name': name, 'arguments': arguments}})
    tools.assert_not_called()
    result = response['result']
    assert result['isError'] is True
    assert json.loads(result['content'][0]['text']) == result['structuredContent']


def test_mcp_real_interactive_subprocess_roundtrip_and_flush():
    process = subprocess.Popen([sys.executable, '-B', '-m', 'rndplz.agent', 'mcp'], cwd=ROOT,
                               env=child_env(), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, text=True, encoding='utf-8', bufsize=1)
    received = queue.Queue()

    def read_lines():
        for line in process.stdout:
            received.put(line)

    reader = threading.Thread(target=read_lines, daemon=True)
    reader.start()

    def send(message):
        process.stdin.write(json.dumps(message, ensure_ascii=False) + '\n')
        process.stdin.flush()

    def response():
        return json.loads(received.get(timeout=60))

    try:
        send(initialize())
        answer = response()
        assert answer['id'] == 1
        assert answer['result']['serverInfo']['name'] == 'susomun'
        assert answer['result']['protocolVersion'] == agent.PROTOCOL_VERSIONS[0]
        send({'jsonrpc': '2.0', 'method': 'notifications/initialized'})
        send({'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'})
        answer = response()
        assert answer['id'] == 2  # initialized notification emitted no reply
        definitions = answer['result']['tools']
        assert {tool['name'] for tool in definitions} == {tool['name'] for tool in agent.TOOL_DEFINITIONS}
        assert len(definitions) == 6
        assert all(tool['annotations']['readOnlyHint'] is True for tool in definitions)
        assert all(tool['inputSchema']['additionalProperties'] is False for tool in definitions)
        assert all(any('\uac00' <= char <= '\ud7a3' for char in tool['description']) for tool in definitions)
        send({'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call',
              'params': {'name': 'list_capabilities', 'arguments': {}}})
        answer = response()
        assert answer['id'] == 3
        assert answer['result']['isError'] is False
        data = answer['result']['structuredContent']
        assert json.loads(answer['result']['content'][0]['text']) == data
        assert data['capabilities']
        send({'jsonrpc': '2.0', 'id': 4, 'method': 'unknown/method'})
        assert response()['error']['code'] == -32601
        send({'jsonrpc': '2.0', 'id': 5, 'method': 'tools/call',
              'params': {'name': 'find_people', 'arguments': {'query': '촉매', 'limit': True}}})
        assert response()['result']['isError'] is True
        send({'jsonrpc': '2.0', 'id': 6, 'method': 'ping'})
        assert response() == {'jsonrpc': '2.0', 'id': 6, 'result': {}}
        process.stdin.close()
        assert process.wait(timeout=60) == 0
        reader.join(timeout=5)
        assert received.empty()  # stdout contains only expected protocol messages
        assert process.stderr.read() == ''
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=10)
        for stream in (process.stdin, process.stdout, process.stderr):
            stream.close()


@pytest.mark.parametrize('version', [*agent.PROTOCOL_VERSIONS, '2099-01-01', '2024-11-05'])
def test_protocol_version_negotiation(version):
    result = agent.MCPServer().handle(initialize(version))['result']
    expected = version if version in agent.PROTOCOL_VERSIONS else agent.PROTOCOL_VERSIONS[0]
    assert result['protocolVersion'] == expected


@pytest.mark.parametrize('value', [[], None, 1, {}, {'jsonrpc': '1.0', 'method': 'ping', 'id': 1},
                                  {'jsonrpc': '2.0', 'method': 'ping', 'id': True},
                                  {'jsonrpc': '2.0', 'method': 'ping', 'id': None}])
def test_invalid_rpc_envelopes(value):
    assert agent.MCPServer().handle(value)['error']['code'] == -32600


def test_mcp_parse_errors_do_not_break_later_requests():
    output = io.StringIO()
    incoming = '\n'.join(['{bad', '{"jsonrpc":"2.0","id":1,"method":"ping","params":{"x":NaN}}',
                           json.dumps({'jsonrpc': '2.0', 'id': '한글', 'method': 'ping'})]) + '\n'
    assert agent.serve_mcp(io.StringIO(incoming), output) == 0
    responses = [json.loads(line) for line in output.getvalue().splitlines()]
    assert [row['error']['code'] for row in responses[:2]] == [-32700, -32700]
    assert responses[2] == {'jsonrpc': '2.0', 'id': '한글', 'result': {}}


@pytest.mark.parametrize('malformed', [
    b'{"jsonrpc":"2.0","id":"\\ud800","method":"ping"}',
    b'{"jsonrpc":"2.0","id":1,"method":"ping","params":{"nested":[{"value":"\\udc00"}]}}',
    b'{"jsonrpc":"2.0","id":1,"method":"ping","params":{"nested":[{"\\ud800":"value"}]}}',
    b'{"jsonrpc":"2.0","id":"\xff","method":"ping"}',
    b'{"jsonrpc":"2.0","id":"\xc0\xaf","method":"ping"}',
    b'{"jsonrpc":"2.0","id":"\xed\xa0\x80","method":"ping"}',
])
def test_mcp_invalid_unicode_recovers_at_next_line_in_real_subprocess(malformed):
    # Both adjacent messages are in the same write: decoding the entire stdin
    # text buffer would lose the valid ping as well as the malformed line.
    valid = {'jsonrpc': '2.0', 'id': '한글\U0001f600', 'method': 'ping'}
    payload = malformed + b'\n' + json.dumps(valid, ensure_ascii=False).encode('utf-8') + b'\n'
    result = subprocess.run([sys.executable, '-B', '-m', 'rndplz.agent', 'mcp'], cwd=ROOT,
                            env=child_env(), input=payload, capture_output=True, timeout=60)
    assert result.returncode == 0, result.stderr
    assert result.stderr == b''
    responses = [json.loads(line) for line in result.stdout.decode('utf-8', errors='strict').splitlines()]
    assert len(responses) == 2
    assert responses[0]['error']['code'] == -32700
    assert responses[0]['id'] is None
    assert responses[1] == {'jsonrpc': '2.0', 'id': valid['id'], 'result': {}}
    assert valid['id'].encode('utf-8') in result.stdout


def test_mcp_valid_surrogate_pair_is_preserved_as_unicode():
    output = io.StringIO()
    incoming = '{"jsonrpc":"2.0","id":"\\ud83d\\ude00","method":"ping"}\n'
    assert agent.serve_mcp(io.StringIO(incoming), output) == 0
    assert json.loads(output.getvalue()) == {'jsonrpc': '2.0', 'id': '\U0001f600', 'result': {}}
    assert '\U0001f600' in output.getvalue()


def test_mcp_invalid_response_unicode_is_replaced_by_internal_error_before_write():
    incoming = '\n'.join(json.dumps({'jsonrpc': '2.0', 'id': item, 'method': 'ping'}) for item in (1, 2)) + '\n'
    output = io.StringIO()
    answers = [{'jsonrpc': '2.0', 'id': 1, 'result': {'text': '\ud800'}},
               {'jsonrpc': '2.0', 'id': 2, 'result': {}}]
    with patch.object(agent.MCPServer, 'handle', side_effect=answers), patch('sys.stderr', new_callable=io.StringIO):
        assert agent.serve_mcp(io.StringIO(incoming), output) == 0
    output.getvalue().encode('utf-8', errors='strict')
    responses = [json.loads(line) for line in output.getvalue().splitlines()]
    assert responses[0]['id'] == 1
    assert responses[0]['error']['code'] == -32603
    assert responses[1] == answers[1]


def test_mcp_notifications_do_not_execute_tools_or_reply():
    server = ready_server()
    with patch.object(agent, 'call_tool') as call:
        assert server.handle({'jsonrpc': '2.0', 'method': 'tools/call',
                              'params': {'name': 'list_capabilities'}}) is None
        assert server.handle({'jsonrpc': '2.0', 'method': 'notifications/unknown'}) is None
    call.assert_not_called()


def test_mcp_requires_initialize_then_initialized_but_allows_ping():
    server = agent.MCPServer()
    assert server.handle({'jsonrpc': '2.0', 'id': 1, 'method': 'ping'})['result'] == {}
    request = {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'}
    assert server.handle(request)['error']['code'] == -32000
    server.handle(initialize())
    assert server.handle(request)['error']['code'] == -32000
    server.handle({'jsonrpc': '2.0', 'method': 'notifications/initialized'})
    assert len(server.handle(request)['result']['tools']) == 6


def test_mcp_routes_all_six_tools_and_keeps_stdout_clean():
    calls = [('find_people', {'query': '촉매'}), ('get_person', {'person_id': 'P1'}),
             ('get_record', {'record_id': 'R1'}), ('list_capabilities', {}),
             ('people_for_capability', {'capability_id': 'C1'}),
             ('draft_request', {'person_ids': ['P1'], 'need': '촉매'})]
    server = ready_server()
    for name, arguments in calls:
        def implementation(**kwargs):
            print('도구 내부 로그')
            assert kwargs == arguments
            return {'status': 'ok', 'message': '한글 결과'}

        with patch.object(agent, '_tools') as tools, patch('sys.stdout', new_callable=io.StringIO) as out, \
                patch('sys.stderr', new_callable=io.StringIO) as err:
            setattr(tools.return_value, name, implementation)
            result = server.handle({'jsonrpc': '2.0', 'id': 5, 'method': 'tools/call',
                                    'params': {'name': name, 'arguments': arguments}})['result']
            assert out.getvalue() == ''
            assert err.getvalue() == '도구 내부 로그\n'
        assert result['structuredContent'] == {'status': 'ok', 'message': '한글 결과'}
        assert result['isError'] is False


def test_tool_exception_does_not_expose_private_exception_text():
    with patch.object(agent, '_tools') as tools, patch('sys.stderr', new_callable=io.StringIO) as err:
        tools.return_value.get_person.side_effect = RuntimeError('private-profile-secret')
        tools.return_value.error_response.return_value = {'status': 'error', 'error': {'code': 'internal_error'}}
        result = agent.call_tool('get_person', {'person_id': 'P1'})
        assert result['error']['code'] == 'internal_error'
        assert 'private-profile-secret' not in err.getvalue()
