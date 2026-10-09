"""Allowlist-backed static versions and bounded public-response gzip caching.

Only callers that have already classified a response as public may use gzip_bytes.
Account/session/bootstrap/chat/profile responses and NDJSON streams must never use
this helper: reflecting input beside secrets would introduce a BREACH oracle.
"""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
import gzip
import hashlib
import html
from html.parser import HTMLParser
from pathlib import Path
import re
import threading
from typing import Callable
from urllib.parse import unquote, unquote_plus, urljoin, urlsplit


MIN_GZIP_BYTES = 1024
_TEXT_MIMES = frozenset({
    'text/html', 'text/css', 'text/javascript', 'application/javascript',
    'application/json', 'image/svg+xml',
})
_ATTR = re.compile(r'''\s+([^\s=/>]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+)))?''')
_CSS_TOKEN = re.compile(
    r'''/\*.*?\*/|(?P<url>url\(\s*(?:"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|[^)"']*)\s*\))'''
    r'''|(?P<import>@import\s+(?:"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'))'''
    r'''|"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*' ''',
    re.IGNORECASE | re.DOTALL | re.VERBOSE,
)


def prefers_gzip(accept_encoding: str) -> bool:
    """Honor explicit gzip/identity weights; implicit identity remains a fallback."""
    weights = {}
    for item in accept_encoding.split(','):
        fields = item.strip().lower().split(';')
        coding = fields[0].strip()
        if not coding:
            continue
        quality = 1.0
        for field in fields[1:]:
            name, separator, value = field.strip().partition('=')
            if name.strip() == 'q' and separator:
                try:
                    quality = float(value.strip())
                except ValueError:
                    quality = 0.0
                if not 0.0 <= quality <= 1.0:
                    quality = 0.0
        # A duplicate explicit refusal wins, rather than accidentally bypassing it.
        weights[coding] = min(weights.get(coding, quality), quality)
    quality = weights.get('gzip', weights.get('*', 0.0))
    return quality > 0 and quality >= weights.get('identity', 0.0)


def is_compressible(mime: str, body: bytes) -> bool:
    """Compress only >=1 KiB public text, never fonts/images/NDJSON or tiny bodies."""
    return len(body) >= MIN_GZIP_BYTES and mime.split(';', 1)[0].strip().lower() in _TEXT_MIMES


@dataclass(frozen=True)
class StaticAsset:
    path: str
    raw: bytes
    body: bytes
    mime: str
    version: str


class _CSSCycle(Exception):
    def __init__(self, paths):
        self.paths = set(paths)


class _HTMLVersions(HTMLParser):
    """Patch attributes in place, preserving markup, whitespace and line endings."""
    def __init__(self, source, version_url):
        super().__init__(convert_charrefs=False)
        self.source = source
        self.version_url = version_url
        self.patches = []
        self.offsets = [0]
        for line in source.splitlines(keepends=True):
            self.offsets.append(self.offsets[-1] + len(line))

    def handle_starttag(self, tag, attrs):
        if tag not in ('script', 'link'):
            return
        attr_values = dict(attrs)
        target = 'src' if tag == 'script' else 'href'
        rel = set((attr_values.get('rel') or '').lower().split())
        if tag == 'link' and not rel.intersection({'stylesheet', 'preload', 'modulepreload'}):
            return
        raw_tag = self.get_starttag_text()
        line, column = self.getpos()
        tag_offset = self.offsets[line - 1] + column
        for match in _ATTR.finditer(raw_tag):
            if match.group(1).lower() != target:
                continue
            group = next((number for number in (2, 3, 4) if match.group(number) is not None), None)
            if group is None:
                return
            original = html.unescape(match.group(group))
            rewritten = self.version_url(original)
            if rewritten == original:
                return
            escaped = html.escape(rewritten, quote=True)
            if group == 4:
                escaped = '"' + escaped + '"'
            self.patches.append((tag_offset + match.start(group), tag_offset + match.end(group), escaped))
            return

    handle_startendtag = handle_starttag

    def rendered(self):
        source = self.source
        for start, end, value in reversed(self.patches):
            source = source[:start] + value + source[end:]
        return source


class StaticAssets:
    """Resolve only existing allowlisted paths; hashes cover served representation.

    Disk bytes are read for each request, so same-size/same-mtime replacements and
    transitive CSS font/image changes invalidate versions immediately. Only gzip
    results are cached, with one digest per path plus global count/byte limits.
    """
    def __init__(self, resolve: Callable[[str], tuple[Path, str] | None], origin: str = '',
                 max_cache_bytes: int = 32 * 1024 * 1024, max_cache_entries: int = 128):
        self.resolve = resolve
        self.origin = urlsplit(origin)
        self.max_cache_bytes = max_cache_bytes
        self.max_cache_entries = max_cache_entries
        self._gzip_cache = OrderedDict()
        self._gzip_cache_bytes = 0
        self._lock = threading.Lock()

    def read(self, path: str) -> StaticAsset | None:
        excluded = set()
        while True:
            try:
                return self._read(path, (), excluded, {})
            except _CSSCycle as cycle:
                # Cyclic stylesheets keep unversioned links (and thus no-store),
                # rather than publishing mutually inconsistent immutable hashes.
                excluded.update(cycle.paths)

    def _read(self, path, stack, excluded, memo):
        if path in memo:
            return memo[path]
        if path in stack:
            raise _CSSCycle(stack[stack.index(path):])
        resolved = self.resolve(path)
        if resolved is None:
            return None
        file_path, mime = resolved
        try:
            raw = file_path.read_bytes()
        except (FileNotFoundError, IsADirectoryError):
            return None
        body = raw
        media_type = mime.split(';', 1)[0].strip().lower()
        version_url = lambda url: self._versioned_url(url, path, stack + (path,), excluded, memo)
        if media_type in ('text/css', 'text/html'):
            source = raw.decode('utf-8')
            if media_type == 'text/css':
                source = self._rewrite_css(source, version_url)
            else:
                parser = _HTMLVersions(source, version_url)
                parser.feed(source)
                parser.close()
                source = parser.rendered()
            body = source.encode('utf-8')
        asset = StaticAsset(path, raw, body, mime, hashlib.sha256(body).hexdigest()[:10])
        memo[path] = asset
        return asset

    def versioned_url(self, url: str, base_path: str) -> str:
        excluded = set()
        while True:
            try:
                return self._versioned_url(url, base_path, (), excluded, {})
            except _CSSCycle as cycle:
                excluded.update(cycle.paths)

    def _versioned_url(self, url, base_path, stack, excluded, memo):
        if not url or url.startswith('#') or '\\' in url:
            return url
        try:
            parts = urlsplit(url)
        except ValueError:
            return url
        if parts.scheme or parts.netloc:
            if not self.origin.netloc or (parts.scheme or self.origin.scheme).lower() != self.origin.scheme.lower():
                return url
            default_port = 443 if self.origin.scheme.lower() == 'https' else 80
            try:
                port, origin_port = parts.port, self.origin.port
            except ValueError:
                return url
            if (parts.hostname != self.origin.hostname or
                    (default_port if port is None else port) !=
                    (default_port if origin_port is None else origin_port)):
                return url
        joined = urlsplit(urljoin(base_path, url))
        path = unquote(joined.path)
        if path in excluded:
            return url
        asset = self._read(path, stack, excluded, memo)
        if asset is None or asset.mime.split(';', 1)[0].strip().lower() == 'text/html':
            return url
        # Keep the original query encoding/order and fragment; replace only v.
        query = [part for part in parts.query.split('&') if part and unquote_plus(part.partition('=')[0]) != 'v']
        query.append('v=' + asset.version)
        return parts._replace(query='&'.join(query)).geturl()

    @staticmethod
    def _rewrite_css(source, version_url):
        def replace(match):
            token = match.group(0)
            if match.group('url') is not None:
                start, end = token.index('(') + 1, token.rfind(')')
                value = token[start:end]
            elif match.group('import') is not None:
                found = re.search(r'''["']''', token)
                start, end = found.start(), len(token)
                value = token[start:end]
            else:
                return token
            leading = len(value) - len(value.lstrip())
            trailing = len(value.rstrip())
            text = value[leading:trailing]
            quote = text[:1] if text[:1] in ('"', "'") else ''
            original = text[1:-1] if quote else text
            rewritten = version_url(original)
            if original == rewritten:
                return token
            return token[:start + leading] + quote + rewritten + quote + token[start + trailing:]
        return _CSS_TOKEN.sub(replace, source)

    def gzip_body(self, asset: StaticAsset, accept_encoding: str) -> bytes | None:
        return self.gzip_bytes(asset.body, asset.mime, accept_encoding, cache_key='static:' + asset.path)

    def gzip_bytes(self, body: bytes, mime: str, accept_encoding: str, *, cache_key: str) -> bytes | None:
        """Return gzip bytes, or None for identity; use only for explicitly public data."""
        if not prefers_gzip(accept_encoding) or not is_compressible(mime, body):
            return None
        digest = hashlib.sha256(body).digest()
        with self._lock:
            cached = self._gzip_cache.pop(cache_key, None)
            if cached is not None:
                self._gzip_cache_bytes -= len(cached[1] or b'')
            if cached is not None and cached[0] == digest:
                encoded = cached[1]
            else:
                encoded = gzip.compress(body, compresslevel=6, mtime=0)
                if len(encoded) >= len(body):
                    encoded = None
            self._gzip_cache[cache_key] = (digest, encoded)
            self._gzip_cache_bytes += len(encoded or b'')
            while (len(self._gzip_cache) > self.max_cache_entries or
                   self._gzip_cache_bytes > self.max_cache_bytes):
                _, (_, discarded) = self._gzip_cache.popitem(last=False)
                self._gzip_cache_bytes -= len(discarded or b'')
            return encoded
