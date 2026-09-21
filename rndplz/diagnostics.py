"""Bounded operational diagnostics, independent from dialogue and model execution.

Importing this module performs no I/O. Files written here belong to the supplied
private diagnostics directory; original conversation/attachment files are never
read or removed. API callers must authorize remote reads with DiagnosticAuth.
"""
from __future__ import annotations

import contextlib
import contextvars
import copy
from datetime import datetime, timezone
import hashlib
import hmac
import json
import math
import os
from pathlib import Path
import re
import threading
import time
from urllib.parse import urlsplit, urlunsplit
import uuid

_VERSION = 1
_CONTEXT = contextvars.ContextVar('rndplz_diagnostic_context', default=None)
_ID = re.compile(r'[A-Za-z0-9_.:-]{1,100}\Z')
_RECORD_ID = re.compile(r'(?:[A-Za-z0-9_.:-]{1,100}|https://openalex\.org/[AW][0-9]{1,24})\Z')
_TOKEN = re.compile(r'(?:[a-fA-F0-9]{64}|[A-Za-z0-9_-]{43})\Z')
_HEX = re.compile(r'[a-f0-9]{64}\Z')
_ROUTES = {'model','records','clarify','cancel','guide','reject','unknown'}
_EXECUTIONS = {'records','guide','bridge','ollama','api','unknown'}
_STATUSES = {'started','complete','error','cancelled','rejected','pending'}
_ID_FIELDS = {'diagnostic_run','visitor_ref','session_id','turn_id','attempt_id','request_id','trace_id','job_id','event_id',
              'route_reason','error_kind','failure_stage','code_fingerprint','prompt_sha256',
              'worker_source_fingerprint','worker_input_fingerprint','worker_instance','credential_id','event_type','previous_mode','next_mode',
              'generation_contract','model_phase','plan_sha256','tool_call_id','deployment_revision',
              'client_request_id','claimed_session_id','claimed_turn_id','client_event_id'}
_PROVIDER_REASONS = frozenset(('http_error','provider_error','prompt_blocked','candidate_count',
    'incomplete','content_role','content_parts','content_part','nontext_content','text_limit',
    'invalid_json','deadline','response_type','response_size','response_json','transport_failure',
    'process_call_cap','chat_minimum_calls'))
_MODEL_FIELDS = {'model_selected','model_job','provider_model_observed'}
_NUMBER_FIELDS = {'input_chars','output_chars','attachment_count','elapsed_ms','queue_ms','first_delta_ms',
                  'model_ms','http_status','candidate_count','evidence_count','sequence','num_ctx','num_predict','storage_elapsed_ms','poll_count'}
_BOOL_FIELDS = {'partial_output','cached','model_called','truncated','eof','terminal_yielded',
                'session_verified','request_verified','pending_present','pending_cleared','client_reported'}
_SELECTION_SOURCES = {'lexical_search','record_id_read','registered_name'}
# Current summary values are replaceable; immutable event_contents retains every
# observed original/response attempt, including a superseded first response.
_CURRENT_CONTENT_FIELDS = {'assistant_text','model_plan','model_plan_raw','model_plan_base',
    'model_assessment_raw','model_assessment','model_assessment_materials','model_assessment_status',
    'model_response_attempts','model_response_status','model_plan_attempts','model_search_attempts',
    'model_generation_budget','model_consultation_attempts'}
_SECRET_KEY = re.compile(r'(?i)(?:token|secret|password|api.?key|authorization|cookie|csrf|lease|headers?|environ|config|image|base64|raw_bytes)')
_LIMITS = {'retention_seconds':7*86400,'content_retention_seconds':86400,'snapshot_retention_seconds':86400,
           'max_event_bytes':2*1024*1024,'max_total_event_bytes':32*1024*1024,
           'max_content_bytes':64*1024*1024,'max_attempt_bytes':2*1024*1024,
           'max_snapshot_bytes':5*1024*1024,'max_total_snapshot_bytes':32*1024*1024}


def _stamp(value):
    return datetime.fromtimestamp(value,timezone.utc).isoformat(timespec='milliseconds')


def _time(value):
    if isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value):return float(value)
    if not isinstance(value,str) or len(value)>64:raise ValueError('진단 시간 범위를 확인해 주세요.')
    try:
        parsed=datetime.fromisoformat(value.replace('Z','+00:00'))
        if parsed.tzinfo is None:raise ValueError()
        return parsed.timestamp()
    except (ValueError,OverflowError):raise ValueError('진단 시간 범위를 확인해 주세요.') from None


def _identifier(value):
    if not isinstance(value,str) or not _ID.fullmatch(value):raise ValueError('진단 식별자를 확인해 주세요.')
    return value


def _bytes_present(value, seen=None):
    if isinstance(value,(bytes,bytearray,memoryview)):return True
    if not isinstance(value,(dict,list,tuple)):return False
    seen=set() if seen is None else seen
    if id(value) in seen:return True
    seen.add(id(value))
    parts=list(value.values())+list(value.keys()) if isinstance(value,dict) else value
    found=any(_bytes_present(item,seen) for item in parts)
    seen.remove(id(value));return found


def redact_text(value, limit=24000):
    """Best-effort content filter. Metadata uses a separate strict allowlist."""
    if not isinstance(value,str):return ''
    value=value[:limit]
    value=re.sub(r'(?i)\bsk-[A-Za-z0-9_-]{8,}', '[REDACTED]', value)
    value=re.sub(r'(?i)\bBearer\s+[^\s\"\'<>]+', 'Bearer [REDACTED]', value)
    value=re.sub(r'(?i)(?:[\"\']?(?:authorization|set-cookie|cookie|csrf|lease|(?:[A-Za-z0-9_]*)(?:api_key|token|secret|password))[\"\']?\s*[:=])[^\r\n]*', '[REDACTED]', value)
    value=re.sub(r'(?i)data:image/[^\s,]+;base64,[A-Za-z0-9+/=\s]+','[REDACTED]',value)
    value=re.sub(r'(?<![A-Za-z0-9+/])[A-Za-z0-9+/]{160,}={0,2}(?![A-Za-z0-9+/])','[REDACTED]',value)
    value=re.sub(r'\b[A-Za-z]:[\\/][^\r\n]+','[REDACTED]',value)
    def clean_url(match):
        try:
            parts=urlsplit(match.group())
            host=parts.hostname or ''
            if parts.port:host+=':'+str(parts.port)
            return urlunsplit((parts.scheme,host,parts.path,'[REDACTED]' if parts.query else '', ''))
        except ValueError:return '[REDACTED]'
    return re.sub(r'https?://[^\s<>\"\']+',clean_url,value)


def _metadata(values):
    if not isinstance(values,dict) or _bytes_present(values):raise ValueError('진단 메타데이터 형식을 확인해 주세요.')
    result={}
    for key,value in values.items():
        if not isinstance(key,str) or _SECRET_KEY.search(key):continue
        if key in _OPERATION_ENUMS and key not in _ID_FIELDS:
            if isinstance(value,str) and value in _OPERATION_ENUMS[key]:result[key]=value
        elif key.startswith('client_') and key[7:] in _ATTACHMENT_CLIENT_NUMBERS:
            lower,upper=_ATTACHMENT_CLIENT_NUMBERS[key[7:]]
            if type(value) is int and lower<=value<=upper:result[key]=value
        elif key=='provider_error_reason':
            if isinstance(value,str) and value in _PROVIDER_REASONS:result[key]=value
        elif key=='provider_http_status':
            if type(value) is int and 100<=value<=599:result[key]=value
        elif key in _ID_FIELDS:
            if value is None:result[key]=None
            elif isinstance(value,str) and _ID.fullmatch(value) and redact_text(value)==value:result[key]=value
        elif key in _MODEL_FIELDS:
            if value is None:result[key]=None
            elif isinstance(value,str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:/-]{0,149}',value) and redact_text(value)==value:result[key]=value
        elif key in _NUMBER_FIELDS:
            if value is None:result[key]=None
            elif isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value) and 0<=value<=10**10:result[key]=value
        elif key in _BOOL_FIELDS and isinstance(value,bool):result[key]=value
        elif key=='route' and value in _ROUTES:result[key]=value
        elif key=='execution_kind' and value in _EXECUTIONS:result[key]=value
        elif key=='status' and value in _STATUSES:result[key]=value
    if result.get('event_type') in _PHASE_EVENTS and result.get('status') in ('complete','error','rejected','cancelled'):
        result['phase_status']=result['status'];result['status']='started'
    return result


def _assessment_text(value, limit):
    # Redaction can expand a short secret to a marker; enforce the final cap too.
    return redact_text(value, limit)[:limit]


def _assessment_id(value):
    # Keep the existing stricter ID alphabet/100-character bound, not free text.
    return value if isinstance(value,str) and _ID.fullmatch(value) and redact_text(value)==value else None


def _assessment_list(value, limit):
    return value[:limit] if isinstance(value,list) else []


def _assessment_ids(value, limit):
    return [item for item in _assessment_list(value,limit) if _assessment_id(item) is not None]


def _assessment_fields(value):
    return [item for item in _assessment_list(value,2) if item in ('title','text')]


def _assessment_matching(value):
    """Literal search observations, not an assessment of professional ability."""
    branches=[]
    for branch in _assessment_list(value,3):
        if not isinstance(branch,dict):continue
        row={'groups':[]}
        if type(branch.get('index')) is int and 0<=branch['index']<=2:row['index']=branch['index']
        if isinstance(branch.get('label'),str):row['label']=_assessment_text(branch['label'],120)
        if branch.get('source')=='model_interpretation':row['source']='model_interpretation'
        for group in _assessment_list(branch.get('groups'),3):
            if not isinstance(group,dict):continue
            clean={'record_ids':_assessment_ids(group.get('record_ids'),3),'matches':[]}
            if type(group.get('index')) is int and 0<=group['index']<=2:clean['index']=group['index']
            for match in _assessment_list(group.get('matches'),3):
                if not isinstance(match,dict):continue
                hit={'topic_ids':_assessment_ids(match.get('topic_ids'),5),'queries':[]}
                if _assessment_id(match.get('record_id')) is not None:hit['record_id']=match['record_id']
                score=match.get('score')
                if type(score) in (int,float) and 0<=score<=10**10 and math.isfinite(score):hit['score']=score
                for query in _assessment_list(match.get('queries'),5):
                    if not isinstance(query,dict):continue
                    detail={'fields':_assessment_fields(query.get('fields'))}
                    if isinstance(query.get('query'),str):detail['query']=_assessment_text(query['query'],200)
                    if query.get('match_mode') in ('exact_phrase','all_terms'):detail['match_mode']=query['match_mode']
                    # A 200-character query has at most 100 whitespace-separated
                    # terms. Bound both the item count and aggregate copied text.
                    detail['terms']=[];remaining=200
                    for term in _assessment_list(query.get('terms'),100):
                        if not isinstance(term,str):continue
                        if len(term)>remaining:break
                        cleaned=_assessment_text(term,remaining)
                        detail['terms'].append(cleaned);remaining-=len(cleaned)
                    detail['term_fields']=[];remaining=200
                    for term in _assessment_list(query.get('term_fields'),100):
                        if not isinstance(term,dict) or not isinstance(term.get('term'),str):continue
                        if len(term['term'])>remaining:break
                        cleaned=_assessment_text(term['term'],remaining)
                        detail['term_fields'].append({'term':cleaned,'fields':_assessment_fields(term.get('fields'))})
                        remaining-=len(cleaned)
                    hit['queries'].append(detail)
                clean['matches'].append(hit)
            row['groups'].append(clean)
        branches.append(row)
    return branches


def _record_ids(value, limit):
    return [item for item in _assessment_list(value,limit)
            if isinstance(item,str) and _RECORD_ID.fullmatch(item) and redact_text(item)==item]


def _clean_interpretations(value):
    interpretations=[]
    for branch in _assessment_list(value,3):
        if not isinstance(branch,dict):continue
        item={'label':redact_text(branch.get('label',''),1000),'groups':[]}
        for group in _assessment_list(branch.get('groups'),3):
            if not isinstance(group,dict):continue
            item['groups'].append({'topic_ids':_assessment_ids(group.get('topic_ids'),8),
                'queries':[redact_text(q,500) for q in _assessment_list(group.get('queries'),6) if isinstance(q,str)]})
        interpretations.append(item)
    return interpretations


def _clean_next_lookup(value):
    clean={}
    if isinstance(value.get('interpretations'),list):clean['interpretations']=_clean_interpretations(value['interpretations'])
    if isinstance(value.get('record_ids'),list):clean['record_ids']=_record_ids(value['record_ids'],21)
    return clean


def _clean_assessment(value):
    clean={'assessments':[]}
    if isinstance(value.get('empty_reply'),str):clean['empty_reply']=_assessment_text(value['empty_reply'],800)
    # New response contract keeps the complete model reply; legacy empty_reply
    # remains readable for retained older diagnostic events.
    if isinstance(value.get('reply'),str):clean['reply']=_assessment_text(value['reply'],6000)
    if 'next_lookup' in value:
        if value['next_lookup'] is None:clean['next_lookup']=None
        elif isinstance(value['next_lookup'],dict):clean['next_lookup']=_clean_next_lookup(value['next_lookup'])
    for assessment in _assessment_list(value.get('assessments'),7):
        if not isinstance(assessment,dict):continue
        row={'evidence':[]}
        if _assessment_id(assessment.get('person_id')) is not None:row['person_id']=assessment['person_id']
        if assessment.get('relation') in ('direct','adjacent','insufficient'):row['relation']=assessment['relation']
        for key,limit in (('text',400),('missing',300)):
            if isinstance(assessment.get(key),str):row[key]=_assessment_text(assessment[key],limit)
        for evidence in _assessment_list(assessment.get('evidence'),3):
            if not isinstance(evidence,dict):continue
            item={}
            if _assessment_id(evidence.get('record_id')) is not None:item['record_id']=evidence['record_id']
            if isinstance(evidence.get('quote'),str):item['quote']=_assessment_text(evidence['quote'],240)
            row['evidence'].append(item)
        clean['assessments'].append(row)
    return clean


def _clean_assessment_materials(value):
    materials=[]
    for person in value[:7]:
        if not isinstance(person,dict):continue
        row={'evidence':[]}
        if _assessment_id(person.get('id')) is not None:row['id']=person['id']
        if isinstance(person.get('name'),str):row['name']=_assessment_text(person['name'],200)
        if isinstance(person.get('unverified_conditions'),list):
            row['unverified_conditions']=[_assessment_text(item,1000) for item in person['unverified_conditions'][:100] if isinstance(item,str)]
        if type(person.get('individual_performance_verified')) is bool:
            row['individual_performance_verified']=person['individual_performance_verified']
        if isinstance(person.get('availability'),str):row['availability']=_assessment_text(person['availability'],100)
        if person.get('selection_source') in _SELECTION_SOURCES:row['selection_source']=person['selection_source']
        for key in ('selected_record_ids','omitted_selected_record_ids'):
            if isinstance(person.get(key),list):row[key]=_record_ids(person[key],21)
        if isinstance(person.get('matching_interpretations'),list):
            row['matching_interpretations']=_assessment_matching(person['matching_interpretations'])
        for record in _assessment_list(person.get('evidence'),3):
            if not isinstance(record,dict):continue
            item={}
            if _assessment_id(record.get('id')) is not None:item['id']=record['id']
            for key,limit in (('title',400),('excerpt',800),('scope_label',200),('source',200),
                              ('scope',100),('kind',100),('url',2000)):
                if isinstance(record.get(key),str):item[key]=_assessment_text(record[key],limit)
            if isinstance(record.get('record_subject'),dict):
                subject=record['record_subject'];item['record_subject']={}
                if _assessment_id(subject.get('id')) is not None:item['record_subject']['id']=subject['id']
                if isinstance(subject.get('name'),str):item['record_subject']['name']=_assessment_text(subject['name'],200)
            if record.get('source_channel')=='registered_corpus':item['source_channel']='registered_corpus'
            key='retrieved_from_current_conversation_attachment'
            if type(record.get(key)) is bool:item[key]=record[key]
            for key in ('submitter_identity','current_conversation_user_relation'):
                if record.get(key)=='not_established':item[key]='not_established'
            row['evidence'].append(item)
        materials.append(row)
    return materials


def _clean_content(value):
    if not isinstance(value,dict) or _bytes_present(value):raise ValueError('진단 상세 형식을 확인해 주세요.')
    result={}
    for key in ('user_text','assistant_text','model_plan_raw'):
        if key in value:result[key]=redact_text(value[key])
    if isinstance(value.get('model_assessment_raw'),str):
        result['model_assessment_raw']=_assessment_text(value['model_assessment_raw'],24000)
    if 'model_assessment' in value and value['model_assessment'] is None:
        result['model_assessment']=None
    elif isinstance(value.get('model_assessment'),dict):
        result['model_assessment']=_clean_assessment(value['model_assessment'])
    if isinstance(value.get('model_assessment_materials'),list):
        result['model_assessment_materials']=_clean_assessment_materials(value['model_assessment_materials'])
    for key in ('model_assessment_status','model_response_status'):
        if _assessment_id(value.get(key)) is not None:result[key]=value[key]
    if isinstance(value.get('model_response_attempts'),list):
        responses=[]
        for row in value['model_response_attempts'][:2]:
            if not isinstance(row,dict):continue
            item={}
            if type(row.get('attempt')) is int and 1<=row['attempt']<=2:item['attempt']=row['attempt']
            if isinstance(row.get('raw'),str):item['raw']=_assessment_text(row['raw'],24000)
            if 'parsed' in row:
                if row['parsed'] is None:item['parsed']=None
                elif isinstance(row['parsed'],dict):item['parsed']=_clean_assessment(row['parsed'])
            if isinstance(row.get('materials'),list):item['materials']=_clean_assessment_materials(row['materials'])
            for key in ('adopted','provider_completed'):
                if type(row.get(key)) is bool:item[key]=row[key]
            if row.get('validation') in (None,'accepted','rejected') and 'validation' in row:item['validation']=row['validation']
            for key in ('tool_call_id','discovery_revision','reason','status'):
                if key in row and row[key] is None:item[key]=None
                elif _assessment_id(row.get(key)) is not None:item[key]=row[key]
            if 'next_plan' in row:
                if row['next_plan'] is None:item['next_plan']=None
                elif isinstance(row['next_plan'],dict):item['next_plan']=_clean_content({'model_plan':row['next_plan']})['model_plan']
            responses.append(item)
        result['model_response_attempts']=responses
    if isinstance(value.get('model_consultation_attempts'),list):
        consultations=[]
        for row in value['model_consultation_attempts'][:1]:
            if not isinstance(row,dict):continue
            item={}
            if type(row.get('attempt')) is int and row['attempt']==1:item['attempt']=1
            if isinstance(row.get('raw'),str):item['raw']=_assessment_text(row['raw'],8000)
            for key in ('provider_completed','adopted'):
                if type(row.get(key)) is bool:item[key]=row[key]
            if row.get('validation') in (None,'accepted','rejected') and 'validation' in row:item['validation']=row['validation']
            for key in ('revision','reason'):
                if _assessment_id(row.get(key)) is not None:item[key]=row[key]
            consultations.append(item)
        result['model_consultation_attempts']=consultations
    if isinstance(value.get('model_generation_budget'),dict):
        budget=value['model_generation_budget'];clean_budget={}
        if _assessment_id(budget.get('origin_turn_id')) is not None:clean_budget['origin_turn_id']=budget['origin_turn_id']
        if type(budget.get('calls')) is int and 0<=budget['calls']<=4:clean_budget['calls']=budget['calls']
        if type(budget.get('extra_consumed')) is bool:clean_budget['extra_consumed']=budget['extra_consumed']
        result['model_generation_budget']=clean_budget
    if isinstance(value.get('model_plan'),dict):
        plan=value['model_plan'];clean={}
        for key in ('reply','intent','lookup_action','summary'):
            if isinstance(plan.get(key),str):clean[key]=redact_text(plan[key],4000)
        clean['person_names']=[redact_text(x,200) for x in _assessment_list(plan.get('person_names'),10) if isinstance(x,str)]
        clean['conditions']=[]
        for row in _assessment_list(plan.get('conditions'),20):
            if not isinstance(row,dict):continue
            item={k:redact_text(row[k],4000) for k in ('kind','text','source_quote') if isinstance(row.get(k),str)}
            if isinstance(row.get('source_turn_id'),str) and _ID.fullmatch(row['source_turn_id']):item['source_turn_id']=row['source_turn_id']
            clean['conditions'].append(item)
        clean['interpretations']=_clean_interpretations(plan.get('interpretations'))
        if isinstance(plan.get('record_ids'),list):clean['record_ids']=_record_ids(plan['record_ids'],21)
        result['model_plan']=clean
    if isinstance(value.get('model_plan_base'),dict):
        result['model_plan_base']=_clean_content({'model_plan':value['model_plan_base']})['model_plan']
    if isinstance(value.get('model_plan_attempts'),list):
        attempts=[]
        for row in value['model_plan_attempts'][:2]:
            if not isinstance(row,dict):continue
            item={}
            if type(row.get('attempt')) is int and 1<=row['attempt']<=2:item['attempt']=row['attempt']
            if row.get('phase') in ('interpret','repair','refine'):item['phase']=row['phase']
            if isinstance(row.get('raw'),str):item['raw']=redact_text(row['raw'],24000)
            for key in ('origin_turn_id','reason'):
                if isinstance(row.get(key),str) and _ID.fullmatch(row[key]):item[key]=row[key]
            for key in ('provider_completed','adopted'):
                if type(row.get(key)) is bool:item[key]=row[key]
            if row.get('validation') in (None,'accepted','rejected'):item['validation']=row.get('validation')
            if row.get('decision') in ('search_again','no_further_search'):item['decision']=row['decision']
            attempts.append(item)
        result['model_plan_attempts']=attempts
    if isinstance(value.get('model_search_attempts'),list):
        searches=[]
        for row in value['model_search_attempts'][:2]:
            if not isinstance(row,dict):continue
            item={}
            for key in ('tool_call_id','plan_sha256','revision','lookup_resolution'):
                if isinstance(row.get(key),str) and _ID.fullmatch(row[key]):item[key]=row[key]
            for key in ('attempt','candidate_count'):
                if type(row.get(key)) is int and 0<=row[key]<=7:item[key]=row[key]
            if row.get('selection_source') in _SELECTION_SOURCES:item['selection_source']=row['selection_source']
            for key,limit in (('record_ids',21),('selected_record_ids',21),('omitted_selected_record_ids',21),('matching_record_ids',200)):
                if isinstance(row.get(key),list):item[key]=_record_ids(row[key],limit)
            searches.append(item)
        result['model_search_attempts']=searches
    if isinstance(value.get('request_context'),dict):
        item=value['request_context'];ctx={}
        if isinstance(item.get('query'),str):ctx['query']=redact_text(item['query'],16000)
        if isinstance(item.get('unresolved'),list):ctx['unresolved']=[redact_text(x,1000) for x in item['unresolved'][:20] if isinstance(x,str)]
        if isinstance(item.get('sources'),list):
            ctx['sources']=[]
            for source in item['sources'][:100]:
                if not isinstance(source,dict):continue
                entry={k:redact_text(source[k],4000) for k in ('text','quote','selection_quote','option_quote') if isinstance(source.get(k),str)}
                for k in ('turn_id','kind','attachment_id','accepted_by','option_turn_id'):
                    if isinstance(source.get(k),str) and _ID.fullmatch(source[k]):entry[k]=source[k]
                ctx['sources'].append(entry)
        result['request_context']=ctx
    if isinstance(value.get('model_messages'),list):
        messages=[]
        for row in value['model_messages'][:100]:
            if isinstance(row,dict) and row.get('role') in ('system','user','assistant') and isinstance(row.get('content'),str):
                messages.append({'role':row['role'],'content':redact_text(row['content'])})
        result['model_messages']=messages
    if isinstance(value.get('retrieval'),dict):
        entry={}
        for key in ('candidate_ids','evidence_ids'):
            if isinstance(value['retrieval'].get(key),list):entry[key]=[x for x in value['retrieval'][key][:200] if isinstance(x,str) and _RECORD_ID.fullmatch(x)]
        if value['retrieval'].get('selection_source') in _SELECTION_SOURCES:entry['selection_source']=value['retrieval']['selection_source']
        for key,limit in (('record_ids',21),('selected_record_ids',21),('omitted_selected_record_ids',21),('matching_record_ids',200)):
            if isinstance(value['retrieval'].get(key),list):entry[key]=_record_ids(value['retrieval'][key],limit)
        if isinstance(value['retrieval'].get('corpus_fingerprint'),str) and _ID.fullmatch(value['retrieval']['corpus_fingerprint']):entry['corpus_fingerprint']=value['retrieval']['corpus_fingerprint']
        if isinstance(value['retrieval'].get('candidates'),list):
            entry['candidates']=[]
            for candidate in value['retrieval']['candidates'][:20]:
                if not isinstance(candidate,dict):continue
                row={}
                if isinstance(candidate.get('id'),str) and _RECORD_ID.fullmatch(candidate['id']):row['id']=candidate['id']
                if isinstance(candidate.get('reason'),str):row['reason']=redact_text(candidate['reason'],4000)
                if candidate.get('selection_source') in _SELECTION_SOURCES:row['selection_source']=candidate['selection_source']
                for key in ('selected_record_ids','omitted_selected_record_ids'):
                    if isinstance(candidate.get(key),list):row[key]=_record_ids(candidate[key],21)
                row['evidence']=[]
                for evidence in candidate.get('evidence',[])[:10] if isinstance(candidate.get('evidence'),list) else []:
                    if not isinstance(evidence,dict):continue
                    item={k:redact_text(evidence[k],2000) for k in ('title','scope','role','boundary') if isinstance(evidence.get(k),str)}
                    if isinstance(evidence.get('id'),str) and _RECORD_ID.fullmatch(evidence['id']):item['id']=evidence['id']
                    row['evidence'].append(item)
                entry['candidates'].append(row)
        result['retrieval']=entry
    if isinstance(value.get('attachments'),list):
        result['attachments']=[]
        for row in value['attachments'][:20]:
            if not isinstance(row,dict):continue
            entry={}
            for key in ('id','opaque_id','extension','kind'):
                if isinstance(row.get(key),str) and _ID.fullmatch(row[key]):entry[key]=row[key]
            for key in ('size','characters'):
                if isinstance(row.get(key),int) and not isinstance(row[key],bool) and 0<=row[key]<=10**9:entry[key]=row[key]
            if isinstance(row.get('truncated'),bool):entry['truncated']=row['truncated']
            result['attachments'].append(entry)
    if isinstance(value.get('missing_fields'),list):result['missing_fields']=[x for x in value['missing_fields'][:50] if isinstance(x,str) and _ID.fullmatch(x)]
    # Nothing else, including images, original files, headers or exceptions, is copied.
    return result


def _content_observations(original, cleaned):
    omissions=[]
    def walk(before,after,path):
        if isinstance(before,dict) and isinstance(after,dict):
            removed=[key for key in before if key not in after]
            if removed:
                omissions.append({'field':path or 'content','reason':'excluded_fields','count':len(removed)})
                if any(key in ('image','images','base64','raw_bytes') for key in removed):
                    omissions.append({'field':path or 'content','reason':'image_or_binary_excluded'})
            for key in after:
                if key in before:walk(before[key],after[key],(path+'.' if path else '')+key)
        elif isinstance(before,list) and isinstance(after,list):
            if len(before)>len(after):omissions.append({'field':path,'reason':'item_limit_or_invalid_items','original_count':len(before),'captured_count':len(after)})
            for index,(old,new) in enumerate(zip(before,after)):walk(old,new,path+'['+str(index)+']')
        elif isinstance(before,str) and isinstance(after,str):
            leaf=path.rsplit('.',1)[-1]
            limit=16000 if leaf=='query' else 4000 if leaf in ('text','quote','selection_quote','option_quote','reason') else 2000 if leaf in ('title','scope','role','boundary') else 1000 if '.unresolved[' in path else 24000
            response_text=(path.startswith('model_assessment.') or path.startswith('model_response_attempts['))
            if path.startswith('model_consultation_attempts[') and leaf=='raw':limit=8000
            elif response_text and leaf=='reply':limit=6000
            elif response_text and leaf=='empty_reply':limit=800
            elif response_text and leaf=='raw':limit=24000
            if len(before)>limit:omissions.append({'field':path,'reason':'text_limit','original_chars':len(before),'captured_chars':len(after)})
            elif len(before)>len(after):
                # Narrow field caps and redaction can both shorten a value.
                # Report the observable loss without calling redaction truncation.
                omissions.append({'field':path,'reason':'text_shortened','original_chars':len(before),'captured_chars':len(after)})
    walk(original,cleaned,'')
    changed=json.dumps(original,ensure_ascii=False,sort_keys=True,default=str)!=json.dumps(cleaned,ensure_ascii=False,sort_keys=True)
    return {'redaction_applied':changed,'omissions':omissions}


def make_session_ref(visitor_ref, session_id):
    _identifier(visitor_ref);_identifier(session_id)
    return hashlib.sha256(('session\0'+visitor_ref+'\0'+session_id).encode()).hexdigest()[:32]


def _attempt_key(metadata):
    parts=[metadata.get(key) for key in ('visitor_ref','session_id','attempt_id')]
    return hashlib.sha256(('attempt\0'+'\0'.join(parts)).encode()).hexdigest()[:32] if all(parts) else None


class DiagnosticAuth:
    """Independent read credential; never derive it from a worker/visitor key."""
    def __init__(self, env=None, verifier_path=None):
        env=os.environ if env is None else env
        self.enabled=False;self.credential_id=None;self._digest=None
        raw=env.get('RNDPLZ_DIAGNOSTIC_TOKEN','')
        try:
            if raw:
                if not isinstance(raw,str) or not _TOKEN.fullmatch(raw):return
                digest=hashlib.sha256(raw.encode()).hexdigest()
                credential='operator-'+digest[:12]
            elif verifier_path is not None:
                path=Path(verifier_path)
                if _is_link(path) or path.stat().st_size>2048:return
                item=json.loads(path.read_text(encoding='utf-8'))
                if not isinstance(item,dict) or set(item)!={'version','scheme','credential_id','token_sha256'}:return
                if item['version']!=1 or item['scheme']!='sha256':return
                digest=item['token_sha256'];credential=item['credential_id']
                if not isinstance(digest,str) or not _HEX.fullmatch(digest):return
                _identifier(credential)
            else:return
            for key in ('RNDPLZ_BRIDGE_TOKEN','RNDPLZ_SESSION_SECRET'):
                other=env.get(key,'')
                if isinstance(other,str) and other and hmac.compare_digest(digest,hashlib.sha256(other.encode()).hexdigest()):return
            self._digest=digest;self.credential_id=credential;self.enabled=True
        except (OSError,ValueError,TypeError,KeyError):return

    def authorized(self, token):
        return bool(self.enabled and isinstance(token,str) and _TOKEN.fullmatch(token) and
                    hmac.compare_digest(self._digest,hashlib.sha256(token.encode()).hexdigest()))


def _is_link(path):
    return path.is_symlink() or bool(getattr(path,'is_junction',lambda:False)())


class Diagnostics:
    def __init__(self, directory, *, clock=None, limits=None):
        self.directory=Path(directory).absolute();self._root=self.directory.resolve()
        self.clock=clock or time.time;self.limits=dict(_LIMITS)
        for key,value in (limits or {}).items():
            if key not in self.limits or not isinstance(value,(int,float)) or isinstance(value,bool) or not math.isfinite(value) or value<=0:raise ValueError('진단 저장 한도를 확인해 주세요.')
            self.limits[key]=value
        self.lock=threading.RLock();self._active=set();self._seen={};self._sequence=0
        self._health={'write_errors':0,'read_errors':0,'rejected_events':0,'dropped_content':0,'purged_files':0,'last_error':None}

    def health(self):
        with self.lock:return {'enabled':True,**copy.deepcopy(self._health)}

    def _problem(self, field, code):
        self._health[field]+=1;self._health['last_error']=code

    def _path(self, relative):
        path=self.directory/relative
        if _is_link(self.directory) or self.directory.resolve()!=self._root or not path.resolve().is_relative_to(self._root):raise ValueError('진단 저장 경로를 확인해 주세요.')
        for part in (path,*path.parents):
            if part==self.directory.parent:break
            if _is_link(part):raise ValueError('진단 저장 경로를 확인해 주세요.')
        return path

    def _files(self, folder, pattern):
        path=self._path(folder)
        if not path.exists():return []
        found=[]
        for candidate in path.glob(pattern):
            relative=candidate.relative_to(self.directory)
            safe=self._path(relative)
            if safe.is_file():found.append(safe)
        return sorted(found,key=lambda x:(x.stat().st_mtime_ns,x.name))

    def _atomic(self, relative, value):
        path=self._path(relative);path.parent.mkdir(parents=True,exist_ok=True)
        raw=json.dumps(value,ensure_ascii=False,separators=(',',':')).encode()
        temporary=self._path(str(relative)+'.next')
        try:
            with temporary.open('wb') as handle:handle.write(raw);handle.flush();os.fsync(handle.fileno())
            os.replace(temporary,path)
        finally:
            if temporary.exists():temporary.unlink()

    def _read(self, path, limit):
        path=self._path(path.relative_to(self.directory))
        with path.open('rb') as handle:raw=handle.read(int(limit)+1)
        if len(raw)>limit:raise ValueError('진단 파일 크기 제한을 넘었습니다.')
        value=json.loads(raw)
        if not isinstance(value,dict):raise ValueError('진단 파일 형식을 확인해 주세요.')
        return value

    def _append(self, group, row, prune=True):
        raw=(json.dumps(row,ensure_ascii=False,separators=(',',':'))+'\n').encode()
        cap=self.limits['max_event_bytes']
        if len(raw)>cap:raise ValueError('진단 이벤트 크기 제한을 넘었습니다.')
        if prune:self._prune(dry_run=False,reserve_event_bytes=len(raw))
        total=sum(p.stat().st_size for pattern in ('events-*.jsonl','audit-*.jsonl') for p in self._files('.',pattern))
        if total+len(raw)>self.limits['max_total_event_bytes']:raise ValueError('진단 이벤트 총량 제한을 넘었습니다.')
        path=self._path(group+'-active.jsonl');path.parent.mkdir(parents=True,exist_ok=True)
        if path.exists() and path.stat().st_size+len(raw)>cap:
            rotated=self._path(group+'-'+str(int(self.clock()*1000))+'-'+uuid.uuid4().hex[:8]+'.jsonl')
            os.replace(path,rotated)
        with path.open('ab') as handle:handle.write(raw);handle.flush()

    def _events(self):
        rows=[];budget=self.limits['max_total_event_bytes']
        files=list(reversed(self._files('.', 'events-*.jsonl')))
        for path in files:
            if budget<=0:break
            size=path.stat().st_size
            if size>self.limits['max_event_bytes']:self._problem('read_errors','event_size');continue
            budget-=size
            with path.open('rb') as handle:
                for line in handle:
                    try:
                        row=json.loads(line)
                        if isinstance(row,dict) and row.get('version')==1 and isinstance(row.get('metadata'),dict):
                            _time(row['observed_at']);_identifier(row['event_id'])
                            clean=_metadata(row['metadata'])
                            if clean.get('visitor_ref') and clean.get('session_id'):clean['session_ref']=make_session_ref(clean['visitor_ref'],clean['session_id'])
                            for extra in ('capture_status','detail_ref'):
                                if isinstance(row['metadata'].get(extra),str) and _ID.fullmatch(row['metadata'][extra]):clean[extra]=row['metadata'][extra]
                            row['metadata']=clean;rows.append(row)
                    except (ValueError,TypeError,KeyError):self._problem('read_errors','invalid_event')
        return sorted(rows,key=lambda x:(x.get('observed_at',''),x.get('sequence_index',0),x.get('event_id','')))

    def record(self, metadata, content=None):
        """Capture an observation. Failure is visible in health, never raised."""
        with self.lock:
            try:
                clean=_metadata(metadata)
                if content is not None and _bytes_present(content):raise ValueError('binary')
                identifier=clean.pop('event_id',None) or uuid.uuid4().hex
                captured=_clean_content(content) if content is not None else None
                input_digest=hashlib.sha256(json.dumps([clean,captured],sort_keys=True,ensure_ascii=False).encode()).hexdigest()
                if identifier in self._seen:
                    if self._seen[identifier]==input_digest:return True
                    raise ValueError('duplicate_event_conflict')
                at=_stamp(self.clock());self._sequence+=1
                if clean.get('visitor_ref') and clean.get('session_id'):clean['session_ref']=make_session_ref(clean['visitor_ref'],clean['session_id'])
                key=_attempt_key(clean)
                if captured is not None:
                    if not key:raise ValueError('content_requires_attempt')
                    path=self._path('attempts/'+key+'.json')
                    prior=self._read(path,self.limits['max_attempt_bytes']) if path.exists() else {}
                    merged=copy.deepcopy(prior.get('content',{}))
                    for field,value in captured.items():
                        if field in _CURRENT_CONTENT_FIELDS or field not in merged:merged[field]=value
                    observed=_content_observations(content,captured)
                    omissions=copy.deepcopy(prior.get('omissions',[]))+observed['omissions']
                    event_contents=copy.deepcopy(prior.get('event_contents',[]))
                    event_contents.append({'event_id':identifier,'observed_at':at,'content':captured,**observed})
                    item={'version':1,'attempt_key':key,'created_at':prior.get('created_at',at),'updated_at':at,
                          'expires_at':_stamp(self.clock()+self.limits['content_retention_seconds']),
                          'metadata':{**prior.get('metadata',{}),**clean},'content':merged,'event_contents':event_contents,
                          'redaction_applied':bool(prior.get('redaction_applied')) or observed['redaction_applied'],'omissions':omissions,
                          'content_status':'recorded'}
                    encoded=json.dumps(item,ensure_ascii=False,separators=(',',':')).encode()
                    if len(encoded)>self.limits['max_attempt_bytes'] or len(encoded)>self.limits['max_content_bytes']:
                        self._problem('dropped_content','content_limit');clean['capture_status']='partial'
                    else:
                        self._atomic('attempts/'+key+'.json',item)
                        clean['capture_status']='recorded';clean['detail_ref']=key
                else:clean['capture_status']='not_recorded'
                row={'version':1,'event_id':identifier,'observed_at':at,'sequence_index':self._sequence,'metadata':clean}
                self._append('events',row)
                self._seen[identifier]=input_digest
                if len(self._seen)>20000:self._seen.pop(next(iter(self._seen)))
                self._prune(dry_run=False)
                return True
            except OSError:
                self._problem('write_errors','storage_write_failed');return False
            except (ValueError,TypeError,KeyError,OverflowError,RecursionError):
                self._problem('rejected_events','invalid_diagnostic_event');return False

    def mark_interrupted(self):
        """Call once at server startup, never from an operator read operation."""
        with self.lock:
            try:
                latest={}
                for row in self._events():
                    key=_attempt_key(row['metadata'])
                    if key:latest[key]={**latest.get(key,{}),**row['metadata']}
                count=0
                for metadata in latest.values():
                    if metadata.get('status') not in ('started','pending'):continue
                    count+=bool(self.record({**metadata,'event_type':'restart_interrupted','status':'error',
                                            'error_kind':'restart_interrupted','failure_stage':'server_restart'}))
                return count
            except (OSError,ValueError,TypeError,KeyError):
                self._problem('read_errors','restart_capture_failed');return 0

    def _audit(self, operation, actor, selector=None, result_count=0, prune=True):
        try:
            row={'version':1,'event_id':uuid.uuid4().hex,'observed_at':_stamp(self.clock()),'operation':operation,
                 'credential_id':_identifier(actor),'result_count':result_count}
            if selector is not None:row['session_ref']=_identifier(selector)
            self._append('audit',row,prune=prune)
            if prune:self._prune(dry_run=False)
        except (OSError,ValueError,TypeError):self._problem('write_errors','audit_write_failed')

    def recent(self, *, since=None, model=None, status=None, limit=50, actor='local'):
        if not isinstance(limit,int) or isinstance(limit,bool) or not 1<=limit<=200:raise ValueError('조회 개수는 1~200입니다.')
        at=self.clock();cutoff=at-min(86400,self.limits['retention_seconds']) if since is None else _time(since)
        if cutoff<at-min(7*86400,self.limits['retention_seconds']) or cutoff>at:raise ValueError('최근 7일 이내의 진단 범위를 지정해 주세요.')
        if model is not None and (not isinstance(model,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:/-]{0,149}',model)):raise ValueError('진단 모델을 확인해 주세요.')
        if status is not None and status not in _STATUSES:raise ValueError('진단 상태를 확인해 주세요.')
        _identifier(actor)
        with self.lock:
            latest={}
            for row in self._events():
                if _time(row['observed_at'])<cutoff:continue
                meta=row['metadata'];key=_attempt_key(meta) or row['event_id']
                latest[key]={**latest.get(key,{}),'event_id':row['event_id'],'observed_at':row['observed_at'],**meta}
            rows=[row for row in latest.values() if (model is None or row.get('model_selected')==model) and (status is None or row.get('status')==status)]
            rows.sort(key=lambda x:(x['observed_at'],x['event_id']),reverse=True)
            self._audit('recent',actor,result_count=min(len(rows),limit))
            return {'version':1,'items':rows[:limit],'truncated':len(rows)>limit,'diagnostics':self.health()}

    def _session(self, session_ref, turn_id=None, turn_ids=None):
        if not isinstance(session_ref,str) or not re.fullmatch(r'[a-f0-9]{32}',session_ref):raise ValueError('진단 세션 식별자를 확인해 주세요.')
        if turn_id is not None:_identifier(turn_id)
        selected_turns=set(turn_ids) if turn_ids is not None else {turn_id} if turn_id is not None else None
        cutoff=self.clock()-self.limits['retention_seconds'];groups={}
        for row in self._events():
            meta=row['metadata']
            if meta.get('session_ref')!=session_ref or (selected_turns is not None and meta.get('turn_id') not in selected_turns) or _time(row['observed_at'])<cutoff:continue
            key=_attempt_key(meta)
            if key is None:continue
            group=groups.setdefault(key,{'attempt_id':meta['attempt_id'],'metadata':{},'events':[],'content':None,'event_contents':[],'content_status':'not_recorded'})
            group['metadata'].update(meta);group['events'].append(row)
        if not groups:raise ValueError('진단 세션을 찾을 수 없습니다. 보존기간이 지났거나 기록되지 않았습니다.')
        detail_bytes=len(json.dumps(groups,ensure_ascii=False,separators=(',',':')).encode())
        if detail_bytes>self.limits['max_snapshot_bytes']:raise ValueError('진단 상세 크기를 넘었습니다. 턴 범위를 줄여 주세요.')
        for key,group in groups.items():
            path=self._path('attempts/'+key+'.json')
            if path.exists():
                detail_bytes+=path.stat().st_size
                if detail_bytes>self.limits['max_snapshot_bytes']:raise ValueError('진단 상세 크기를 넘었습니다. 턴 범위를 줄여 주세요.')
                try:
                    item=self._read(path,self.limits['max_attempt_bytes'])
                    if _time(item['expires_at'])>self.clock():
                        group['content']=_clean_content(item.get('content',{}));group['content_status']='recorded'
                        group['event_contents']=[{'event_id':x['event_id'],'observed_at':x['observed_at'],'content':_clean_content(x['content']),'redaction_applied':bool(x.get('redaction_applied')),'omissions':x.get('omissions',[])}
                                                 for x in item.get('event_contents',[]) if isinstance(x,dict) and isinstance(x.get('content'),dict)]
                        group['redaction_applied']=bool(item.get('redaction_applied'))
                        group['omissions']=item.get('omissions',[])
                        group['input_complete']=not group['redaction_applied'] and not group['omissions']
                        if any(e['metadata'].get('capture_status')=='partial' for e in group['events']):
                            group['content_status']='partial';group['input_complete']=False
                            group['omissions'].append({'field':'event_content','reason':'storage_limit'})
                    else:group['content_status']='expired'
                except (OSError,ValueError,TypeError,KeyError):self._problem('read_errors','content_unavailable');group['content_status']='unavailable'
        result={'version':1,'session_ref':session_ref,'attempts':list(groups.values()),'missing_fields':['unobserved_legacy_fields_are_not_reconstructed']}
        if len(json.dumps(result,ensure_ascii=False).encode())>self.limits['max_snapshot_bytes']:raise ValueError('진단 상세 크기를 넘었습니다. 턴 범위를 줄여 주세요.')
        return result

    def session(self, session_ref, *, turn_id=None, actor='local'):
        _identifier(actor)
        with self.lock:
            result=self._session(session_ref,turn_id)
            self._audit('session',actor,session_ref,len(result['attempts']))
            return {**result,'diagnostics':self.health()}

    def snapshot(self, session_ref, *, turn_ids=None, include_content=False, actor='local'):
        _identifier(actor)
        if not isinstance(include_content,bool):raise ValueError('상세 포함 설정을 확인해 주세요.')
        if turn_ids is not None and (not isinstance(turn_ids,list) or len(turn_ids)>100 or any(not isinstance(x,str) or not _ID.fullmatch(x) for x in turn_ids)):raise ValueError('진단 턴 범위를 확인해 주세요.')
        with self.lock:
            result=self._session(session_ref,turn_ids=turn_ids)
            if not result['attempts']:raise ValueError('선택한 진단 턴을 찾을 수 없습니다.')
            if not include_content:
                for row in result['attempts']:row['content']=None;row['event_contents']=[];row['content_status']='not_requested'
            raw=json.dumps(result,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()
            manifest={**result,'snapshot_id':uuid.uuid4().hex,'captured_at':_stamp(self.clock()),
                      'expires_at':_stamp(self.clock()+self.limits['snapshot_retention_seconds']),
                      'include_content':include_content,'content_sha256':hashlib.sha256(raw).hexdigest(),
                      'replay_executed':False,'diagnostics':self.health()}
            if len(json.dumps(manifest,ensure_ascii=False).encode())>self.limits['max_snapshot_bytes']:raise ValueError('진단 스냅샷 크기 제한을 넘었습니다. 턴 범위를 줄여 주세요.')
            try:
                self._atomic('snapshots/'+manifest['snapshot_id']+'.json',manifest)
                self._prune(dry_run=False)
            except (OSError,ValueError):self._problem('write_errors','snapshot_write_failed');raise ValueError('진단 스냅샷을 저장하지 못했습니다.') from None
            self._audit('snapshot',actor,session_ref,len(result['attempts']))
            manifest['diagnostics']=self.health();return manifest

    def _prune(self, *, before=None, dry_run=True, reserve_event_bytes=0):
        now=self.clock();explicit=_time(before) if before is not None else None;selected=[]
        files=sorted([p for group in ('events','audit') for p in self._files('.',group+'-*.jsonl')],key=lambda p:(p.stat().st_mtime_ns,p.name))
        total=sum(p.stat().st_size for p in files)
        for path in files:
            modified=path.stat().st_mtime;size=path.stat().st_size
            try:
                with path.open('rb') as handle:
                    entries=[json.loads(line) for line in handle if line.strip()]
                    moments=[_time(entry['observed_at']) for entry in entries]
                if any(_attempt_key(entry.get('metadata',{})) in self._active for entry in entries):continue
                modified=max(moments,default=modified)
            except (OSError,ValueError,KeyError):pass
            expired=modified<(explicit if explicit is not None else now-self.limits['retention_seconds'])
            if expired or total>max(0,self.limits['max_total_event_bytes']-reserve_event_bytes):
                selected.append(path);total-=size
        for folder,ttl,cap,maxfile in [('attempts','content_retention_seconds','max_content_bytes','max_attempt_bytes'),('snapshots','snapshot_retention_seconds','max_total_snapshot_bytes','max_snapshot_bytes')]:
            files=self._files(folder,'*.json');total=sum(p.stat().st_size for p in files)
            for path in files:
                if folder=='attempts' and path.stem in self._active:continue
                try:
                    item=self._read(path,self.limits[maxfile]);stamp=_time(item.get('updated_at',item.get('captured_at')))
                except (OSError,ValueError,TypeError,KeyError):stamp=path.stat().st_mtime
                if stamp<(explicit if explicit is not None else now-self.limits[ttl]) or total>self.limits[cap]:
                    selected.append(path);total-=path.stat().st_size
        selected=list(dict.fromkeys(selected));size=sum(p.stat().st_size for p in selected)
        if not dry_run:
            for path in selected:self._path(path.relative_to(self.directory)).unlink(missing_ok=True)
            self._health['purged_files']+=len(selected)
        return {'dry_run':dry_run,'files':len(selected),'bytes':size}

    def purge(self, *, before=None, dry_run=True, actor='local'):
        if not isinstance(dry_run,bool):raise ValueError('삭제 실행 설정을 확인해 주세요.')
        _identifier(actor)
        with self.lock:
            result=self._prune(before=before,dry_run=dry_run)
            self._audit('purge_dry_run' if dry_run else 'purge',actor,result_count=result['files'],prune=not dry_run)
            return {**result,'diagnostics':self.health()}


@contextlib.contextmanager
def scope(store, metadata):
    """Hold this scope while consuming a stream; nesting is restored in finally."""
    try:clean=_metadata(metadata)
    except (ValueError,TypeError,RecursionError):
        if store is not None:
            with store.lock:store._problem('rejected_events','invalid_scope_metadata')
        clean={};store=None
    for key in ('request_id','attempt_id','trace_id'):clean.setdefault(key,uuid.uuid4().hex)
    context=(store,clean);token=_CONTEXT.set(context);key=_attempt_key(clean)
    if store is not None and key:
        with store.lock:store._active.add(key)
    try:yield copy.deepcopy(clean)
    finally:
        if store is not None and key:
            with store.lock:store._active.discard(key)
        _CONTEXT.reset(token)


def capture_scope():
    context=_CONTEXT.get()
    return (context[0],copy.deepcopy(context[1])) if context is not None else None


def _record_safely(store, metadata, content):
    try:return store.record(metadata,content)
    except Exception:
        try:
            with store.lock:store._problem('write_errors','diagnostic_callback_failed')
        except Exception:pass
        return False


def record_captured(captured, kind, *, content=None, **metadata):
    if captured is None or captured[0] is None:return False
    store,base=captured
    return _record_safely(store,{**base,**metadata,'event_type':kind},content)


def event(kind, **metadata):
    context=_CONTEXT.get()
    if context is None:return False
    store,base=context
    if store is None:return False
    content=metadata.pop('content',None)
    return _record_safely(store,{**base,**metadata,'event_type':kind},content)


def replay_fixture(snapshot):
    """Extract a local offline fixture; never run a model or contact the service."""
    if not isinstance(snapshot,dict) or _bytes_present(snapshot) or not isinstance(snapshot.get('attempts'),list):raise ValueError('진단 스냅샷 형식을 확인해 주세요.')
    attempts=[]
    for row in snapshot['attempts'][:200]:
        if not isinstance(row,dict):continue
        content=_clean_content(row['content']) if isinstance(row.get('content'),dict) else None
        attempts.append({'attempt_id':row.get('attempt_id'),'metadata':_metadata(row.get('metadata',{})),
                         'content':content,'content_status':row.get('content_status','not_recorded')})
    return {'version':1,'replay_mode':'offline_routing_only','replay_executed':False,
            'snapshot_id':snapshot.get('snapshot_id'),'session_ref':snapshot.get('session_ref'),
            'redaction_changed_input':any(x.get('redaction_applied') or x.get('content_status')!='recorded' for x in snapshot['attempts'] if isinstance(x,dict)),
            'attempts':attempts,'missing_fields':['no_automatic_model_replay','actual_weight_identity_not_verified']}


_PHASE_EVENTS = frozenset(('model_dispatch_started', 'model_provider_rejected', 'model_provider_error',
    'model_plan_validated', 'model_plan_rejected', 'model_lookup_attempt', 'model_tool_completed',
    'model_consultation_rejected', 'model_response_validated', 'model_response_rejected'))
# Client attachment failures are unverified browser claims, never stored files or turns.
_ATTACHMENT_CLIENT_ENUMS = {'reason': ('image_path_unsupported', 'scope_attachment_restricted', 'unsupported_file_type', 'batch_limit', 'name_invalid', 'empty_file', 'file_too_large'), 'category': ('document', 'image', 'other', 'mixed'), 'extension': ('txt', 'md', 'csv', 'json', 'log', 'pdf', 'docx', 'pptx', 'html', 'htm', 'png', 'jpg', 'jpeg', 'webp', 'other', 'none'), 'mime': ('text/plain', 'text/markdown', 'text/csv', 'application/json', 'application/pdf', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document', 'application/vnd.openxmlformats-officedocument.presentationml.presentation', 'text/html', 'image/png', 'image/jpeg', 'image/webp', 'other', 'none'), 'selected_model': ('runtime', 'guide', 'gemini', 'openai', 'claude', 'bridge', 'ollama', 'other', 'none')}
_ATTACHMENT_CLIENT_NUMBERS = {'size_bytes': (0, 9007199254740991), 'batch_index': (1, 10000), 'batch_count': (1, 10000)}


def attachment_client_metadata(payload):
    allowed = {'client_event_id', *_ATTACHMENT_CLIENT_ENUMS, *_ATTACHMENT_CLIENT_NUMBERS}
    if not isinstance(payload, dict) or set(payload) != allowed:
        raise ValueError('attachment_client_report_invalid')
    event_id = payload['client_event_id']
    if not isinstance(event_id, str) or not re.fullmatch(r'[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}', event_id):
        raise ValueError('attachment_client_report_invalid')
    result = {'client_event_id': event_id, 'client_reported': True}
    for key, allowed_values in _ATTACHMENT_CLIENT_ENUMS.items():
        value = payload[key]
        if not isinstance(value, str) or value not in allowed_values:
            raise ValueError('attachment_client_report_invalid')
        result['client_' + key] = value
    for key, (lower, upper) in _ATTACHMENT_CLIENT_NUMBERS.items():
        value = payload[key]
        if type(value) is not int or not lower <= value <= upper:
            raise ValueError('attachment_client_report_invalid')
        result['client_' + key] = value
    if payload['batch_index'] > payload['batch_count']:
        raise ValueError('attachment_client_report_invalid')
    return result


_OPERATION_EVENTS = _PHASE_EVENTS | frozenset(('request_received', 'request_rejected', 'turn_started',
    'cached_return', 'turn_storage_completed', 'turn_storage_failed', 'turn_finished', 'prepare_completed',
    'stream_started', 'stream_phase', 'stream_first_delta', 'stream_terminal_yielded', 'stream_eof',
    'stream_error', 'stream_closed', 'client_recovery_report', 'recovery_report_rejected',
    'session_read_failed', 'session_read_completed', 'capture_failed', 'attachment_client_rejected'))
_OPERATION_ENUMS = {
    **{'client_'+key:frozenset(values) for key,values in _ATTACHMENT_CLIENT_ENUMS.items()},
    'provider_observed': frozenset(('codex_oauth','openai_api','gemini','mock')),
    'phase_status': _STATUSES,
    'model_phase': frozenset(('interpret','repair','tool','consultation','answer','complete')),
    'phase': frozenset(('interpreting','searching','reading','answering')),
    'storage_status': frozenset(('committed','stale_ignored','failed')),
    'terminal_type': frozenset(('done','error')),
    'close_reason': frozenset(('eof','closed','iteration_error','cleanup_error')),
    'outcome': frozenset(('stream_interrupted','recovered','pending','unavailable')),
    'client_error_kind': frozenset(('eof','aborted','stream_error','http','network','timeout','invalid_response')),
    'failure_stage': frozenset(('predispatch','provider','request','stream','storage','model_response','context_capture')),
}
_OPERATION_ERRORS = frozenset(('storage_write_failed','stream_iteration_failed','stream_cleanup_failed',
    'diagnostic_write_failed','generation_error','validation','server_error','rate_limit','busy','message_limit',
    'context_input_too_large','client_disconnect','runtime_config_invalid','auth_missing','auth_invalid',
    'auth_expired','oauth_unauthorized','model_access_denied','process_call_cap','timeout','transport_error',
    'provider_http_error','rate_limited','incomplete_response','invalid_structured_output','cancelled',
    'provider_error','http_error','prompt_blocked','invalid_json','deadline','response_json','transport_failure'))


def operation_metadata(values):
    """Bounded stdout schema: never render arbitrary content, models, URLs or exceptions."""
    if not isinstance(values, dict) or values.get('event_type') not in _OPERATION_EVENTS:
        return None
    result = {'event_type': values['event_type']}
    if values['event_type']=='attachment_client_rejected':
        # Revalidate even direct sink callers; this event cannot carry session, turn, attempt or content.
        try:
            claim=attachment_client_metadata({'client_event_id':values.get('client_event_id'),
                **{key:values.get('client_'+key) for key in (*_ATTACHMENT_CLIENT_ENUMS,*_ATTACHMENT_CLIENT_NUMBERS)}})
        except ValueError:return None
        result.update(claim)
        for key,length in (('request_id',32),('visitor_ref',64),('deployment_revision',40),('code_fingerprint',64)):
            value=values.get(key)
            if isinstance(value,str) and re.fullmatch('[a-f0-9]{'+str(length)+'}',value):result[key]=value
        return result
    for key in ('request_id','attempt_id','trace_id','session_id','turn_id',
                'client_request_id','claimed_session_id','claimed_turn_id'):
        value = values.get(key)
        # Browser UUIDs and server UUIDs only. Legacy custom IDs are omitted from stdout.
        if isinstance(value, str) and re.fullmatch(r'(?:[a-f0-9]{32}|[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12})', value):
            result[key] = value
    for key, length in (('deployment_revision',40),('code_fingerprint',64),('visitor_ref',64)):
        value=values.get(key)
        if isinstance(value,str) and re.fullmatch('[a-f0-9]{'+str(length)+'}',value):result[key]=value
    for key, allowed in _OPERATION_ENUMS.items():
        value=values.get(key)
        if isinstance(value,str) and value in allowed:result[key]=value
    if isinstance(values.get('status'),str) and values['status'] in _STATUSES:result['status']=values['status']
    for key in ('model_called','eof','terminal_yielded','session_verified','request_verified','pending_present','pending_cleared'):
        if type(values.get(key)) is bool:result[key]=values[key]
    for key in ('elapsed_ms','storage_elapsed_ms','poll_count'):
        value=values.get(key)
        if type(value) is int and 0<=value<=3600000:result[key]=value
    for key in ('http_status','provider_http_status'):
        value=values.get(key)
        if type(value) is int and 100<=value<=599:result[key]=value
    for key in ('error_kind','provider_error_reason'):
        value=values.get(key)
        if isinstance(value,str) and value in _OPERATION_ERRORS:result[key]=value
        elif value is not None:result[key]='other_code'
    value=values.get('generation_contract')
    if value in ('dialogue_plan.v1','dialogue_plan.v2','dialogue_answer.v1','dialogue_response.v1','dialogue_refine.v1','dialogue_assessment.v1'):
        result['generation_contract']=value
    if values.get('model_selected') in ('runtime','guide'):result['model_selected']=values['model_selected']
    if result['event_type'] in ('request_received','request_rejected'):
        for key in ('session_id','turn_id'):
            if key in result:result['claimed_'+key]=result.pop(key)
    return result


class OperationalDiagnostics:
    """Metadata-only stdout plus an optional unchanged private diagnostic store."""
    def __init__(self, private=None, *, provider=None, model=None, writer=None):
        self.private=private
        self.lock=private.lock if private is not None else threading.RLock()
        self._active=private._active if private is not None else set()
        self.provider=provider if provider in ('codex_oauth','openai_api','gemini','guide') else 'unknown'
        # Model identity is server configuration, never incoming request text.
        self.model=model if isinstance(model,str) and re.fullmatch(r'[a-z][a-z0-9.-]{0,79}',model) else None
        self.writer=writer

    def _problem(self, kind, code):
        if self.private is not None:self.private._problem(kind,code)

    def record(self, metadata, content=None):
        try:clean=_metadata(metadata)
        except Exception:return False
        try:safe=operation_metadata(clean)
        except Exception:safe=None
        wrote=False
        if safe is not None:
            safe.update(schema='rndplz.operation.v1', observed_at=_stamp(time.time()), provider=self.provider)
            if self.model is not None:safe['model_configured']=self.model
            if safe['event_type']!='attachment_client_rejected' and self.model is not None and clean.get('provider_model_observed')==self.model:
                safe['provider_model_observed']=self.model
            try:
                line=json.dumps(safe,ensure_ascii=True,separators=(',',':'))
                with self.lock:
                    if self.writer is None:print(line,flush=True)
                    else:self.writer(line)
                wrote=True
            except Exception:pass
        if self.private is not None:
            try:return bool(self.private.record(clean,content)) or wrote
            except Exception:return wrote
        return wrote
