"""Explicit self-profile actions in a chat, independent of model conversation.

Only generic labels and receipt references enter the transcript. Profile values
are always read from the current, redaction-aware private Profiles view.
"""
import copy
import hashlib
import json
import re
import uuid

from .profiles import ProfileError
from .service import now


LABELS = {'이름': 'name', '소속': 'organization', '역할': 'role', '직무': 'role',
          '소개': 'bio', '자기소개': 'bio', '전문분야': 'skills', '전문 분야': 'skills',
          '기술': 'skills', '스킬': 'skills', '관심분야': 'interests', '관심 분야': 'interests'}
FIELD_PATTERN = '|'.join(sorted(map(re.escape, LABELS), key=len, reverse=True))


def command(text):
    """Conservative imperative grammar; facts, quotations and guesses do not save."""
    if not isinstance(text, str) or len(text) > 16000:
        raise ProfileError('프로필 요청의 길이를 확인해 주세요.')
    value = text.strip().rstrip('.!').strip()
    if re.search(r'[\n?？"“”‘’`]|(?:만약|예를\s*들|가정|하지\s*마|지\s*않|안\s*바꿔|라고)', value):
        return None
    if re.fullmatch(r'(?:내|제)\s*프로필(?:을|은)?\s*(?:보여\s*줘|보여주세요|열어\s*줘|확인|수정|편집)(?:해\s*줘|해주세요)?', value):
        return {'action': 'read'}
    match = re.fullmatch(r'(?:내|제)\s*(?:프로필(?:의)?\s*)?(' + FIELD_PATTERN +
                         r')(?:을|를)\s+(.+?)(?:으로|로)\s*(?:바꿔\s*줘|변경해\s*줘|수정해\s*줘|변경해주세요|수정해주세요)', value)
    if match:
        return {'action': 'set', 'field': LABELS[match[1]], 'value': match[2].strip()}
    match = re.fullmatch(r'(?:내|제)\s*(?:프로필(?:의)?\s*)?(' + FIELD_PATTERN +
                         r')(?:에|에서)\s+(.+?)\s*(?:을|를)?\s*(추가|삭제|제거)(?:해\s*줘|해주세요)', value)
    if match and LABELS[match[1]] in ('skills', 'interests'):
        return {'action': 'add' if match[3] == '추가' else 'remove',
                'field': LABELS[match[1]], 'value': match[2].strip()}
    return None


class ProfileChat:
    def __init__(self, service, profiles):
        self.service = service
        self.store = service.store
        self.profiles = profiles

    def handle(self, payload):
        if not isinstance(payload, dict) or set(payload) - {'action', 'session_id', 'turn_id', 'payload', 'text'}:
            raise ProfileError('프로필 대화 요청 형식을 확인해 주세요.')
        action = payload.get('action')
        if action not in ('text', 'read', 'save', 'upload', 'suggest', 'undo', 'source-action'):
            raise ProfileError('지원하지 않는 프로필 작업입니다.')
        turn_id = payload.get('turn_id')
        if not isinstance(turn_id, str) or not re.fullmatch(r'[A-Za-z0-9-]{16,80}', turn_id):
            raise ProfileError('프로필 메시지 식별자를 확인해 주세요.')
        sid = payload.get('session_id')
        if sid is not None and (not isinstance(sid, str) or not re.fullmatch(r'[a-f0-9]{32}', sid)):
            raise ProfileError('현재 대화를 확인해 주세요.')
        data = payload.get('payload', {})
        if not isinstance(data, dict):
            raise ProfileError('프로필 작업 내용을 확인해 주세요.')
        intent = command(payload.get('text', '')) if action == 'text' else None
        if action == 'text' and intent is None:
            # Do not reserve a session, write a fact, or dispatch to a model.
            raise ProfileError('내 프로필에서 바꿀 항목과 값을 명확히 알려 주세요.', code='not_profile_command')
        effective = ('read' if intent['action'] == 'read' else 'save') if intent else action
        request_id = ('profile-' + turn_id) if action == 'text' else data.get('request_id')
        digest = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()

        def reserve(state):
            session = next((s for s in state['sessions'] if s['id'] == sid), None) if sid else next(
                (s for s in state['sessions'] if any(m.get('turn_id') == turn_id for m in s.get('messages', []))), None)
            if sid and not session:
                raise ProfileError('현재 방문자의 대화를 찾을 수 없습니다.', code='session_unavailable', status=404)
            if session and session.get('kind') != 'chat':
                raise ProfileError('현재 채팅에서 내 프로필을 열어 주세요.')
            if not session:
                if len(state['sessions']) >= 100:
                    raise ProfileError('대화 개수 한도에 도달했습니다.', code='limit', status=429)
                session = {'id': uuid.uuid4().hex, 'kind': 'chat', 'created': now(), 'updated': now(),
                           'original': '내 프로필', 'messages': [], 'turns': 0, 'mode': 'advice', 'asker': 'lab',
                           'slots': {'target': '', 'conditions': '', 'resources': '', 'deadline': '', 'goal': ''},
                           'result': None, 'ready': False, 'followup': None, 'can_propose': False, 'pending': None}
                state['sessions'].append(session)
            user = next((m for m in session['messages'] if m.get('turn_id') == turn_id and m['role'] == 'user'), None)
            if user and (user.get('kind') != 'self_profile' or user.get('digest') != digest):
                raise ProfileError('같은 메시지 ID에 다른 변경이 있습니다.', code='request_conflict', status=409)
            done = next((m for m in session['messages'] if m.get('turn_id') == turn_id and m['role'] == 'assistant' and m.get('status') == 'complete'), None)
            if done:
                return session['id'], copy.deepcopy(done), None
            if session.get('pending'):
                raise ProfileError('현재 응답이 끝난 뒤 다시 시도해 주세요.', code='busy', status=409)
            if len(session['messages']) >= 400:
                raise ProfileError('대화 길이 한도에 도달했습니다.', code='limit', status=429)
            prior = None
            if user and request_id:
                # Matching gateway digest binds this receipt to the same command.
                # Recovery never reconstructs a private value from old chat text.
                prior = copy.deepcopy(state.get('self_profile', {}).get('requests', {}).get(request_id))
            if not user:
                session['messages'].append({'role': 'user', 'text': '내 프로필 확인' if effective == 'read' else '내 프로필 작업',
                                            'kind': 'self_profile', 'turn_id': turn_id, 'digest': digest})
            session['pending'] = turn_id
            session['updated'] = now()
            return session['id'], None, prior

        session_id, completed, prior = self.store.transaction(reserve)
        if completed:
            return {'session': self.service.session(session_id), 'profile_view': self.profiles.read(),
                    'reply': completed['text'], 'receipt': completed.get('profile_receipt')}
        try:
            if prior:
                view = self.profiles.read()
                operation = {'action': prior['action'], 'replayed': True, 'version': prior['version'],
                             'request_id': request_id, 'event_ids': prior.get('event_ids', [])}
                view['operation'] = operation
            elif effective == 'read':
                view = self.profiles.read()
            else:
                if intent:
                    current = self.profiles.read()['profile']
                    field, new = intent['field'], intent['value']
                    if intent['action'] in ('add', 'remove'):
                        entries = [v.strip() for v in re.split(r'[,\n;]+', current['fields'][field]) if v.strip()]
                        if intent['action'] == 'add' and new not in entries:
                            entries.append(new)
                        elif intent['action'] == 'remove':
                            entries = [v for v in entries if v != new]
                        new = ', '.join(entries)
                    data = {'fields': {field: new}, 'base_version': current['version'], 'request_id': request_id}
                method = getattr(self.profiles, effective.replace('-', '_'))
                view = method(data)
            op = view.get('operation')
            receipt = {'version': op['version'], 'event_ids': op['event_ids']} if op else None
            reply = {'read': '내 프로필을 열었어요.', 'save': '프로필 변경을 저장했어요.',
                     'upload': '프로필 자료를 받았어요. 반영할 내용은 직접 선택해 주세요.',
                     'suggest': '자료의 변경 후보를 준비했어요. 아직 프로필에 반영하지 않았어요.',
                     'undo': '선택한 한 항목의 변경을 되돌렸어요.', 'source-action': '프로필 자료 상태를 변경했어요.'}[effective]

            def finish(state):
                session = next(s for s in state['sessions'] if s['id'] == session_id)
                if session.get('pending') != turn_id:
                    raise ProfileError('저장 결과를 다시 확인해 주세요.', code='conflict', status=409)
                session['messages'] = [m for m in session['messages'] if not (m.get('turn_id') == turn_id and m['role'] == 'assistant')]
                session['messages'].append({'role': 'assistant', 'kind': 'self_profile', 'source': 'self_profile',
                                            'text': reply, 'model': '내 프로필', 'status': 'complete',
                                            'turn_id': turn_id, 'profile_receipt': receipt})
                session['pending'] = None
                session['updated'] = now()
                return self.service.present_session(session)
            session = self.store.transaction(finish)
            return {'session': session, 'profile_view': view, 'reply': reply, 'receipt': receipt}
        except Exception as exc:
            # Only the explicit command is returned transiently for conflict UI.
            # Never copy the previous profile/source value into chat or errors.
            if isinstance(exc, ProfileError) and exc.code == "conflict" and intent and effective == "save":
                exc.profile_command = copy.deepcopy(intent)
            def release(state):
                session = next(s for s in state['sessions'] if s['id'] == session_id)
                if session.get('pending') == turn_id:
                    session['pending'] = None
            self.store.transaction(release)
            raise
