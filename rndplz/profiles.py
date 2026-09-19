"""Private visitor profile drafts; document claims never edit the public corpus.

The caller supplies the current visitor's StateStore. This module has no account,
catalog, model, network, or diagnostic-log dependency. All writes are explicit.
"""
from __future__ import annotations

import base64
import copy
import hashlib
import json
import re
import stat
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .attachments import Attachments, MAX_BYTES


FIELDS = {'name': 120, 'organization': 180, 'role': 180, 'bio': 2000,
          'skills': 4000, 'interests': 2000}
CAREER_FIELDS = {'title': 240, 'organization': 180, 'period': 120,
                 'role': 180, 'description': 4000}
MAX_SOURCES = 12
MAX_CAREERS = 50
MAX_SUGGESTIONS = 160


class ProfileError(ValueError):
    def __init__(self, message, *, code='invalid', status=400):
        super().__init__(message)
        self.code = code
        self.status = status


def _text(value, limit, label):
    if not isinstance(value, str) or len(value) > limit or '\x00' in value:
        raise ProfileError(f'{label}의 형식과 길이를 확인해 주세요.')
    return value.strip()


def _keys(payload, allowed):
    if not isinstance(payload, dict) or set(payload) - set(allowed):
        raise ProfileError('지원하지 않는 프로필 항목이 포함되어 있습니다.')


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':')).encode()).hexdigest()


def _id(value):
    if not isinstance(value, str) or not re.fullmatch(r'[a-f0-9]{32}', value):
        raise ProfileError('자료 또는 항목 식별자를 확인해 주세요.')
    return value


class Profiles:
    """One private draft. `version` guards every profile/source operation.

    Mutations return read() plus `operation`; repeat request IDs return the latest
    view, never an old cached response that could contain a deleted source.
    """

    def __init__(self, store, *, public=False, clock=None):
        self.store = store
        self.public = bool(public)
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.directory = Path(store.directory) / 'self-profile'
        self._check_path(self.directory)
        self._check_path(self.directory / 'attachments')
        self.attachments = Attachments(self.directory)

    def _now(self):
        value = self.clock()
        return value.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')

    def _check_path(self, path):
        base = Path(self.store.directory).resolve()
        path = Path(path)
        if not path.resolve().is_relative_to(base):
            raise ProfileError('프로필 자료 저장 경로를 확인할 수 없습니다.', code='storage')
        for part in (self.directory, self.directory / 'attachments', path):
            if part.exists() or part.is_symlink():
                info = part.lstat()
                if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
                    raise ProfileError('연결된 파일 경로는 사용할 수 없습니다.', code='storage')
        return path

    def _path(self, attachment_id):
        return self._check_path(self.attachments.directory / (_id(attachment_id) + '.json'))

    @staticmethod
    def _empty():
        return {'schema': 1, 'profile': {'id': None, 'version': 0, 'fields': {k: '' for k in FIELDS},
                'careers': [], 'provenance': {}, 'updated_at': None, 'mode': 'unverified'},
                'sources': [], 'suggestions': [], 'history': [], 'requests': {}}

    def _state(self, state):
        data = state.get('self_profile')
        if data is None:
            return self._empty()
        if not isinstance(data, dict) or data.get('schema') != 1:
            raise ProfileError('내 프로필 저장 형식을 확인할 수 없습니다.', code='storage')
        return data

    def _view(self, data):
        result = copy.deepcopy({k: data[k] for k in ('profile', 'sources', 'suggestions', 'history')})
        for event in result['history']:
            _, reason, _ = self._undo_event(data, event['version'])
            event['can_undo'] = not reason
            event['undo_unavailable_reason'] = reason
            # Restore metadata is domain-private, not another copy for old UI cards.
            event.pop('undo_metadata', None)
        for source in result['sources']:
            source['impact'] = {
                'profile_items': [key for key, value in result['profile']['provenance'].items()
                                  if source['id'] in value.get('source_ids', [])],
                'suggestions': sum(p['source_id'] == source['id'] or source['id'] in p.get('lineage_source_ids', [])
                                   for p in result['suggestions']),
                'history_entries': sum(source['id'] in event.get('source_ids', []) for event in result['history']),
                'stored_file': bool(source.get('attachment_id')),
            }
            source.pop('attachment_id', None)
        result['scope'] = {
            'kind': 'visitor_private' if self.public else 'local_private', 'person_id': None,
            'identity_status': 'unlinked', 'person_confirmed': False, 'shared': False,
            'reviewer_label': '이 방문자가 검토함' if self.public else '로컬 편집자가 검토함',
            'cookie_lifetime_seconds': 86400 if self.public else None,
            'cross_device_recovery': False, 'permanent_storage': False,
            'notice': ('이 방문자에게만 저장하는 시연 초안입니다. 실제 계정이나 공개 인물과 연결되지 않습니다. '
                       '쿠키 발급 후 24시간·쿠키 삭제·다른 기기·서버 저장소 초기화 뒤에는 다시 열 수 없습니다. '
                       '접근 만료가 서버 자료 삭제를 뜻하지는 않습니다.') if self.public else
                      '이 로컬 작업 저장소의 초안입니다. 계정 본인 확인·기기 간 복구·영구 보관 기능은 없습니다.',
        }
        result['limits'] = {'file_bytes': 1024 * 1024 if self.public else MAX_BYTES,
                            'sources': MAX_SOURCES, 'careers': MAX_CAREERS,
                            'fields': FIELDS, 'career_fields': CAREER_FIELDS,
                            'formats': ['txt', 'md', 'csv', 'json', 'log', 'pdf', 'docx'],
                            'model_calls': 0, 'extraction': 'paragraph_rules'}
        return result

    def read(self):
        return self._view(self._state(self.store.read()))

    @staticmethod
    def _undo_event(data, version):
        """Describe the narrow single-field undo without mutating the draft."""
        events = [event for event in data['history'] if event['version'] == version]
        receipt = next((item for item in data['requests'].values()
                        if item.get('version') == version), None)
        if not receipt or receipt.get('action') != 'save' or len(events) != 1:
            return None, '기본정보 한 항목을 저장한 변경만 되돌릴 수 있습니다.', 'undo_unavailable'
        event = events[0]
        field = event.get('field')
        if field not in FIELDS or event.get('action') != 'edit':
            return None, '기본정보 한 항목을 저장한 변경만 되돌릴 수 있습니다.', 'undo_unavailable'
        if event.get('redacted'):
            return None, '관련 자료가 삭제되어 이전 값으로 되돌릴 수 없습니다.', 'conflict'
        meta = event.get('undo_metadata')
        if not isinstance(meta, dict):
            return None, '이전 변경에는 되돌리기에 필요한 정보가 없습니다.', 'undo_unavailable'
        if any(item['version'] > version and item.get('field') == field for item in data['history']):
            return None, '이 항목이 이후에 변경되었습니다. 현재 값과 다시 비교해 주세요.', 'conflict'
        profile = data['profile']
        if (profile['fields'][field] != event.get('after') or
                profile['provenance'].get(field) != meta.get('after_provenance')):
            return None, '현재 값이나 출처 상태가 달라졌습니다. 다시 비교해 주세요.', 'conflict'
        sources = {source['id']: source for source in data['sources']}
        for identifier, original in meta['source_versions'].items():
            current = sources.get(identifier)
            if (not current or original.get('status') != 'active' or current['status'] != 'active' or
                    current['version'] != original.get('version')):
                return None, '관련 자료가 삭제·연결 해제·교체되어 되돌릴 수 없습니다.', 'conflict'
        return event, '', None

    def undo(self, payload):
        """Restore one basic value as a new correction, never a whole draft."""
        _keys(payload, ('version', 'base_version', 'request_id'))
        version = payload.get('version')
        if type(version) is not int or version < 1:
            raise ProfileError('되돌릴 저장 버전을 확인해 주세요.')

        def restore(data):
            event, reason, code = self._undo_event(data, version)
            if reason:
                raise ProfileError(reason, code=code, status=409 if code == 'conflict' else 400)
            field = event['field']
            meta = event['undo_metadata']
            self._record(data, field, data['profile']['fields'][field], event['before'],
                         event['source_ids'], 'undo')
            data['history'][-1]['undo_of_version'] = version
            data['history'][-1]['undo_of_event_id'] = event['id']
            data['profile']['fields'][field] = copy.deepcopy(event['before'])
            if meta['before_provenance_present']:
                data['profile']['provenance'][field] = copy.deepcopy(meta['before_provenance'])
            else:
                data['profile']['provenance'].pop(field, None)
            return {'undone_version': version, 'field': field}

        return self._mutate(payload, 'undo', restore)

    def _mutate(self, payload, action, operation):
        request_id = payload.get('request_id')
        if not isinstance(request_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{8,80}', request_id):
            raise ProfileError('저장 요청 식별자를 확인해 주세요.')
        version = payload.get('base_version')
        if type(version) is not int or version < 0:
            raise ProfileError('프로필 기준 버전을 확인해 주세요.')
        fingerprint = _digest({'action': action, 'payload': payload})

        def change(state):
            data = self._state(state)
            old = data['requests'].get(request_id)
            if old:
                if old['digest'] != fingerprint:
                    raise ProfileError('같은 요청 ID에 다른 변경이 있습니다.', code='request_conflict', status=409)
                event_ids = old.get('event_ids', [event['id'] for event in data['history']
                                                  if event['version'] == old['version']])
                return {**self._view(data), 'operation': {'action': action, 'replayed': True,
                        'version': old['version'], 'request_id': request_id, 'event_ids': list(event_ids)}}
            if data['profile']['version'] != version:
                raise ProfileError('다른 변경이 저장되었습니다. 현재 값과 다시 비교해 주세요.', code='conflict', status=409)
            if len(data['requests']) >= 2000:
                raise ProfileError('이 초안의 변경 요청 한도에 도달했습니다.', code='limit', status=429)
            before_profile = copy.deepcopy(data['profile']) if action == 'save' else None
            history_start = len(data['history'])
            detail = operation(data) or {}
            events = data['history'][history_start:]
            if (action == 'save' and len(events) == 1 and events[0].get('field') in FIELDS
                    and events[0].get('action') == 'edit'):
                event = events[0]
                field = event['field']
                sources = {source['id']: source for source in data['sources']}
                event['undo_metadata'] = {
                    'before_provenance_present': field in before_profile['provenance'],
                    'before_provenance': copy.deepcopy(before_profile['provenance'].get(field)),
                    'after_provenance': copy.deepcopy(data['profile']['provenance'].get(field)),
                    'source_versions': {identifier: {
                        'version': sources.get(identifier, {}).get('version'),
                        'status': sources.get(identifier, {}).get('status')}
                        for identifier in event.get('source_ids', [])},
                }
            profile = data['profile']
            profile['id'] = profile['id'] or uuid.uuid4().hex
            profile['version'] += 1
            profile['updated_at'] = self._now()
            event_ids = [event['id'] for event in events]
            data['requests'][request_id] = {'digest': fingerprint, 'action': action,
                                           'version': profile['version'], 'event_ids': event_ids}
            state['self_profile'] = data
            return {**self._view(data), 'operation': {'action': action, 'replayed': False, **detail,
                    'version': profile['version'], 'request_id': request_id, 'event_ids': event_ids}}

        return self.store.transaction(change)

    @staticmethod
    def _find_source(data, identifier, *, readable=False):
        _id(identifier)
        source = next((s for s in data['sources'] if s['id'] == identifier), None)
        if not source or source['status'] in ('deleting', 'deleted'):
            raise ProfileError('이 초안에서 읽을 수 있는 자료가 아닙니다.', code='source_unavailable', status=404)
        if not readable and source['status'] != 'active':
            raise ProfileError('연결 해제되거나 교체된 자료입니다. 새 자료로 검토해 주세요.', code='source_inactive')
        return source

    def source(self, identifier):
        data = self._state(self.store.read())
        source = self._find_source(data, identifier, readable=True)
        self._path(source['attachment_id'])
        item = self.attachments.load(source['attachment_id'])
        return {'source': {k: copy.deepcopy(v) for k, v in source.items() if k != 'attachment_id'},
                'text': item['text'], 'original_stored': False, 'location_basis': 'extracted_text'}

    def upload(self, payload):
        _keys(payload, ('name', 'data', 'base_version', 'request_id'))
        name = _text(payload.get('name'), 240, '파일 이름')
        if Path(name).suffix.lower() not in ('.txt', '.md', '.csv', '.json', '.log', '.pdf', '.docx'):
            raise ProfileError('텍스트·PDF·DOCX 문서를 선택해 주세요. 이미지 속 이력 읽기는 지원하지 않습니다.', code='unsupported')
        encoded = payload.get('data')
        cap = 1024 * 1024 if self.public else MAX_BYTES
        if not isinstance(encoded, str) or len(encoded) > ((cap + 2) // 3) * 4:
            raise ProfileError('자료 용량 제한을 넘었습니다.', code='limit', status=413)
        try:
            raw = base64.b64decode(encoded, validate=True)
        except (ValueError, TypeError):
            raise ProfileError('파일 전송 형식을 확인해 주세요.') from None
        if not raw or len(raw) > cap:
            raise ProfileError('빈 자료이거나 용량 제한을 넘었습니다.', code='limit', status=413)
        original_hash = hashlib.sha256(raw).hexdigest()
        created = []

        def add(data):
            same = next((s for s in data['sources'] if s.get('original_sha256') == original_hash and s['status'] == 'active'), None)
            if same:
                return {'source_id': same['id'], 'duplicate': True}
            if sum(s['status'] != 'deleted' for s in data['sources']) >= MAX_SOURCES:
                raise ProfileError('이 초안의 자료는 12개까지 보관할 수 있습니다.', code='limit', status=429)
            self._check_path(self.attachments.directory)
            item = self.attachments.upload({'name': name, 'data': encoded})
            created.append(item['id'])
            self._path(item['id'])
            loaded = self.attachments.load(item['id'])
            source_id = uuid.uuid4().hex
            data['sources'].append({**item, 'id': source_id, 'attachment_id': item['id'],
                'version': 1, 'status': 'active', 'created_at': self._now(),
                'original_stored': False, 'original_sha256': original_hash,
                'text_sha256': hashlib.sha256(loaded['text'].encode()).hexdigest(),
                'hash_targets': ['original_bytes_not_stored', 'extracted_text'],
                'location_basis': 'extracted_text', 'access': 'private',
                'notice': '문서 원본은 보관하지 않습니다. 추출된 내용만 읽을 수 있습니다.'})
            return {'source_id': source_id, 'duplicate': False}

        try:
            return self._mutate(payload, 'upload', add)
        except Exception:
            for identifier in created:
                self._path(identifier).unlink(missing_ok=True)
            raise

    def suggest(self, payload):
        _keys(payload, ('source_ids', 'base_version', 'request_id'))
        identifiers = payload.get('source_ids')
        if not isinstance(identifiers, list) or not 1 <= len(identifiers) <= MAX_SOURCES or any(not isinstance(x, str) for x in identifiers):
            raise ProfileError('변경 후보를 만들 자료를 선택해 주세요.')
        identifiers = list(dict.fromkeys(identifiers))

        def make(data):
            count = 0
            for identifier in identifiers:
                source = self._find_source(data, identifier)
                self._path(source['attachment_id'])
                text = self.attachments.load(source['attachment_id'])['text']
                known = {(p['source_id'], p['location']['start'], p['location']['end']): p for p in data['suggestions']}
                for line in re.finditer(r'[^\n]+', text):
                    segment = line.group()
                    start = line.start() + len(segment) - len(segment.lstrip())
                    end = line.end() - (len(segment) - len(segment.rstrip()))
                    for offset in range(start, end, 1200):
                        stop = min(end, offset + 1200)
                        old = known.get((identifier, offset, stop))
                        if old:
                            if old['decision'] in ('pending', 'deferred', 'excluded'):
                                old['base_version'] = data['profile']['version'] + 1
                                old['source_version'] = source['version']
                            continue
                        if len(data['suggestions']) >= MAX_SUGGESTIONS:
                            raise ProfileError('변경 후보가 너무 많습니다. 자료의 필요한 부분만 등록해 주세요.', code='limit', status=429)
                        quote = text[offset:stop]
                        data['suggestions'].append({'id': uuid.uuid4().hex, 'source_id': identifier,
                            'source_version': source['version'], 'base_version': data['profile']['version'] + 1,
                            'field': None, 'before': None, 'after': quote, 'quote': quote,
                            'location': {'basis': 'extracted_text', 'start': offset, 'end': stop,
                                         'line': text.count('\n', 0, offset) + 1},
                            'origin': 'source_claim', 'method': 'paragraph_rules',
                            'decision': 'pending', 'notice': '문서 문단입니다. 내 항목인지 확인하고 적용할 종류를 골라 주세요.'})
                        count += 1
            return {'created': count, 'model_calls': 0}

        return self._mutate(payload, 'suggest', make)

    def _provenance(self, source_ids=(), *, edited=False):
        return {'origin': ('user_edited_source' if edited else 'source_claim') if source_ids else 'user_input',
                'source_ids': list(source_ids), 'review': 'edited_accepted' if edited else 'accepted',
                'reviewer': 'current_visitor' if self.public else 'local_editor',
                'reviewed_at': self._now(), 'identity_verified': False,
                'evidence_status': 'linked_claim' if source_ids else 'not_provided'}

    def _record(self, data, key, before, after, sources, action):
        data['history'].append({'id': uuid.uuid4().hex, 'version': data['profile']['version'] + 1,
            'at': self._now(), 'actor': 'current_visitor' if self.public else 'local_editor',
            'action': action, 'field': key, 'before': copy.deepcopy(before),
            'after': copy.deepcopy(after), 'source_ids': list(dict.fromkeys(sources))})

    def _set_field(self, data, field, value, sources=(), *, edited=False):
        profile = data['profile']
        value = _text(value, FIELDS[field], field)
        before = profile['fields'][field]
        previous = profile['provenance'].get(field, {})
        if before == value and not sources:
            return
        # A typed edit of a derived value keeps its lineage; relabeling does not erase it.
        lineage = list(sources or previous.get('source_ids', []))
        self._record(data, field, before, value, lineage + previous.get('source_ids', []), 'edit')
        profile['fields'][field] = value
        profile['provenance'][field] = self._provenance(lineage, edited=edited or (bool(lineage) and not sources))

    def save(self, payload):
        _keys(payload, ('fields', 'careers', 'decisions', 'base_version', 'request_id'))
        fields = payload.get('fields', {})
        _keys(fields, FIELDS)
        decisions = payload.get('decisions', [])
        if not isinstance(decisions, list) or len(decisions) > MAX_SUGGESTIONS:
            raise ProfileError('검토할 변경 후보를 확인해 주세요.')

        def apply(data):
            profile = data['profile']
            targets = set()
            for field, value in fields.items():
                if value != profile['fields'][field]:
                    targets.add(field)
                self._set_field(data, field, value)
            if 'careers' in payload:
                rows = payload['careers']
                if not isinstance(rows, list) or len(rows) > MAX_CAREERS:
                    raise ProfileError('경력 항목은 50개까지 작성할 수 있습니다.')
                old = {r['id']: r for r in profile['careers']}
                new = []
                seen = set()
                for row in rows:
                    _keys(row, ('id', *CAREER_FIELDS))
                    identifier = row.get('id') or uuid.uuid4().hex
                    _id(identifier)
                    if row.get('id') and identifier not in old:
                        raise ProfileError('이 초안의 경력 항목이 아닙니다.')
                    if identifier in seen:
                        raise ProfileError('경력 항목이 중복되었습니다.')
                    seen.add(identifier)
                    clean = {'id': identifier, **{k: _text(row.get(k, ''), n, k) for k, n in CAREER_FIELDS.items()}}
                    key = 'career:' + identifier
                    if old.get(identifier) != clean:
                        targets.add(key)
                        sources = profile['provenance'].get(key, {}).get('source_ids', [])
                        self._record(data, key, old.get(identifier), clean, sources, 'edit')
                        profile['provenance'][key] = self._provenance(sources, edited=bool(sources))
                    new.append(clean)
                for identifier, row in old.items():
                    if identifier not in seen:
                        key = 'career:' + identifier
                        targets.add(key)
                        self._record(data, key, row, None, profile['provenance'].get(key, {}).get('source_ids', []), 'remove_item')
                        profile['provenance'].pop(key, None)
                profile['careers'] = new
            seen_decisions = set()
            for decision in decisions:
                _keys(decision, ('id', 'decision', 'field', 'value', 'item_id'))
                identifier = _id(decision.get('id'))
                if identifier in seen_decisions:
                    raise ProfileError('같은 변경 후보가 중복되었습니다.')
                seen_decisions.add(identifier)
                proposal = next((p for p in data['suggestions'] if p['id'] == identifier), None)
                choice = decision.get('decision')
                if not proposal or proposal['decision'] in ('accepted', 'edited_accepted', 'redacted', 'withdrawn'):
                    raise ProfileError('현재 검토할 수 있는 변경 후보가 아닙니다.')
                if choice not in ('accept', 'edit', 'exclude', 'defer'):
                    raise ProfileError('채택·수정·제외·보류 중에서 선택해 주세요.')
                if choice in ('exclude', 'defer'):
                    proposal['decision'] = 'excluded' if choice == 'exclude' else 'deferred'
                    proposal['reviewed_at'] = self._now()
                    continue
                source = self._find_source(data, proposal['source_id'])
                if proposal['base_version'] != profile['version']:
                    raise ProfileError('후보 생성 뒤 프로필이 바뀌었습니다. 자료에서 변경 후보를 다시 열어 비교해 주세요.', code='conflict', status=409)
                if proposal['source_version'] != source['version']:
                    raise ProfileError('자료 버전이 바뀌었습니다. 변경 후보를 다시 만들어 주세요.', code='conflict', status=409)
                field = decision.get('field')
                if field not in (*FIELDS, 'career'):
                    raise ProfileError('변경 후보를 적용할 항목을 선택해 주세요.')
                value = decision.get('value', proposal['after']) if choice == 'edit' else proposal['after']
                target = field if field != 'career' else 'career:' + (decision.get('item_id') or uuid.uuid4().hex)
                if target in targets:
                    raise ProfileError('같은 항목에 여러 변경이 있습니다. 한 값을 선택해 주세요.', code='conflict', status=409)
                targets.add(target)
                if field == 'career':
                    identifier = _id(target.split(':', 1)[1])
                    existing = next((r for r in profile['careers'] if r['id'] == identifier), None)
                    if decision.get('item_id') and not existing:
                        raise ProfileError('이 초안의 경력 항목이 아닙니다.')
                    if not existing and len(profile['careers']) >= MAX_CAREERS:
                        raise ProfileError('경력 항목은 50개까지 작성할 수 있습니다.')
                    before = copy.deepcopy(existing)
                    clean = {**(existing or {k: '' for k in CAREER_FIELDS}), 'id': identifier,
                             'description': _text(value, 4000, '경력 설명')}
                    if existing:
                        existing.update(clean)
                    else:
                        profile['careers'].append(clean)
                    lineage = profile['provenance'].get(target, {}).get('source_ids', [])
                    self._record(data, target, before, clean, lineage + [source['id']], 'adopt')
                    profile['provenance'][target] = self._provenance(list(dict.fromkeys(lineage + [source['id']])), edited=choice == 'edit')
                else:
                    before = profile['fields'][field]
                    lineage = profile['provenance'].get(field, {}).get('source_ids', [])
                    self._set_field(data, field, value, [source['id']], edited=choice == 'edit')
                proposal.update(field=field, before=before, after=copy.deepcopy(value),
                    decision='edited_accepted' if choice == 'edit' else 'accepted',
                    target=target, reviewed_at=self._now(), applied_version=profile['version'] + 1,
                    lineage_source_ids=list(dict.fromkeys(lineage + [source['id']])))
            return {'saved': True}

        return self._mutate(payload, 'save', apply)

    def _withdraw(self, data, source_id, *, delete=False):
        profile = data['profile']
        impacted = []
        for key, provenance in profile['provenance'].items():
            if source_id not in provenance.get('source_ids', []):
                continue
            impacted.append(key)
            provenance.update(evidence_status='source_deleted' if delete else 'requires_review', review='needs_review')
            if delete:
                if key.startswith('career:'):
                    profile['careers'] = [r for r in profile['careers'] if 'career:' + r['id'] != key]
                else:
                    profile['fields'][key] = ''
        for proposal in data['suggestions']:
            if proposal['source_id'] == source_id or (delete and source_id in proposal.get('lineage_source_ids', [])):
                proposal['decision'] = 'redacted' if delete else 'withdrawn'
                if delete:
                    proposal['redaction_reason'] = 'related_source_deleted'
                    for key in ('quote', 'before', 'after'):
                        proposal[key] = None
        if delete:
            for event in data['history']:
                if source_id in event.get('source_ids', []):
                    event.update(before=None, after=None, redacted=True)
                    event.pop('undo_metadata', None)
        self._record(data, 'source:' + source_id, None, None, [source_id], 'delete_source' if delete else 'unlink_source')
        return impacted

    def source_action(self, payload):
        _keys(payload, ('id', 'action', 'replacement_id', 'base_version', 'request_id'))
        identifier = _id(payload.get('id'))
        action = payload.get('action')
        if action not in ('delete', 'unlink', 'replace'):
            raise ProfileError('자료 동작을 확인해 주세요.')

        def change(data):
            pending = next((s for s in data['sources']
                            if s['id'] == identifier and s['status'] == 'deleting'), None)
            if action == 'delete' and pending:
                # A reopened page has no original request ID. Its explicit new
                # request still passes the latest-version guard in _mutate;
                # resume file cleanup without replaying withdrawal or content.
                return {'source_id': identifier, 'resuming': True,
                        'affected_items': [key for key, value in data['profile']['provenance'].items()
                                           if identifier in value.get('source_ids', [])]}
            source = self._find_source(data, identifier, readable=True)
            if action == 'replace':
                replacement = self._find_source(data, payload.get('replacement_id'))
                if replacement['id'] == identifier:
                    raise ProfileError('다른 새 자료를 선택해 주세요.')
                replacement['previous_id'] = identifier
                replacement['version'] = source['version'] + 1
                source['replacement_id'] = replacement['id']
                source['status'] = 'replaced'
            else:
                source['status'] = 'deleting' if action == 'delete' else 'unlinked'
            source['changed_at'] = self._now()
            impact = self._withdraw(data, identifier, delete=action == 'delete')
            if action == 'delete':
                attachment_id = source['attachment_id']
                source_version = source['version']
                source.clear()
                source.update(id=identifier, version=source_version, status='deleting', attachment_id=attachment_id,
                              name='삭제한 자료', original_stored=False, changed_at=self._now())
            return {'source_id': identifier, 'affected_items': impact}

        result = self._mutate(payload, 'source_' + action, change)
        # First persist the tombstone and remove all derived text. Failed unlink
        # cannot make the file readable again. An explicit delete retry resumes.
        if action == 'delete':
            data = self._state(self.store.read())
            source = next(s for s in data['sources'] if s['id'] == identifier)
            if source['status'] == 'deleting':
                try:
                    self._path(source['attachment_id']).unlink(missing_ok=True)
                except OSError:
                    result['operation']['deletion_pending'] = True
                    return result
                def finish(state):
                    data = self._state(state)
                    source = next(s for s in data['sources'] if s['id'] == identifier)
                    source.pop('attachment_id', None)
                    source['status'] = 'deleted'
                    source['deleted_at'] = self._now()
                    state['self_profile'] = data
                self.store.transaction(finish)
                result = {**self.read(), 'operation': {**result['operation'], 'deletion_pending': False}}
        return result
