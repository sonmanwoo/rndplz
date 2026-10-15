"""How a request turned out, kept as a case note (2026-10-15).

After a send, the requester can leave the result on that send (one 제안함에 보내기, its group_id): solved,
partly solved, not solved (with where it got stuck) or still going, a few lines prefilled from the
conversation's request, and who may see it. A note stays the requester's own; one shared with the team is
copied to <state>/cases/ for the admin to put up or hold (the team's case library reads approved ones).
A note on a send that did not work keeps no recipient name.
"""
from __future__ import annotations

import json
import os
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

RESULTS = ('solved', 'partial', 'unsolved', 'ongoing')
REASONS = ('field', 'evidence', 'unreachable', 'changed', 'other')
NOTE_FIELDS = {'solved': ('problem', 'helped', 'lesson'), 'partial': ('problem', 'helped', 'remaining', 'lesson'),
               'unsolved': ('problem', 'tried', 'next'), 'ongoing': ()}
VISIBILITY = ('private', 'team')
NOTE_LIMIT = 1000
SENT_STATES = ('sent', 'accepted', 'declined', 'closed')


def validate(payload):
    """The outcome a requester sends, checked; ValueError with a plain reason otherwise."""
    if not isinstance(payload, dict) or set(payload) - {'group_id', 'result', 'reasons', 'notes', 'visibility'}:
        raise ValueError('결과 형식을 확인해 주세요.')
    group = payload.get('group_id')
    if not isinstance(group, str) or not re.fullmatch(r'[0-9a-f]{32}', group):
        raise ValueError('결과를 남길 의뢰를 찾을 수 없습니다.')
    result = payload.get('result')
    if result not in RESULTS:
        raise ValueError('결과를 하나 골라 주세요.')
    reasons = payload.get('reasons') or []
    if (not isinstance(reasons, list) or len(set(reasons)) != len(reasons) or any(r not in REASONS for r in reasons)
            or (reasons and result != 'unsolved')):
        raise ValueError('막힌 이유 형식을 확인해 주세요.')
    notes = payload.get('notes') or {}
    allowed = NOTE_FIELDS[result]
    if not isinstance(notes, dict) or set(notes) - set(allowed) or any(not isinstance(v, str) or len(v) > NOTE_LIMIT for v in notes.values()):
        raise ValueError('적은 내용의 형식이나 길이를 확인해 주세요.')
    visibility = payload.get('visibility', 'private')
    if visibility not in VISIBILITY or (result == 'ongoing' and visibility != 'private'):
        raise ValueError('공개 범위를 확인해 주세요.')
    return {'group_id': group, 'result': result, 'reasons': reasons,
            'notes': {k: notes[k].strip() for k in allowed if isinstance(notes.get(k), str) and notes[k].strip()},
            'visibility': visibility}


def letters_of(state, group):
    return [p for p in state.get('proposals') or [] if p.get('group_id') == group and p.get('state') in SENT_STATES]


def _days(start, end):
    try:
        return max(0, (end - datetime.fromisoformat(start)).days)
    except (TypeError, ValueError):
        return None


def route(session, letter):
    """How the person was found, in words: the card's place in the result, or a pick on the map; the first record."""
    evidence = letter.get('evidence') or []
    record = ' · 근거 「' + evidence[0]['title'] + '」' if evidence and isinstance(evidence[0], dict) and evidence[0].get('title') else ''
    if letter.get('selection') == 'user_pick':
        return '연구 맵에서 직접 고른 분' + record
    cards = [c.get('id') for c in ((session or {}).get('result') or {}).get('candidates') or [] if isinstance(c, dict)]
    place = cards.index(letter.get('recipient_id')) + 1 if letter.get('recipient_id') in cards else None
    return ('수소문 추천 ' + str(place) + '번째 카드' if place else '수소문 추천 카드') + record


def problem_text(session):
    """The request in the conversation's own words: the approved purposes, else its summary, else the first message."""
    spec = (session or {}).get('request_spec') or {}
    purposes = [row.get('text') for row in spec.get('purposes') or [] if isinstance(row, dict) and row.get('text')]
    text = ' · '.join(purposes) or spec.get('summary') or (session or {}).get('original') or ''
    return text.strip()[:NOTE_LIMIT]


def draft(state, group, now=None):
    """What the result sheet opens with: who it went to, when, how they were found, the request as the problem."""
    letters = letters_of(state, group)
    if not letters:
        raise ValueError('결과를 남길 의뢰를 찾을 수 없습니다.')
    first = letters[0]
    session = next((s for s in state.get('sessions') or [] if s.get('id') == first.get('session_id')), None)
    saved = first.get('outcome') if isinstance(first.get('outcome'), dict) else None
    return {'group_id': group, 'recipients': [p.get('recipient_name') for p in letters],
            'sent_at': first.get('created'), 'days': _days(first.get('created'), now or datetime.now(timezone.utc)),
            'route': route(session, first), 'problem': problem_text(session), 'saved': saved}


def apply(state, outcome, now=None):
    """Keep the outcome on every sent letter of that send; the saved note."""
    letters = letters_of(state, outcome['group_id'])
    if not letters:
        raise ValueError('결과를 남길 의뢰를 찾을 수 없습니다.')
    moment = now or datetime.now(timezone.utc)
    session = next((s for s in state.get('sessions') or [] if s.get('id') == letters[0].get('session_id')), None)
    previous = letters[0].get('outcome') if isinstance(letters[0].get('outcome'), dict) else {}
    note = {**outcome, 'route': route(session, letters[0]), 'days': _days(letters[0].get('created'), moment),
            'at': moment.isoformat(timespec='seconds'), 'case_id': previous.get('case_id') or uuid.uuid4().hex}
    for letter in letters:
        letter['outcome'] = dict(note)
    return note


class CaseShelf:
    """Notes shared with the team, one file each under <state>/cases/, waiting for the admin or put up."""

    def __init__(self, directory):
        self.directory = Path(directory)
        self.lock = threading.Lock()

    def _path(self, case_id):
        if not isinstance(case_id, str) or not re.fullmatch(r'[0-9a-f]{32}', case_id):
            raise ValueError('사례를 찾을 수 없습니다.')
        return self.directory / (case_id + '.json')

    def _write(self, path, value):
        self.directory.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix('.tmp')
        temporary.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
        os.replace(temporary, path)

    def share(self, note, recipients):
        """Copy a team note (names only when it worked); a private note takes a shared copy back."""
        path = self._path(note['case_id'])
        with self.lock:
            if note['visibility'] != 'team':
                path.unlink(missing_ok=True)
                return None
            try:
                old = json.loads(path.read_text(encoding='utf-8'))
            except (OSError, ValueError):
                old = {}
            case = {'case_id': note['case_id'], 'result': note['result'], 'reasons': note['reasons'],
                    'notes': note['notes'], 'route': note['route'], 'days': note['days'], 'at': note['at'],
                    'recipients': list(recipients) if note['result'] in ('solved', 'partial') else [],
                    'review': 'pending' if old.get('notes') != note['notes'] or old.get('result') != note['result'] else old.get('review', 'pending')}
            self._write(path, case)
            return case

    def review(self, case_id, decision):
        if decision not in ('approved', 'held'):
            raise ValueError('검토 결정을 확인해 주세요.')
        path = self._path(case_id)
        with self.lock:
            try:
                case = json.loads(path.read_text(encoding='utf-8'))
            except (OSError, ValueError):
                raise ValueError('사례를 찾을 수 없습니다.') from None
            case['review'] = decision
            self._write(path, case)
            return case

    def all(self):
        cases = []
        for path in sorted(self.directory.glob('*.json')) if self.directory.is_dir() else ():
            try:
                cases.append(json.loads(path.read_text(encoding='utf-8')))
            except (OSError, ValueError):
                continue
        return sorted(cases, key=lambda c: c.get('at') or '', reverse=True)
