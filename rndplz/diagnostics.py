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
              'worker_source_fingerprint','worker_input_fingerprint','worker_instance','credential_id','event_type','previous_mode','next_mode'}
_MODEL_FIELDS = {'model_selected','model_job','provider_model_observed'}
_NUMBER_FIELDS = {'input_chars','output_chars','attachment_count','elapsed_ms','queue_ms','first_delta_ms',
                  'model_ms','http_status','candidate_count','evidence_count','sequence','num_ctx','num_predict'}
_BOOL_FIELDS = {'partial_output','cached','model_called','truncated'}
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
        if key in _ID_FIELDS:
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
    return result


def _clean_content(value):
    if not isinstance(value,dict) or _bytes_present(value):raise ValueError('진단 상세 형식을 확인해 주세요.')
    result={}
    for key in ('user_text','assistant_text'):
        if key in value:result[key]=redact_text(value[key])
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
        if isinstance(value['retrieval'].get('corpus_fingerprint'),str) and _ID.fullmatch(value['retrieval']['corpus_fingerprint']):entry['corpus_fingerprint']=value['retrieval']['corpus_fingerprint']
        if isinstance(value['retrieval'].get('candidates'),list):
            entry['candidates']=[]
            for candidate in value['retrieval']['candidates'][:20]:
                if not isinstance(candidate,dict):continue
                row={}
                if isinstance(candidate.get('id'),str) and _RECORD_ID.fullmatch(candidate['id']):row['id']=candidate['id']
                if isinstance(candidate.get('reason'),str):row['reason']=redact_text(candidate['reason'],4000)
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
            if len(before)>limit:omissions.append({'field':path,'reason':'text_limit','original_chars':len(before),'captured_chars':len(after)})
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
                        if field=='assistant_text' or field not in merged:merged[field]=value
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
