"""Google code-flow core candidate. No import-time network or account creation."""
import base64
from dataclasses import dataclass, field
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import tempfile
import time
import urllib.request
from urllib.parse import urlencode, urlsplit
from .account_storage import AccountStorage, AuthError

AUTHORIZATION = 'https://accounts.google.com/o/oauth2/v2/auth'
TOKEN = 'https://oauth2.googleapis.com/token'
JWKS = 'https://www.googleapis.com/oauth2/v3/certs'
ISSUERS = {'https://accounts.google.com', 'accounts.google.com'}


def require(condition, code, status=403):
    if not condition:
        raise AuthError(code, status)


def strict_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'duplicate_json_key')
            result[key] = value
        return result
    try:
        return json.loads(raw, object_pairs_hook=pairs, parse_constant=lambda _: (_ for _ in ()).throw(AuthError('nonfinite_json')))
    except AuthError:
        raise
    except (ValueError, TypeError) as error:
        raise AuthError('invalid_json') from error


def decode_segment(value):
    require(isinstance(value, str) and re.fullmatch('[A-Za-z0-9_-]+', value) is not None, 'jwt_encoding')
    try:
        return base64.urlsafe_b64decode(value + '=' * (-len(value) % 4))
    except ValueError as error:
        raise AuthError('jwt_encoding') from error


def verify_google_token(token, jwks, client_id, nonce, *, now=None):
    """google-auth performs RSA signature/audience/time verification; no custom crypto."""
    now = int(time.time()) if now is None else now
    require(isinstance(token, str) and len(token) <= 16384 and token.count('.') == 2, 'id_token_shape')
    parts = token.split('.')
    header = strict_json(decode_segment(parts[0]))
    require(isinstance(header, dict) and header.get('alg') == 'RS256' and
            isinstance(header.get('kid'), str) and len(header['kid']) <= 200 and
            not any(k in header for k in ('crit', 'jku', 'x5u')), 'id_token_header')
    require(isinstance(jwks, dict) and isinstance(jwks.get('keys'), list) and len(jwks['keys']) <= 32, 'jwks_shape')
    keys = [k for k in jwks['keys'] if isinstance(k, dict) and k.get('kid') == header['kid']]
    require(bool(keys), 'jwks_key_unknown')
    require(len(keys) == 1, 'jwks_key_duplicate')
    key = keys[0]
    require(key.get('kty') == 'RSA' and key.get('use', 'sig') == 'sig' and key.get('alg', 'RS256') == 'RS256' and
            ('key_ops' not in key or key['key_ops'] == ['verify']), 'jwks_key_usage')
    try:
        from google.auth import jwt
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.hazmat.primitives import serialization
    except ImportError as error:
        raise AuthError('verification_dependency_missing', 503) from error
    try:
        require(len(key['n']) <= 1600 and len(key['e']) <= 16, 'jwks_key_size')
        public = rsa.RSAPublicNumbers(int.from_bytes(decode_segment(key['e']), 'big'),
                                     int.from_bytes(decode_segment(key['n']), 'big')).public_key()
        require(2048 <= public.key_size <= 8192, 'jwks_key_size')
        pem = public.public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        claims = jwt.decode(token, certs={header['kid']: pem}, audience=client_id, clock_skew_in_seconds=0)
    except AuthError:
        raise
    except Exception as error:
        raise AuthError('id_token_verification_failed') from error
    # Parse payload strictly too: the verifier library need not reject duplicate keys.
    strict_claims = strict_json(decode_segment(parts[1]))
    require(claims == strict_claims and isinstance(claims, dict), 'id_token_claims_shape')
    require(claims.get('iss') in ISSUERS, 'issuer_mismatch')
    require(claims.get('aud') == client_id, 'audience_mismatch')
    require('azp' not in claims or claims['azp'] == client_id, 'authorized_party_mismatch')
    require(type(claims.get('exp')) is int and claims['exp'] > now and type(claims.get('iat')) is int and claims['iat'] <= now + 30, 'token_time_invalid')
    require('nbf' not in claims or (type(claims['nbf']) is int and claims['nbf'] <= now), 'token_not_yet_valid')
    require(isinstance(claims.get('nonce'), str) and hmac.compare_digest(claims['nonce'], nonce), 'nonce_mismatch')
    sub = claims.get('sub')
    require(isinstance(sub, str) and 1 <= len(sub) <= 255 and sub.isascii() and not any(ord(c) < 33 for c in sub), 'subject_invalid')
    return claims


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args):
        raise AuthError('provider_redirect_rejected', 503)


class GoogleTransport:
    """Fixed Google HTTPS endpoints, TLS defaults, no redirects/proxies or token logs."""
    def __init__(self):
        self._keys, self._keys_until = None, 0

    def _request(self, url, fields=None):
        require(url in (TOKEN, JWKS), 'provider_endpoint_not_allowed')
        data = None if fields is None else urlencode(fields).encode('ascii')
        request = urllib.request.Request(url, data=data, method='GET' if data is None else 'POST',
            headers={'Content-Type': 'application/x-www-form-urlencoded', 'Accept': 'application/json'})
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        try:
            with opener.open(request, timeout=15) as response:
                require(response.status == 200 and response.geturl() == url, 'provider_response_invalid', 503)
                raw = response.read(262145)
                require(len(raw) <= 262144, 'provider_response_too_large', 503)
                return strict_json(raw), response.headers.get('Cache-Control', '')
        except AuthError:
            raise
        except Exception as error:
            raise AuthError('provider_unavailable', 503) from error

    def exchange(self, *, code, verifier, client_id, client_secret, redirect_uri):
        data, _ = self._request(TOKEN, {'code': code, 'code_verifier': verifier, 'client_id': client_id,
            'client_secret': client_secret, 'redirect_uri': redirect_uri, 'grant_type': 'authorization_code'})
        require(isinstance(data, dict) and isinstance(data.get('id_token'), str), 'provider_id_token_missing', 503)
        return data['id_token']  # Access/refresh tokens are discarded, not persisted.

    def keys(self, *, force=False):
        if not force and self._keys is not None and time.time() < self._keys_until:
            return self._keys
        value, cache = self._request(JWKS)
        match = re.search(r'(?:^|,)\s*max-age=(\d+)', cache)
        age = min(int(match.group(1)), 21600) if match else 300
        self._keys, self._keys_until = value, time.time() + age
        return value


@dataclass(frozen=True)
class Config:
    client_id: str
    client_secret: str = field(repr=False)
    redirect_uri: str
    allowed_subs: frozenset


class AuthService:
    SESSION_COOKIE_NAME = '__Host-rndplz_account'
    LOGIN_COOKIE_NAME = '__Host-rndplz_login'

    def __init__(self, config=None, storage=None, transport=None, *, reason='account_not_configured'):
        self.config, self.storage = config, storage
        self.transport = transport or GoogleTransport()
        self.enabled, self.reason = config is not None and storage is not None, reason
        self.storage_deployment_verified = False  # Configuration is not durability evidence.

    @classmethod
    def from_env(cls, env):
        try:
            keys = ('RNDPLZ_GOOGLE_CLIENT_ID', 'RNDPLZ_GOOGLE_CLIENT_SECRET', 'RNDPLZ_GOOGLE_REDIRECT_URI',
                    'RNDPLZ_GOOGLE_ALLOWED_SUBS', 'RNDPLZ_ACCOUNT_DB_PATH', 'RNDPLZ_ACCOUNT_FILES_ROOT',
                    'RNDPLZ_ACCOUNT_TRUSTED_STORAGE_ROOTS')
            require(all(isinstance(env.get(k), str) and env[k] for k in keys), 'account_not_configured', 503)
            redirect = urlsplit(env[keys[2]])
            require(redirect.scheme == 'https' and redirect.netloc and not redirect.username and not redirect.password and
                    not redirect.query and not redirect.fragment and redirect.path == '/auth/google/callback', 'redirect_configuration_invalid', 503)
            if env.get('RNDPLZ_PUBLIC_ORIGIN'):
                require(env['RNDPLZ_PUBLIC_ORIGIN'].rstrip('/') == redirect.scheme + '://' + redirect.netloc, 'redirect_origin_mismatch', 503)
            subs, roots = strict_json(env[keys[3]]), strict_json(env[keys[6]])
            require(isinstance(subs, list) and 0 < len(subs) <= 100 and all(isinstance(s, str) and 1 <= len(s) <= 255 for s in subs), 'team_allowlist_missing', 503)
            require(isinstance(roots, list) and roots and all(isinstance(x, str) and Path(x).is_absolute() and Path(x).is_dir() for x in roots), 'trusted_storage_roots_missing', 503)
            trusted = [Path(x).resolve() for x in roots]
            paths = [Path(env[keys[4]]), Path(env[keys[5]])]
            for p in paths:
                require(p.is_absolute() and any(p.resolve().is_relative_to(r) for r in trusted), 'storage_path_untrusted', 503)
                require(not p.resolve().is_relative_to(Path(tempfile.gettempdir()).resolve()) and
                        not any(part.lower() in ('tmp', 'temp') for part in p.parts), 'ephemeral_storage_rejected', 503)
                for part in (p, *p.parents):
                    if part.exists():
                        require(not part.is_symlink() and not (getattr(part.stat(), 'st_file_attributes', 0) & 0x400), 'linked_storage_rejected', 503)
            # Dependencies must be available before exposing a login button.
            from google.auth import jwt
            from cryptography.hazmat.primitives.asymmetric import rsa
            config = Config(env[keys[0]], env[keys[1]], env[keys[2]], frozenset(subs))
            return cls(config, AccountStorage(*paths), reason='configured_not_deployment_verified')
        except AuthError as error:
            return cls(reason=error.code)
        except ImportError:
            return cls(reason='verification_dependency_missing')
        except Exception:
            return cls(reason='account_configuration_invalid')

    def _enabled(self):
        require(self.enabled, self.reason, 503)

    def begin_login(self, return_path='/'):
        self._enabled()
        require(return_path == '/', 'return_path_not_allowed', 400)
        state, cookie, nonce, verifier = [secrets.token_urlsafe(32) for _ in range(4)]
        self.storage.add_flow(state, cookie, nonce, verifier)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode('ascii')).digest()).rstrip(b'=').decode('ascii')
        params = {'client_id': self.config.client_id, 'redirect_uri': self.config.redirect_uri,
            'response_type': 'code', 'scope': 'openid email profile', 'state': state, 'nonce': nonce,
            'code_challenge': challenge, 'code_challenge_method': 'S256', 'access_type': 'online'}
        return {'authorization_url': AUTHORIZATION + '?' + urlencode(params), 'login_cookie': cookie, 'cookie_max_age': 600}

    def finish(self, code, state, login_cookie, previous_cookie=None):
        self._enabled()
        require(isinstance(code, str) and 1 <= len(code) <= 4096, 'authorization_code_invalid', 400)
        flow = self.storage.consume_flow(state, login_cookie)
        token = self.transport.exchange(code=code, verifier=flow['verifier'], client_id=self.config.client_id,
            client_secret=self.config.client_secret, redirect_uri=self.config.redirect_uri)
        try:
            claims = verify_google_token(token, self.transport.keys(), self.config.client_id, flow['nonce'])
        except AuthError as error:
            if error.code != 'jwks_key_unknown':
                raise
            claims = verify_google_token(token, self.transport.keys(force=True), self.config.client_id, flow['nonce'])
        require(claims['sub'] in self.config.allowed_subs, 'team_member_not_allowed')
        def safe_text(value, limit):
            return ''.join(c for c in value if ord(c) >= 32)[:limit] if isinstance(value, str) else ''
        return self.storage.issue_session(claims['sub'], safe_text(claims.get('name'), 200),
            safe_text(claims.get('email'), 320) if claims.get('email_verified') is True else '', previous_cookie)

    def authenticate(self, cookie):
        if not self.enabled:
            return None
        principal = self.storage.authenticate(cookie)
        if principal is not None:
            try:
                with self.storage.connection() as db:
                    row = self.storage.principal(db, cookie)
                    if row['google_sub'] not in self.config.allowed_subs:
                        return None
            except AuthError:  # Logout may commit between the two reads.
                return None
        return principal

    def logout(self, cookie, csrf):
        self._enabled()
        return self.storage.logout(cookie, csrf)

    def profile_store(self, account_id, session_cookie=None):
        self._enabled()
        if session_cookie is not None:
            principal = self.authenticate(session_cookie)
            require(principal is not None and principal['account']['id'] == account_id, 'account_session_mismatch', 401)
        return self.storage.profile_store(account_id, session_cookie=session_cookie)
