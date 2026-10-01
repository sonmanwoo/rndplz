"""Profile drafts. A visitor's or unbound account's draft stays private; a bound account's
saved draft is its map card (person_cards). Document claims reach a draft only through review.

The caller supplies an authorized visitor/account store. Account authentication
and storage selection belong to the server, never the request payload. This
module has no catalog, model, network, or diagnostic-log dependency.
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

from .attachments import Attachments, MAX_BYTES, MAX_FILE_BYTES
from .profile_reading import MAX_PROFILE_TEXT, ReadingError, split_parts


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


def list_items(value):
    """Entries of a list field: one per line when it has lines (a seeded card), else comma/semicolon separated."""
    value = value or ''
    parts = value.split('\n') if '\n' in value else re.split(r'[,;]+', value)
    return [part.strip() for part in parts if part.strip()]


def list_join(entries, like=''):
    """Keep a one-per-line list (or entries that contain commas) one per line."""
    return ('\n' if '\n' in (like or '') or any(',' in entry for entry in entries) else ', ').join(entries)


def _account_metadata(value):
    if value is None:
        return None
    if (not isinstance(value, dict) or set(value) != {'id', 'verified', 'storage_lifetime'} or
            not isinstance(value.get('id'), str) or not re.fullmatch(r'[a-f0-9]{32}', value['id']) or
            value.get('verified') is not True or value.get('storage_lifetime') != 'account_database'):
        raise ProfileError('서버 계정 범위를 확인할 수 없습니다.', code='account_scope')
    return dict(value)


class Profiles:
    """One private draft. `version` guards every profile/source operation.

    Mutations return read() plus `operation`; repeat request IDs return the latest
    view, never an old cached response that could contain a deleted source.
    """

    def __init__(self, store, *, public=False, clock=None, account=None, reader=None, staged=None, card=None):
        self.account = _account_metadata(account)
        # The map card of the person this account is bound to (person_cards.CardBinding): it seeds
        # the draft once, and each saved draft is shown as that card.
        self.card = card if self.account else None
        # Optional Gemma reader (profile_reading.ProfileReader); without it documents are
        # offered as paragraph rows as before.
        self.reader = reader
        # Optional upload_id -> (name, bytes) for documents sent in chunks (the chat's staging).
        self.staged = staged
        self.store = store
        self.public = bool(public)
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.directory = Path(store.directory) / 'self-profile'
        self._check_path(self.directory)
        self._check_path(self.directory / 'attachments')
        # A private profile document is read whole (a 70-page note is ~78k characters);
        # chat attachments keep their own 16k limit.
        self.attachments = Attachments(self.directory, text_limit=MAX_PROFILE_TEXT, unit_floor=20000)

    def _now(self):
        value = self.clock()
        return value.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')

    def _actor(self):
        return self.account['id'] if self.account else ('current_visitor' if self.public else 'local_editor')

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
        if self.account:
            result['scope'] = {
                'kind': 'account_private', 'person_id': None,
                'identity_status': 'google_authenticated', 'person_confirmed': False, 'shared': False,
                'reviewer_label': '계정 사용자가 검토함', 'cookie_lifetime_seconds': None,
                'cross_device_recovery': True, 'permanent_storage': False,
                'storage_lifetime': self.account['storage_lifetime'], 'storage_deployment_verified': False,
                'notice': '같은 Google 계정으로 다시 로그인하면 계정 저장소의 초안을 열 수 있습니다. '
                          'Google 로그인은 경력 진위나 공개 인물과의 연결을 확인하지 않습니다. '
                          '실제 운영 저장소의 지속 보관·첨부 보관 설정은 별도 확인이 필요하며 영구 보관을 보장하지 않습니다.',
            }
        if self._linked(data):
            label = self.card.label
            result['scope'].update(kind='person_card', person_id=self.card.person_id, person_label=label,
                                   person_confirmed=True, shared=True,
                                   notice=f'연구맵의 「{label}」 카드와 연결된 프로필이에요. 저장하면 연구맵 카드·약력·추천 근거에 '
                                          '바로 반영되어 모든 방문자에게 보여요. 자료나 대화로 요청한 변경은 지금 값과 바뀔 값을 '
                                          '먼저 보여 드리고, 확인한 것만 저장해요.')
        result['limits'] = {'file_bytes': MAX_FILE_BYTES,
                            'sources': MAX_SOURCES, 'careers': MAX_CAREERS,
                            'fields': FIELDS, 'career_fields': CAREER_FIELDS,
                            'formats': ['txt', 'md', 'csv', 'json', 'log', 'pdf', 'docx'],
                            'model_calls': 0 if self.reader is None else 'per_part',
                            'extraction': 'paragraph_rules' if self.reader is None else 'model_reading',
                            'text_characters': MAX_PROFILE_TEXT}
        return result

    def read(self):
        data = self._state(self.store.read())
        if self.card is not None and (not data.get('card') or self._stale_seed(data)):
            # Values the account wrote before the link differ from the card and show on it now.
            return self._publish(self._view(self.store.transaction(self._seed)))
        return self._view(data)

    def _linked(self, data):
        return self.card is not None and data.get('card', {}).get('person_id') == self.card.person_id

    def _stale_seed(self, data):
        """Careers still exactly as an earlier seed wrote them (the record text, not the card's timeline lines)."""
        careers = data['profile']['careers']
        return (self._linked(data) and bool(careers) and careers == self.card.legacy_careers()
                and careers != self.card.values()['careers'])

    def _seed(self, state):
        """First open of a bound account: start from the card's own values; written values are kept."""
        data = self._state(state)
        if data.get('card'):
            if self._stale_seed(data):
                profile = data['profile']
                for old, new in zip(profile['careers'], self.card.values()['careers']):
                    if old != new:
                        self._record(data, 'career:' + new['id'], old, new, [], 'card_seed')
                profile['careers'] = self.card.values()['careers']
                profile['version'] += 1
                profile['updated_at'] = self._now()
                for proposal in data['suggestions']:
                    if proposal['decision'] in ('pending', 'deferred', 'excluded'):
                        proposal['base_version'] = profile['version']
                state['self_profile'] = data
            return data
        values, profile, seeded = self.card.values(), data['profile'], False
        origin = {**self._provenance(), 'origin': 'public_card'}
        for key, value in values['fields'].items():
            if value and not profile['fields'][key]:
                self._record(data, key, '', value, [], 'card_seed')
                profile['fields'][key] = value
                profile['provenance'][key] = dict(origin)
                seeded = True
        if not profile['careers'] and values['careers']:
            for row in values['careers']:
                self._record(data, 'career:' + row['id'], None, row, [], 'card_seed')
                profile['provenance']['career:' + row['id']] = dict(origin)
            profile['careers'] = values['careers']
            seeded = True
        data['card'] = {'person_id': self.card.person_id, 'seeded_at': self._now()}
        if seeded:
            profile['id'] = profile['id'] or uuid.uuid4().hex
            profile['version'] += 1
            profile['updated_at'] = self._now()
            # Seeding only fills blanks, so undecided proposals still apply to this draft.
            for proposal in data['suggestions']:
                if proposal['decision'] in ('pending', 'deferred', 'excluded'):
                    proposal['base_version'] = profile['version']
        state['self_profile'] = data
        return data

    def _publish(self, view):
        """A bound account's saved draft is its map card right away."""
        if view.get('scope', {}).get('kind') == 'person_card':
            view['card_update'] = {'person_id': self.card.person_id, 'changed': self.card.publish(view['profile'])}
        return view

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

        return self._publish(self.store.transaction(change))

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
        _keys(payload, ('name', 'data', 'upload_id', 'base_version', 'request_id'))
        if 'upload_id' in payload:
            # One 8 MB request failed from a phone (2026-09-28); chat attachments already went
            # through in 512 KB chunks. The staged file is claimed before the draft is locked.
            if self.staged is None or 'name' in payload or 'data' in payload:
                raise ProfileError('파일 전송 형식을 확인해 주세요.')
            name, raw = self.staged(payload['upload_id'])
            payload = {**{k: v for k, v in payload.items() if k != 'upload_id'},
                       'name': name, 'data': base64.b64encode(raw).decode('ascii')}
        name = _text(payload.get('name'), 240, '파일 이름')
        if Path(name).suffix.lower() not in ('.txt', '.md', '.csv', '.json', '.log', '.pdf', '.docx'):
            raise ProfileError('텍스트·PDF·DOCX 문서를 선택해 주세요. 이미지 속 이력 읽기는 지원하지 않습니다.', code='unsupported')
        encoded = payload.get('data')
        cap = MAX_FILE_BYTES
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

    # ---- Gemma reading: parts are cached beside the draft (not versioned); the merge creates
    # typed proposals in one versioned suggest, so reading progress never moves the profile version.
    def _reading_path(self, source_id):
        return self._check_path(self.directory / 'readings' / (_id(source_id) + '.json'))

    def _reading(self, source):
        path = self._reading_path(source['id'])
        try:
            record = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            record = None
        if (not isinstance(record, dict) or record.get('source_version') != source['version']
                or record.get('text_sha256') != source.get('text_sha256')):
            record = {'source_id': source['id'], 'source_version': source['version'],
                      'text_sha256': source.get('text_sha256'), 'parts': {}}
        return record

    def _snapshot(self, data):
        fields = data['profile']['fields']
        return {'skills': list_items(fields['skills']), 'interests': list_items(fields['interests']),
                'career_titles': [c['title'] for c in data['profile']['careers'] if c.get('title')]}

    def read_part(self, payload):
        _keys(payload, ('source_id', 'part', 'model_id'))
        if self.reader is None:
            raise ProfileError('자료를 읽을 모델이 연결되어 있지 않습니다.', code='model_unavailable', status=503)
        part = payload.get('part')
        if type(part) is not int or part < 1:
            raise ProfileError('읽을 부분을 확인해 주세요.')
        data = self._state(self.store.read())
        source = self._find_source(data, payload.get('source_id'))
        self._path(source['attachment_id'])
        parts = split_parts(self.attachments.load(source['attachment_id'])['text'])
        if part > len(parts):
            raise ProfileError('읽을 부분을 확인해 주세요.')
        record = self._reading(source)
        done = record['parts'].get(str(part))
        if done is None:
            try:
                kept, dropped = self.reader.read_part(payload.get('model_id'), source['name'], parts, part, self._snapshot(data))
            except ReadingError as error:
                raise ProfileError(str(error), code='model_unavailable', status=503) from None
            done = record['parts'][str(part)] = {'kept': kept, 'dropped': dropped}
            path = self._reading_path(source['id'])
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix('.tmp')
            temporary.write_text(json.dumps(record, ensure_ascii=False), encoding='utf-8')
            temporary.replace(path)
        return {'part': part, 'total': len(parts), 'kept': len(done['kept']), 'dropped': done['dropped'],
                'read_parts': len(record['parts']), 'done': len(record['parts']) >= len(parts)}

    def _suggest_from_reading(self, payload):
        identifiers = payload.get('source_ids')
        if not isinstance(identifiers, list) or len(identifiers) != 1 or not isinstance(identifiers[0], str):
            raise ProfileError('읽은 자료 하나를 선택해 주세요.')
        if self.reader is None:
            raise ProfileError('자료를 읽을 모델이 연결되어 있지 않습니다.', code='model_unavailable', status=503)
        data = self._state(self.store.read())
        source = self._find_source(data, identifiers[0])
        self._path(source['attachment_id'])
        text = self.attachments.load(source['attachment_id'])['text']
        total = len(split_parts(text))
        record = self._reading(source)
        if len(record['parts']) < total:
            raise ProfileError('자료를 아직 끝까지 읽지 않았어요. 다시 읽기를 이어가 주세요.', code='reading_incomplete', status=409)
        candidates = [row for key in sorted(record['parts'], key=int) for row in record['parts'][key]['kept']]
        try:
            proposals = self.reader.merge(payload.get('model_id'), candidates, self._snapshot(data), text) if candidates else []
        except ReadingError as error:
            raise ProfileError(str(error), code='model_unavailable', status=503) from None

        def make(data):
            current = self._find_source(data, identifiers[0])
            if current['version'] != source['version']:
                raise ProfileError('자료 버전이 바뀌었습니다. 다시 읽어 주세요.', code='conflict', status=409)
            # Reading again replaces this source's undecided model proposals.
            data['suggestions'] = [p for p in data['suggestions'] if not (
                p['source_id'] == current['id'] and p.get('method') == 'model_reading' and p['decision'] in ('pending', 'deferred'))]
            created = 0
            for item in proposals:
                if len(data['suggestions']) >= MAX_SUGGESTIONS:
                    break
                data['suggestions'].append({'id': uuid.uuid4().hex, 'source_id': current['id'],
                    'source_version': current['version'], 'base_version': data['profile']['version'] + 1,
                    'field': item['field'], 'before': None, 'after': item['after'], 'career': item['career'],
                    'quote': item['quote'], 'evidence': item['evidence'],
                    'location': {'basis': 'extracted_text', 'start': item['start'], 'end': item['end'],
                                 'line': text.count('\n', 0, item['start']) + 1},
                    'origin': 'source_claim', 'method': 'model_reading', 'decision': 'pending',
                    **({'actor': self._actor()} if self.account else {}),
                    'notice': 'Gemma가 자료를 읽고 만든 변경안입니다. 근거 원문과 내 역할을 확인하고 선택해 주세요.'})
                created += 1
            return {'created': created, 'model_calls': total + 1, 'candidates': len(candidates)}

        return self._mutate(payload, 'suggest', make)

    def suggest(self, payload):
        _keys(payload, ('source_ids', 'base_version', 'request_id', 'model_id'))
        if payload.get('model_id') is not None:
            return self._suggest_from_reading(payload)
        identifiers = payload.get('source_ids')
        if not isinstance(identifiers, list) or not 1 <= len(identifiers) <= MAX_SOURCES or any(not isinstance(x, str) for x in identifiers):
            raise ProfileError('변경 후보를 만들 자료를 선택해 주세요.')
        identifiers = list(dict.fromkeys(identifiers))

        def make(data):
            count = 0
            for identifier in identifiers:
                source = self._find_source(data, identifier)
                self._path(source['attachment_id'])
                typed = [p for p in data['suggestions'] if p['source_id'] == identifier and p.get('method') == 'model_reading']
                if typed:
                    # A read document keeps its model proposals; refreshing only re-bases them.
                    for p in typed:
                        if p['decision'] in ('pending', 'deferred', 'excluded'):
                            p['base_version'] = data['profile']['version'] + 1
                            p['source_version'] = source['version']
                    continue
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
                        if self.account:
                            data['suggestions'][-1]['actor'] = self._actor()
                        count += 1
            return {'created': count, 'model_calls': 0}

        return self._mutate(payload, 'suggest', make)

    def _provenance(self, source_ids=(), *, edited=False):
        return {'origin': ('user_edited_source' if edited else 'source_claim') if source_ids else 'user_input',
                'source_ids': list(source_ids), 'review': 'edited_accepted' if edited else 'accepted',
                'reviewer': self._actor(),
                'reviewed_at': self._now(), 'identity_verified': False,
                'evidence_status': 'linked_claim' if source_ids else 'not_provided'}

    def _record(self, data, key, before, after, sources, action):
        data['history'].append({'id': uuid.uuid4().hex, 'version': data['profile']['version'] + 1,
            'at': self._now(), 'actor': self._actor(),
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
        return self._mutate(payload, 'save', lambda data: self._save_into(data, payload))

    def _save_into(self, data, payload):
        """Apply a save payload (edits and review decisions) to the draft `data`."""
        fields = payload.get('fields', {})
        _keys(fields, FIELDS)
        decisions = payload.get('decisions', [])
        if not isinstance(decisions, list) or len(decisions) > MAX_SUGGESTIONS:
            raise ProfileError('검토할 변경 후보를 확인해 주세요.')
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
            if self.account:
                proposal['reviewer'] = self._actor()
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
            # A model proposal for a list field adds one entry, so several may apply together.
            appends = field in ('skills', 'interests') and proposal.get('method') == 'model_reading'
            if target in targets and not appends:
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
                base = existing or {k: '' for k in CAREER_FIELDS}
                typed = proposal.get('career') if not existing and proposal.get('method') == 'model_reading' else None
                if isinstance(typed, dict):
                    # A new career from a model proposal keeps its title, period and role.
                    base = {k: _text(typed.get(k, '') or '', n, k) for k, n in CAREER_FIELDS.items()}
                clean = {**base, 'id': identifier,
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
                if appends:
                    entries = list_items(before)
                    added = _text(value, FIELDS[field], field).strip()
                    value = list_join(entries + ([added] if added not in entries else []), before)
                self._set_field(data, field, value, [source['id']], edited=choice == 'edit')
            proposal.update(field=field, before=before, after=copy.deepcopy(value),
                decision='edited_accepted' if choice == 'edit' else 'accepted',
                target=target, reviewed_at=self._now(), applied_version=profile['version'] + 1,
                lineage_source_ids=list(dict.fromkeys(lineage + [source['id']])))
        return {'saved': True}

    def card_preview(self, payload):
        """The map card as it would look after saving these edits and choices. Nothing is stored."""
        _keys(payload, ('fields', 'careers', 'decisions'))
        data = self._state(self.store.read())
        if not self._linked(data):
            raise ProfileError('연구맵 카드와 연결된 계정에서만 카드를 미리 볼 수 있어요.', code='not_linked', status=409)
        data = copy.deepcopy(data)
        self._save_into(data, payload)
        return {'card': self.card.preview(data['profile'])}

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
