"""Bounded anonymous public HTTPS documents; fetched content is untrusted data.

No browser state, cookies, authorization, proxy credentials, client certificates,
JavaScript, embedded resources, retries, or persistence. The outer worker timeout
covers DNS and slowly delivered HTTP headers as well as the final response body.
"""
from __future__ import annotations

import base64
from datetime import datetime, timezone
import hashlib
from html.parser import HTMLParser
import http.client
import ipaddress
import json
import os
from pathlib import Path
import re
import socket
import ssl
import subprocess
import sys
import time
from urllib.parse import quote, unquote, urljoin, urlsplit, urlunsplit

# The isolated -I -S fetch worker has no package search path. Load only this
# server-owned sibling; URLs, document paths and document text never select it.
if __package__:
    from .bounded_html import BundledHTMLError, unpack_html_template, is_loading_only
else:
    import importlib.util
    _bundle_spec = importlib.util.spec_from_file_location(
        '_rndplz_https_bounded_html', Path(__file__).resolve().with_name('bounded_html.py'))
    _bundle_module = importlib.util.module_from_spec(_bundle_spec)
    _bundle_spec.loader.exec_module(_bundle_module)
    BundledHTMLError = _bundle_module.BundledHTMLError
    unpack_html_template = _bundle_module.unpack_html_template
    is_loading_only = _bundle_module.is_loading_only

MAX_BYTES = 10 * 1024 * 1024
# Preserve extraction inside the deadline worker. Its JSON contains raw base64
# and text: at most six JSON bytes per decoded character, plus bounded metadata.
MAX_WORKER_JSON_BYTES = 4 * ((MAX_BYTES + 2) // 3) + 6 * MAX_BYTES + 32768
TOTAL_SECONDS = 30
MAX_REDIRECTS = 3
MAX_URL = 2048
_MIMES = {
    'text/plain': ('.txt', 'text'), 'text/markdown': ('.md', 'text'),
    'text/x-markdown': ('.md', 'text'), 'text/html': ('.html', 'html'),
    'application/xhtml+xml': ('.html', 'html'), 'application/pdf': ('.pdf', 'pdf'),
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document': ('.docx', 'docx'),
    'application/vnd.openxmlformats-officedocument.presentationml.presentation': ('.pptx', 'pptx'),
}
_ERRORS = {
    'https_invalid_url': '공개 HTTPS 문서 주소를 확인해 주세요.',
    'https_private_address': '공개 인터넷의 HTTPS 문서만 가져올 수 있어요.',
    'https_resolution_failed': '이 링크의 공개 주소를 확인하지 못했어요.',
    'https_redirect_limit': '이 링크의 이동이 너무 많아 가져오지 못했어요.',
    'https_timeout': '링크 자료를 가져오는 시간이 초과됐어요.',
    'https_fetch_failed': '이 링크에서 자료를 가져오지 못했어요.',
    'https_login_required': '로그인 없이 열 수 있는 공개 HTTPS 문서를 사용해 주세요.',
    'https_too_large': '링크 자료가 10MiB를 넘어요.',
    'https_resource_limit': '링크 문서 내부 내용이 안전한 처리 범위를 넘었어요.',
    'https_empty': '이 링크에서 읽을 수 있는 내용을 찾지 못했어요.',
    'https_unsupported_type': '이 링크는 지원하는 문서 형식이 아니에요.',
    'https_invalid_response': '이 링크의 문서 응답을 읽지 못했어요.',
}


class FetchError(ValueError):
    def __init__(self, code):
        self.code = code if code in _ERRORS else 'https_fetch_failed'
        self.status = 400
        super().__init__(_ERRORS[self.code])


def _need(value, code):
    if not value:
        raise FetchError(code)


def _remaining(deadline, clock=time.monotonic):
    left = deadline - clock()
    _need(left > 0, 'https_timeout')
    return left


def _public_ip(value):
    try:
        ip = ipaddress.ip_address(value)
    except ValueError:
        raise FetchError('https_private_address') from None
    _need(ip.is_global and not (ip.is_private or ip.is_loopback or ip.is_link_local
          or ip.is_multicast or ip.is_reserved or ip.is_unspecified), 'https_private_address')
    # No IPv4-through-IPv6 transition addresses that could hide a different target.
    if ip.version == 6:
        _need(ip.ipv4_mapped is None and ip.sixtofour is None and ip.teredo is None,
              'https_private_address')
    return ip


def validate_url(value):
    _need(isinstance(value, str) and 0 < len(value) <= MAX_URL
          and not any(ord(c) <= 32 or ord(c) == 127 for c in value)
          and '\\' not in value, 'https_invalid_url')
    try:
        parts = urlsplit(value)
        _need(parts.scheme == 'https' and bool(parts.hostname) and not parts.fragment
              and parts.username is None and parts.password is None
              and parts.port in (None, 443), 'https_invalid_url')
        host = parts.hostname.encode('idna').decode('ascii').lower()
        _need(not host.endswith('.') and '%' not in host, 'https_invalid_url')
        try:
            ipaddress.ip_address(host)
        except ValueError:
            labels = host.split('.')
            _need(len(labels) >= 2 and len(host) <= 253
                  and all(re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', v) for v in labels)
                  and not host.endswith(('.localhost', '.local', '.internal', '.intranet', '.lan', '.home', '.test', '.invalid'))
                  and not all(re.fullmatch(r'(?:[0-9]+|0x[0-9a-f]+)', label) for label in labels),
                  'https_invalid_url')
        else:
            _public_ip(host)
        authority = '['+host+']' if ':' in host else host
        target = quote(parts.path or '/', safe="/%:@!$&'()*+,;=-._~")
        query = quote(parts.query, safe="/%?:@!$&'()*+,;=-._~")
        return urlunsplit(('https', authority, target, query, '')), host
    except (UnicodeError, ValueError) as exc:
        if isinstance(exc, FetchError):
            raise
        raise FetchError('https_invalid_url') from None


def _resolve(host, deadline):
    _remaining(deadline)
    try:
        answers = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP)
    except OSError:
        raise FetchError('https_resolution_failed') from None
    _remaining(deadline)
    addresses = list(dict.fromkeys(str(_public_ip(row[4][0])) for row in answers))
    _need(bool(addresses), 'https_resolution_failed')
    return addresses


class _PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self, host, address, deadline):
        super().__init__(host, 443, timeout=_remaining(deadline), context=ssl.create_default_context())
        self._address, self._deadline = address, deadline

    def connect(self):
        ip = _public_ip(self._address)
        channel = socket.socket(socket.AF_INET6 if ip.version == 6 else socket.AF_INET, socket.SOCK_STREAM)
        try:
            channel.settimeout(_remaining(self._deadline))
            channel.connect((str(ip), 443))
            _need(ipaddress.ip_address(channel.getpeername()[0]) == ip, 'https_private_address')
            channel.settimeout(_remaining(self._deadline))
            # Verify normal public PKI and hostname while connecting only to the checked IP.
            self.sock = self._context.wrap_socket(channel, server_hostname=self.host)
        except BaseException:
            channel.close()
            raise


class _Reply:
    def __init__(self, connection, response, channel):
        self.connection, self.response, self.channel = connection, response, channel
        self.status = response.status
        self.headers = response.getheaders()

    def read(self, count, deadline):
        self.channel.settimeout(_remaining(deadline))
        return self.response.read1(count)

    def close(self):
        self.response.close()
        self.connection.close()


def _open(url, host, address, deadline):
    conn = _PinnedHTTPS(host, address, deadline)
    try:
        conn.connect()
        channel = conn.sock
        parts = urlsplit(url)
        target = parts.path + ('?'+parts.query if parts.query else '')
        channel.settimeout(_remaining(deadline))
        conn.request('GET', target, headers={
            'Accept': 'text/plain, text/markdown, text/html, application/pdf, application/vnd.openxmlformats-officedocument.wordprocessingml.document, application/vnd.openxmlformats-officedocument.presentationml.presentation',
            'Accept-Encoding': 'identity', 'User-Agent': 'RnDplz-PublicDocument/1.0',
            'Connection': 'close',
        })
        channel.settimeout(_remaining(deadline))
        return _Reply(conn, conn.getresponse(), channel)
    except BaseException:
        conn.close()
        raise


def _header(headers, name):
    values = [value for key, value in headers if key.lower() == name]
    _need(len(values) <= 1, 'https_invalid_response')
    return values[0].strip() if values else ''


def _classify(raw, content_type, final_url):
    mime = content_type.split(';', 1)[0].strip().lower()
    if mime == 'application/octet-stream':
        ext = Path(unquote(urlsplit(final_url).path)).suffix.lower()
        choices = {'.pdf': 'application/pdf', '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                   '.pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation'}
        mime = choices.get(ext, '')
    _need(mime in _MIMES, 'https_unsupported_type')
    ext, kind = _MIMES[mime]
    if kind == 'pdf':
        _need(raw.startswith(b'%PDF-'), 'https_invalid_response')
    elif kind in ('docx', 'pptx'):
        _need(raw.startswith(b'PK\x03\x04'), 'https_invalid_response')
    else:
        _need(b'\0' not in raw, 'https_unsupported_type')
    basename = unquote(urlsplit(final_url).path).rsplit('/', 1)[-1]
    basename = re.sub(r'[\x00-\x1f\x7f/\\:*?"<>|]', '_', basename)[:160]
    if not basename or Path(basename).suffix.lower() != ext:
        basename = (Path(basename).stem or 'https-document')[:140] + ext
    return basename, mime, kind


def _collect(url, *, resolver=_resolve, opener=_open, clock=time.monotonic):
    original = url
    current, _ = validate_url(url)
    deadline = clock() + TOTAL_SECONDS
    visited, redirects = set(), []
    for hop in range(MAX_REDIRECTS+1):
        current, host = validate_url(current)
        _need(current not in visited, 'https_redirect_limit')
        visited.add(current)
        _remaining(deadline, clock)
        addresses = resolver(host, deadline)
        _need(bool(addresses), 'https_resolution_failed')
        # Validate every answer, then connect once to the first pinned address. No address retries.
        for address in addresses:
            _public_ip(address)
        _remaining(deadline, clock)
        reply = opener(current, host, addresses[0], deadline)
        try:
            _remaining(deadline, clock)
            if reply.status in (301, 302, 303, 307, 308):
                _need(hop < MAX_REDIRECTS, 'https_redirect_limit')
                location = _header(reply.headers, 'location')
                _need(bool(location) and len(location) <= MAX_URL, 'https_invalid_response')
                current, _ = validate_url(urljoin(current, location))
                redirects.append(current)
                continue
            _need(reply.status not in (401, 403), 'https_login_required')
            _need(reply.status != 204, 'https_empty')
            _need(reply.status == 200, 'https_fetch_failed')
            _need(_header(reply.headers, 'content-encoding').lower() in ('', 'identity'), 'https_unsupported_type')
            length = _header(reply.headers, 'content-length')
            if length:
                _need(bool(re.fullmatch(r'[0-9]{1,12}', length)), 'https_invalid_response')
                _need(int(length) <= MAX_BYTES, 'https_too_large')
            body = bytearray()
            while True:
                _remaining(deadline, clock)
                chunk = reply.read(min(65536, MAX_BYTES+1-len(body)), deadline)
                _remaining(deadline, clock)
                if not chunk:
                    break
                body.extend(chunk)
                _need(len(body) <= MAX_BYTES, 'https_too_large')
            raw = bytes(body)
            _need(bool(raw), 'https_empty')
            if length:
                _need(len(raw) == int(length), 'https_invalid_response')
            content_type = _header(reply.headers, 'content-type')
            name, mime, kind = _classify(raw, content_type, current)
            result = {'raw': raw, 'name': name, 'mime': mime, 'document_kind': kind,
                      'source': {'kind': 'https_document', 'original_url': original, 'final_url': current,
                                 'acquired_at': datetime.now(timezone.utc).isoformat(),
                                 'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw),
                                 'trust': 'untrusted', 'redirects': redirects}}
            if kind in ('text', 'html'):
                result['text'], bundled = extract_web_text(raw, content_type, _with_bundle_status=True)
                if bundled:result['html_bundle_template'] = True
            return result
        finally:
            reply.close()
    raise FetchError('https_redirect_limit')


class _VisibleText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack, self.output = [], []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        skip = bool(self.stack and self.stack[-1][1]) or tag in {'script', 'style', 'template', 'noscript', 'iframe', 'svg', 'canvas', 'form'}
        skip = skip or 'hidden' in values or values.get('aria-hidden', '').lower() == 'true'
        style = re.sub(r'\s', '', values.get('style', '')).lower()
        skip = skip or 'display:none' in style or 'visibility:hidden' in style
        if tag not in {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'}:
            self.stack.append((tag, skip))
        if not skip and tag in {'p', 'div', 'br', 'li', 'tr', 'h1', 'h2', 'h3', 'h4', 'section', 'article'}:
            self.output.append('\n')

    def handle_endtag(self, tag):
        for index in range(len(self.stack)-1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                break
        if tag in {'p', 'div', 'li', 'tr', 'section', 'article'}:
            self.output.append('\n')

    def handle_data(self, data):
        if not self.stack or not self.stack[-1][1]:
            self.output.append(data)


def extract_web_text(raw, content_type, *, _with_bundle_status=False):
    _need(isinstance(raw, bytes) and len(raw) <= MAX_BYTES and b'\0' not in raw, 'https_unsupported_type')
    match = re.search(r'charset\s*=\s*[\"\']?([a-zA-Z0-9_-]+)', content_type)
    encoding = match.group(1).lower() if match else 'utf-8-sig'
    _need(encoding in {'utf-8', 'utf-8-sig', 'us-ascii', 'ascii', 'euc-kr', 'cp949', 'iso-8859-1', 'windows-1252'}, 'https_unsupported_type')
    try:
        text = raw.decode(encoding)
    except (UnicodeError, LookupError):
        raise FetchError('https_invalid_response') from None
    bundled = False
    if content_type.split(';', 1)[0].strip().lower() in {'text/html', 'application/xhtml+xml'}:
        if '__bundler/' in text:
            try:
                template = unpack_html_template(text.encode('utf-8'))
            except BundledHTMLError as exc:
                code = {'invalid':'https_invalid_response', 'unsupported':'https_unsupported_type',
                        'empty':'https_empty', 'resource_limit':'https_resource_limit'}[exc.reason]
                raise FetchError(code) from None
            if template is not None:
                text = template.decode('utf-8')
                bundled = True
        parser = _VisibleText()
        parser.feed(text)
        parser.close()
        text = re.sub(r'\n[ \t]*\n+', '\n\n', ''.join(parser.output))
    if bundled:
        text = '\n'.join(line.strip() for line in text.splitlines() if line.strip())
        _need(not is_loading_only(text), 'https_unsupported_type')
    text = text.strip()
    _need(bool(text), 'https_empty')
    return (text, bundled) if _with_bundle_status else text


def fetch_document(url):
    """Fetch one explicit URL. Returns data only; caller owns parsing and private storage.

    The worker is killed after the total bound including DNS/header slow delivery.
    No inherited application secrets/proxy credentials are passed to that process.
    """
    validate_url(url)
    environment = {key: os.environ[key] for key in ('SystemRoot', 'WINDIR') if key in os.environ}
    try:
        result = subprocess.run([sys.executable, '-I', '-S', '-B', str(Path(__file__).resolve()), '--fetch-worker'],
                                input=json.dumps({'url': url}).encode('utf-8'), stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, env=environment, timeout=TOTAL_SECONDS, check=False)
        _need(result.returncode == 0 and len(result.stdout) <= MAX_WORKER_JSON_BYTES, 'https_fetch_failed')
        value = json.loads(result.stdout)
        if value.get('error'):
            raise FetchError(value['error'])
        value['raw'] = base64.b64decode(value.pop('raw_base64'), validate=True)
        _need(0 < len(value['raw']) <= MAX_BYTES, 'https_invalid_response')
        return value
    except subprocess.TimeoutExpired:
        raise FetchError('https_timeout') from None
    except FetchError:
        raise
    except Exception:
        raise FetchError('https_fetch_failed') from None


def _worker():
    try:
        payload = json.loads(sys.stdin.buffer.read(MAX_URL*6+64))
        value = _collect(payload['url'])
        value['raw_base64'] = base64.b64encode(value.pop('raw')).decode('ascii')
    except FetchError as exc:
        value = {'error': exc.code}
    except (TimeoutError, socket.timeout):
        value = {'error': 'https_timeout'}
    except Exception:
        value = {'error': 'https_fetch_failed'}
    # Internal parent-worker pipe only, never a diagnostic log or public CLI output.
    sys.stdout.buffer.write(json.dumps(value, ensure_ascii=False).encode('utf-8'))


if __name__ == '__main__':
    if sys.argv[1:] != ['--fetch-worker']:
        raise SystemExit('This module is an attachment collector, not a network test CLI.')
    _worker()
