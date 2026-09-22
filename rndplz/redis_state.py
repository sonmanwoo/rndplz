"""Opt-in shared visitor state. No automatic migration, retry, or local fallback."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import secrets
import time
import urllib.parse
import urllib.request
from pathlib import Path

_ERROR = '공유 저장소를 확인할 수 없습니다. 저장 작업을 중단했습니다.'
_BUSY = '다른 저장 작업이 진행 중입니다. 잠시 후 다시 시도해 주세요.'
_MAX_BYTES = 8_000_000
_LEASE_MS = 120_000
_READ = "return {redis.call('EXISTS',KEYS[2]),redis.call('GET',KEYS[1]) or false}"
_COMMIT = """if redis.call('GET',KEYS[1]) ~= ARGV[1] or redis.call('PTTL',KEYS[1]) <= 0 or redis.call('EXISTS',KEYS[3]) ~= 0 then return 0 end
redis.call('SET',KEYS[2],ARGV[2]); redis.call('DEL',KEYS[1]); return 1"""
_RELEASE = "if redis.call('GET',KEYS[1]) == ARGV[1] then return redis.call('DEL',KEYS[1]) end return 0"
_REVOKE = """if redis.call('EXISTS',KEYS[2]) ~= 0 then return 0 end
local raw=redis.call('GET',KEYS[3])
if raw then
 local ok,s=pcall(cjson.decode,raw)
 if not ok or type(s) ~= 'table' or s.version ~= 1 or type(s.sessions) ~= 'table' or type(s.proposals) ~= 'table' then return -1 end
 for _,rows in ipairs({s.sessions,s.proposals}) do
  local count=0
  for k,row in pairs(rows) do
   if type(k) ~= 'number' or k < 1 or k % 1 ~= 0 or type(row) ~= 'table' then return -1 end
   count=count+1
  end
  if count ~= #rows then return -1 end
 end
 for _,session in ipairs(s.sessions) do
  if session.pending ~= nil and session.pending ~= cjson.null and session.pending ~= false then return 0 end
 end
end
redis.call('SET',KEYS[1],'1'); return 1"""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(_ERROR)
        result[key] = value
    return result


def _loads(raw):
    def invalid(_):
        raise ValueError(_ERROR)
    return json.loads(raw, object_pairs_hook=_pairs, parse_constant=invalid)


def _validate(state):
    if (not isinstance(state, dict) or type(state.get('version')) is not int
            or state['version'] != 1
            or not all(isinstance(state.get(k), list) for k in ('sessions', 'proposals'))
            or not all(isinstance(row, dict) for k in ('sessions', 'proposals') for row in state[k])
            or not isinstance(state.get('idempotency', {}), dict)):
        raise ValueError(_ERROR)
    return state


class RedisStateStore:
    shared = True

    def __init__(self, directory, env):
        self.directory = Path(directory)
        self.path = self.directory / 'state.json'
        pairs = [(env.get(url, ''), env.get(token, '')) for url, token in (
            ('UPSTASH_REDIS_REST_URL', 'UPSTASH_REDIS_REST_TOKEN'),
            ('KV_REST_API_URL', 'KV_REST_API_TOKEN'))]
        configured = [pair for pair in pairs if any(pair)]
        if len(configured) != 1:
            raise ValueError(_ERROR)
        endpoint, token = configured[0]
        namespace = env.get('RNDPLZ_STATE_NAMESPACE', '')
        try:
            parsed = urllib.parse.urlsplit(endpoint)
            valid = (isinstance(endpoint, str) and len(endpoint) <= 2048
                     and parsed.scheme == 'https' and parsed.hostname
                     and parsed.username is None and parsed.password is None
                     and parsed.port in (None, 443) and parsed.path in ('', '/')
                     and not parsed.query and not parsed.fragment
                     and all(32 < ord(c) < 127 for c in endpoint)
                     and isinstance(token, str) and 1 <= len(token) <= 8192
                     and all(32 < ord(c) < 127 for c in token)
                     and isinstance(namespace, str)
                     and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}', namespace))
        except Exception:
            valid = False
        if not valid:
            raise ValueError(_ERROR) from None
        self._endpoint = endpoint.rstrip('/')
        self._token = token
        identity = os.path.normcase(os.path.abspath(os.fspath(self.directory)))
        digest = hashlib.sha256(identity.encode('utf-8')).hexdigest()
        prefix = 'rndplz:{' + namespace + ':' + digest + '}'
        self._state_key, self._lock_key, self._revoked_key = (
            prefix + ':state', prefix + ':lock', prefix + ':revoked')

    def _command(self, command, timeout=5.0):
        try:
            body = json.dumps(command, ensure_ascii=False, allow_nan=False,
                              separators=(',', ':')).encode('utf-8')
            if len(body) > _MAX_BYTES or timeout <= 0:
                raise ValueError(_ERROR)
            request = urllib.request.Request(self._endpoint, data=body, method='POST',
                headers={'Authorization': 'Bearer ' + self._token, 'Content-Type': 'application/json'})
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
            with opener.open(request, timeout=min(float(timeout), 5.0)) as response:
                if response.status != 200:
                    raise ValueError(_ERROR)
                raw = response.read(_MAX_BYTES + 1)
            if len(raw) > _MAX_BYTES:
                raise ValueError(_ERROR)
            value = _loads(raw)
            if not isinstance(value, dict) or set(value) != {'result'}:
                raise ValueError(_ERROR)
            return value['result']
        except Exception:
            raise ValueError(_ERROR) from None

    def read(self):
        try:
            response = self._command(['EVAL', _READ, 2, self._state_key, self._revoked_key])
            if (not isinstance(response, list) or len(response) != 2
                    or type(response[0]) is not int or response[0] != 0):
                raise ValueError(_ERROR)
            raw = response[1]
            if raw is None:
                return {'version': 1, 'sessions': [], 'proposals': [], 'idempotency': {}}
            if not isinstance(raw, str) or len(raw.encode('utf-8')) > _MAX_BYTES:
                raise ValueError(_ERROR)
            return _validate(_loads(raw))
        except Exception:
            raise ValueError(_ERROR) from None

    def transaction(self, fn):
        token = secrets.token_hex(32)
        deadline = time.monotonic() + 3.0
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ValueError(_BUSY)
            acquired = self._command(['SET', self._lock_key, token, 'NX', 'PX', _LEASE_MS], timeout=remaining)
            if acquired == 'OK':
                break
            if acquired is not None:
                raise ValueError(_ERROR)
            time.sleep(min(.03, max(0, deadline - time.monotonic())))
        committed = False
        try:
            state = copy.deepcopy(self.read())
            result = fn(state)
            _validate(state)
            try:
                serialized = json.dumps(state, ensure_ascii=False, allow_nan=False, separators=(',', ':'))
                too_large = len(serialized.encode('utf-8')) > _MAX_BYTES
            except Exception:
                raise ValueError(_ERROR) from None
            if too_large:
                raise ValueError(_ERROR)
            committed = self._command(['EVAL', _COMMIT, 3, self._lock_key,
                                       self._state_key, self._revoked_key, token, serialized])
            if type(committed) is not int or committed != 1:
                committed = False
                raise ValueError(_ERROR)
            return result
        finally:
            if not committed:
                # A failed/ambiguous commit is never retried. Release only our lease.
                try:
                    self._command(['EVAL', _RELEASE, 1, self._lock_key, token])
                except ValueError:
                    pass

    def is_revoked(self):
        value = self._command(['GET', self._revoked_key])
        if value not in (None, '1'):
            raise ValueError(_ERROR)
        return value == '1'

    def revoke(self):
        value = self._command(['EVAL', _REVOKE, 3, self._revoked_key, self._lock_key, self._state_key])
        if type(value) is not int or value not in (0, 1):
            raise ValueError(_ERROR)
        return value == 1
