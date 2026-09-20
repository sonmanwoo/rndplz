"""Model interpretation, bounded read-only tools, and separately grounded answers."""
import copy
import hashlib
import json
import time
import uuid
from dataclasses import asdict

from .chat_models import validate_generation_input
from .diagnostics import event as diagnostic_event
from .discovery import DiscoveryError
from .evidence_search import PublicEvidenceSearch
from .model_dialogue import PlanValidationError, parse_plan, parse_refinement, unapplied_plan_reply, plan_repair_feedback, parse_assessment, AssessmentValidationError
from .service import now


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':')).encode()).hexdigest()


def record_origin(person_id, person_name):
    """Describe the retrieved record's subject without inferring its submitter."""
    return {'record_subject':{'id':person_id, 'name':person_name},
            'source_channel':'registered_corpus',
            'retrieved_from_current_conversation_attachment':False,
            'submitter_identity':'not_established',
            'current_conversation_user_relation':'not_established'}


# Only errors in a normally completed model proposal can enter one repair.
# Server source/allowlist errors, size limits and transport errors never do.
REPAIRABLE_PLAN_ERRORS = frozenset({
    'duplicate_json_key', 'object_fields_mismatch', 'array_shape_or_limit',
    'string_required', 'enum_value_invalid', 'string_length_invalid',
    'nonblank_string_required', 'group_term_limit', 'duplicate_group_term',
    'unknown_active_topic', 'duplicate_person_name', 'condition_quote_not_in_user_turn',
    'duplicate_or_conflicting_condition', 'nonlookup_intent_action_conflict',
    'stop_with_active_lookup_scope', 'offer_scope_missing_or_mixed',
    'search_scope_missing', 'person_name_missing',
})


class PlanMessages(list):
    """Server-only immutable request basis; JSON providers see a normal list."""
    def __init__(self, values, *, basis, deadline=None):
        super().__init__(values)
        self.basis = copy.deepcopy(basis)
        self.generation_deadline = deadline


class AssessmentMessages(list):
    def __init__(self, values, materials):
        super().__init__(values)
        self.materials = copy.deepcopy(materials)


class ModelBasisChanged(ValueError):
    pass


class ModelConversation:
    """Mixin: legacy guide/UI actions remain in Conversation; text goes to the model."""

    def _model_corpus_fingerprint(self):
        # Authorization checks need a fresh basis, not the diagnostic cache.
        corpus = self.service.corpus
        if self.service.engine.corpus is not corpus:
            raise ModelBasisChanged('대화와 조회 도구의 근거 자료가 달라 이전 모델 계획을 적용하지 않았습니다.')
        return digest({'people':[asdict(corpus.people[k]) for k in sorted(corpus.people)],
                       'records':[asdict(corpus.records[k]) for k in sorted(corpus.records)],
                       'topics':corpus.topics})

    def _model_sources(self, session):
        rows = []
        for item in session['messages']:
            if item.get('role') != 'user' or item.get('kind') == 'self_profile':
                continue
            row = {k:item[k] for k in ('role', 'turn_id', 'text', 'input_text') if k in item}
            row['source_texts'] = []
            for ref in item.get('attachments', []):
                loaded = self.attachments.load(ref['id'])
                if not loaded.get('image'):
                    row['source_texts'].append(loaded.get('text', ''))
                else:
                    row.setdefault('source_image_sha256', []).append(digest(loaded['image']))
            rows.append(row)
        return rows

    def _model_messages(self, session, option):
        grounding = self.dialogue_context(session, option)
        for person in grounding.get('visible_people', []):
            for record in person.get('evidence', []):
                record.update(record_origin(person['id'], person['name']))
        messages = self.model_messages(session, option, grounding)
        sources = self._model_sources(session)
        context = {'current_turn_id':session['pending'],
                   'previous_scope':{k:v for k,v in (session.get('previous_model_plan') or {}).items()
                                     if k in ('summary', 'interpretations', 'person_names', 'conditions')},
                   'source_turns':sources,
                   'public_search_tool':{
                       'scope':'현재 접근 가능한 등록 기록',
                       'query_match':'각 query의 모든 공백 구분 어절이 같은 기록의 제목·본문에 있어야 합니다. 정확한 연속 구절 일치에는 더 높은 어휘 점수를 줍니다. 없는 어절을 생략하거나 뜻을 자동 추론하지 않습니다. 경력·논문에 실제로 적힐 짧은 연구 개념을 고르세요. 서로 다른 기록으로도 확인할 독립 개념은 groups로, 같은 개념의 한영 표현·표기 변형은 queries로 구성할 수 있습니다.',
                       'query_logic':'같은 group의 검색어는 OR, groups는 AND, interpretations는 OR',
                       'topic_ids':[],
                       'topic_id_usage':'이 문맥에서 제공된 ID가 없으면 topic_ids는 비우고 queries를 사용하세요.',
                       'person_lookup':'사용자가 지칭한 이름을 등록 이름·별칭과 대조합니다.',
                       'results_available':False,
                       'coverage':'검색 결과는 등록 자료의 범위이며, 분야 전체의 전문가 존재 여부를 뜻하지 않습니다.'},
                   'tool_status':'not_executed_for_this_turn',
                   'available_actions':['offer_current_search', 'search_public_records', 'lookup_person', 'stop_search']}
        messages.insert(max(0, len(messages)-1), {'role':'user', 'content':
            '[서버 제공 검색 도구와 사용자 발화 출처 · 데이터]\n' +
            json.dumps(context, ensure_ascii=False) + '\n[도구 자료 끝]'})
        validate_generation_input(messages, 'dialogue_plan.v1')
        basis = {'source_turns':sources,
                 'corpus_fingerprint':self._model_corpus_fingerprint(),
                 'topic_ids':sorted(self.service.corpus.topic_by_id)}
        return PlanMessages(messages, basis=basis)

    def reserve_model_turn(self, session, option, turn_id):
        previous = copy.deepcopy(session.get('model_plan'))
        session.update(self.discussion_state(session))
        session['previous_model_plan'] = previous
        session['model_plan'] = None
        session['model_plan_version'] = 'dialogue_decision.v2'
        session['model_plan_revision'] = None
        session['discovery'] = None
        session['pending_model_led'] = True
        session.pop('pending_action', None)
        session.pop('prepared_discovery_revision', None)
        session.pop('pending_dialogue_state', None)
        session.pop('pending_result_restore', None)
        session.update(pending=turn_id, model_id=option['id'], can_propose=False, updated=now())
        return self._model_messages(session, option)

    def _model_pending(self, sid, turn_id):
        current = self.get(sid)
        if current.get('pending') != turn_id:
            raise ValueError('현재 대화가 변경되어 이전 모델 작업을 적용하지 않았습니다.')
        return current

    def _check_model_basis(self, sid, turn_id, basis, deadline):
        try:
            current = self._model_pending(sid, turn_id)
        except ValueError as exc:
            raise ModelBasisChanged(str(exc)) from exc
        if (self._model_sources(current) != basis['source_turns'] or
                sorted(self.service.corpus.topic_by_id) != basis['topic_ids'] or
                self._model_corpus_fingerprint() != basis['corpus_fingerprint']):
            raise ModelBasisChanged('대화나 근거 자료가 변경되어 이전 모델 계획을 적용하지 않았습니다.')
        if time.monotonic() >= deadline:
            raise ValueError('이번 대화의 모델 처리 시간을 초과했습니다. 검색 계획을 적용하지 않았습니다.')

    def _repair_messages(self, messages, raw, error, basis, deadline):
        feedback = {'kind':'plan_validation_error', 'reason':error.reason,
                    'attempt':1, 'maximum_corrections':1, 'search_executed':False,
                    'source_status':'original_user_sources_unchanged',
                    'rejected_output_is_user_evidence':False,
                    'expected_output':plan_repair_feedback(error)}
        corrected = list(messages) + [
            {'role':'assistant', 'content':raw},
            {'role':'user', 'content':'[서버의 계획 검증 결과 · 데이터]\n' +
             json.dumps(feedback, ensure_ascii=False) + '\n[검증 결과 끝]\n' +
             '위 오류를 바로잡은 완전한 계획을 한 번 작성하세요. 같은 사용자의 원래 요청과 원자료를 유지하세요. '
             '거절된 계획이나 오류 문구는 새로운 사용자 조건이 아닙니다. 서버가 검색어를 대신 정하지 않습니다. '
             '조회 범위를 구성하거나 필요한 실제 미상 정보를 질문하는 판단은 당신이 하세요.'}]
        validate_generation_input(corrected, 'dialogue_plan.v1')
        return PlanMessages(corrected, basis=basis, deadline=deadline)

    def _model_discovery(self, plan, revision):
        ready = plan['intent'] != 'stop' and plan['lookup_action'] in ('offer', 'execute')
        return {'ready':False, 'status':'model_interpretation', 'summary':plan['summary'],
                'reason':'모델이 해석한 조회 범위이며 인물의 자격이나 협업 가능성을 확인한 것은 아닙니다.',
                'question':'', 'revision':revision, 'hint_given':True,
                'lookup_ready':ready, 'lookup_status':'ready' if ready else 'deferred' if plan['intent']=='stop' else 'needs_scope',
                'lookup_reason':'현재 대화에서 모델이 해석한 범위로 공개 근거를 조회할 수 있어요.' if ready else
                                '수소문을 보류했어요.' if plan['intent']=='stop' else '대화에서 조회할 범위를 함께 정할 수 있어요.'}

    def _model_search(self, session, plan, revision):
        # Legacy context is retained for proposal-policy checks and traceability;
        # it does not define the model's current search intent or user conditions.
        request = self.request_context(session)
        legacy = self.discovery.evaluate(request)
        conditions = list(dict.fromkeys(c['source_quote'] for c in plan['conditions']))
        legacy_policy_blockers = list(dict.fromkeys(
            legacy.get('unsupported', []) + legacy.get('proposal_blockers', [])))
        execution_plan = {**plan, 'lookup_action':'execute'}
        if execution_plan['intent']=='chat':
            # An offered tool is distinct from the conversational question that
            # accompanies it. Only the user's button invokes this stored offer.
            execution_plan['intent']='person' if plan['person_names'] else 'search'
        result = PublicEvidenceSearch(self.service.engine).search(execution_plan,
            excluded_person_ids=request.get('excluded_person_ids', []),
            unverified_conditions=conditions, request_revision=revision, original_query=request['query'])
        # Existing evidence-based proposal gates may preserve established eligibility.
        # Model text and topic selection alone never grant it.
        for candidate in result['candidates']:
            candidate['unverified_request_conditions'] = list(conditions)
            evidence = {e['id'] for e in candidate.get('evidence', [])}
            allowed = (legacy.get('ready') is True and not conditions and not legacy_policy_blockers and
                       candidate['id'] in legacy['candidate_ids'] and bool(evidence) and
                       evidence.issubset(legacy['record_ids']))
            if allowed:
                candidate['lookup_only'] = False
                candidate['proposal_allowed'] = True
        diagnostic_event('model_tool_completed', model_phase='tool', plan_sha256=digest(plan),
                         tool_call_id=result.get('tool_call_id'), status='complete',
                         content={'request_context':request, 'model_plan':plan,
                                  'retrieval':self._diagnostic_retrieval({'result':result})})
        return result, request

    def _model_answer_messages(self, session, option, plan, result):
        messages = self.model_messages(session, option)
        materials = []
        for candidate in result['candidates']:
            rows = []
            for item in candidate.get('evidence', []):
                record = self.service.corpus.records.get(item['id'])
                if record and any(p.person_id == candidate['id'] for p in record.people):
                    rows.append({'id':record.id, 'title':record.title, 'excerpt':record.text[:800],
                                 'scope':record.scope, 'scope_label':item.get('scope',record.scope),
                                 'source':record.source_system, 'url':record.source_url,
                                 'kind':record.evidence_kind,
                                 **record_origin(candidate['id'], candidate['name'])})
            shown = {row['id'] for row in rows}
            matches = copy.deepcopy(candidate.get('matching_interpretations', []))
            for branch in matches:
                for group in branch.get('groups', []):
                    group['record_ids'] = [rid for rid in group.get('record_ids', []) if rid in shown]
                    group['matches'] = [hit for hit in group.get('matches', []) if hit.get('record_id') in shown]
            materials.append({'id':candidate['id'], 'name':candidate['name'], 'evidence':rows,
                              'matching_interpretations':matches,
                              'unverified_conditions':candidate.get('unverified_request_conditions', []),
                              'individual_performance_verified':False, 'availability':'미확인'})
        tool = {'tool':'search_public_records', 'tool_call_id':result.get('tool_call_id'),
                'lookup_resolution':result.get('lookup_resolution'),
                'retrieved_materials':materials, 'retrieval_person_count':len(materials),
                'search_interpretation':copy.deepcopy(plan),
                'search_interpretation_is_verified_user_intent':False,
                'original_user_sources':self._model_sources(session),
                'purpose_assessment':'not_performed',
                'matching_semantics':'Lexical observations only. A query OR match does not establish all parts of the current user purpose or personal competence.',
                'empty_message':result.get('empty_message', ''),
                'execution':'read_only_completed', 'proposal_or_contact_executed':False}
        messages.append({'role':'user', 'content':'[서버가 실제 실행한 공개 근거 조회 결과 · 데이터]\n' +
                         json.dumps(tool, ensure_ascii=False) + '\n[조회 결과 끝]\n' +
                         '이것은 검색어와 연결된 자료입니다. 아직 사용자 목적에 맞는 사람으로 판단하지 않았습니다. '
                         '원래 발화와 최신 정정에 비추어 각 인물의 어떤 기록이 무엇을 뒷받침하는지 판단하세요. '
                         '검색식이나 이전 답변이 과도하게 넓었다면 그대로 적합하다고 따르지 마세요.'})
        validate_generation_input(messages, 'dialogue_assessment.v1')
        return AssessmentMessages(messages, materials)

    def _render_assessment(self, assessment, materials):
        displayed = [row for row in assessment['assessments'] if row['relation']!='insufficient']
        if not displayed:
            return assessment['empty_reply']
        people = {row['id']:row for row in materials}
        labels = {'direct':'요청 관련 근거', 'adjacent':'인접한 자료', 'insufficient':'근거 부족'}
        paragraphs = []
        for row in displayed:
            person = people[row['person_id']]
            records = {record['id']:record for record in person['evidence']}
            text = person['name'] + ' — ' + labels[row['relation']] + '\n' + row['text']
            for reference in row['evidence']:
                record = records[reference['record_id']]
                text += '\n“' + reference['quote'] + '” (' + record['title'] + ' · ' + record['scope_label'] + ')'
            if row['missing']:
                text += '\n미확인: ' + row['missing']
            paragraphs.append(text)
        return '\n\n'.join(paragraphs)

    def _assessed_result(self, result, assessment, reply):
        value = copy.deepcopy(result)
        value.update(retrieved_candidate_count=len(result['candidates']),
                     retrieved_candidate_ids=[c['id'] for c in result['candidates']],
                     retrieved_record_ids=list(result.get('matching_record_ids', [])),
                     assessment_status='accepted', assessed_candidate_count=len(assessment['assessments']))
        selected = {row['person_id']:row for row in assessment['assessments'] if row['relation']=='direct'}
        cards = []
        for card in value['candidates']:
            row = selected.get(card['id'])
            if row is None:
                continue
            ids = {e['record_id'] for e in row['evidence']}
            card['evidence'] = [e for e in card['evidence'] if e['id'] in ids]
            card.update(reason=row['text'], role='요청 관련 기록', purpose_relation='direct',
                        purpose_assessment_source='model', assessment_evidence=copy.deepcopy(row['evidence']))
            # The model's relevance assessment never grants an additional right.
            cards.append(card)
        ids = {e['id'] for c in cards for e in c['evidence']}
        value.update(candidates=cards, matching_record_ids=sorted(ids), record_count=len(ids),
                     evidence=[e for e in value.get('evidence', []) if e['id'] in ids],
                     matched_candidate_count=len(cards),
                     retrieval_matched_candidate_count=result.get('matched_candidate_count', len(result['candidates'])),
                     assessment_outcomes=[{'person_id':row['person_id'], 'relation':row['relation'],
                                           'record_ids':[e['record_id'] for e in row['evidence']]}
                                          for row in assessment['assessments']])
        if not cards and result['candidates']:
            value.update(lookup_resolution='no_purpose_supported_records', empty_message=reply)
        return value

    def _stream_model_assessment(self, session, option, plan, result, basis, pending, deadline, state):
        prepared = self._model_answer_messages(session, option, plan, result)
        state.update(materials=prepared.materials, raw='', parsed=None, status='provider_incomplete')
        messages = PlanMessages(prepared, basis=basis, deadline=deadline)
        self._check_model_basis(session['id'], pending, basis, deadline)
        state['dispatched'] = True
        diagnostic_event('model_dispatch_started', model_called=True, model_phase='answer',
                         generation_contract='dialogue_assessment.v1', content={'model_messages':messages})
        for piece in self.models.stream(option['id'], messages, contract='dialogue_assessment.v1'):
            state['raw'] += piece
            if len(state['raw']) > 24000:
                raise ValueError('모델의 근거 평가가 허용 크기를 넘었습니다.')
            if time.monotonic() >= deadline:
                raise ValueError('이번 대화의 모델 처리 시간을 초과했습니다.')
            yield {'type':'phase', 'phase':'interpreting'}
        self._check_model_basis(session['id'], pending, basis, deadline)
        try:
            state['parsed'] = parse_assessment(state['raw'], materials=state['materials'])
        except AssessmentValidationError as exc:
            state['status'] = 'rejected'
            diagnostic_event('model_assessment_rejected', model_phase='answer', status='error',
                             error_kind=exc.reason,
                             content={'model_assessment_raw':state['raw'],
                                      'model_assessment_materials':state['materials']})
            raise
        self._check_model_basis(session['id'], pending, basis, deadline)
        reply = self._render_assessment(state['parsed'], state['materials'])
        assessed = self._assessed_result(result, state['parsed'], reply)
        state['status'] = 'accepted'
        diagnostic_event('model_assessment_validated', model_phase='answer', status='complete',
                         tool_call_id=result.get('tool_call_id'),
                         content={'model_assessment_raw':state['raw'], 'model_assessment':state['parsed'],
                                  'model_assessment_materials':state['materials'], 'assistant_text':reply})
        return reply, assessed

    def _finish_model_turn(self, sid, turn_id, option, reply, status, error, elapsed,
                           *, plan=None, raw_plan='', raw_plan_contract='dialogue_plan.v1', revision=None, result=None, request=None,
                           kind=None, plan_source_turn=None, plan_attempts=None, search_attempts=None, assessment=None):
        def update(state):
            session = next(s for s in state['sessions'] if s['id'] == sid)
            if session.get('pending') != turn_id:
                return self.service.present_session(session)
            # Model-led scope lives in model_plan; legacy compiler state is
            # retained only as the current successful proposal-policy snapshot.
            session.pop('request_context', None)
            session.pop('proposal_policy_context', None)
            message = {'role':'assistant', 'text':reply, 'status':status, 'error':error,
                       'turn_id':turn_id, 'model':option['name'], 'model_id':option['id'],
                       'source':'model', 'elapsed_ms':round(elapsed*1000),
                       'model_plan_raw':raw_plan, 'model_plan':plan,
                       'plan_origin_version':'dialogue_decision.v2',
                       'model_plan_raw_contract':raw_plan_contract,
                       'generation_contract':'dialogue_assessment.v1' if assessment and assessment.get('dispatched') else 'dialogue_plan.v1',
                       'model_assessment_raw':(assessment or {}).get('raw', ''),
                       'model_assessment':(assessment or {}).get('parsed'),
                       'model_assessment_materials':(assessment or {}).get('materials', []),
                       'model_assessment_status':(assessment or {}).get('status')}
            if plan_attempts is not None:
                message['model_plan_attempts'] = copy.deepcopy(plan_attempts)
            if search_attempts is not None:
                message['model_search_attempts'] = copy.deepcopy(search_attempts)
            if kind: message['kind'] = kind
            session['messages'].append(message)
            session.update(pending=None, updated=now(), can_propose=False)
            session.pop('pending_model_led', None)
            if status == 'complete' and plan is not None:
                session['model_plan'] = plan
                session['model_plan_revision'] = revision
                session['model_plan_source_turn'] = plan_source_turn or turn_id
                session['model_plan_corpus_fingerprint'] = self._model_corpus_fingerprint()
                session['discovery'] = self._model_discovery(plan, revision)
                session['lookup_paused'] = plan['intent'] == 'stop'
                if result is not None:
                    result['pool_version'] = getattr(self.service.corpus, 'demo_pool', {}).get('version')
                    session.update(result=result, ready=True,
                        search_context={'kind':'recommend', 'ids':[r['id'] for r in result['candidates']],
                                        'query':plan['summary'], 'model_plan_revision':revision},
                        prepared_discovery_revision=revision,
                        can_propose=any(c.get('proposal_allowed') and not c.get('lookup_only') for c in result['candidates']))
                elif plan['intent'] == 'stop':
                    session.update(result=None, ready=False, search_context={'kind':'stopped', 'ids':[]})
                else:
                    session['search_context'] = {'kind':'discovery' if session['discovery']['lookup_ready'] else 'discussion',
                                                 'ids':[], 'query':plan['summary']}
                if request:
                    session['proposal_policy_context'] = request
                    session['proposal_context'] = request['query'][:12000]
                    session['slots']['goal'] = request['query'][:1600]
            else:
                session['model_plan'] = None
                session['model_plan_revision'] = None
                session['discovery'] = None
                session.pop('prepared_discovery_revision', None)
                # A lexical retrieval is not a purpose-matching candidate set.
                # Preserve its trace/counts, without promoting unassessed cards.
                if result is not None:
                    failed_result = copy.deepcopy(result)
                    count = result.get('retrieved_candidate_count', len(result['candidates']))
                    failed_result.update(retrieved_candidate_count=count,
                                  retrieved_candidate_ids=result.get('retrieved_candidate_ids', [c['id'] for c in result['candidates']]),
                                  retrieved_record_ids=result.get('retrieved_record_ids', result.get('matching_record_ids', [])),
                                  candidates=[], evidence=[], matching_record_ids=[], record_count=0,
                                  matched_candidate_count=0, assessment_status='incomplete', inspection_only=True,
                                  proposal_allowed=False, can_propose=False, lookup_only=True,
                                  pool_version=getattr(self.service.corpus, 'demo_pool', {}).get('version'))
                    if count:
                        failed_result.update(lookup_resolution='assessment_incomplete',
                                      empty_message='자료를 조회했지만 사용자 목적과의 관련성 평가는 완료하지 못했습니다.')
                    session.update(result=failed_result, ready=False, search_context={'kind':'discussion', 'ids':[]})
            return self.service.present_session(session)
        return self.store.transaction(update)

    def _lookup_attempt(self, attempts, plan, revision, result):
        attempts.append({'attempt':len(attempts)+1, 'tool_call_id':result['tool_call_id'],
                         'plan_sha256':digest(plan), 'revision':revision,
                         'candidate_count':len(result['candidates']),
                         'lookup_resolution':result.get('lookup_resolution')})
        diagnostic_event('model_lookup_attempt', model_phase='tool', status='complete',
                         tool_call_id=result['tool_call_id'],
                         content={'model_search_attempts':copy.deepcopy(attempts)})

    def _refine_empty_result(self, session, option, messages, basis, pending, source_turn,
                             deadline, plan, raw, raw_contract, revision, result, request, attempts, searches):
        # One extra planning generation per originating user turn: validation
        # repair OR result feedback. A button cannot replenish this budget.
        record_lookup = (plan['intent'] == 'search' or
                         plan['intent'] == 'chat' and plan['lookup_action'] == 'offer' and
                         bool(plan['interpretations']))
        if (not record_lookup or result.get('candidates') or
                result.get('lookup_resolution') != 'no_linked_evidence' or
                any(a.get('phase') in ('repair', 'refine') for a in attempts)):
            return plan, raw, raw_contract, revision, result, request
        self._check_model_basis(session['id'], pending, basis, deadline)
        observations = PublicEvidenceSearch(self.service.engine).refinement_observation(
            excluded_person_ids=request.get('excluded_person_ids', []))
        feedback = {'kind':'empty_search_result', 'failed_plan':plan,
                    'source_tool_call_id':result['tool_call_id'],
                    'result':{'candidate_count':0, 'lookup_resolution':result['lookup_resolution']},
                    'record_observations':observations, 'observations_are_user_sources':False,
                    'remaining_plan_feedback':0}
        values = list(messages) + [
            {'role':'assistant', 'content':raw or json.dumps(plan, ensure_ascii=False)},
            {'role':'user', 'content':'[서버의 실제 0건 조회 관측 · 데이터]\n' +
             json.dumps(feedback, ensure_ascii=False) + '\n[조회 관측 끝]\n' +
             '원래 사용자가 정한 목적과 최신 정정, 추가 조건, 지칭한 이름을 유지하세요. '
             '이 기록 표본은 검색 표현을 판단하기 위한 관측이며 후보나 검증된 역량이 아닙니다. '
             '목록에 맞추어 사용자 분야를 바꾸지 마세요. 검색어의 모든 어절은 같은 기록에 있어야 합니다. '
             '원래 뜻을 보존하면서 기록에 쓰인 검색 표현을 선택해 한 번 더 조회하려면 execute와 검색 범위를, '
             '현재 자료로 추가 조회가 유용하지 않으면 insufficient와 빈 범위를 반환하세요. '
             '원래 사용자 조건과 이름은 서버가 그대로 유지합니다. 이 단계에서는 검색 표현만 결정합니다.'}]
        validate_generation_input(values, 'dialogue_refine.v1')
        inputs = PlanMessages(values, basis=basis, deadline=deadline)
        self._check_model_basis(session['id'], pending, basis, deadline)
        attempt = {'attempt':len(attempts)+1, 'phase':'refine', 'origin_turn_id':source_turn,
                   'raw':'', 'provider_completed':False, 'validation':None, 'adopted':False}
        attempts.append(attempt)
        diagnostic_event('model_dispatch_started', model_called=True, model_phase='refine',
                         generation_contract='dialogue_refine.v1',
                         content={'model_messages':inputs, 'plan_attempt':attempt['attempt'],
                                  'basis_sha256':digest(basis), 'origin_turn_id':source_turn})
        for piece in self.models.stream(option['id'], inputs, contract='dialogue_refine.v1'):
            attempt['raw'] += piece
            if len(attempt['raw']) > 24000:
                raise ValueError('모델의 조회 계획이 허용 크기를 넘었습니다.')
            if time.monotonic() >= deadline:
                raise ValueError('이번 대화의 모델 처리 시간을 초과했습니다.')
            yield {'type':'phase', 'phase':'interpreting'}
        attempt['provider_completed'] = True
        self._check_model_basis(session['id'], pending, basis, deadline)
        try:
            # An offered scope reaches this point only after the user's button
            # already executed its first lookup. Preserve that execution basis.
            executed_base = {**plan, 'intent':'search', 'lookup_action':'execute'}
            revised = parse_refinement(attempt['raw'], base_plan=executed_base,
                                       user_messages=basis['source_turns'],
                                       allowed_topic_ids=basis['topic_ids'])
        except PlanValidationError as exc:
            attempt.update(validation='rejected', reason=exc.reason)
            diagnostic_event('model_plan_rejected', model_phase='refine', status='error',
                             error_kind=exc.reason,
                             content={'model_plan_raw':attempt['raw'], 'plan_attempt':attempt['attempt']})
            raise ValueError('추가 조회 계획에서 원래 요청의 유지 여부를 확인하지 못해 추가 검색을 실행하지 않았습니다.') from exc
        execute = revised is not None
        attempt.update(validation='accepted', adopted=execute,
                       decision='search_again' if execute else 'no_further_search')
        diagnostic_event('model_plan_validated', model_phase='refine', plan_sha256=digest(revised or plan),
                         status='complete', content={'model_plan':revised or plan, 'model_plan_raw':attempt['raw'],
                                                    'model_plan_base':executed_base,
                                                    'plan_attempt':attempt['attempt']})
        if not execute:
            return plan, raw, raw_contract, revision, result, request
        self._check_model_basis(session['id'], pending, basis, deadline)
        updated_revision = digest({'turn_id':source_turn, 'plan':revised, 'corpus':basis['corpus_fingerprint']})
        updated_result, updated_request = self._model_search(session, revised, updated_revision)
        self._lookup_attempt(searches, revised, updated_revision, updated_result)
        return revised, attempt['raw'], 'dialogue_refine.v1', updated_revision, updated_result, updated_request

    def stream_model_turn(self, session, payload, option, messages):
        sid, turn_id = session['id'], payload['turn_id']
        started = time.monotonic(); deadline = started + 180
        raw = ''; raw_contract = 'dialogue_plan.v1'
        reply = ''; error = ''; status = 'cancelled'; fallback_reply = ''
        dispatched = False; attempts = []; searches = []; assessment = {}
        plan = revision = result = request = None
        try:
            yield {'type':'start', 'session':session}
            if not isinstance(messages, PlanMessages):
                raise ValueError('모델 입력의 기준 자료를 확인하지 못했습니다.')
            basis = copy.deepcopy(messages.basis)
            current_messages = PlanMessages(messages, basis=basis, deadline=deadline)
            for number in (1, 2):
                phase = 'interpret' if number == 1 else 'repair'
                self._check_model_basis(sid, turn_id, basis, deadline)
                validate_generation_input(current_messages, 'dialogue_plan.v1')
                attempt = {'attempt':number, 'phase':phase, 'origin_turn_id':turn_id, 'raw':'',
                           'provider_completed':False, 'validation':None, 'adopted':False}
                attempts.append(attempt)
                diagnostic_event('model_dispatch_started', model_called=True, model_phase=phase,
                                 generation_contract='dialogue_plan.v1',
                                 content={'model_messages':current_messages, 'plan_attempt':number,
                                          'basis_sha256':digest(basis)})
                dispatched = True; raw = ''
                for piece in self.models.stream(option['id'], current_messages, contract='dialogue_plan.v1'):
                    raw += piece; attempt['raw'] = raw
                    if len(raw) > 24000:raise ValueError('모델의 조회 계획이 허용 크기를 넘었습니다.')
                    if time.monotonic() >= deadline:raise ValueError('이번 대화의 모델 처리 시간을 초과했습니다.')
                    yield {'type':'phase', 'phase':'interpreting'}
                attempt['provider_completed'] = True
                self._check_model_basis(sid, turn_id, basis, deadline)
                try:
                    plan = parse_plan(raw, user_messages=basis['source_turns'],
                                      allowed_topic_ids=basis['topic_ids'])
                except PlanValidationError as exc:
                    attempt.update(validation='rejected', reason=exc.reason)
                    diagnostic_event('model_plan_rejected', model_phase=phase,
                                     error_kind=exc.reason, status='error',
                                     content={'model_plan_raw':raw, 'plan_attempt':number})
                    if number == 1:
                        fallback_reply = unapplied_plan_reply(raw)
                    if number == 1 and exc.reason in REPAIRABLE_PLAN_ERRORS:
                        current_messages = self._repair_messages(messages, raw, exc, basis, deadline)
                        continue
                    reply = fallback_reply or unapplied_plan_reply(raw)
                    if reply:
                        yield {'type':'delta', 'text':reply}
                        raise ValueError('모델 답변은 그대로 표시했지만 조회 계획을 확인하지 못해 검색은 실행하지 않았어요. 이전 조회 조건도 적용하지 않았습니다.') from exc
                    raise
                attempt.update(validation='accepted', adopted=True)
                revision = digest({'turn_id':turn_id, 'plan':plan, 'corpus':basis['corpus_fingerprint']})
                diagnostic_event('model_plan_validated', model_phase=phase, plan_sha256=digest(plan),
                                 status='complete', content={'model_plan':plan, 'model_plan_raw':raw,
                                                             'plan_attempt':number})
                break
            if plan['lookup_action'] == 'execute':
                yield {'type':'phase', 'phase':'searching'}
                self._check_model_basis(sid, turn_id, basis, deadline)
                result, request = self._model_search(session, plan, revision)
                self._lookup_attempt(searches, plan, revision, result)
                plan, raw, raw_contract, revision, result, request = yield from self._refine_empty_result(
                    session, option, messages, basis, turn_id, turn_id, deadline,
                    plan, raw, raw_contract, revision, result, request, attempts, searches)
                reply, result = yield from self._stream_model_assessment(
                    session, option, plan, result, basis, turn_id, deadline, assessment)
                yield {'type':'delta', 'text':reply}
            else:
                reply = plan['reply']
                yield {'type':'delta', 'text':reply}
            if not reply.strip():raise ValueError('모델이 빈 답변을 반환했습니다.')
            self._check_model_basis(sid, turn_id, basis, deadline)
            status = 'complete'
        except GeneratorExit:
            raise
        except Exception as exc:
            status = 'error'
            if not reply and fallback_reply and not isinstance(exc, ModelBasisChanged):
                # Preserve the first completed model reply when its one repair
                # fails; partial provider output is never interpreted as a plan.
                reply = fallback_reply
                yield {'type':'delta', 'text':reply}
            error = str(exc) if isinstance(exc, ValueError) else '모델의 해석 또는 조회를 완료하지 못했습니다. 다시 시도해 주세요.'
        finally:
            session = self._finish_model_turn(sid, turn_id, option, reply, status, error,
                time.monotonic()-started, plan=plan, raw_plan=raw, raw_plan_contract=raw_contract, revision=revision,
                result=result, request=request, plan_attempts=attempts, search_attempts=searches, assessment=assessment)
            diagnostic_event('turn_finished', status=status, model_called=dispatched, output_chars=len(reply),
                             model_phase='complete', partial_output=bool(reply) and status!='complete',
                             error_kind=None if status=='complete' else 'generation_error',
                             content={'assistant_text':reply, 'model_plan_raw':raw, 'model_plan':plan or {},
                                      'model_plan_attempts':attempts, 'model_search_attempts':searches,
                                      'model_assessment_raw':assessment.get('raw',''),
                                      'model_assessment':assessment.get('parsed'),
                                      'model_assessment_materials':assessment.get('materials',[])})
        yield {'type':'done' if status=='complete' else 'error', 'session':session, 'error':error}

    def prepare_model_turn(self, payload):
        sid = payload.get('session_id')
        operation = 'prepare-' + uuid.uuid4().hex
        def reserve(state):
            session = next((s for s in state['sessions'] if s['id']==sid), None)
            if not session or session.get('pending') or session.get('lookup_paused'):
                raise ValueError('현재 응답이 끝난 대화에서 수소문을 시작해 주세요.')
            if session.get('model_plan_version') != 'dialogue_decision.v2':
                # A saved offer from an older contract never becomes a lookup
                # merely because the model's output contract changed.
                session.update(self.discussion_state(session))
                session.update(model_plan=None,model_plan_revision=None,discovery=None,can_propose=False)
                session.pop('prepared_discovery_revision',None)
                return copy.deepcopy(session), 'stale'
            revision = session.get('model_plan_revision')
            plan = session.get('model_plan')
            if not plan or not revision or payload.get('discovery_revision')!=revision or not (session.get('discovery') or {}).get('lookup_ready'):
                raise DiscoveryError()
            corpus_fingerprint = self._model_corpus_fingerprint()
            expected = digest({'turn_id':session.get('model_plan_source_turn'), 'plan':plan,
                               'corpus':corpus_fingerprint})
            if session.get('model_plan_corpus_fingerprint')!=corpus_fingerprint or expected!=revision:
                session.update(self.discussion_state(session))
                session.update(model_plan=None,model_plan_revision=None,discovery=None,can_propose=False)
                session.pop('prepared_discovery_revision',None)
                return copy.deepcopy(session), 'stale'
            if session.get('prepared_discovery_revision')==revision and session.get('result') is not None:
                return copy.deepcopy(session), True
            session.update(pending=operation, pending_model_led=True, can_propose=False)
            return copy.deepcopy(session), False
        session, cached = self.store.transaction(reserve)
        if cached=='stale':raise DiscoveryError()
        if cached:return self.service.present_session(session)
        option = {'id':session['model_id'], 'name':session['model_id'], 'provider':'unknown'}
        plan, revision = session['model_plan'], session['model_plan_revision']
        started = time.monotonic(); reply=''; result=request=None; status='error'; error=''; dispatched=False; assessment={}
        deadline = started + 180
        source_turn = session['model_plan_source_turn']
        original = next((m for m in reversed(session['messages'])
                         if m.get('role') == 'assistant' and m.get('turn_id') == source_turn), {})
        attempts = copy.deepcopy(original.get('model_plan_attempts', [])); searches = []
        raw = original.get('model_plan_raw', '')
        raw_contract = original.get('model_plan_raw_contract', 'dialogue_plan.v1')
        try:
            option = self.models.get(session['model_id'])
            inputs = self._model_messages(session, option)
            basis = copy.deepcopy(inputs.basis)
            self._check_model_basis(sid, operation, basis, deadline)
            result, request = self._model_search(session, plan, revision)
            self._lookup_attempt(searches, plan, revision, result)
            refinement = self._refine_empty_result(session, option, inputs, basis, operation,
                source_turn, deadline, plan, raw, raw_contract, revision, result, request, attempts, searches)
            try:
                while True:
                    next(refinement)
            except StopIteration as completed:
                plan, raw, raw_contract, revision, result, request = completed.value
            generation = self._stream_model_assessment(session, option, plan, result,
                basis, operation, deadline, assessment)
            try:
                while True:
                    next(generation)
            except StopIteration as completed:
                reply, result = completed.value
            dispatched = assessment.get('dispatched', False)
            self._check_model_basis(sid, operation, basis, deadline)
            status='complete'
        except Exception as exc:
            error = str(exc) if isinstance(exc, ValueError) else '공개 근거 조회 또는 모델 설명을 완료하지 못했습니다.'
        finally:
            current = self._finish_model_turn(sid, operation, option, reply, status, error,
                time.monotonic()-started, plan=plan, raw_plan=raw, raw_plan_contract=raw_contract, revision=revision, result=result,
                request=request, kind='recommendation', plan_source_turn=source_turn,
                plan_attempts=attempts, search_attempts=searches, assessment=assessment)
            diagnostic_event('prepare_completed', session_id=sid, status=status, route='model',
                route_reason='model_plan_prepare', execution_kind=option['provider'],
                model_called=bool(assessment.get('dispatched')) or any(a.get('phase')=='refine' for a in attempts),
                model_phase='answer', plan_sha256=digest(plan),
                content={'assistant_text':reply, 'model_plan':plan, 'model_plan_raw':raw,
                         'model_plan_attempts':attempts, 'model_search_attempts':searches,
                         'model_assessment_raw':assessment.get('raw',''),
                         'model_assessment':assessment.get('parsed'),
                         'model_assessment_materials':assessment.get('materials',[]),
                         'retrieval':self._diagnostic_retrieval({'result':result})})
        return current
