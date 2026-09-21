"""Native Gemini text generation; one HTTP attempt per product reservation.

Only server-owned contract systems are supplied by ChatModels. JSON MIME is
requested for structured contracts; full schema/evidence enforcement remains
in the existing system instructions and application parsers. No transport retry,
credential file loading, alternate provider, or raw provider-response logging.
"""
import json
import re
import time
import urllib.error
import urllib.request

from .models import NoRedirect


ENDPOINT = 'https://generativelanguage.googleapis.com/v1beta/models/'
MAX_RESPONSE_BYTES = 8 * 1024 * 1024


class GeminiError(ValueError):
    """Safe fixed error text; original provider bodies/headers are not retained."""
    def __init__(self, reason, message, *, http_status=None):
        super().__init__(message)
        self.reason = reason
        self.http_status = http_status


def validate_config(model, key):
    if (not isinstance(model, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,149}', model)
            or not isinstance(key, str) or not 1 <= len(key) <= 500
            or any(ord(c) < 33 or ord(c) > 126 for c in key)):
        raise ValueError('Gemini 모델 ID와 서버 연결 설정을 확인해 주세요.')


def make_payload(messages, *, system, max_tokens, structured):
    if (not isinstance(system, str) or not system.strip()
            or type(max_tokens) is not int or not 1 <= max_tokens <= 8192
            or not isinstance(messages, list)
            or any(not isinstance(row, dict) or row.get('role') not in ('user', 'assistant')
                   or not isinstance(row.get('content'), str) for row in messages)):
        raise ValueError('Gemini 대화 생성 입력 형식이 올바르지 않습니다.')
    config = {'maxOutputTokens': max_tokens}
    if structured:
        config['responseMimeType'] = 'application/json'
    return {'systemInstruction': {'parts': [{'text': system}]},
            'contents': [{'role': 'model' if row['role'] == 'assistant' else 'user',
                          'parts': [{'text': row['content']}]} for row in messages],
            'generationConfig': config}


def _strict_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('duplicate_key')
            result[key] = value
        return result
    def constant(_):
        raise ValueError('invalid_constant')
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)


def completed_text(data, *, structured, max_chars):
    if not isinstance(data, dict) or 'error' in data:
        raise GeminiError('provider_error', 'Gemini가 요청을 처리하지 못했습니다.')
    feedback = data.get('promptFeedback', {})
    if not isinstance(feedback, dict) or feedback.get('blockReason'):
        raise GeminiError('prompt_blocked', 'Gemini가 이 요청에 대한 응답을 거절했습니다.')
    candidates = data.get('candidates')
    if not isinstance(candidates, list) or len(candidates) != 1:
        raise GeminiError('candidate_count', 'Gemini 응답 형식을 확인하지 못했습니다.')
    candidate = candidates[0]
    if not isinstance(candidate, dict) or candidate.get('finishReason') != 'STOP':
        raise GeminiError('incomplete', 'Gemini 응답이 끝까지 생성되지 않았습니다.')
    content = candidate.get('content', {})
    if not isinstance(content, dict) or content.get('role') not in (None, 'model'):
        raise GeminiError('content_role', 'Gemini 응답 형식을 확인하지 못했습니다.')
    parts = content.get('parts')
    if not isinstance(parts, list):
        raise GeminiError('content_parts', 'Gemini 응답 형식을 확인하지 못했습니다.')
    visible = []
    for part in parts:
        if not isinstance(part, dict):
            raise GeminiError('content_part', 'Gemini 응답 형식을 확인하지 못했습니다.')
        if part.get('thought') is True:
            continue  # Do not access thought text/signature.
        if ('thought' in part and type(part['thought']) is not bool) or any(
                key in part for key in ('functionCall', 'inlineData', 'fileData', 'executableCode', 'codeExecutionResult')):
            raise GeminiError('nontext_content', 'Gemini가 요청하지 않은 응답 형식을 반환했습니다.')
        if 'text' in part:
            if not isinstance(part['text'], str):
                raise GeminiError('nontext_content', 'Gemini 응답 형식을 확인하지 못했습니다.')
            visible.append(part['text'])
    text = ''.join(visible)
    if not text.strip() or len(text) > max_chars:
        raise GeminiError('text_limit', 'Gemini 응답이 비어 있거나 허용 길이를 넘었습니다.')
    if structured:
        try:
            if not isinstance(_strict_json(text), dict):
                raise ValueError('object_required')
        except (ValueError, TypeError):
            raise GeminiError('invalid_json', 'Gemini가 유효한 대화 계획 JSON을 반환하지 않았습니다.') from None
    return text


def generate(model, key, payload, *, deadline, structured, max_chars=24000):
    """No retry: a failed HTTP attempt consumes its existing caller reservation."""
    validate_config(model, key)
    def remaining():
        value = min(180, deadline - time.monotonic())
        if value <= 0:
            raise GeminiError('deadline', '이번 대화의 모델 처리 시간을 초과했습니다.')
        return value
    remaining()
    request = urllib.request.Request(ENDPOINT + model + ':generateContent',
        data=json.dumps(payload, ensure_ascii=False, allow_nan=False).encode('utf-8'),
        headers={'Content-Type': 'application/json', 'x-goog-api-key': key}, method='POST')
    try:
        with urllib.request.build_opener(NoRedirect()).open(request, timeout=remaining()) as response:
            if response.status != 200 or 'application/json' not in response.headers.get('Content-Type', '').lower():
                raise GeminiError('response_type', 'Gemini 응답 형식을 확인하지 못했습니다.')
            chunks = []
            size = 0
            while True:
                remaining()
                sock = getattr(getattr(getattr(response, 'fp', None), 'raw', None), '_sock', None)
                if sock is not None:
                    sock.settimeout(remaining())
                chunk = response.read(65536)
                remaining()
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_RESPONSE_BYTES:
                    raise GeminiError('response_size', 'Gemini 응답이 허용 범위를 넘었습니다.')
                chunks.append(chunk)
            try:
                data = _strict_json(b''.join(chunks).decode('utf-8'))
            except (ValueError, UnicodeError, TypeError):
                raise GeminiError('response_json', 'Gemini 응답 형식을 확인하지 못했습니다.') from None
            text = completed_text(data, structured=structured, max_chars=max_chars)
            remaining()
            return text
    except urllib.error.HTTPError as exc:
        status = exc.code
        exc.close()  # Never read/retain provider error prose, headers or credentials.
        if status == 503:
            message = '일시적으로 응답할 수 없습니다. 잠시 후 다시 시도해 주세요.'
        elif status in (401, 403):
            message = 'Gemini 서버 연결 권한을 확인해 주세요.'
        elif status == 429:
            message = 'Gemini의 요청 한도에 도달했습니다. 잠시 후 다시 시도해 주세요.'
        else:
            message = 'Gemini가 요청을 처리하지 못했습니다. 서버 연결 설정을 확인해 주세요.'
        raise GeminiError('http_error', message, http_status=status) from None
    except GeminiError:
        raise
    except Exception:
        raise GeminiError('transport_failure', 'Gemini 연결에 실패했습니다. 연결 상태와 모델 ID를 확인해 주세요.') from None
