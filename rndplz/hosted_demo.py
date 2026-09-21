"""Public hosted-demo WSGI admission; no credentials, model calls or I/O.

PublicApp must construct this before its runtime/auth initialization whenever
APP_RUNTIME is hosted_demo, and invoke admit before every existing route.
None means continue through the existing visitor, CSRF and request-slot checks.
This policy does not authenticate visitors and does not replace those checks.
"""

from __future__ import annotations

import ipaddress
import json
import re
from urllib.parse import urlsplit


# Each prefix matches itself or a slash descendant, never a lookalike prefix.
DISABLED_PREFIXES = (
    '/api/operator', '/api/diagnostics', '/api/worker', '/api/bridge',
    '/auth', '/api/auth', '/api/account', '/api/self-profile',
    '/api/admin', '/api/enrollment', '/api/chat/configure',
    '/api/export', '/api/ai',
)
DISABLED_PAGES = frozenset((
    '/profile', '/profile.html', '/account-enroll.html', '/account-enroll.js',
    '/owner/login', '/owner/logout',
))
_DNS_LABEL = re.compile(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\Z')
_STATUS = {200: 'OK', 400: 'Bad Request', 403: 'Forbidden',
           404: 'Not Found', 405: 'Method Not Allowed', 421: 'Misdirected Request'}


def _origin(value):
    """Accept a single explicit HTTPS DNS origin, not paths or credentials."""
    try:
        if not isinstance(value, str) or not value or value != value.strip():
            raise ValueError
        parsed = urlsplit(value)
        if (parsed.scheme != 'https' or parsed.username is not None
                or parsed.password is not None or parsed.path not in ('', '/')
                or parsed.query or parsed.fragment or not parsed.hostname):
            raise ValueError
        host = parsed.hostname
        if (len(host) > 253 or host != host.lower() or '.' not in host
                or not all(_DNS_LABEL.fullmatch(part) for part in host.split('.'))):
            raise ValueError
        try:
            ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            raise ValueError
        port = parsed.port
        if port is not None and not 1 <= port <= 65535:
            raise ValueError
        authority = host if port in (None, 443) else host + ':' + str(port)
        canonical = 'https://' + authority
        allowed = {canonical, canonical + '/'}
        if port in (None, 443):
            allowed.update(('https://' + host + ':443', 'https://' + host + ':443/'))
        if value not in allowed:
            raise ValueError
        return canonical, authority
    except (ValueError, TypeError, AttributeError):
        raise ValueError('Hosted demo requires a fixed HTTPS public origin.') from None


class HostedDemoPolicy:
    """Immutable outer admission policy for a separate public demonstration.

    Existing PublicApp owns visitor/session isolation, CSRF, the four model
    request slots, POST rate limits and body limits. RuntimeChatModels owns its
    atomic process call cap. No overlapping counters or implicit fallback are
    introduced here. Google/account and operator/worker services stay disabled
    regardless of cookies, headers or other environment configuration.
    """

    __slots__ = ('origin', 'authority')

    def __init__(self, env):
        if env.get('APP_RUNTIME') != 'hosted_demo':
            raise ValueError('Hosted demo policy requires hosted_demo runtime.')
        self.origin, self.authority = _origin(env.get('RNDPLZ_PUBLIC_ORIGIN', ''))

    @staticmethod
    def _response(start_response, status, code=None, message=None, *, extra=()):
        value = {'status': 'ok'} if status == 200 else {'error': message, 'code': code}
        body = json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
        headers = [('Content-Type', 'application/json; charset=utf-8'),
                   ('Content-Length', str(len(body))), ('Cache-Control', 'no-store'),
                   ('X-Content-Type-Options', 'nosniff'), ('Referrer-Policy', 'no-referrer'),
                   ('Content-Security-Policy', "default-src 'none'; frame-ancestors 'none'; base-uri 'none'")]
        start_response(str(status) + ' ' + _STATUS[status], headers + list(extra))
        return [body]

    def _host_matches(self, value):
        if not isinstance(value, str) or value != value.strip():
            return False
        expected = {self.authority}
        if ':' not in self.authority:
            expected.add(self.authority + ':443')
        return value.lower() in expected

    def admit(self, environ, start_response):
        """Return a WSGI response if handled, otherwise None for PublicApp.

        Only HTTP_HOST and the configured HTTPS origin determine the origin.
        Forwarded/X-Forwarded-* and REMOTE_ADDR cannot grant access. No request
        body, cookie, authorization header, auth file or model is inspected.
        """
        if not self._host_matches(environ.get('HTTP_HOST', '')):
            return self._response(start_response, 421, 'hosted_demo_host_rejected', '허용되지 않은 서비스 주소입니다.')
        path = environ.get('PATH_INFO', '')
        if (not isinstance(path, str) or not path.startswith('/') or len(path) > 2048
                or '\\' in path or '%' in path or '//' in path
                or any(part in ('.', '..') for part in path.split('/'))
                or any(ord(char) < 32 or ord(char) == 127 for char in path)
                or environ.get('SCRIPT_NAME', '') not in ('',)):
            return self._response(start_response, 400, 'hosted_demo_path_rejected', '요청 주소를 확인해 주세요.')
        if path in DISABLED_PAGES or any(path == prefix or path.startswith(prefix + '/') for prefix in DISABLED_PREFIXES):
            return self._response(start_response, 404, 'hosted_demo_endpoint_disabled', '이 시연에서 제공하지 않는 기능입니다.')
        method = environ.get('REQUEST_METHOD', '')
        if method not in ('GET', 'POST'):
            return self._response(start_response, 405, 'hosted_demo_method_rejected', '지원하지 않는 요청입니다.', extra=(('Allow', 'GET, POST'),))
        origin = environ.get('HTTP_ORIGIN')
        if (origin is not None and origin != self.origin) or (method == 'POST' and origin != self.origin):
            return self._response(start_response, 403, 'hosted_demo_origin_rejected', '허용되지 않는 요청입니다.')
        if path == '/healthz':
            if method != 'GET':
                return self._response(start_response, 405, 'hosted_demo_method_rejected', '지원하지 않는 요청입니다.', extra=(('Allow', 'GET'),))
            if environ.get('QUERY_STRING', ''):
                return self._response(start_response, 400, 'hosted_demo_query_rejected', '요청 주소를 확인해 주세요.')
            return self._response(start_response, 200)
        return None
