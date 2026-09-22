"""Server-only registered-record lookup and separately authorized draft review.

Snapshots live outside sessions/messages/results. They are browser data, never a
provider tool result, model grounding or permission to submit/send a proposal.
"""
from __future__ import annotations

import copy
import hashlib
import json
import uuid
from dataclasses import asdict

from .demo_pool import proposal_boundary, require_proposal_boundary
from .engine import Engine
from .scout_projection import _request_spec


SCHEMA = 'registered_expert_lookup.v1'
_STATE_KEY = 'registered_expert_snapshots'
_ERROR = '현재 의뢰의 등록 이력 조회를 다시 확인해 주세요.'
_EVIDENCE_FIELDS = ('id', 'kind', 'title', 'date', 'url', 'scope', 'scope_key',
                    'evidence_kind', 'evidence_label', 'checked_at', 'virtual',
                    'boundary', 'role', 'corresponding', 'access', 'tags')


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def _view(service):
    # The base Service must already expose these approved records. No loader,
    # hidden-profile restoration or provider-scoped personal-data expansion.
    from .public_profiles import APPROVED_PERSON_IDS, APPROVED_RECORD_IDS
    if getattr(service, '_provider_scope', None):
        raise ValueError(_ERROR)
    base = service.corpus
    view = copy.copy(base)
    view.people = {pid: copy.deepcopy(p) for pid, p in base.people.items()
                   if pid in APPROVED_PERSON_IDS and not p.virtual}
    view.records = {rid: copy.deepcopy(r) for rid, r in base.records.items()
                    if rid in APPROVED_RECORD_IDS and r.kind in ('career_record', 'paper', 'patent_record')
                    and not r.virtual and r.access_policy_ref in ('public_metadata', 'local_self_reported')
                    and any(c.person_id in view.people for c in r.people)}
    view.by_person = {pid: [r for r in view.records.values()
                           if any(c.person_id == pid for c in r.people)]
                      for pid in view.people}
    active = {tag for r in view.records.values() for tag in r.tags}
    view.topics = [copy.deepcopy(t) for t in base.topics if t['id'] in active]
    view.topic_by_id = {t['id']: t for t in view.topics}
    return view


def _corpus_hash(view):
    return _digest({'people': [asdict(view.people[k]) for k in sorted(view.people)],
                    'records': [asdict(view.records[k]) for k in sorted(view.records)],
                    'topics': view.topics,
                    'policy': getattr(view, 'demo_pool', None)})


def _current(service, state, sid, revision=None):
    from .model_conversation import request_revision
    from .service import provider_scope
    session = next((s for s in state['sessions'] if s.get('id') == sid), None)
    if not session or session.get('kind') != 'chat':
        raise ValueError(_ERROR)
    spec = _request_spec(session.get('request_spec'), session)
    scout = session.get('scout') or {}
    current = spec.get('revision') if spec else None
    if (not spec or spec.get('state') != 'current' or not spec.get('has_content')
            or not current or (revision is not None and current != revision)
            or session.get('pending') or session.get('lookup_paused')
            or scout.get('disclosed') is not True
            or current != session.get('scout_authorized_revision')
            or current != session.get('prepared_discovery_revision')):
        raise ValueError(_ERROR)
    scope = provider_scope(session)
    if not scope or not isinstance(session.get('model_plan'), dict):
        raise ValueError(_ERROR)
    scoped = service.for_provider_scope(scope)
    corpus = scoped.corpus
    fingerprint = _digest({'people': [asdict(corpus.people[k]) for k in sorted(corpus.people)],
                           'records': [asdict(corpus.records[k]) for k in sorted(corpus.records)],
                           'topics': corpus.topics})
    if request_revision(session['model_plan_source_turn'], session['model_plan'],
                        fingerprint, session['request_spec']) != current:
        raise ValueError(_ERROR)
    # A current revision alone is not permission to reuse evidence after edits.
    binding = _digest({key: session.get(key) for key in (
        'id', 'provider_scope', 'execution_binding', 'model_id', 'mode', 'slots',
        'messages', 'request_spec', 'model_plan', 'model_plan_source_turn',
        'model_plan_revision', 'request_attachment_sources', 'scout_authorized_revision',
        'prepared_discovery_revision')})
    return session, spec, binding


def _project(snapshot):
    if snapshot.get('schema') != SCHEMA or snapshot.get('audience') != 'browser_only':
        raise ValueError(_ERROR)
    keys = ('schema', 'audience', 'session_id', 'revision', 'source_turn_id',
            'snapshot_id', 'corpus_fingerprint', 'candidate_count', 'candidates')
    return {**{key: copy.deepcopy(snapshot[key]) for key in keys},
            'model_data_sent': False, 'can_propose': False, 'delivery_allowed': False}


def lookup(service, sid, revision, *, context_builder):
    """Explicit prepare caller only. context_builder is server-owned, not JSON."""
    if not callable(context_builder):
        raise ValueError(_ERROR)

    def update(state):
        session, spec, binding = _current(service, state, sid, revision)
        context = context_builder(copy.deepcopy(session))
        if (not isinstance(context, dict)
                or not isinstance(context.get('excluded_person_ids'), list)
                or not all(isinstance(pid, str) for pid in context['excluded_person_ids'])):
            raise ValueError(_ERROR)
        excluded = set(context['excluded_person_ids'])
        from .chat_actions import ChatActions
        actions = ChatActions(service)
        # Reuse the existing registered-name exclusion grammar on current
        # compiler sources, including mixed condition/name clauses.
        for source in context.get('sources') or []:
            if isinstance(source, dict) and isinstance(source.get('text'), str):
                excluded.update(actions.excluded(source['text']))
        # Positive current request only. Conditions remain questions, not keywords
        # which could turn an exclusion into a positive match.
        query = '\n'.join(row['text'] for key in ('purposes', 'requested_help')
                          for row in spec[key] if row['text'].strip())
        if not query.strip() or len(query) > 12000:
            raise ValueError(_ERROR)
        view = _view(service)
        engine = Engine(view)
        result = engine.recommend(query, 'advice', limit=7)
        unresolved = context.get('unresolved') or []
        if not isinstance(unresolved, list) or not all(isinstance(x, str) for x in unresolved):
            raise ValueError(_ERROR)
        conditions = [('필수: ' if c['kind'] == 'required' else '선호: ') + c['text']
                      for c in spec['conditions']]
        questions = list(dict.fromkeys(conditions + spec['open_questions'] + unresolved))
        candidates = []
        for row in result['candidates']:
            if row['id'] in excluded or row['id'] not in view.people:
                continue
            evidence = [{key: copy.deepcopy(e[key]) for key in _EVIDENCE_FIELDS if key in e}
                        for e in row['evidence'] if e.get('id') in view.records]
            if not evidence:
                continue
            reason = proposal_boundary(view, row['id'], evidence)
            display_name = view.people[row['id']].profile.get('display_name')
            display_name = display_name.strip() if isinstance(display_name, str) and display_name.strip() else row['name']
            candidates.append({
                **{key: row[key] for key in ('id', 'name', 'org', 'role', 'reason')},
                'name': display_name,
                'kind': 'registered_expert', 'virtual': False, 'evidence': evidence,
                'purpose_relation': 'unknown',
                'purpose_missing': '등록 이력의 주제 연결입니다. 구체 목적의 직접 충족과 개인 수행 수준은 확인하지 않았습니다.',
                'unverified_conditions': copy.deepcopy(questions),
                'can_review_draft': not bool(reason), 'proposal_unavailable_reason': reason or '',
                'proposal_allowed': False, 'lookup_only': False,
                'individual_performance_verified': False, 'person_confirmed': False,
                'availability': '미확인', 'source_kind': 'registered_career',
            })
        corpus_hash = _corpus_hash(view)
        snapshot = {'schema': SCHEMA, 'audience': 'browser_only', 'session_id': sid,
                    'revision': spec['revision'], 'source_turn_id': spec['source_turn_id'],
                    'snapshot_id': uuid.uuid4().hex, 'request_binding': binding,
                    'corpus_fingerprint': corpus_hash, 'candidate_count': len(candidates),
                    'candidates': candidates, 'excluded_person_ids': sorted(excluded)}
        snapshot['evidence_fingerprint'] = _digest(candidates)
        # No mutation of session, result, messages, provider scope or permissions.
        state.setdefault(_STATE_KEY, {})[sid] = snapshot
        return _project(snapshot)

    return service.store.transaction(update)


def _saved(service, state, sid, snapshot_id=None, revision=None):
    session, spec, binding = _current(service, state, sid, revision)
    snapshot = state.get(_STATE_KEY, {}).get(sid)
    view = _view(service)
    if (not isinstance(snapshot, dict) or snapshot.get('audience') != 'browser_only'
            or snapshot.get('schema') != SCHEMA or snapshot.get('session_id') != sid
            or snapshot.get('revision') != spec['revision']
            or snapshot.get('source_turn_id') != spec['source_turn_id']
            or (snapshot_id is not None and snapshot.get('snapshot_id') != snapshot_id)
            or snapshot.get('request_binding') != binding
            or snapshot.get('corpus_fingerprint') != _corpus_hash(view)
            or snapshot.get('evidence_fingerprint') != _digest(snapshot.get('candidates'))):
        raise ValueError(_ERROR)
    return session, spec, snapshot, view


def present(service, sid):
    """Read an existing current snapshot; never discover or repair on a GET."""
    try:
        _, _, snapshot, _ = _saved(service, service.store.read(), sid)
        return _project(snapshot)
    except (ValueError, KeyError, TypeError):
        return None


def draft(service, sid, cid, snapshot_id, revision):
    from .model_conversation import proposal_brief
    if not all(isinstance(v, str) and v for v in (sid, cid, snapshot_id, revision)):
        raise ValueError(_ERROR)
    session, spec, snapshot, view = _saved(service, service.store.read(), sid, snapshot_id, revision)
    candidate = next((c for c in snapshot['candidates'] if c['id'] == cid), None)
    if (not candidate or candidate.get('can_review_draft') is not True
            or cid in snapshot['excluded_person_ids']):
        raise ValueError(_ERROR)
    require_proposal_boundary(view, cid, candidate['evidence'])
    template = copy.deepcopy(session)
    template['proposal_context'], goal = proposal_brief(spec, '')
    template['slots'] = dict(template.get('slots') or {})
    for key in ('goal', 'target', 'resources', 'conditions', 'deadline'):
        template['slots'].setdefault(key, '')
    template['slots']['goal'] = goal
    if template.get('mode') == 'verify':
        template['result'] = {'claims': (session.get('result') or {}).get('claims', [])}
    # Reuse rendering only, never insert a registered candidate into result.
    rendered = service._render_draft(template, candidate)
    questions = candidate['unverified_conditions']
    limits = list(dict.fromkeys(e['boundary'] for e in candidate['evidence'] if e.get('boundary')))
    body = rendered['body'] + '\n\n[등록 이력 근거의 한계]\n' + '\n'.join('- ' + x for x in limits)
    body += '\n\n[검토 전에 확인할 점]\n' + '\n'.join('- ' + x for x in (
        questions + ['이 의뢰에서 직접 맡을 수 있는 역할과 현재 협업 가능 여부를 확인해 주세요.']))
    if len(body) > 30000:
        raise ValueError(_ERROR)
    return {'session_id': sid, 'candidate': {'id': cid, 'name': candidate['name']},
            'body': body, 'request_kind': template['mode'], 'snapshot_id': snapshot_id,
            'revision': revision, 'source_turn_id': spec['source_turn_id'],
            'kind': 'registered_review', 'review_kind': 'registered_career',
            'proposal_allowed': False, 'can_propose': False,
            'delivery_allowed': False, 'model_data_sent': False}
