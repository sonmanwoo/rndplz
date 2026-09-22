"""Read one known inert JSON HTML template; never execute or fetch bundle assets."""
from html.parser import HTMLParser
import json
import re

MAX_INPUT_BYTES = 10 * 1024 * 1024
MAX_ENCODED_TEMPLATE_CHARS = 4 * 1024 * 1024
MAX_TEMPLATE_BYTES = 2 * 1024 * 1024
MAX_BUNDLE_TAGS = 64
MAX_TEMPLATE_DEPTH = 1
BUNDLE_LIMIT = 'html_bundle_assets_not_read'


class BundledHTMLError(ValueError):
    def __init__(self, reason):
        self.reason = reason
        super().__init__(reason)


class _TemplateCollector(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.bundle_tags = 0
        self.templates = []
        self.collecting = False
        self.parts = []
        self.length = 0

    def handle_starttag(self, tag, attrs):
        if tag != 'script':
            return
        types = [value or '' for key, value in attrs if key == 'type']
        known = [value for value in types if value.startswith('__bundler/')]
        if not known:
            return
        if len(types) != 1:
            raise BundledHTMLError('invalid')
        self.bundle_tags += 1
        if self.bundle_tags > MAX_BUNDLE_TAGS:
            raise BundledHTMLError('resource_limit')
        if types[0] == '__bundler/template':
            if self.collecting or self.templates:
                raise BundledHTMLError('invalid')
            self.collecting = True
            self.parts = []
            self.length = 0

    def handle_startendtag(self, tag, attrs):
        if tag == 'script' and any(key == 'type' and (value or '').startswith('__bundler/') for key, value in attrs):
            raise BundledHTMLError('invalid')

    def handle_data(self, data):
        if self.collecting:
            self.length += len(data)
            if self.length > MAX_ENCODED_TEMPLATE_CHARS:
                raise BundledHTMLError('resource_limit')
            self.parts.append(data)

    def handle_endtag(self, tag):
        if tag == 'script' and self.collecting:
            self.templates.append(''.join(self.parts))
            self.parts = []
            self.collecting = False


def _scan(text):
    parser = _TemplateCollector()
    parser.feed(text)
    parser.close()
    if parser.collecting:
        raise BundledHTMLError('invalid')
    return parser


def unpack_html_template(raw):
    """Return decoded HTML bytes, or None for ordinary HTML. Exactly one layer."""
    if not isinstance(raw, bytes) or len(raw) > MAX_INPUT_BYTES:
        raise BundledHTMLError('resource_limit')
    # Do not change decoding/validation of ordinary HTML in the existing parser.
    if b'__bundler/' not in raw:
        return None
    try:
        try:
            text = raw.decode('utf-8-sig')
        except UnicodeDecodeError:
            text = raw.decode('cp949')
    except UnicodeError:
        raise BundledHTMLError('invalid') from None
    outer = _scan(text)
    if not outer.bundle_tags:
        return None
    if len(outer.templates) != 1:
        raise BundledHTMLError('unsupported')
    encoded = outer.templates[0].strip()
    # Admit a JSON string only; arrays/objects and their nesting are never parsed.
    if not encoded.startswith('"') or not encoded.endswith('"'):
        raise BundledHTMLError('invalid')
    try:
        template = json.loads(encoded)
        if not isinstance(template, str) or '\x00' in template:
            raise BundledHTMLError('invalid')
        decoded = template.encode('utf-8')
    except (ValueError, UnicodeError):
        raise BundledHTMLError('invalid') from None
    if len(decoded) > MAX_TEMPLATE_BYTES:
        raise BundledHTMLError('resource_limit')
    if not template.strip():
        raise BundledHTMLError('empty')
    # No recursive unwrapping: an inner bundle needs a separately supported format.
    if _scan(template).bundle_tags:
        raise BundledHTMLError('unsupported')
    return decoded


def is_loading_only(text):
    """Reject known loader-only output, without guessing the meaning of prose."""
    labels = {'bundled page', 'loading', 'unpacking',
              'this page requires javascript to display',
              '로딩 중', '불러오는 중', '준비 중'}
    lines = [re.sub(r'[\s.!…]+', ' ', line).strip().casefold()
             for line in text.splitlines() if line.strip()]
    return bool(lines) and all(line in labels for line in lines)
