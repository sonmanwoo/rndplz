"""Bounded retrieval over an Engine's already-visible corpus.

The selected model supplies search expressions or record IDs from the exposed
neutral catalog, never facts or invented people IDs.
Topic IDs are checked against this corpus; lexical queries search record title/text
only. An exact phrase is preferred; otherwise every whitespace-delimited query
term must occur in the same record's title/text. No query term is discarded.
Alternatives in a group are OR, groups are AND at person level, and distinct
interpretations are OR. Different records can support a person's different groups;
this does not establish that one project met every condition.

catalog() returns {topics: [{id, name, keywords}], people: [{name, aliases}]}.
search() requires a validated, explicit execute plan and returns a ChatActions-style
result, not an action envelope. The caller owns user intent/source validation and
request revision freshness. Retrieval never certifies required conditions or grants
proposal authority. This module performs no model, network, or filesystem calls.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
import json
import re
import unicodedata
import uuid


MAX_INTERPRETATIONS = 3
MAX_GROUPS = 3
MAX_TOPIC_IDS = 8
MAX_QUERIES = 5
MAX_CANDIDATES = 7
MAX_EVIDENCE = 3
MAX_SNIPPET = 700
MAX_READ_RECORDS = 21


def _normalized(value):
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _name_key(value):
    return re.sub(r"[\s.·-]", "", _normalized(value))


def _text(value, limit, label, *, empty=False):
    if not isinstance(value, str) or len(value) > limit:
        raise ValueError(label + "_invalid")
    if not empty and not value.strip():
        raise ValueError(label + "_empty")
    if any(ord(char) < 32 and char not in "\n\r\t" for char in value):
        raise ValueError(label + "_control_character")
    return value.strip()


def _strings(value, maximum, limit, label):
    if not isinstance(value, list) or len(value) > maximum:
        raise ValueError(label + "_invalid")
    values = [_text(item, limit, label) for item in value]
    if len(set(values)) != len(values):
        raise ValueError(label + "_duplicate")
    return values


def _contains(haystack, query):
    # A generic literal phrase match, with Latin/digit edges to avoid e.g. an
    # acronym inside another word. Korean inflections may follow a Korean phrase.
    needle = _normalized(query)
    if not needle or not any(char.isalnum() for char in needle):
        return False
    pattern = re.escape(needle)
    if re.match(r"[a-z0-9]", needle):
        pattern = r"(?<![a-z0-9])" + pattern
    if re.search(r"[a-z0-9]$", needle):
        pattern += r"(?![a-z0-9])"
    return re.search(pattern, _normalized(haystack)) is not None


def _query_hit(record, query):
    values = (("title", record.title or ""), ("text", record.text or ""))
    # Unicode whitespace delimits terms. Keep punctuation, particles and every
    # content term; matching is not a domain alias, stemmer or stopword filter.
    terms = _normalized(query).split()
    if not terms:
        return None
    phrase_fields = [field for field, value in values if _contains(value, query)]
    term_fields = [{"term": term, "fields": [field for field, value in values
                                             if _contains(value, term)]}
                   for term in terms]
    if phrase_fields:
        return {"query": query, "fields": phrase_fields, "match_mode": "exact_phrase",
                "terms": terms, "term_fields": term_fields}
    if not all(hit["fields"] for hit in term_fields):
        return None
    fields = [field for field, _ in values
              if any(field in hit["fields"] for hit in term_fields)]
    return {"query": query, "fields": fields, "match_mode": "all_terms",
            "terms": terms, "term_fields": term_fields}


class PublicEvidenceSearch:
    def __init__(self, engine):
        self.engine = engine
        # This must be the service's projected corpus. Never reload Corpus or
        # inspect an original/full corpus to recover a missing record.
        self.corpus = engine.corpus

    def _people(self):
        return {pid: person for pid, person in self.corpus.people.items()
                if not person.virtual}

    def _records(self, people):
        return {rid: record for rid, record in self.corpus.records.items()
                if not record.virtual and any(c.person_id in people for c in record.people)}

    def catalog(self):
        topics = []
        for topic in sorted(self.corpus.topics, key=lambda row: row["id"]):
            topics.append({"id": topic["id"], "name": topic["name"],
                           "keywords": [word for word in topic.get("keywords", [])
                                        if isinstance(word, str) and word.strip()]})
        names = []
        for person in sorted(self._people().values(), key=lambda row: row.id):
            aliases = person.profile.get("aliases", [])
            names.append({"name": person.name,
                          "aliases": list(dict.fromkeys(alias for alias in aliases
                                      if isinstance(alias, str) and alias.strip()))
                          if isinstance(aliases, list) else []})
        records = sorted(self._records(self._people()).values(), key=lambda row: row.id)
        # These are data expressions for the model to understand, not preselected
        # people or search results. Only the current visible corpus is consulted.
        examples = [{"title":record.title, "excerpt":record.text[:160],
                     "field":record.field, "scope":record.scope} for record in records[:60]]
        return {"topics": topics, "people": names, "record_expressions":examples,
                "record_expressions_omitted":max(0,len(records)-len(examples)),
                "catalog_is_search_result":False}

    def record_catalog(self, *, excluded_person_ids=()):
        """Expose neutral titles/scopes from this same projected corpus only."""
        if self.engine.corpus is not self.corpus:
            raise ValueError("catalog_corpus_changed")
        people = self._people()
        if not isinstance(excluded_person_ids, (list, tuple, set, frozenset)):
            raise ValueError("excluded_person_ids_invalid")
        excluded = set()
        for pid in excluded_person_ids:
            if not isinstance(pid, str) or pid not in people:
                raise ValueError("excluded_person_id_outside_current_corpus")
            excluded.add(pid)
        records = sorted((record for record in self._records(people).values()
                          if not any(c.person_id in excluded for c in record.people)),
                         key=lambda record: record.id)
        catalog = {"records": [], "omitted_count": len(records), "record_limit": 48,
                   "data_char_limit": 14000, "catalog_is_search_result": False}
        for record in records[:48]:
            _text(record.id, 200, "catalog_record_id")
            if not isinstance(record.title, str) or not isinstance(record.scope, str):
                raise ValueError("catalog_record_field_invalid")
            item = {"record_id": record.id, "title": record.title, "scope": record.scope}
            trial = {**catalog, "records": [*catalog["records"], item],
                     "omitted_count": len(records) - len(catalog["records"]) - 1}
            if len(json.dumps(trial, ensure_ascii=False, separators=(",", ":"))) > 14000:
                break
            catalog = trial
        return catalog

    def refinement_observation(self, *, excluded_person_ids=()):
        """Bounded source prefixes for a caller-authorized post-zero review.

        No query, relevance selection, names/topics catalog or qualification is
        inferred here. The caller must first perform the actual zero-result
        lookup and validate the current user/source basis before calling this.
        The size cap includes the whole compact JSON data object, not a prompt.
        """
        import json

        if self.engine.corpus is not self.corpus:
            raise ValueError("refinement_corpus_changed")
        people = self._people()
        if not isinstance(excluded_person_ids, (list, tuple, set, frozenset)):
            raise ValueError("excluded_person_ids_invalid")
        excluded = set()
        for pid in excluded_person_ids:
            if not isinstance(pid, str) or pid not in people:
                raise ValueError("excluded_person_id_outside_current_corpus")
            excluded.add(pid)
        records = [record for record in self._records(people).values()
                   if not any(link.person_id in excluded for link in record.people)]
        for record in records:
            _text(record.id, 200, "refinement_record_id")
        records.sort(key=lambda record: record.id)
        observation = {"records": [], "omitted_count": len(records),
                       "record_limit": 48, "data_char_limit": 14000,
                       "observations_are_candidates": False,
                       "qualification_verified": False}
        for record in records[:48]:
            item = {"record_id": record.id}
            for field, value, limit in (("title", record.title, 160),
                                        ("excerpt", record.text, 160),
                                        ("scope", record.scope, 80),
                                        ("source", record.source_system, 80),
                                        ("evidence_kind", record.evidence_kind, 80)):
                if not isinstance(value, str):
                    raise ValueError("refinement_record_field_invalid")
                # Keep exact source prefixes, including whitespace and Unicode.
                item[field] = value[:limit]
            trial = {**observation, "records": [*observation["records"], item],
                     "omitted_count": len(records) - len(observation["records"]) - 1}
            if len(json.dumps(trial, ensure_ascii=False, separators=(",", ":"))) > 14000:
                break
            observation = trial
        return observation

    def _validate(self, plan):
        allowed = {"reply", "intent", "lookup_action", "summary", "interpretations",
                   "person_names", "conditions", "record_ids"}
        if not isinstance(plan, dict) or set(plan) - allowed:
            raise ValueError("plan_invalid")
        if plan.get("intent") not in ("search", "person"):
            raise ValueError("search_intent_required")
        if plan.get("lookup_action") != "execute":
            raise ValueError("explicit_execute_required")
        for key, limit in (("reply", 6000), ("summary", 2000)):
            _text(plan.get(key, ""), limit, key, empty=True)
        names = _strings(plan.get("person_names", []), MAX_CANDIDATES, 160, "person_names")
        if any(not _name_key(name) for name in names):
            raise ValueError("person_names_empty")
        if plan["intent"] == "person" and not names:
            raise ValueError("person_name_required")
        branches = plan.get("interpretations", [])
        record_ids = _strings(plan.get("record_ids", []), MAX_READ_RECORDS, 200, "record_ids")
        if not isinstance(branches, list) or len(branches) > MAX_INTERPRETATIONS:
            raise ValueError("interpretations_invalid")
        if record_ids and branches:
            raise ValueError("mixed_lookup_modes")
        if plan["intent"] == "search" and not (branches or record_ids):
            raise ValueError("interpretation_required")
        current_topics = {topic["id"] for topic in self.corpus.topics}
        interpretations = []
        for index, branch in enumerate(branches):
            if not isinstance(branch, dict) or set(branch) != {"label", "groups"}:
                raise ValueError("interpretation_invalid")
            label = _text(branch["label"], 200, "interpretation_label")
            groups = branch["groups"]
            if not isinstance(groups, list) or not 1 <= len(groups) <= MAX_GROUPS:
                raise ValueError("groups_invalid")
            checked = []
            for group in groups:
                if not isinstance(group, dict) or set(group) != {"topic_ids", "queries"}:
                    raise ValueError("group_invalid")
                tids = _strings(group["topic_ids"], MAX_TOPIC_IDS, 100, "topic_ids")
                queries = _strings(group["queries"], MAX_QUERIES, 200, "queries")
                if not tids and not queries:
                    raise ValueError("group_empty")
                if any(tid not in current_topics for tid in tids):
                    raise ValueError("topic_id_outside_current_corpus")
                if any(not any(char.isalnum() for char in query) for query in queries):
                    raise ValueError("query_without_searchable_text")
                checked.append({"topic_ids": tids, "queries": queries})
            interpretations.append({"index": index, "label": label, "groups": checked,
                                    "source": "model_interpretation"})
        conditions = plan.get("conditions", [])
        if not isinstance(conditions, list) or len(conditions) > 16:
            raise ValueError("conditions_invalid")
        for condition in conditions:
            if not isinstance(condition, dict) or set(condition) != {
                    "kind", "text", "source_turn_id", "source_quote"}:
                raise ValueError("condition_invalid")
            if condition["kind"] not in ("required", "preference"):
                raise ValueError("condition_kind_invalid")
            _text(condition["text"], 1000, "condition_text")
            _text(condition["source_turn_id"], 200, "condition_source_turn_id")
            _text(condition["source_quote"], 2000, "condition_source_quote")
        return interpretations, names, deepcopy(conditions), record_ids

    def _names(self, names, people):
        registry = {}
        for pid, person in people.items():
            aliases = person.profile.get("aliases", [])
            aliases = aliases if isinstance(aliases, list) else []
            for alias in [person.name, *aliases]:
                if isinstance(alias, str) and _name_key(alias):
                    registry.setdefault(_name_key(alias), set()).add(pid)
        selected, unresolved, ambiguous = set(), [], []
        for name in names:
            found = registry.get(_name_key(name), set())
            selected.update(found)
            if not found:
                unresolved.append(name)
            elif len(found) > 1:
                ambiguous.append(name)
        return selected, unresolved, ambiguous

    def _group_matches(self, group, records, people):
        topics = {tid: 1 for tid in group["topic_ids"]}
        query_text = " ".join(group["queries"])
        field = self.engine.field_for(topics, "advice", query_text)
        ranked = {record.id: score for record, score in
                  self.engine.record_scores(query_text, topics, field, "advice")} if topics else {}
        matches = {}
        for record in records.values():
            tids = [tid for tid in group["topic_ids"] if tid in record.tags]
            query_hits = []
            for query in group["queries"]:
                hit = _query_hit(record, query)
                if hit:
                    query_hits.append(hit)
            if not tids and not query_hits:
                continue
            # Engine scoring is optional ranking, never a gate for tagless text.
            # Preserve original phrase scores. Even MAX_QUERIES fallback hits
            # contribute less than one exact phrase; topic ranking stays intact.
            lexical_score = sum((1.0 if "title" in hit["fields"] else 0.5)
                                if hit["match_mode"] == "exact_phrase"
                                else (0.05 if "title" in hit["fields"] else 0.025)
                                for hit in query_hits)
            score = round(max(ranked.get(record.id, 0.0), 0.2 if tids else 0.0) + lexical_score, 6)
            match = {"record_id": record.id, "topic_ids": tids,
                     "queries": query_hits, "score": score}
            for contribution in record.people:
                if contribution.person_id in people:
                    matches.setdefault(contribution.person_id, {})[record.id] = match
        return matches

    def _evidence(self, record, pid=None):
        contribution = next((c for c in record.people if c.person_id == pid), None) if pid else None
        evidence = deepcopy(self.engine.explain_record(record, contribution))
        text = record.text or ""
        evidence.update(snippet=text[:MAX_SNIPPET], snippet_source="record.text",
                        snippet_truncated=len(text) > MAX_SNIPPET)
        return evidence

    def _candidate(self, person, scored, topics, original_query, interpretations, records):
        best = scored[0][0]
        if best.tags and best.tags[0] in self.corpus.topic_by_id:
            card = deepcopy(self.engine.candidate(person, scored, topics, original_query))
        else:
            # Tagless lexical evidence cannot call Engine.candidate, whose reason
            # requires best.tags[0]. Build the same card fields from current data.
            own = [record for record in records.values()
                   if any(c.person_id == person.id for c in record.people)]
            card = {"id": person.id, "name": person.name, "org": person.org,
                    "org_type": person.org_type,
                    "profile": deepcopy(person.profile) if person.profile.get("curated") else {},
                    "virtual": False, "kind": person.kind, "role": "관련 등록 기록",
                    "experience": best.title, "evidence_counts": dict(Counter(r.evidence_kind for r in own)),
                    "works_count": person.profile.get("works_count"), "works_in_corpus": len(own),
                    "profile_topics": [], "portfolio": "등록 기록 연결 · 조건 충족 미확인",
                    "availability": "미확인", "details": {}, "score_internal": scored[0][1]}
        card["evidence"] = [self._evidence(record, person.id) for record, _ in scored[:MAX_EVIDENCE]]
        card.update(
            reason="모델이 해석한 검색 표현과 연결된 현재 등록 기록입니다. "
                   "서로 다른 기록이 각 검색 조건에 연결될 수 있으며, 요청 분야의 적임자나 필수조건 충족을 입증하지 않습니다.",
            role="모델 해석과 연결된 등록 기록", topics=sorted({tid for record, _ in scored
                                                        for tid in record.tags if tid in self.corpus.topic_by_id}),
            record_count=len(scored), relevant_records=len(scored), record_confirmed=True,
            condition_checked=False, individual_performance_verified=False, person_confirmed=False,
            lookup_only=True, proposal_allowed=False,
            proposal_unavailable_reason="관련 기록 열람 결과입니다. 필수조건 충족과 제안 권한은 별도 확인이 필요합니다.",
            matching_interpretations=deepcopy(interpretations), interpretation_source="model_interpretation")
        return card

    def search(self, plan, *, excluded_person_ids=(), unverified_conditions=(),
               request_revision="", original_query=""):
        if self.engine.corpus is not self.corpus:
            raise ValueError("search_corpus_changed")
        interpretations, names, conditions, record_ids = self._validate(plan)
        request_revision = _text(request_revision, 200, "request_revision", empty=True)
        original_query = _text(original_query, 12000, "original_query", empty=True)
        people = self._people()
        records = self._records(people)
        if not isinstance(excluded_person_ids, (list, tuple, set, frozenset)):
            raise ValueError("excluded_person_ids_invalid")
        excluded = set()
        for pid in excluded_person_ids:
            if not isinstance(pid, str) or pid not in people:
                raise ValueError("excluded_person_id_outside_current_corpus")
            excluded.add(pid)
        if not isinstance(unverified_conditions, (list, tuple)) or len(unverified_conditions) > 100:
            raise ValueError("unverified_conditions_invalid")
        # These are server-provided notes, kept distinct from model-proposed source
        # conditions. Neither is promoted into record evidence or a qualification.
        notes = deepcopy(list(unverified_conditions))
        if any(not isinstance(note, (str, dict)) for note in notes):
            raise ValueError("unverified_condition_invalid")
        named, unresolved_names, ambiguous_names = self._names(names, people)
        selection_source = "record_id_read" if record_ids else "lexical_search" if interpretations else "registered_name"
        if record_ids:
            catalog_ids = {row["record_id"] for row in
                           self.record_catalog(excluded_person_ids=excluded)["records"]}
            if any(rid not in records or rid not in catalog_ids for rid in record_ids):
                raise ValueError("record_id_not_exposed")
        per_person = {}
        summaries = []
        for rid in record_ids:
            # ID selection grants access to this record, not lexical evidence or
            # semantic relevance. Actual links and an optional name filter bind it.
            for contribution in records[rid].people:
                pid = contribution.person_id
                if pid not in people or pid in excluded or names and pid not in named:
                    continue
                per_person.setdefault(pid, {"records": {}, "interpretations": []})["records"][rid] = 1.0
        for interpretation in interpretations:
            groups = [self._group_matches(group, records, people) for group in interpretation["groups"]]
            eligible = set(groups[0])
            for group in groups[1:]:
                eligible.intersection_update(group)
            if names:
                eligible.intersection_update(named)
            admitted = eligible - excluded
            summaries.append({**deepcopy(interpretation), "matched_candidate_count": len(admitted)})
            for pid in eligible:
                row = per_person.setdefault(pid, {"records": {}, "interpretations": []})
                details = []
                for index, group in enumerate(groups):
                    hits = sorted(group[pid].values(), key=lambda hit: (-hit["score"], hit["record_id"]))
                    details.append({"index": index, "record_ids": [hit["record_id"] for hit in hits],
                                    "matches": deepcopy(hits)})
                    for hit in hits:
                        rid = hit["record_id"]
                        row["records"][rid] = max(row["records"].get(rid, 0), hit["score"])
                row["interpretations"].append({"index": interpretation["index"], "label": interpretation["label"],
                                               "source": "model_interpretation", "groups": details})
        if not interpretations and not record_ids and names:
            for pid in named:
                # by_person is an index, not a second authority: require the same
                # visible current record and an actual contribution linking pid.
                linked = {record.id: 1.0 for record in self.corpus.by_person.get(pid, [])
                          if record.id in records and any(c.person_id == pid for c in records[record.id].people)}
                if linked:
                    per_person[pid] = {"records": linked, "interpretations": []}
        before_exclusion = bool(per_person)
        per_person = {pid: row for pid, row in per_person.items() if pid not in excluded}
        topics = {tid: 1 for interpretation in interpretations for group in interpretation["groups"]
                  for tid in group["topic_ids"]}
        ordered = sorted(per_person, key=lambda pid: (-max(per_person[pid]["records"].values()), pid))
        cards = []
        for pid in ordered[:MAX_CANDIDATES]:
            row = per_person[pid]
            ranked_ids = sorted(row["records"], key=lambda rid: (-row["records"][rid], rid))
            # Keep one witness for each AND group of the first interpretation in
            # the visible three. Full group IDs remain available for re-grounding.
            witness_ids = []
            if row["interpretations"]:
                for group in row["interpretations"][0]["groups"]:
                    rid = group["record_ids"][0]
                    if rid not in witness_ids:
                        witness_ids.append(rid)
            scored_ids = witness_ids + [rid for rid in ranked_ids if rid not in witness_ids]
            scored = [(records[rid], row["records"][rid]) for rid in scored_ids]
            card = self._candidate(people[pid], scored, topics, original_query, row["interpretations"], records)
            card["selection_source"] = selection_source
            if record_ids:
                card.update(role="선택한 등록 자료",
                            reason="모델이 현재 자료 목록에서 선택해 읽은 기록입니다. 요청 목적의 적합성이나 개인의 역량을 확인한 결과는 아닙니다.",
                            interpretation_source="record_id_read")
            elif names and not interpretations:
                card.update(role="등록 이름과 연결된 기록",
                            reason="선택된 이름과 연결된 현재 등록 기록입니다. 인물 본인 확인이나 요청 업무의 적합성 검증을 뜻하지 않습니다.",
                            interpretation_source="registered_name")
            cards.append(card)
        if cards:
            resolution, message = "matched", ""
        elif before_exclusion:
            resolution, message = "excluded_all", "현재 검색 표현과 연결된 기록의 인물이 모두 제외되어 표시할 후보가 없습니다."
        elif names and not named:
            resolution, message = "name_not_found", "현재 조회 가능한 등록 이름에서 해당 이름을 확인하지 못했습니다."
        else:
            resolution = "no_linked_evidence"
            message = "모델이 해석한 검색 표현으로 현재 조회 가능한 기록을 찾아보았지만, 조건 그룹에 함께 연결되는 인물 기록을 찾지 못했습니다. 자료 전체에 해당 전문성이 없다는 뜻은 아닙니다."
        visible_ids = {card["id"] for card in cards}
        linked_ids = sorted({rid for pid in visible_ids for rid in per_person[pid]["records"]})
        shown_ids = sorted({evidence["id"] for card in cards for evidence in card["evidence"]})
        result = {"intent": "recommend", "mode": "advice", "mode_label": "관련 기록 조회",
                  "field": self.engine.field_for(topics, "advice", original_query), "topic_ids": list(topics),
                  "candidates": cards, "choices": [], "author_strip": [], "author_strip_record": None,
                  "closest_topics": [], "empty_message": message, "record_count": len(linked_ids),
                  "model_calls": 0,
                  "ranking_source": "모델이 선택한 등록 자료 읽기" if record_ids else "모델 검색 해석 · 현재 등록 기록 조회",
                  "claims": [],
                  "tool_call_id": uuid.uuid4().hex, "tool_name": "public_evidence_search",
                  "request_revision": request_revision, "original_query": original_query,
                  "selection_source": selection_source,
                  "selected_record_ids": list(record_ids),
                  "omitted_selected_record_ids": sorted(set(record_ids) - set(shown_ids)),
                  "lookup_resolution": resolution, "interpretations": summaries,
                  "interpretation_source": "record_id_read" if record_ids else "model_interpretation",
                  "group_semantics": "selected_records_with_name_filter" if record_ids else "OR_terms_AND_groups_per_person_OR_interpretations",
                  "matching_record_ids": linked_ids, "evidence": [self._evidence(records[rid]) for rid in shown_ids],
                  "unresolved_person_names": unresolved_names, "ambiguous_person_names": ambiguous_names,
                  "unverified_request_conditions": notes, "model_proposed_conditions": conditions,
                  "required_conditions_verified": False, "lookup_only": True, "proposal_allowed": False,
                  "can_propose": False, "candidate_limit": MAX_CANDIDATES,
                  "matched_candidate_count": len(per_person), "candidates_truncated": len(per_person) > MAX_CANDIDATES}
        pool = getattr(self.corpus, "demo_pool", None)
        if isinstance(pool, dict) and isinstance(pool.get("version"), str):
            result["pool_version"] = pool["version"]
        return result
