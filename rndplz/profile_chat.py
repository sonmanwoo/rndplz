"""Self-profile actions in a chat. Explicit commands, and other sentences the intent reader
routed here (read by Gemma), become a draft the user compares and saves in the profile panel.

Only generic labels and receipt references enter the transcript. Profile values
are always read from the current, redaction-aware private Profiles view.
"""
import copy
import hashlib
import json
import re
import uuid

from .profiles import ProfileError, list_items, list_join
from .service import now


# The profile panel's labels (profile-chat.js FIELDS).
FIELD_NAMES = {'name': '표시 이름', 'organization': '소속·부서', 'role': '현재 역할', 'bio': '짧은 소개', 'skills': '전문분야', 'interests': '관심 분야'}
GUIDE = {
    'help': "바꿀 내용을 한 문장으로 말씀해 주세요. 예: '소속을 바이오공정팀으로 바꿔줘', '관심 분야에 수소 액화 추가'. "
            "이력서·연구노트 같은 파일을 이 입력창에 첨부해 보내면 Gemma가 끝까지 읽고 변경안을 만들어요.",
    'document': "말씀하신 파일을 이 입력창에 첨부해 보내 주세요. 프로필 창이 열려 있을 때 보낸 파일은 Gemma가 끝까지 읽고 "
                "경력·기술·관심 분야 변경안을 만들어요. 반영은 고른 항목만 됩니다.",
    'again': "프로필 창에서 이어서 하면 돼요. 바꿀 항목과 값을 말씀하시거나 파일을 첨부해 보내 주세요.",
}
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

    def _interpret(self, payload):
        reader, text = getattr(self.profiles, 'reader', None), payload.get('text', '')
        plan = None
        if reader is not None and isinstance(payload.get('model_id'), str):
            try:
                profile = self.profiles.read()['profile']
                snapshot = {**{k: profile['fields'][k] for k in ('name', 'organization', 'role')},
                            'skills': list_items(profile['fields']['skills']), 'interests': list_items(profile['fields']['interests']),
                            'career_titles': [c['title'] for c in profile['careers'] if c.get('title')]}
                plan = reader.interpret(payload['model_id'], text, snapshot)
            except Exception:
                plan = None  # no model or no answer: guidance still helps
        if plan and plan['kind'] == 'edit':
            return {'action': 'draft', 'edits': plan['edits'], 'careers': plan['careers']}
        return {'action': 'read', 'guide': plan['kind'] if plan else 'help'}

    def _last_reply(self, sid):
        if not sid:
            return None
        session = next((s for s in self.store.read()['sessions'] if s['id'] == sid), None)
        return next((m.get('text') for m in reversed((session or {}).get('messages', [])) if m.get('role') == 'assistant'), None)

    def _draft(self, intent):
        """A requested change as a save the user confirms in the profile panel; nothing is written here."""
        current = self.profiles.read()['profile']
        fields = {}
        for edit in intent['edits']:
            field, value = edit['field'], edit['value']
            if field in ('skills', 'interests') and edit['action'] in ('add', 'remove'):
                base = fields.get(field, current['fields'][field])
                entries = list_items(base)
                if edit['action'] == 'add' and value.lower() not in [v.lower() for v in entries]:
                    entries.append(value)
                elif edit['action'] == 'remove':
                    entries = [v for v in entries if v.lower() != value.lower()]
                fields[field] = list_join(entries, base)
            else:
                fields[field] = value
        return {'fields': fields, 'careers': intent['careers'], 'base_version': current['version']}

    def handle(self, payload):
        if not isinstance(payload, dict) or set(payload) - {'action', 'session_id', 'turn_id', 'payload', 'text', 'routed', 'model_id'}:
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
            if payload.get('routed') is not True:
                # Do not reserve a session, write a fact, or dispatch to a model.
                raise ProfileError('내 프로필에서 바꿀 항목과 값을 명확히 알려 주세요.', code='not_profile_command')
            # Gemma read a profile update that is not an explicit command. It interprets the sentence:
            # values the user wrote become a draft the user saves in the profile panel; otherwise the
            # reply says what to do next.
            intent = self._interpret(payload)
        elif intent and intent['action'] in ('set', 'add', 'remove'):
            # An explicit command is shown as current -> new too; it saves when the user confirms.
            intent = {'action': 'draft', 'careers': [],
                      'edits': [{key: intent[key] for key in ('action', 'field', 'value')}]}
        effective = 'read' if intent else action
        if intent and intent.get('guide'):
            previous = self._last_reply(sid)
            intent['reply'] = GUIDE['again'] if previous == GUIDE[intent['guide']] else GUIDE[intent['guide']]
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
                session['messages'].append({'role': 'user', 'text': '내 프로필 업데이트 요청' if intent and ('guide' in intent or intent['action'] == 'draft') else '내 프로필 확인' if effective == 'read' else '내 프로필 작업',
                                            'kind': 'self_profile', 'turn_id': turn_id, 'digest': digest})
            session['pending'] = turn_id
            session['updated'] = now()
            return session['id'], None, prior

        session_id, completed, prior = self.store.transaction(reserve)
        draft = None
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
                if intent and intent['action'] == 'draft':
                    draft = self._draft(intent)
            else:
                method = getattr(self.profiles, effective.replace('-', '_'))
                view = method(data)
            op = view.get('operation')
            receipt = {'version': op['version'], 'event_ids': op['event_ids']} if op else None
            reply = {'read': '내 프로필을 열었어요.', 'save': '프로필 변경을 저장했어요.',
                     'upload': '프로필 자료를 받았어요. 반영할 내용은 직접 선택해 주세요.',
                     'suggest': '자료의 변경 후보를 준비했어요. 아직 프로필에 반영하지 않았어요.',
                     'undo': '선택한 한 항목의 변경을 되돌렸어요.', 'source-action': '프로필 자료 상태를 변경했어요.'}[effective]
            if effective == 'suggest' and (view.get('operation') or {}).get('model_calls'):
                reply = 'Gemma가 자료 전체를 읽고 변경안을 만들었어요. 근거 원문을 확인하고 반영할 항목만 골라 주세요.'
            if view.get('card_update') and effective in ('save', 'undo', 'source-action'):
                reply += ' 연구맵 카드에도 바로 반영했어요.'
            if intent and intent.get('guide'):
                reply = intent['reply']
            elif draft:
                # Field names only: the values go to the profile panel, not into the transcript.
                names = list(dict.fromkeys([FIELD_NAMES[e['field']] for e in intent['edits']] + ['경력'] * bool(intent['careers'])))
                reply = f"{', '.join(names)} 변경안을 프로필 창에 준비했어요. 맞으면 '이대로 저장'을 눌러 주세요."

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
            result = {'session': session, 'profile_view': view, 'reply': reply, 'receipt': receipt}
            return {**result, 'draft': draft} if draft else result
        except Exception:
            def release(state):
                session = next(s for s in state['sessions'] if s['id'] == session_id)
                if session.get('pending') == turn_id:
                    session['pending'] = None
            self.store.transaction(release)
            raise
