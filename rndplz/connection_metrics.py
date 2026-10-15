"""Connection signals read from what people already do, for the operator's account only (2026-10-14).

Every conversation folder under the state root is read, never written, and only counts leave this
module: no request text, letter, recipient name or requester. The page /admin/connections shows them
to the admin account alone.

  started    conversations with at least one message from the person
  searched   conversations that disclosed candidates (이 정보로 수소문하기)
  proposed   searched conversations with a saved letter; sent = at least one 시연 보냄
  choice     who got each letter: the first card, another recommended card, or someone picked on the map
  edit       how far the saved letter moved from its draft (saved since 2026-10-14)
  letter     whether the draft's request part was the company AI's paragraph or the rule text
  reaction   the one-tap answer after a send (잘 맞아요·애매해요·안 맞아요 and a reason), once per send
  outcome    how the request of a send turned out (case_notes), with where it got stuck, once per send
  visits     people who opened a page (visit_counter: keys only, automated browsers left out)
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

KST = timezone(timedelta(hours=9))
SAME, LIGHT = 0.98, 0.8  # draft similarity at or above SAME is "그대로", at or above LIGHT "조금 고침"
PERIODS = ('today', 'week', 'all')


def draft_similarity(draft, body):
    """How much of the draft the saved letter kept, 0..1 (difflib over the first 4000 characters)."""
    from difflib import SequenceMatcher
    if not isinstance(draft, str) or not isinstance(body, str):
        return None
    return round(SequenceMatcher(None, draft[:4000], body[:4000], autojunk=False).ratio(), 3)


def _when(value):
    try:
        moment = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _searched(session):
    result = session.get('result') if isinstance(session.get('result'), dict) else {}
    cards = [c for c in result.get('candidates') or [] if isinstance(c, dict)]
    return bool((session.get('scout') or {}).get('disclosed') is True and cards
                and not result.get('inspection_only') and not any(c.get('lookup_only') for c in cards))


def _states(root):
    """(kind, state) for every readable conversation folder; a folder being written is skipped."""
    for folder in sorted(Path(root).iterdir()) if Path(root).is_dir() else ():
        path = folder / 'state.json'
        if not folder.is_dir() or not path.is_file():
            continue
        try:
            state = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            continue
        if isinstance(state, dict):
            yield ('account' if folder.name.startswith('account-') else 'visitor'), state


def _blank():
    return {'started': 0, 'searched': 0, 'proposed': 0, 'sent': 0,
            'searched_by': {'visitor': 0, 'account': 0},
            'letters': 0, 'letters_sent': 0,
            'choice': {'first': 0, 'other': 0, 'picked': 0, 'unknown': 0},
            'edit': {'same': 0, 'light': 0, 'heavy': 0},
            'letter': {'model': 0, 'rule': 0},
            'sends': 0, 'reaction': {'good': 0, 'unsure': 0, 'bad': 0},
            'outcome': {'solved': 0, 'partial': 0, 'unsolved': 0, 'ongoing': 0},
            'stuck': {'field': 0, 'evidence': 0, 'unreachable': 0, 'changed': 0, 'other': 0}, 'shared': 0,
            'reason': {'field': 0, 'evidence': 0, 'known': 0}}


def collect(root, now=None):
    """Counts per period (today and the last 7 days in KST, and all time) over every conversation."""
    now = now or datetime.now(timezone.utc)
    today = now.astimezone(KST).replace(hour=0, minute=0, second=0, microsecond=0)
    since = {'today': today, 'week': today - timedelta(days=6), 'all': None}
    rows = {name: _blank() for name in PERIODS}

    def periods(moment):
        return [name for name in PERIODS if since[name] is None or (moment is not None and moment >= since[name])]

    for kind, state in _states(root):
        sessions = {s.get('id'): s for s in state.get('sessions') or [] if isinstance(s, dict)}
        letters = {}
        for proposal in state.get('proposals') or []:
            if isinstance(proposal, dict):
                letters.setdefault(proposal.get('session_id'), []).append(proposal)
        for sid, session in sessions.items():
            moment = _when(session.get('created'))
            names = periods(moment)
            started = any(m.get('role') == 'user' for m in session.get('messages') or [] if isinstance(m, dict))
            searched = _searched(session)
            saved = letters.get(sid, [])
            for name in names:
                row = rows[name]
                row['started'] += started
                if searched:
                    row['searched'] += 1
                    row['searched_by'][kind] += 1
                    row['proposed'] += bool(saved)
                    row['sent'] += any(p.get('state') == 'sent' for p in saved)
            cards = [c.get('id') for c in ((session.get('result') or {}).get('candidates') or []) if isinstance(c, dict)]
            for proposal in saved:
                choice = ('picked' if proposal.get('selection') == 'user_pick' else
                          'first' if cards and proposal.get('recipient_id') == cards[0] else
                          'other' if proposal.get('recipient_id') in cards else 'unknown')
                similarity = proposal.get('draft_similarity')
                edit = (None if not isinstance(similarity, (int, float)) else
                        'same' if similarity >= SAME else 'light' if similarity >= LIGHT else 'heavy')
                source = proposal.get('letter_source')
                for name in periods(_when(proposal.get('created'))):
                    row = rows[name]
                    row['letters'] += 1
                    row['letters_sent'] += proposal.get('state') == 'sent'
                    row['choice'][choice] += 1
                    if edit:
                        row['edit'][edit] += 1
                    if source in row['letter']:
                        row['letter'][source] += 1
        # One send (one 제안함에 보내기) may reach several people; its reaction counts once.
        sends = {}
        for proposal in state.get('proposals') or []:
            if isinstance(proposal, dict) and proposal.get('state') == 'sent' and proposal.get('group_id'):
                sends.setdefault(proposal['group_id'], []).append(proposal)
        for letters_sent in sends.values():
            reaction = next((p['reaction'] for p in letters_sent if isinstance(p.get('reaction'), dict)), {})
            outcome = next((p['outcome'] for p in letters_sent if isinstance(p.get('outcome'), dict)), {})
            moments = [m for m in (_when(p.get('created')) for p in letters_sent) if m is not None]
            for name in periods(min(moments) if moments else None):
                row = rows[name]
                row['sends'] += 1
                if reaction.get('fit') in row['reaction']:
                    row['reaction'][reaction['fit']] += 1
                if reaction.get('reason') in row['reason']:
                    row['reason'][reaction['reason']] += 1
                if outcome.get('result') in row['outcome']:
                    row['outcome'][outcome['result']] += 1
                    row['shared'] += outcome.get('visibility') == 'team'
                for reason in outcome.get('reasons') or []:
                    if reason in row['stuck']:
                        row['stuck'][reason] += 1
    from .visit_counter import visit_counts
    visits, first = visit_counts(Path(root) / 'visits', since)
    return {'generated_at': now.astimezone(KST).isoformat(timespec='seconds'),
            'since': {name: value.date().isoformat() if value else None for name, value in since.items()},
            'periods': rows, 'visits': visits, 'visits_since': first}
