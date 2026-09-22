"""Immutable, chunked chat attachments in the existing visitor Redis namespace."""
from __future__ import annotations

import hashlib
import json
import re
import secrets
import time

from .redis_state import _BUSY, _ERROR, _LEASE_MS, _RELEASE, _loads

_CHUNK_CHARS = 1_000_000
_MAX_CHARS = 16_000_000
_MAX_BYTES = 20_000_000
_MAX_CHUNKS = 16
_STAGING_SECONDS = 600
_COUNT_LIMIT = 12
_COUNT = "if redis.call('EXISTS',KEYS[1]) ~= 0 then return -1 end return redis.call('SCARD',KEYS[2])"
_STAGE = """if redis.call('GET',KEYS[1]) ~= ARGV[1] or redis.call('PTTL',KEYS[1]) <= 0 or redis.call('EXISTS',KEYS[2]) ~= 0 then return 0 end
if redis.call('SET',KEYS[3],ARGV[2],'NX','EX',600) then return 1 end return 0"""
_PUBLISH = """if redis.call('GET',KEYS[1]) ~= ARGV[1] or redis.call('PTTL',KEYS[1]) <= 0 or redis.call('EXISTS',KEYS[2]) ~= 0 then return 0 end
if redis.call('SCARD',KEYS[3]) >= 12 then return 2 end
if redis.call('EXISTS',KEYS[4]) ~= 0 or redis.call('SISMEMBER',KEYS[3],ARGV[3]) ~= 0 then return 0 end
for i=5,#KEYS do if redis.call('EXISTS',KEYS[i]) ~= 1 or redis.call('TTL',KEYS[i]) <= 0 then return 0 end end
for i=5,#KEYS do redis.call('PERSIST',KEYS[i]) end
redis.call('SET',KEYS[4],ARGV[2]); redis.call('SADD',KEYS[3],ARGV[3]); redis.call('DEL',KEYS[1]); return 1"""
_READ = """if redis.call('EXISTS',KEYS[1]) ~= 0 then return {0,false} end
if redis.call('SISMEMBER',KEYS[2],ARGV[1]) ~= 1 then return {0,false} end
return {1,redis.call('GET',KEYS[3]) or false}"""
_FINAL_READ = """if redis.call('EXISTS',KEYS[1]) ~= 0 or redis.call('SISMEMBER',KEYS[2],ARGV[1]) ~= 1 then return 0 end
if redis.call('GET',KEYS[3]) ~= ARGV[2] then return 0 end return 1"""


def _sha(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def _identifier(value):
    return isinstance(value, str) and re.fullmatch(r'[a-f0-9]{32}', value) is not None


def _item(value, identifier):
    if (not isinstance(value, dict) or not _identifier(identifier) or value.get('id') != identifier
            or not isinstance(value.get('name'), str) or not 0 < len(value['name']) <= 240
            or type(value.get('size')) is not int or not 0 < value['size'] <= 10 * 1024 * 1024
            or not isinstance(value.get('text'), str) or len(value['text']) > 16000
            or not isinstance(value.get('image'), str) or len(value['image']) > 13_981_016
            or type(value.get('truncated')) is not bool
            or value.get('mime') not in ('', 'image/png', 'image/jpeg', 'image/webp')
            or (not value['image'] and not value['text'].strip())
            or (bool(value['image']) != bool(value['mime']))):
        raise ValueError(_ERROR)
    return value


class RedisAttachments:
    """Explicitly injected into Conversation; Profiles keeps its local default."""
    def __init__(self, store):
        self.store = store
        self.prefix = store._key_prefix + ':attachments'
        self.index = self.prefix + ':index'

    def _manifest_key(self, identifier):
        return self.prefix + ':' + identifier + ':manifest'

    def _chunk_keys(self, identifier, generation, count):
        return [self.prefix + ':' + identifier + ':' + generation + ':' + str(i) for i in range(count)]

    def count(self):
        value = self.store._command(['EVAL', _COUNT, 2, self.store._revoked_key, self.index])
        if type(value) is not int or not 0 <= value <= _COUNT_LIMIT:
            raise ValueError(_ERROR)
        return value

    def put(self, item):
        try:
            identifier = item.get('id') if isinstance(item, dict) else None
            _item(item, identifier)
            encoded = json.dumps(item, ensure_ascii=False, allow_nan=False, separators=(',', ':'))
            byte_count = len(encoded.encode('utf-8'))
            if len(encoded) > _MAX_CHARS or byte_count > _MAX_BYTES:
                raise ValueError(_ERROR)
            chunks = [encoded[i:i + _CHUNK_CHARS] for i in range(0, len(encoded), _CHUNK_CHARS)]
            generation = secrets.token_hex(16)
            chunk_keys = self._chunk_keys(identifier, generation, len(chunks))
            manifest = {'version': 1, 'id': identifier, 'generation': generation,
                        'sha256': _sha(encoded), 'utf8_bytes': byte_count, 'characters': len(encoded),
                        'chunk_count': len(chunks), 'chunk_chars': [len(c) for c in chunks],
                        'chunk_sha256': [_sha(c) for c in chunks]}
            manifest_json = json.dumps(manifest, sort_keys=True, separators=(',', ':'))
        except Exception:
            raise ValueError(_ERROR) from None
        token = secrets.token_hex(32)
        deadline = time.monotonic() + 3
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ValueError(_BUSY)
            acquired = self.store._command(['SET', self.store._lock_key, token, 'NX', 'PX', _LEASE_MS], timeout=remaining)
            if acquired == 'OK':
                break
            if acquired is not None:
                raise ValueError(_ERROR)
            time.sleep(min(.03, max(0, deadline - time.monotonic())))
        try:
            # Same lease as StateStore.transaction/revoke: another instance cannot
            # start/finish a chat between this pending check and fenced publish.
            state = self.store.read()
            if any(session.get('pending') for session in state['sessions']):
                raise ValueError(_BUSY)
            if self.count() >= _COUNT_LIMIT:
                return False
            for key, chunk in zip(chunk_keys, chunks):
                result = self.store._command(['EVAL', _STAGE, 3, self.store._lock_key,
                                             self.store._revoked_key, key, token, chunk])
                if type(result) is not int or result != 1:
                    raise ValueError(_ERROR)
            keys = [self.store._lock_key, self.store._revoked_key, self.index,
                    self._manifest_key(identifier)] + chunk_keys
            result = self.store._command(['EVAL', _PUBLISH, len(keys), *keys,
                                         token, manifest_json, identifier])
            if type(result) is not int or result not in (1, 2):
                raise ValueError(_ERROR)
            return result == 1
        finally:
            # Commit may have succeeded despite a lost response. Never delete chunks here.
            # Unpublished chunks expire; published chunks have no TTL.
            try:
                self.store._command(['EVAL', _RELEASE, 1, self.store._lock_key, token])
            except ValueError:
                pass

    def _read(self, identifier, key):
        result = self.store._command(['EVAL', _READ, 3, self.store._revoked_key, self.index, key, identifier])
        if (not isinstance(result, list) or len(result) != 2 or type(result[0]) is not int
                or result[0] != 1 or not isinstance(result[1], str)):
            raise ValueError(_ERROR)
        return result[1]

    def load(self, identifier):
        try:
            if not _identifier(identifier):
                raise ValueError(_ERROR)
            manifest_key = self._manifest_key(identifier)
            raw_manifest = self._read(identifier, manifest_key)
            if len(raw_manifest) > 8192:
                raise ValueError(_ERROR)
            m = _loads(raw_manifest)
            fields = {'version', 'id', 'generation', 'sha256', 'utf8_bytes', 'characters',
                      'chunk_count', 'chunk_chars', 'chunk_sha256'}
            if (not isinstance(m, dict) or set(m) != fields or type(m['version']) is not int or m['version'] != 1
                    or m['id'] != identifier or not _identifier(m['generation'])
                    or type(m['chunk_count']) is not int or not 1 <= m['chunk_count'] <= _MAX_CHUNKS
                    or type(m['characters']) is not int or not 1 <= m['characters'] <= _MAX_CHARS
                    or type(m['utf8_bytes']) is not int or not 1 <= m['utf8_bytes'] <= _MAX_BYTES
                    or not isinstance(m['chunk_chars'], list) or len(m['chunk_chars']) != m['chunk_count']
                    or not all(type(n) is int and 1 <= n <= _CHUNK_CHARS for n in m['chunk_chars'])
                    or sum(m['chunk_chars']) != m['characters']
                    or not isinstance(m['chunk_sha256'], list) or len(m['chunk_sha256']) != m['chunk_count']
                    or not all(isinstance(s, str) and re.fullmatch(r'[a-f0-9]{64}', s)
                               for s in m['chunk_sha256'] + [m['sha256']])):
                raise ValueError(_ERROR)
            chunks = []
            for i, key in enumerate(self._chunk_keys(identifier, m['generation'], m['chunk_count'])):
                chunk = self._read(identifier, key)
                if len(chunk) != m['chunk_chars'][i] or _sha(chunk) != m['chunk_sha256'][i]:
                    raise ValueError(_ERROR)
                chunks.append(chunk)
            encoded = ''.join(chunks)
            if len(encoded.encode('utf-8')) != m['utf8_bytes'] or _sha(encoded) != m['sha256']:
                raise ValueError(_ERROR)
            item = _item(_loads(encoded), identifier)
            result = self.store._command(['EVAL', _FINAL_READ, 3, self.store._revoked_key,
                                         self.index, manifest_key, identifier, raw_manifest])
            if type(result) is not int or result != 1:
                raise ValueError(_ERROR)
            return item
        except Exception:
            raise ValueError(_ERROR) from None
