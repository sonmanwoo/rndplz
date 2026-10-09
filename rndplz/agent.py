"""수소문의 로컬 명령행과 줄 단위 JSON-RPC MCP 입구 (표준 라이브러리만 사용)."""
from __future__ import annotations

import argparse
from contextlib import redirect_stdout
import json
import sys
from typing import Any, TextIO

from . import __version__


PROTOCOL_VERSIONS = ('2025-11-25', '2025-06-18')


def _schema(properties: dict, required: tuple = ()) -> dict:
    return {'type': 'object', 'properties': properties, 'required': list(required),
            'additionalProperties': False}


_NONEMPTY = {'type': 'string', 'minLength': 1, 'pattern': r'\S'}
TOOL_DEFINITIONS = [
    {'name': 'find_people', 'description': '연구 문제와 공개 근거가 연결되는 사람을 찾습니다. 연락 가능성과 협업 의사는 미확인입니다.',
     'inputSchema': _schema({'query': {**_NONEMPTY, 'maxLength': 20000, 'description': '함께 풀 연구 문제'},
                             'limit': {'type': 'integer', 'minimum': 1, 'maximum': 50, 'default': 5}}, ('query',))},
    {'name': 'get_person', 'description': '공개된 사람 카드와 경력·기술·근거 기록을 확인합니다.',
     'inputSchema': _schema({'person_id': {**_NONEMPTY, 'maxLength': 300, 'description': '공개 사람 ID'}}, ('person_id',))},
    {'name': 'get_record', 'description': '공개 근거 기록의 상세 내용과 출처를 확인합니다.',
     'inputSchema': _schema({'record_id': {**_NONEMPTY, 'maxLength': 300, 'description': '공개 근거 기록 ID'}}, ('record_id',))},
    {'name': 'list_capabilities', 'description': '연구 맵의 역량 목록과 각 역량에 연결된 공개 사람 수를 확인합니다.',
     'inputSchema': _schema({})},
    {'name': 'people_for_capability', 'description': '선택한 연구 역량에 연결된 공개 사람과 근거 수를 확인합니다.',
     'inputSchema': _schema({'capability_id': {**_NONEMPTY, 'maxLength': 300, 'description': '연구 맵 역량 ID'}}, ('capability_id',))},
    {'name': 'draft_request', 'description': '공개 사람에게 보낼 결정적 의뢰 초안을 만듭니다. 저장·발송하지 않으며 사람이 수소문 화면에서 확인·발송해야 합니다.',
     'inputSchema': _schema({'person_ids': {'type': 'array', 'items': {**_NONEMPTY, 'maxLength': 300},
                                           'minItems': 1, 'maxItems': 7, 'uniqueItems': True},
                             'need': {**_NONEMPTY, 'maxLength': 20000, 'description': '도움이 필요한 연구 문제'},
                             'requester_note': {'type': 'string', 'maxLength': 20000, 'default': '', 'description': '의뢰자 참고 사항'}},
                            ('person_ids', 'need'))},
]
for _definition in TOOL_DEFINITIONS:
    _definition['annotations'] = {'readOnlyHint': True, 'destructiveHint': False,
                                  'idempotentHint': True, 'openWorldHint': False}


def _tools():
    # Import and corpus loading cannot write incidental messages to protocol stdout.
    with redirect_stdout(sys.stderr):
        from . import agent_tools
    return agent_tools


def _error(code: str, message: str) -> dict:
    with redirect_stdout(sys.stderr):
        return _tools().error_response(code, message)


def _argument_error(name: str, arguments: Any) -> str | None:
    definition = next((tool for tool in TOOL_DEFINITIONS if tool['name'] == name), None)
    if definition is None:
        return '알 수 없는 도구입니다.'
    if not isinstance(arguments, dict):
        return '도구 인자는 JSON 객체여야 합니다.'
    schema = definition['inputSchema']
    if set(arguments) - set(schema['properties']):
        return '정의되지 않은 도구 인자가 있습니다.'
    if any(key not in arguments for key in schema['required']):
        return '필수 도구 인자가 빠졌습니다.'
    for key, value in arguments.items():
        spec = schema['properties'][key]
        kind = spec['type']
        if kind == 'string' and (not isinstance(value, str) or (spec.get('minLength') and not value.strip())):
            return f'{key} 인자는 ' + ('비어 있지 않은 문자열이어야 합니다.' if spec.get('minLength') else '문자열이어야 합니다.')
        if kind == 'string' and len(value) > spec['maxLength']:
            return f'{key} 인자는 {spec["maxLength"]}자 이하여야 합니다.'
        if kind == 'integer' and (type(value) is not int or not spec['minimum'] <= value <= spec['maximum']):
            return f'{key} 인자는 {spec["minimum"]}~{spec["maximum"]} 사이의 정수여야 합니다.'
        if kind == 'array' and (not isinstance(value, list) or not spec['minItems'] <= len(value) <= spec['maxItems']
                                or any(not isinstance(item, str) or not item.strip() or len(item) > 300 for item in value)
                                or len({item.strip() for item in value}) != len(value)):
            return f'{key} 인자는 1~{spec["maxItems"]}개의 중복 없는 문자열 배열이며 각 항목은 1~300자여야 합니다.'
    return None


def call_tool(name: str, arguments: Any) -> dict:
    """CLI와 MCP가 동일한 엄격 입력 검사와 도구 함수를 사용한다."""
    problem = _argument_error(name, arguments)
    if problem:
        return _error('invalid_arguments', problem)
    try:
        with redirect_stdout(sys.stderr):
            return getattr(_tools(), name)(**arguments)
    except Exception:
        # Do not expose source paths, private data or caller values from exceptions.
        print('수소문 도구 처리 중 내부 오류가 발생했습니다.', file=sys.stderr)
        return _error('internal_error', '도구를 처리하지 못했습니다. 로컬 말뭉치와 설정을 확인해 주세요.')


class _ArgumentError(Exception):
    pass


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise _ArgumentError('명령 또는 인자가 올바르지 않습니다. --help로 사용법을 확인해 주세요.')


def _output_options(parser: argparse.ArgumentParser) -> None:
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--text', action='store_true', default=argparse.SUPPRESS, help='한국어 요약 출력')
    mode.add_argument('--json', action='store_false', dest='text', default=argparse.SUPPRESS, help='JSON 출력 (기본값)')


def _parser() -> argparse.ArgumentParser:
    parser = _Parser(prog='python -m rndplz.agent', description='공개 근거로 함께 풀 사람을 찾는 수소문 로컬 도구')
    _output_options(parser)
    commands = parser.add_subparsers(dest='command', required=True, title='명령')
    find = commands.add_parser('find-people', help='문제로 사람 찾기')
    find.add_argument('query', help='함께 풀 연구 문제')
    find.add_argument('--limit', type=int, default=5, help='최대 결과 수 (1~50, 기본 5)')
    person = commands.add_parser('person', help='공개 사람 카드 확인')
    person.add_argument('person_id', metavar='ID')
    record = commands.add_parser('record', help='공개 근거 기록 확인')
    record.add_argument('record_id', metavar='ID')
    capabilities = commands.add_parser('capabilities', help='역량 목록 확인')
    capability = commands.add_parser('capability', help='역량에 연결된 사람 확인')
    capability.add_argument('capability_id', metavar='ID')
    draft = commands.add_parser('draft', help='의뢰 초안 작성 (저장·발송 없음)')
    draft.add_argument('--to', required=True, help='사람 ID (여러 명은 쉼표로 구분)')
    draft.add_argument('--need', required=True, help='도움이 필요한 문제')
    draft.add_argument('--requester-note', default='', help='의뢰자 참고 사항')
    for command in (find, person, record, capabilities, capability, draft):
        _output_options(command)
    commands.add_parser('mcp', help='표준 입출력 MCP 서버 실행')
    return parser


_LABELS = {
    'schema_version': '응답 형식 버전', 'pool_version': '공개 풀 버전', 'generated_at': '생성 시각',
    'status': '상태', 'error': '오류', 'code': '오류 코드', 'message': '안내', 'notice': '고지',
    'notices': '고지', 'disclaimer': '고지', 'query': '질문', 'people': '사람', 'person': '사람 카드',
    'record': '근거 기록', 'records': '근거 기록', 'evidence': '연결 근거', 'capabilities': '역량 목록',
    'capability': '역량', 'id': 'ID', 'name': '이름', 'display_name': '표시명', 'secondary_name': '보조 이름',
    'aliases': '별칭', 'affiliation': '소속', 'organization': '소속', 'field': '분야', 'fields': '분야',
    'explanation': '연결 이유', 'reason': '연결 이유', 'reasons': '연결 이유', 'title': '제목', 'year': '연도',
    'kind': '근거 종류', 'kind_name': '근거 종류', 'source_url': '출처 주소', 'source': '출처', 'sources': '출처',
    'url': '주소', 'role': '직위', 'bio': '소개', 'biography': '소개', 'skills': '기술', 'interests': '관심',
    'careers': '경력', 'projects': '프로젝트', 'people_count': '사람 수', 'evidence_count': '근거 수',
    'record_count': '근거 수', 'draft': '의뢰 초안', 'drafts': '의뢰 초안', 'subject': '제목', 'body': '본문', 'instruction': '안내',
    'handoff': '사람에게 넘기기', 'need': '도움이 필요한 문제', 'person_ids': '수신 사람 ID',
    'guidance': '안내', 'label': '이름', 'description': '설명', 'summary': '요약', 'name_ko': '한글 이름',
    'availability': '연락·가용성 확인 범위', 'collaboration': '협업 확인 범위', 'clarification': '추가 확인 질문',
    'closest_topics': '관련 연구 분야', 'proposal_allowed': '의뢰 대상 규칙 통과',
    'proposal_unavailable_reason': '의뢰 제한 안내', 'date': '기록 시점', 'scope': '근거 범위',
    'evidence_label': '근거 종류 설명', 'checked_at': '자료 조회 기준일', 'boundary': '근거의 한계',
    'classification_basis': '근거 분류 기준', 'publication_type': '출판물 유형', 'access': '확인 자료 범위',
    'person_confirmed': '당사자 확인 여부', 'virtual': '가상 기록 여부', 'text': '내용', 'details': '상세',
    'person_id': '사람 ID', 'period': '기간', 'outcome': '성과', 'status_note': '상태 설명',
    'question': '질문', 'options': '선택지', 'slot': '확인 항목', 'mode': '요청 유형', 'org': '소속',
    'profile_topics': '연구 분야', 'metadata_sources': '서지 정보 출처', 'access_level': '확인 수준',
    'record_id': '근거 기록 ID', 'corresponding': '교신 저자 여부', 'tags': '연구 분야 ID',
}


def format_text(result: dict) -> str:
    """공개 카드 핵심 값과 근거·한계·출처를 읽기 쉽게 요약한다."""
    lines = ['수소문 결과']

    def show(value: Any, depth: int = 0, label: str = '') -> None:
        prefix = '  ' * depth
        if isinstance(value, dict):
            if label:
                lines.append(f'{prefix}{label}:')
            for key, item in value.items():
                # The expanded person fields already contain the card profile.
                # Rendering raw profile a second time hides the useful summary
                # behind portrait metadata and other web presentation settings.
                if key in ('profile', 'scope_key', 'evidence_kind'):
                    continue
                if key == 'org' and 'organization' in value:
                    continue
                if key == 'profile_topics' and 'skills' in value:
                    continue
                show(item, depth + bool(label), _LABELS.get(key, key))
        elif isinstance(value, list):
            lines.append(f'{prefix}{label}: ' + ('없음' if not value else ''))
            for number, item in enumerate(value, 1):
                show(item, depth + 1, str(number))
        else:
            if value is None:
                rendered = '없음'
            elif type(value) is bool:
                rendered = '예' if value else '아니요'
            else:
                rendered = str(value)
            if label == '상태':
                rendered = {'ok': '완료', 'error': '오류', 'no_results': '결과 없음',
                            'ambiguous': '문제 구체화 필요', 'needs_clarification': '문제 구체화 필요'}.get(rendered, rendered)
            elif label == '요청 유형':
                rendered = {'advice': '자문', 'verify': '근거 검증', 'member': '프로젝트 참여',
                            'site_request': '현장 검토', 'resource_request': '자원 요청'}.get(rendered, rendered)
            elif label == '근거 종류':
                rendered = {'paper': '논문', 'patent': '특허', 'career': '경력', 'project': '프로젝트',
                            'site': '현장 기록', 'unknown': '미확인'}.get(rendered, rendered)
            lines.append(f'{prefix}{label}: {rendered}')

    metadata = ('notices', 'schema_version', 'pool_version', 'generated_at')
    show({**({'status': result['status']} if 'status' in result else {}),
          **{key: value for key, value in result.items() if key not in (*metadata, 'status')},
          **{key: result[key] for key in metadata if key in result}})
    return '\n'.join(lines)


def _rpc_error(request_id: Any, code: int, message: str) -> dict:
    return {'jsonrpc': '2.0', 'id': request_id, 'error': {'code': code, 'message': message}}


def _tool_result(result: dict) -> dict:
    return {'content': [{'type': 'text', 'text': json.dumps(result, ensure_ascii=False, allow_nan=False)}],
            'structuredContent': result, 'isError': result.get('status') == 'error'}


class MCPServer:
    """네트워크·상태 디렉터리 없이 한 프로세스에서 처리하는 MCP 세션."""

    def __init__(self) -> None:
        self.protocol_version: str | None = None
        self.initialized = False

    def handle(self, request: Any) -> dict | None:
        valid_id = lambda value: isinstance(value, str) or type(value) is int
        if (not isinstance(request, dict) or request.get('jsonrpc') != '2.0'
                or not isinstance(request.get('method'), str)
                or ('id' in request and not valid_id(request['id']))):
            return _rpc_error(None, -32600, '올바른 JSON-RPC 2.0 요청이 아닙니다.')
        method = request['method']
        params = request.get('params', {})
        if 'id' not in request:
            # Notifications never receive replies and cannot invoke a tool.
            if method == 'notifications/initialized' and self.protocol_version and isinstance(params, dict):
                self.initialized = True
            return None
        request_id = request['id']
        if not isinstance(params, dict):
            if method == 'tools/call':
                return {'jsonrpc': '2.0', 'id': request_id,
                        'result': _tool_result(_error('invalid_arguments', '도구 호출 인자는 JSON 객체여야 합니다.'))}
            return _rpc_error(request_id, -32602, 'params는 JSON 객체여야 합니다.')
        if method == 'initialize':
            if self.protocol_version:
                return _rpc_error(request_id, -32600, '이미 초기화된 세션입니다.')
            version = params.get('protocolVersion')
            client = params.get('clientInfo')
            if (not isinstance(version, str) or not version
                    or not isinstance(params.get('capabilities'), dict)
                    or not isinstance(client, dict)
                    or any(not isinstance(client.get(key), str) or not client[key] for key in ('name', 'version'))):
                return _rpc_error(request_id, -32602, 'protocolVersion, capabilities, clientInfo가 필요합니다.')
            self.protocol_version = version if version in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0]
            result = {'protocolVersion': self.protocol_version, 'capabilities': {'tools': {'listChanged': False}},
                      'serverInfo': {'name': 'susomun', 'version': __version__},
                      'instructions': '공개 근거를 확인하고 사람에게 전달하세요. 연락 가능성과 협업 의사는 미확인이며, 초안의 확인·발송은 사람이 수소문 화면에서 합니다.'}
        elif method == 'ping':
            result = {}
        elif method in ('tools/list', 'tools/call'):
            if not self.initialized:
                return _rpc_error(request_id, -32000, 'initialize 뒤 notifications/initialized를 보내 주세요.')
            if method == 'tools/list':
                if set(params) - {'_meta'} or ('_meta' in params and not isinstance(params['_meta'], dict)):
                    return _rpc_error(request_id, -32602, '지원하지 않는 도구 목록 인자입니다.')
                result = {'tools': TOOL_DEFINITIONS}
            else:
                name = params.get('name')
                if (not isinstance(name, str) or set(params) - {'name', 'arguments', '_meta'}
                        or ('_meta' in params and not isinstance(params['_meta'], dict))):
                    result = _tool_result(_error('invalid_arguments', '도구 이름과 인자 형식을 확인해 주세요.'))
                elif name not in {tool['name'] for tool in TOOL_DEFINITIONS}:
                    return _rpc_error(request_id, -32602, '알 수 없는 도구입니다.')
                else:
                    result = _tool_result(call_tool(name, params.get('arguments', {})))
        else:
            return _rpc_error(request_id, -32601, '알 수 없는 메서드입니다.')
        return {'jsonrpc': '2.0', 'id': request_id, 'result': result}


def _check_unicode(value: Any) -> None:
    """Reject lone surrogates accepted by json.loads, including object keys."""
    if isinstance(value, str):
        value.encode('utf-8', errors='strict')
    elif isinstance(value, dict):
        for key, item in value.items():
            _check_unicode(key)
            _check_unicode(item)
    elif isinstance(value, list):
        for item in value:
            _check_unicode(item)


def serve_mcp(input_stream: TextIO | None = None, output_stream: TextIO | None = None) -> int:
    input_stream = input_stream or sys.stdin
    output_stream = output_stream or sys.stdout
    server = MCPServer()

    def invalid_constant(value: str) -> None:
        raise ValueError('표준 JSON 숫자가 아닙니다.')

    # TextIOWrapper may decode a whole buffer before yielding its first line.
    # Decode the raw lines separately so one malformed UTF-8 message cannot
    # discard adjacent requests or terminate the session.
    lines = getattr(input_stream, 'buffer', input_stream)
    for line in lines:
        try:
            if isinstance(line, bytes):
                line = line.decode('utf-8', errors='strict')
            request = json.loads(line, parse_constant=invalid_constant)
            _check_unicode(request)
        except (ValueError, RecursionError):
            response = _rpc_error(None, -32700, 'JSON을 해석하지 못했습니다.')
        else:
            try:
                response = server.handle(request)
            except Exception:
                print('수소문 MCP 요청 처리 중 내부 오류가 발생했습니다.', file=sys.stderr)
                request_id = request.get('id') if isinstance(request, dict) else None
                response = _rpc_error(request_id, -32603, '요청을 처리하지 못했습니다.')
        if response is not None:
            try:
                rendered = json.dumps(response, ensure_ascii=False, allow_nan=False) + '\n'
                # Validate before writing any part of the protocol message.
                rendered.encode('utf-8', errors='strict')
            except (ValueError, RecursionError):
                print('수소문 MCP 응답을 JSON으로 표현하지 못했습니다.', file=sys.stderr)
                response = _rpc_error(request.get('id') if isinstance(request, dict) else None,
                                      -32603, '응답을 처리하지 못했습니다.')
                rendered = json.dumps(response, ensure_ascii=False) + '\n'
            output_stream.write(rendered)
            output_stream.flush()
    return 0


def main(argv: list[str] | None = None) -> int:
    # Windows redirected pipes otherwise use the local ANSI codepage.
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    try:
        args = _parser().parse_args(argv)
    except _ArgumentError as exc:
        print(json.dumps(_error('invalid_arguments', str(exc)), ensure_ascii=False))
        return 2
    if args.command == 'mcp':
        if getattr(args, 'text', False):
            print(json.dumps(_error('invalid_arguments', 'MCP는 JSON-RPC 메시지만 출력합니다.'), ensure_ascii=False))
            return 2
        return serve_mcp()
    if args.command == 'find-people':
        name, arguments = 'find_people', {'query': args.query, 'limit': args.limit}
    elif args.command == 'person':
        name, arguments = 'get_person', {'person_id': args.person_id}
    elif args.command == 'record':
        name, arguments = 'get_record', {'record_id': args.record_id}
    elif args.command == 'capabilities':
        name, arguments = 'list_capabilities', {}
    elif args.command == 'capability':
        name, arguments = 'people_for_capability', {'capability_id': args.capability_id}
    else:
        name, arguments = 'draft_request', {'person_ids': [item.strip() for item in args.to.split(',')],
                                            'need': args.need, 'requester_note': args.requester_note}
    result = call_tool(name, arguments)
    # Invalid arguments always have a machine-readable JSON error, even with --text.
    if getattr(args, 'text', False) and result.get('status') != 'error':
        print(format_text(result))
    else:
        print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    return 1 if result.get('status') == 'error' else 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (BrokenPipeError, KeyboardInterrupt):
        raise SystemExit(0)
