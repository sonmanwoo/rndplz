"""Browser-only projection of server-owned consultation/disclosure state.

Never use this projection for internal search, model inputs, persistence or
authorization. The owner marks validated assistant messages with audience and
scout_revision; this helper does not inspect names or infer intent from prose.
Voluntary profile/map APIs and the user's own text are outside this chat gate.
"""
from __future__ import annotations

import hashlib
import math


_STATUSES = {"consulting", "ready", "searching", "complete", "stopped", "error", "stale"}


def _pick(value, fields):
    """Copy only explicitly named scalar fields; reject unexpected nesting."""
    if not isinstance(value, dict):
        return {}
    return {key: value[key] for key in fields if key in value and (
        type(value[key]) in (str, bool, int) or value[key] is None or
        type(value[key]) is float and math.isfinite(value[key]))}


def _rows(value, project):
    return [project(item) for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _strings(value):
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []


def _request_spec(value, session):
    if not isinstance(value, dict):
        return None
    result = _pick(value, ('summary', 'revision', 'source_revision', 'source_turn_id'))
    for key, maximum in (('purposes', 16), ('requested_help', 8)):
        result[key] = []
        for row in value.get(key, [])[:maximum] if isinstance(value.get(key), list) else []:
            if (isinstance(row, dict) and all(isinstance(row.get(field), str)
                    for field in ('text', 'source_turn_id', 'source_quote'))):
                result[key].append(_pick(row, ('text', 'source_turn_id', 'source_quote')))
    result['conditions'] = []
    for row in value.get('conditions', [])[:16] if isinstance(value.get('conditions'), list) else []:
        if (isinstance(row, dict) and row.get('kind') in ('required', 'preference')
                and all(isinstance(row.get(key), str) for key in
                        ('text', 'source_turn_id', 'source_quote', 'strength_quote'))):
            result['conditions'].append(_pick(row, ('kind', 'text', 'source_turn_id', 'source_quote', 'strength_quote')))
    result['open_questions'] = _strings(value.get('open_questions'))[:5]
    result['has_content'] = value.get('has_content') is True and bool(
        result['purposes'] or result['requested_help'] or result['conditions'])
    source = result.get('source_turn_id')
    latest_user = next((m for m in reversed(session.get('messages') or [])
                       if isinstance(m, dict) and m.get('role') == 'user'
                       and m.get('kind') != 'self_profile'), {})
    completed = any(isinstance(m, dict) and m.get('role') == 'assistant'
                    and m.get('turn_id') == source and m.get('status') == 'complete'
                    for m in session.get('messages') or [])
    scout = session.get('scout') or {}
    revision = result.get('revision')
    current = bool(revision and result.get('source_revision') and source
                   and latest_user.get('turn_id') == source and completed
                   and revision == (session.get('discovery') or {}).get('revision') == scout.get('revision'))
    if session.get('model_plan') is not None:
        current = current and source == session.get('model_plan_source_turn') and revision == session.get('model_plan_revision')
    if session.get('pending'):
        state = 'updating'
    elif session.get('lookup_paused') or scout.get('status') == 'stopped':
        state = 'stopped'
    elif (session.get('scout_recovery') or {}).get('status') in ('required', 'unsupported'):
        state = 'stale'
        result['stale_reason'] = 'source_changed'
    elif scout.get('status') == 'error':
        state = 'failed'
    else:
        state = 'current' if current else 'stale'
    result['state'] = state
    return result


def _profile(value):
    profile = _pick(value, ("id", "curated", "slug", "source_type", "display_name", "current_role",
                            "affiliation_as_of", "tagline", "biography", "portrait_note", "profile_note"))
    if not isinstance(value, dict):
        return profile
    for key in ("skills", "interests"):
        if key in value:
            profile[key] = _strings(value[key])
    if isinstance(value.get("topics"), list):
        profile["topics"] = [{"name": item["name"]} for item in value["topics"]
                             if isinstance(item, dict) and isinstance(item.get("name"), str)
                             and item["name"].strip() and len(item["name"]) <= 120][:12]
    if isinstance(value.get("award"), dict):
        profile["award"] = _pick(value["award"], ("name", "year", "category", "motivation", "url"))
    if isinstance(value.get("portrait"), dict):
        portrait = value["portrait"]
        profile["portrait"] = _pick(portrait, ("path", "kind", "background", "generated", "width", "height",
            "label", "generated_credit", "generated_license", "generated_license_url", "change_note",
            "reference_note", "reference_url", "photo_url"))
        if isinstance(portrait.get("reference"), dict):
            profile["portrait"]["reference"] = _pick(portrait["reference"], ("title", "url", "usage", "author", "license", "license_url"))
    for key in ("timeline", "projects", "education", "sources"):
        if key in value:
            profile[key] = _rows(value[key], lambda item: _pick(item, ("date", "title", "text", "url")))
    if "skill_groups" in value:
        profile["skill_groups"] = _rows(value["skill_groups"], lambda item: {
            **_pick(item, ("name",)), "items": _strings(item.get("items"))})
    return profile


def _evidence(value):
    result = _pick(value, ("id", "title", "excerpt", "date", "role", "scope", "scope_label", "boundary",
                           "url", "source", "kind", "in_current_pool", "source_channel",
                           "retrieved_from_current_conversation_attachment", "submitter_identity",
                           "current_conversation_user_relation"))
    if isinstance(value.get("record_subject"), dict):
        result["record_subject"] = _pick(value["record_subject"], ("id", "name"))
    if "metadata_sources" in value:
        result["metadata_sources"] = _rows(value["metadata_sources"],
                                           lambda item: _pick(item, ("url", "title", "label", "basis", "type")))
    return result


def _candidate(value):
    result = _pick(value, ("id", "name", "org", "org_type", "role", "reason", "route_role", "experience",
        "virtual", "kind", "profile_only", "lookup_only", "in_current_pool", "proposal_allowed",
        "proposal_unavailable_reason", "record_confirmed", "individual_performance_verified",
        "person_confirmed", "availability", "works_count", "works_in_corpus", "relevant_records", "portfolio"))
    # The browser's older card renderer treats a missing flag as permission.
    # Projection never manufactures that permission from absence.
    result["proposal_allowed"] = value.get("proposal_allowed") is True
    result["evidence"] = _rows(value.get("evidence"), _evidence)
    result["profile"] = _profile(value.get("profile"))
    return result


def _result(value):
    if not isinstance(value, dict):
        return None
    result = _pick(value, ("intent", "mode", "query", "pool_version", "current_pool_version", "historical_result",
        "scope_note", "empty_message", "inspection_only", "assessment_status", "lookup_resolution"))
    result["candidates"] = _rows(value.get("candidates"), _candidate)
    if "choices" in value:
        result["choices"] = _rows(value["choices"], lambda item: _pick(item, ("id", "name", "org", "virtual", "in_current_pool")))
    # Author strips, raw retrieval IDs, plans, assessments and trace fields are
    # deliberately absent even after disclosure; candidates carry display data.
    return result


def _historical_disclosure_keys(value):
    keys = set()
    for item in value if isinstance(value, list) else []:
        if not isinstance(item, dict):
            continue
        turn_id, revision, text_sha = (item.get(key) for key in ("turn_id", "revision", "text_sha256"))
        if (isinstance(turn_id, str) and turn_id and isinstance(revision, str) and revision
                and isinstance(text_sha, str) and len(text_sha) == 64
                and all(char in "0123456789abcdef" for char in text_sha)):
            keys.add((turn_id, revision, text_sha))
    return keys


def _messages(value, *, disclosed, revision, historical_disclosures=None):
    messages = []
    historical_keys = _historical_disclosure_keys(historical_disclosures)
    for item in value if isinstance(value, list) else []:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        historical = False
        if role == "assistant":
            audience = item.get("audience")
            own_profile = item.get("kind") == "self_profile"
            current_disclosure = disclosed and audience == "disclosed" and item.get("scout_revision") == revision
            if (not current_disclosure and audience == "disclosed" and item.get("status") == "complete"
                    and all(isinstance(item.get(key), str) for key in ("turn_id", "scout_revision", "text"))):
                try:
                    text_sha = hashlib.sha256(item["text"].encode("utf-8")).hexdigest()
                    historical = (item["turn_id"], item["scout_revision"], text_sha) in historical_keys
                except UnicodeError:
                    historical = False
            if not own_profile and audience != "consultation" and not current_disclosure and not historical:
                continue
        elif role != "user":
            continue
        message = _pick(item, ("role", "text", "turn_id", "created", "status", "source", "kind", "error",
                              "model", "model_id", "model_selection_origin", "elapsed", "elapsed_ms", "audience", "scout_revision"))
        if historical:
            message["historical_assistant"] = True
        if role == "assistant" and item.get("kind") == "self_profile" and isinstance(item.get("profile_receipt"), dict):
            message["profile_receipt"] = _pick(item["profile_receipt"], ("version",))
        if role == "user":
            if isinstance(item.get("input_text"), str):
                message["input_text"] = item["input_text"]
            message["attachments"] = _rows(item.get("attachments"),
                lambda attachment: _pick(attachment, ("id", "name", "kind", "mime", "characters", "truncated", "bytes")))
        messages.append(message)
    return messages


def project_session(session):
    """Return a fresh browser session, or None; never mutate server state.

    Only matching server authorization, current/prepared revisions and no
    pending turn disclose chat result data. Unknown counts remain None. This
    shape filter cannot establish that model prose itself is truthful: the
    pipeline must validate consultation output before assigning its audience.
    """
    if session is None:
        return None
    if not isinstance(session, dict):
        raise TypeError("session_must_be_object_or_none")
    scout = session.get("scout") if isinstance(session.get("scout"), dict) else {}
    discovery = session.get("discovery") if isinstance(session.get("discovery"), dict) else {}
    revision = scout.get("revision") if isinstance(scout.get("revision"), str) else ""
    current = bool(revision and revision == discovery.get("revision"))
    disclosed = bool(current and scout.get("disclosed") is True and not session.get("pending")
                     and revision == session.get("prepared_discovery_revision")
                     and revision == session.get("scout_authorized_revision"))
    count = scout.get("count")
    known = current and scout.get("count_status") == "known" and type(count) is int and count >= 0
    status = scout.get("status")
    status = status if isinstance(status, str) and status in _STATUSES else "consulting"
    shaped = _pick(session, ("id", "kind", "created", "updated", "original", "turns", "mode", "asker",
                             "model_id", "model_selection_origin", "pending"))
    scope = session.get('provider_scope')
    if (isinstance(scope, dict) and scope.get('id') == 'gemini_public_papers.v1'
            and scope.get('provider') == 'gemini' and isinstance(scope.get('model_id'), str)
            and scope['model_id'].startswith('gemini:')):
        shaped['provider_scope'] = _pick(scope, ('id', 'provider', 'model_id'))
    shaped["scout"] = {"revision": revision, "status": status, "disclosed": disclosed,
                       "count": count if known else None, "count_status": "known" if known else "unknown"}
    count_basis = scout.get("count_basis")
    if known and count_basis in ("registered_record_matches", "assessed_displayed"):
        shaped["scout"]["count_basis"] = count_basis
    shaped["request_spec"] = _request_spec(session.get("request_spec"), session)
    recovery = session.get('scout_recovery') or {}
    if recovery.get('status') in ('required', 'unsupported', 'revalidated'):
        shaped['scout_recovery'] = _pick(recovery, ('id', 'from_revision', 'target_revision', 'status'))
        budget = session.get('model_generation_budget') or {}
        spec = shaped['request_spec'] or {}
        latest = next((m for m in reversed(session.get('messages') or []) if m.get('role')=='user' and m.get('kind')!='self_profile'), {})
        shaped['scout_recovery']['available'] = bool(recovery.get('status')=='required'
            and not session.get('pending') and not session.get('lookup_paused')
            and spec.get('has_content') and spec.get('state')=='stale'
            and latest.get('turn_id') == recovery.get('source_turn_id') == spec.get('source_turn_id') == budget.get('origin_turn_id')
            and type(budget.get('calls')) is int and 0 <= budget['calls'] < 4)
    shaped["messages"] = _messages(session.get("messages"), disclosed=disclosed, revision=revision,
                                  historical_disclosures=session.get("historical_disclosures"))
    shaped["result"] = _result(session.get("result")) if disclosed else None
    shaped["ready"] = bool(disclosed and session.get("ready") is True and shaped["result"] is not None)
    shaped["can_propose"] = bool(shaped["ready"] and session.get("can_propose") is True)
    shaped["discovery"] = None
    if current:
        shaped["discovery"] = _pick(discovery, ("revision", "summary", "lookup_reason", "question"))
        shaped["discovery"]["lookup_ready"] = (discovery.get("lookup_ready") is True
                and (shaped["request_spec"] or {}).get("state") == "current"
                and (shaped["request_spec"] or {}).get("has_content") is True)
    shaped["search_context"] = {"kind": "stopped" if status == "stopped" else "recommend" if disclosed else "consultation"}
    if disclosed:
        shaped["prepared_discovery_revision"] = revision
        if isinstance(scout.get("requested_revision"), str):
            shaped["scout"]["requested_revision"] = scout["requested_revision"]
    return shaped
