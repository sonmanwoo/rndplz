"""Authenticated outgoing worker for a local Gemma model. No local ingress port."""
import argparse
import collections
import hmac
import hashlib
import math
import json
import re
import secrets
import sys
import uuid
import threading
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlparse
from .chat_models import ChatModels, GENERATION_CONTRACT_NAMES, generation_spec, validate_generation_input
from .models import NoRedirect
from . import chat_models as _chat_models
from . import models as _models
from . import diagnostics as _diagnostics
from .diagnostics import capture_scope, record_captured


def _validated_model_names(values):
    if not isinstance(values,list) or len(values)>32:
        raise ValueError('Gemma 모델 목록 형식을 확인해 주세요.')
    for value in values:
        if not isinstance(value,str) or not 1<=len(value)<=150 or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._/-]*(?::[A-Za-z0-9][A-Za-z0-9._-]*)?',value):
            raise ValueError('Gemma 모델 태그 형식을 확인해 주세요.')
    return tuple(dict.fromkeys(values))


def configured_models(default, additional=None):
    """Operator-owned exact tags; the existing default always remains permitted."""
    _validated_model_names([default])
    if additional is None:additional=[]
    elif isinstance(additional,str):additional=[part.strip() for part in additional.split(',') if part.strip()]
    return _validated_model_names([default]+list(_validated_model_names(additional)))


def installed_worker_models(config, model_client, refresh=False):
    additional=config.get('models')
    if additional is not None and not isinstance(additional,list):
        raise ValueError('연결기 models 설정은 모델 태그 배열이어야 합니다.')
    allowed=configured_models(config.get('model','gemma4:e4b'),additional)
    options=model_client.catalog(refresh=refresh)['models']
    installed={option.get('name') for option in options
               if option.get('provider')=='ollama' and option.get('enabled') and
               option.get('id')=='ollama:'+str(option.get('name','')) and
               'completion' in option.get('capabilities',['completion'])}
    return [name for name in allowed if name in installed]


_TRACE = re.compile(r'[A-Za-z0-9_.:-]{1,100}\Z')
_SHA = re.compile(r'[a-f0-9]{64}\Z')
_WORKER_ERRORS = {'worker_model_unavailable','worker_contract_unavailable','worker_trace_invalid','provider_error','result_delivery_error'}
_WORKER_STAGES = {'validation','generation','result_delivery'}


def _capture_relay_scope():
    try:
        captured=capture_scope()
        if captured is None:return None
        return captured[0],{key:value for key,value in captured[1].items() if key!='status'}
    except Exception:return None


def _relay_event(captured, kind, **metadata):
    # An observation failure must not alter leases, stream results or retries.
    try:return record_captured(captured,kind,execution_kind='bridge',**metadata)
    except Exception:return False


def _validated_observation(payload, job):
    trace=payload.get('trace_id')
    if 'trace_id' in payload and (not isinstance(trace,str) or not _TRACE.fullmatch(trace) or trace!=job['trace_id']):
        raise ValueError('작업 추적 정보가 일치하지 않습니다.')
    if 'diagnostics' not in payload:return {}
    data=payload['diagnostics']
    allowed={'version','worker_instance','worker_source_fingerprint','prompt_sha256','worker_input_fingerprint',
             'model_job','num_ctx','num_predict','model_ms','error_kind','failure_stage'}
    required={'version','worker_instance','worker_source_fingerprint','prompt_sha256'}
    if not isinstance(data,dict) or set(data)-allowed or not required.issubset(data) or trace is None:
        raise ValueError('연결기 관측 정보 형식을 확인해 주세요.')
    if type(data['version']) is not int or data['version']!=1 or not isinstance(data['worker_instance'],str) or not re.fullmatch(r'[a-f0-9]{32}',data['worker_instance']):
        raise ValueError('연결기 관측 정보 형식을 확인해 주세요.')
    for field in ('worker_source_fingerprint','prompt_sha256','worker_input_fingerprint'):
        if field in data and (not isinstance(data[field],str) or not _SHA.fullmatch(data[field])):
            raise ValueError('연결기 관측 지문 형식을 확인해 주세요.')
    if 'model_job' in data:
        if not isinstance(data['model_job'],str) or data['model_job']!=job['model'] or 'worker_input_fingerprint' not in data:
            raise ValueError('연결기 실행 모델 정보가 일치하지 않습니다.')
    for field in ('num_ctx','num_predict'):
        if field in data and (type(data[field]) is not int or not 1<=data[field]<=1048576):raise ValueError('연결기 생성 설정 형식을 확인해 주세요.')
    if 'model_ms' in data and (not isinstance(data['model_ms'],(int,float)) or isinstance(data['model_ms'],bool) or not math.isfinite(data['model_ms']) or not 0<=data['model_ms']<=3600000):
        raise ValueError('연결기 시간 형식을 확인해 주세요.')
    if 'error_kind' in data and data['error_kind'] not in _WORKER_ERRORS:raise ValueError('연결기 오류 정보 형식을 확인해 주세요.')
    if 'failure_stage' in data and data['failure_stage'] not in _WORKER_STAGES:raise ValueError('연결기 단계 정보 형식을 확인해 주세요.')
    stable=('worker_instance','worker_source_fingerprint','prompt_sha256','worker_input_fingerprint','model_job','num_ctx','num_predict')
    previous=job.get('worker_observation',{})
    if any(field in previous and field in data and previous[field]!=data[field] for field in stable):
        raise ValueError('작업 도중 연결기 실행 정보가 달라졌습니다.')
    return {key:value for key,value in data.items() if key!='version'}


def _validated_capabilities(values):
    if values is None:return ()
    if (not isinstance(values,list) or len(values)>len(GENERATION_CONTRACT_NAMES)
            or any(not isinstance(value,str) or value not in GENERATION_CONTRACT_NAMES for value in values)):
        raise ValueError('연결기 대화 계약 목록 형식을 확인해 주세요.')
    return tuple(dict.fromkeys(values))


def _worker_capabilities():
    supported=[]
    for name in GENERATION_CONTRACT_NAMES:
        try:generation_spec(name)
        except ValueError:continue
        supported.append(name)
    return supported


def _worker_identity(capabilities=()):
    """Startup source-file fingerprint, not a claim about weights or process memory."""
    modules={'__init__.py':sys.modules[__package__], 'gemma_bridge.py':sys.modules[__name__],
             'chat_models.py':_chat_models,'models.py':_models,'diagnostics.py':_diagnostics}
    if capabilities:
        from . import model_dialogue
        modules['model_dialogue.py']=model_dialogue
    fingerprints={name:hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest() for name,module in modules.items()}
    return {'version':1,'worker_instance':uuid.uuid4().hex,
            'worker_source_fingerprint':hashlib.sha256(json.dumps(fingerprints,sort_keys=True,separators=(',',':')).encode()).hexdigest(),
            'prompt_sha256':hashlib.sha256(_chat_models.CHAT_SYSTEM.encode()).hexdigest()}


def _observe_worker_payload(provider, payload, observation):
    """Called by ChatModels after constructing the actual request payload."""
    if provider!='ollama' or not isinstance(payload,dict):return
    messages=payload.get('messages')
    if not isinstance(messages,list):return
    text_messages=[]
    for item in messages:
        if not isinstance(item,dict) or item.get('role') not in ('system','user','assistant') or not isinstance(item.get('content'),str):return
        text_messages.append({'role':item['role'],'content':item['content']})
    # Hash only the actual role/text sequence; never headers, credentials or image bytes.
    raw=json.dumps(text_messages,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()
    observation['worker_input_fingerprint']=hashlib.sha256(raw).hexdigest()
    system=[row['content'] for row in text_messages if row['role']=='system']
    if len(system)==1:observation['prompt_sha256']=hashlib.sha256(system[0].encode()).hexdigest()
    if isinstance(payload.get('model'),str):observation['model_job']=payload['model']
    options=payload.get('options',{})
    if isinstance(options,dict):
        for field in ('num_ctx','num_predict'):
            value=options.get(field)
            if type(value) is int and 1<=value<=1048576:observation[field]=value


class GemmaRelay:
    def __init__(self, token, model='gemma4:e4b', timeout=150, models=None):
        self.allowed_models=configured_models(model,models)
        self.token, self.model, self.timeout = token, model, timeout
        self._advertised_models={model}
        self._advertised_capabilities=set()
        self.draining=False
        self.condition = threading.Condition()
        self.jobs = {}
        self.seen = 0

    def authorized(self, token):
        return bool(self.token) and hmac.compare_digest(self.token, token)

    @property
    def online(self): return bool(self.token) and time.monotonic() - self.seen < 90

    @property
    def available_models(self):
        with self.condition:
            return frozenset(self._advertised_models) if self.online else frozenset()

    @property
    def available_capabilities(self):
        with self.condition:
            return frozenset(self._advertised_capabilities) if self.online else frozenset()

    def control(self, command):
        """Authenticated operator control; never a heartbeat or a job claim."""
        if command not in ('status','drain','resume'):
            raise ValueError('지원하지 않는 연결기 제어입니다.')
        with self.condition:
            if command=='drain':self.draining=True
            elif command=='resume':self.draining=False
            return {'active_jobs':len(self.jobs),'draining':self.draining,'models':sorted(self.available_models),
                    'capabilities':sorted(self.available_capabilities)}

    def _event(self, identifier, job, kind, **metadata):
        values={'trace_id':job['trace_id'],'job_id':identifier,'model_job':job['model'],
                'generation_contract':job.get('contract'),
                'worker_instance':None,'worker_source_fingerprint':None,'worker_input_fingerprint':None,'prompt_sha256':None,
                **job.get('worker_observation',{}),**metadata}
        return _relay_event(job.get('captured'),kind,**values)

    def poll(self, models=None, *, capabilities=None):
        advertised={self.model} if models is None else set(_validated_model_names(models))
        advertised.intersection_update(self.allowed_models)
        supported=set(_validated_capabilities(capabilities))
        with self.condition:
            self.seen = time.monotonic()
            self._advertised_models=advertised
            self._advertised_capabilities=supported
            def claim():
                for identifier, job in self.jobs.items():
                    if job['claimed'] or job['done']:continue
                    # A legacy poll can neither consume nor fail a new-contract job.
                    if job.get('contract') is not None and job['contract'] not in supported:continue
                    if job['model'] not in advertised:
                        job['done']=True;job['error']=True
                        self._event(identifier,job,'relay_error',error_kind='worker_model_unavailable',failure_stage='claim')
                        self.condition.notify_all()
                        continue
                    job['claimed'] = True
                    self._event(identifier,job,'relay_claimed',queue_ms=round((time.monotonic()-job['created'])*1000,3))
                    claimed={'id': identifier, 'lease': job['lease'], 'messages': job['messages'], 'model': job['model'],'trace_id':job['trace_id']}
                    if job.get('contract') is not None:claimed['contract']=job['contract']
                    return claimed
                return None
            job=claim()
            if job:return job
            self.condition.wait(5)
            self.seen = time.monotonic()
            return claim()

    def deliver(self, payload):
        with self.condition:
            job = self.jobs.get(payload.get('id'))
            if not job or not job['claimed'] or not hmac.compare_digest(job['lease'], str(payload.get('lease',''))):
                raise ValueError('유효하지 않은 작업입니다.')
            self.seen = time.monotonic()
            try:observation=_validated_observation(payload,job)
            except (ValueError,TypeError):
                self._event(payload['id'],job,'relay_metadata_rejected',error_kind='invalid_worker_metadata',failure_stage='result_validation')
                raise ValueError('연결기 관측 정보가 유효하지 않습니다.') from None
            sequence = payload.get('sequence')
            if not isinstance(sequence, int) or sequence < 0: raise ValueError('작업 순서 오류')
            if sequence < job['sequence']: return
            if sequence != job['sequence'] or job['done']: raise ValueError('작업 순서 오류')
            chunk = payload.get('text','')
            if not isinstance(chunk,str) or job['length']+len(chunk)>24000: raise ValueError('응답 길이 초과')
            job['worker_observation'].update(observation)
            job['sequence'] += 1
            job['length'] += len(chunk)
            if chunk:
                job['chunks'].append(chunk)
                if not job['first_delta']:
                    job['first_delta']=True
                    self._event(payload['id'],job,'relay_first_delta',first_delta_ms=round((time.monotonic()-job['created'])*1000,3),output_chars=job['length'])
            job['done'] = bool(payload.get('done'))
            job['error'] = bool(payload.get('error'))
            if job['error']:
                self._event(payload['id'],job,'relay_error',error_kind=observation.get('error_kind','worker_error'),failure_stage=observation.get('failure_stage','worker'),output_chars=job['length'],partial_output=bool(job['length']))
            elif job['done']:
                self._event(payload['id'],job,'relay_done',output_chars=job['length'])
            self.condition.notify_all()

    def stream(self, messages, model=None, *, contract=None):
        if contract is not None:validate_generation_input(messages,contract)
        captured=_capture_relay_scope()
        model=self.model if model is None else model
        def reject(message,reason):
            _relay_event(captured,'relay_rejected',error_kind=reason,failure_stage='admission')
            raise ValueError(message)
        with self.condition:
            if not isinstance(model,str) or model not in self.allowed_models:reject('허용되지 않은 Gemma 모델입니다.','model_not_allowed')
            if self.draining:reject('Gemma 연결기를 점검 중입니다. 잠시 후 다시 시도해 주세요.','bridge_draining')
            if not self.online:reject('운영자 PC의 Gemma 연결을 기다리고 있습니다.','bridge_offline')
            if model not in self.available_models:reject('선택한 Gemma 모델을 운영자 PC에서 사용할 수 없습니다.','worker_model_unavailable')
            if contract is not None and contract not in self.available_capabilities:
                reject('운영자 PC의 연결기가 이 대화 생성 계약을 지원하지 않습니다.','worker_contract_unavailable')
            if len(self.jobs)>=2:reject('Gemma가 다른 질문에 답하고 있습니다. 잠시 후 다시 시도해 주세요.','bridge_busy')
            requested_deadline=getattr(messages,'generation_deadline',None)
            if requested_deadline is not None and requested_deadline<=time.monotonic():
                reject('이번 대화의 모델 처리 시간을 초과했습니다.','dialogue_deadline')
            identifier=secrets.token_hex(16)
            trace=captured[1].get('trace_id') if captured else None
            if not isinstance(trace,str) or not _TRACE.fullmatch(trace):trace=uuid.uuid4().hex
            job={'messages':messages,'model':model,'lease':secrets.token_hex(24),'claimed':False,'chunks':collections.deque(),
                 'sequence':0,'length':0,'done':False,'error':False,'captured':captured,'trace_id':trace,
                 'created':time.monotonic(),'first_delta':False,'worker_observation':{}}
            if contract is not None:job['contract']=contract
            self.jobs[identifier]=job
            self._event(identifier,job,'relay_queued')
            self.condition.notify_all()
        deadline=time.monotonic()+self.timeout
        if requested_deadline is not None:deadline=min(deadline,requested_deadline)
        try:
            while True:
                with self.condition:
                    if not job['chunks'] and not job['done']:
                        self.condition.wait(max(0,min(1,deadline-time.monotonic())))
                    chunks=list(job['chunks']);job['chunks'].clear()
                    done,error=job['done'],job['error']
                for chunk in chunks: yield chunk
                if error: raise ValueError('PC의 Gemma 응답이 중단됐습니다. 연결 상태를 확인해 주세요.')
                if done: return
                if time.monotonic()>=deadline:
                    self._event(identifier,job,'relay_timeout',error_kind='bridge_timeout',failure_stage='stream',output_chars=job['length'],partial_output=bool(job['length']))
                    raise ValueError('Gemma 응답 대기 시간이 지났습니다. 잠시 후 다시 시도해 주세요.')
        except GeneratorExit:
            self._event(identifier,job,'relay_cancelled',error_kind='client_disconnect',failure_stage='stream',partial_output=bool(job['length']))
            raise
        finally:
            with self.condition: self.jobs.pop(identifier,None)


def run_worker(config):
    base=config['service_url'].rstrip('/')
    parsed=urlparse(base)
    if parsed.scheme!='https' and not (parsed.scheme=='http' and parsed.hostname in ('localhost','127.0.0.1')):
        raise ValueError('공개 서버는 HTTPS 주소여야 합니다.')
    if parsed.username or parsed.password or parsed.query or parsed.fragment: raise ValueError('서버 주소 형식 오류')
    token=config['token'];opener=urllib.request.build_opener(NoRedirect())
    model=ChatModels({})
    capabilities=_worker_capabilities()
    try:identity=_worker_identity(capabilities)
    except Exception:identity=None  # Observation unavailable; inference behavior is unchanged.
    def post(route, payload):
        req=urllib.request.Request(base+'/api/worker/'+route,data=json.dumps(payload,ensure_ascii=False).encode(),
            headers={'Content-Type':'application/json','X-Rndplz-Bridge':token},method='POST')
        for attempt in range(2):
            try:
                with opener.open(req,timeout=20) as response: return json.load(response)
            except Exception:
                if attempt: raise
                time.sleep(1)
    print('Gemma 연결기 시작 · 공개 서버 요청을 기다립니다.',flush=True)
    while True:
        try:
            job=post('poll',{'models':installed_worker_models(config,model),'capabilities':capabilities}).get('job')
            if not job: continue
            seq=0;buffer='';last=time.monotonic();accepted_model=None
            observation=dict(identity or {})
            trace=job.get('trace_id');valid_trace=isinstance(trace,str) and bool(_TRACE.fullmatch(trace))
            stage='validation';generation_started=None
            contract=job.get('contract');contract_valid=contract is None or (isinstance(contract,str) and contract in capabilities)
            def observed_payload(provider,payload):
                try:_observe_worker_payload(provider,payload,observation)
                except Exception:pass
            model.diagnostic_observer=observed_payload
            def result_metadata(error_kind=None):
                value={}
                if valid_trace:
                    value['trace_id']=trace
                    if identity:
                        details=dict(observation)
                        if generation_started is not None:details['model_ms']=round((time.monotonic()-generation_started)*1000,3)
                        if error_kind:details.update(error_kind=error_kind,failure_stage=stage)
                        value['diagnostics']=details
                return value
            try:
                if 'trace_id' in job and not valid_trace:
                    raise ValueError('작업 추적 정보 형식을 확인해 주세요.')
                if not contract_valid:raise ValueError('지원하지 않는 대화 생성 계약입니다.')
                if job.get('model') not in installed_worker_models(config,model,refresh=True):
                    raise ValueError('허용되거나 설치된 모델이 아닙니다.')
                accepted_model=job['model'];stage='generation';generation_started=time.monotonic()
                stream_options={} if contract is None else {'contract':contract}
                for chunk in model.stream('ollama:'+accepted_model,job['messages'],**stream_options):
                    buffer+=chunk
                    if len(buffer)>=60 or time.monotonic()-last>=.5:
                        stage='result_delivery'
                        post('result',{'id':job['id'],'lease':job['lease'],'sequence':seq,'text':buffer,**result_metadata()})
                        seq+=1;buffer='';last=time.monotonic();stage='generation'
                stage='result_delivery'
                post('result',{'id':job['id'],'lease':job['lease'],'sequence':seq,'text':buffer,'done':True,**result_metadata()})
                print('Gemma 응답 전달 완료 · '+accepted_model,flush=True)
            except Exception:
                kind='worker_trace_invalid' if not valid_trace and 'trace_id' in job else 'worker_contract_unavailable' if not contract_valid else 'worker_model_unavailable' if accepted_model is None else 'result_delivery_error' if stage=='result_delivery' else 'provider_error'
                try: post('result',{'id':job['id'],'lease':job['lease'],'sequence':seq,'done':True,'error':True,**result_metadata(kind)})
                except Exception: pass
                print('Gemma 작업 중단'+(' · '+accepted_model if accepted_model else '')+' · 요청 본문과 비밀 값은 기록하지 않습니다.',flush=True)
            finally:
                model.diagnostic_observer=None
        except KeyboardInterrupt: return
        except Exception:
            print('연결 재시도 대기',flush=True)
            time.sleep(5)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--config',required=True);args=p.parse_args()
    run_worker(json.loads(Path(args.config).read_text(encoding='utf-8')))
