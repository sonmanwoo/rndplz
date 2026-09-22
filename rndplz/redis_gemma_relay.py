"""Shared outgoing Gemma worker protocol; no local queue or Redis-error fallback.

GET/CAS retries only an explicit conflict. A lost command response is never
replayed. Jobs are never reclaimed; cancellation/expiry invalidates their lease.
"""
import hashlib
import hmac
import json
import math
import re
import secrets
import time

from .chat_models import validate_generation_input, GENERATION_CONTRACT_NAMES
from .gemma_bridge import (
    configured_models, _validated_model_names, _validated_capabilities,
    _validated_observation, _capture_relay_scope, _relay_event, _TRACE,
)
from .redis_state import RedisStateStore, _loads


_ERROR = '공유 Gemma 연결 상태를 확인할 수 없습니다. 다시 전송하지 않았습니다.'
_CAS = """local current=redis.call('GET',KEYS[1])
if ARGV[1]=='0' then
 if current then return 0 end
elseif current~=ARGV[2] then return 0 end
redis.call('SET',KEYS[1],ARGV[3],'EX',ARGV[4]); return 1"""
_TTL = 300
_CONFLICTS = 8
_POLL_SECONDS = 5.0
_INTERVAL = .25
_MAX_OUTPUT = 24000
_MAX_STATE = 3_000_000  # CAS carries both old and new JSON inside the 8 MB REST cap.


def _dump(value):
    try:
        raw = json.dumps(value, ensure_ascii=False, sort_keys=True,
                         separators=(',', ':'), allow_nan=False)
        if len(raw.encode('utf-8')) > _MAX_STATE:
            raise ValueError(_ERROR)
        return raw
    except (ValueError, TypeError, UnicodeError):
        raise ValueError(_ERROR) from None


def _number(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def _state(raw):
    if raw is None:
        return {'version': 1, 'seen': 0, 'models': [], 'capabilities': [],
                'draining': False, 'jobs': {}}
    try:
        if not isinstance(raw, str) or len(raw.encode('utf-8')) > _MAX_STATE:
            raise ValueError(_ERROR)
        state = _loads(raw)
        if (set(state) != {'version', 'seen', 'models', 'capabilities', 'draining', 'jobs'}
                or type(state['version']) is not int or state['version'] != 1
                or not _number(state['seen']) or type(state['draining']) is not bool
                or not isinstance(state['jobs'], dict) or len(state['jobs']) > 2):
            raise ValueError(_ERROR)
        _validated_model_names(state['models'])
        _validated_capabilities(state['capabilities'])
        for identifier, job in state['jobs'].items():
            if (not re.fullmatch('[a-f0-9]{32}', identifier) or not isinstance(job, dict)
                    or set(job) != {'lease', 'messages', 'model', 'trace_id', 'contract',
                                    'created', 'expires', 'claimed', 'sequence', 'text',
                                    'done', 'error', 'worker_observation', 'deliveries'}
                    or not re.fullmatch('[a-f0-9]{48}', job['lease'])
                    or not isinstance(job['messages'], list)
                    or not isinstance(job['trace_id'], str) or not _TRACE.fullmatch(job['trace_id'])
                    or job['contract'] not in (None, *GENERATION_CONTRACT_NAMES)
                    or not _number(job['created']) or not _number(job['expires'])
                    or not 0 < job['expires'] - job['created'] <= 150
                    or any(type(job[k]) is not bool for k in ('claimed', 'done', 'error'))
                    or type(job['sequence']) is not int or not 0 <= job['sequence'] <= _MAX_OUTPUT + 1
                    or not isinstance(job['text'], str) or len(job['text']) > _MAX_OUTPUT
                    or not isinstance(job['deliveries'], dict)
                    or len(job['deliveries']) != job['sequence']
                    or not isinstance(job['worker_observation'], dict)):
                raise ValueError(_ERROR)
            _validated_model_names([job['model']])
            for n in range(job['sequence']):
                if not re.fullmatch('[a-f0-9]{64}', job['deliveries'].get(str(n), '')):
                    raise ValueError(_ERROR)
            if job['worker_observation']:
                _validated_observation({'trace_id': job['trace_id'],
                    'diagnostics': {'version': 1, **job['worker_observation']}}, job)
        return state
    except (ValueError, TypeError, KeyError, AttributeError, UnicodeError):
        raise ValueError(_ERROR) from None


class RedisGemmaRelay:
    def __init__(self, env, model='gemma4:e4b', timeout=150, models=None):
        self.allowed_models = configured_models(model, models)
        self.token = env.get('RNDPLZ_BRIDGE_TOKEN', '')
        if (not isinstance(self.token, str) or not 1 <= len(self.token) <= 8192
                or any(not 32 < ord(c) < 127 for c in self.token)
                or not _number(timeout) or not 0 < timeout <= 150):
            raise ValueError(_ERROR)
        self.model, self.timeout = model, float(timeout)
        self._store = RedisStateStore('gemma-relay', env)
        digest = hashlib.sha256(self.token.encode('utf-8')).hexdigest()
        self._key = 'rndplz:gemma-relay:{' + env['RNDPLZ_STATE_NAMESPACE'] + ':' + digest + '}:state'

    def authorized(self, token):
        return isinstance(token, str) and token.isascii() and hmac.compare_digest(self.token, token)

    def _mutate(self, change):
        # change is side-effect-free: it may run again only after explicit CAS=0.
        for _ in range(_CONFLICTS):
            raw = self._store._command(['GET', self._key])
            state = _state(raw)
            now = time.time()
            state['jobs'] = {key: job for key, job in state['jobs'].items() if job['expires'] > now}
            result = change(state, now)
            updated = _dump(state)
            if raw == updated:
                return result
            committed = self._store._command(
                ['EVAL', _CAS, 1, self._key, '0' if raw is None else '1',
                 raw or '', updated, _TTL])
            if type(committed) is not int or committed not in (0, 1):
                raise ValueError(_ERROR)
            if committed == 1:
                return result
        raise ValueError('공유 Gemma 연결 상태가 변경 중입니다. 다시 전송하지 않았습니다.')

    def _snapshot(self):
        # Catalog/status observations never create or rewrite shared state.
        state = _state(self._store._command(['GET', self._key]))
        now = time.time()
        state['jobs'] = {key: job for key, job in state['jobs'].items() if job['expires'] > now}
        return state

    def _online(self, state, now):
        return state['seen'] > 0 and 0 <= now - state['seen'] < 90

    @property
    def online(self):
        return self._online(self._snapshot(), time.time())

    @property
    def available_models(self):
        state = self._snapshot()
        return frozenset(state['models']).intersection(self.allowed_models) if self._online(state, time.time()) else frozenset()

    @property
    def available_capabilities(self):
        state = self._snapshot()
        return frozenset(state['capabilities']) if self._online(state, time.time()) else frozenset()

    def control(self, command):
        if command not in ('status', 'drain', 'resume'):
            raise ValueError('지원하지 않는 연결기 제어입니다.')
        def change(state, now):
            if command != 'status':
                state['draining'] = command == 'drain'
            online = self._online(state, now)
            return {'active_jobs': len(state['jobs']), 'draining': state['draining'],
                    'models': sorted(set(state['models']).intersection(self.allowed_models)) if online else [],
                    'capabilities': sorted(state['capabilities']) if online else []}
        if command == 'status':
            return change(self._snapshot(), time.time())
        return self._mutate(change)

    def poll(self, models=None, *, capabilities=None):
        advertised = sorted(set(_validated_model_names([self.model] if models is None else models)).intersection(self.allowed_models))
        supported = sorted(_validated_capabilities(capabilities))
        def claim(state, now):
            state.update(seen=now, models=advertised, capabilities=supported)
            for identifier, job in sorted(state['jobs'].items(), key=lambda item: item[1]['created']):
                if job['claimed'] or job['done']:
                    continue
                if job['contract'] is not None and job['contract'] not in supported:
                    continue
                if job['model'] not in advertised:
                    job.update(done=True, error=True)
                    continue
                job['claimed'] = True
                result = {key: job[key] for key in ('lease', 'messages', 'model', 'trace_id')}
                result['id'] = identifier
                if job['contract'] is not None:
                    result['contract'] = job['contract']
                return result
            return None
        deadline = time.monotonic() + _POLL_SECONDS
        while True:
            result = self._mutate(claim)
            if result is not None or time.monotonic() >= deadline:
                return result
            time.sleep(min(_INTERVAL, max(0, deadline - time.monotonic())))

    def deliver(self, payload):
        if not isinstance(payload, dict):
            raise ValueError('유효하지 않은 작업입니다.')
        identifier, lease, sequence = payload.get('id'), payload.get('lease'), payload.get('sequence')
        if (not isinstance(identifier, str) or not isinstance(lease, str) or not lease.isascii()
                or type(sequence) is not int or sequence < 0
                or any(key in payload and type(payload[key]) is not bool for key in ('done', 'error'))):
            raise ValueError('유효하지 않은 작업입니다.')
        digest = hashlib.sha256(_dump(payload).encode('utf-8')).hexdigest()
        def change(state, now):
            job = state['jobs'].get(identifier)
            if not job or not job['claimed'] or not hmac.compare_digest(job['lease'], lease):
                raise ValueError('유효하지 않은 작업입니다.')
            observation = _validated_observation(payload, job)
            if sequence < job['sequence']:
                if job['deliveries'].get(str(sequence)) != digest:
                    raise ValueError('작업 순서 오류')
                return
            if sequence != job['sequence'] or job['done'] or sequence > _MAX_OUTPUT:
                raise ValueError('작업 순서 오류')
            chunk = payload.get('text', '')
            done, error = payload.get('done', False), payload.get('error', False)
            if (not isinstance(chunk, str) or len(job['text']) + len(chunk) > _MAX_OUTPUT
                    or (not chunk and not done and not error)):
                raise ValueError('응답 길이 또는 완료 형식을 확인해 주세요.')
            job['worker_observation'].update(observation)
            job['text'] += chunk
            job.update(sequence=sequence + 1, done=done or error, error=error)
            job['deliveries'][str(sequence)] = digest
            state['seen'] = now
        self._mutate(change)

    def _remove(self, identifier):
        self._mutate(lambda state, now: state['jobs'].pop(identifier, None))

    def _event(self, captured, identifier, job, kind, **metadata):
        try:
            values = {'trace_id': job['trace_id'], 'job_id': identifier,
                      'model_job': job['model'], 'generation_contract': job['contract'],
                      **job['worker_observation'], **metadata}
            _relay_event(captured, kind, **values)
        except Exception:
            pass  # Diagnostic failure cannot change the job or the stream.

    def stream(self, messages, model=None, *, contract=None):
        if contract is not None:
            validate_generation_input(messages, contract)
        model = self.model if model is None else model
        if not isinstance(model, str) or model not in self.allowed_models:
            raise ValueError('허용되지 않은 Gemma 모델입니다.')
        requested = getattr(messages, 'generation_deadline', None)
        now_mono = time.monotonic()
        if requested is not None and (not _number(requested) or requested <= now_mono):
            raise ValueError('이번 대화의 모델 처리 시간을 초과했습니다.')
        deadline = min(now_mono + self.timeout, requested) if requested is not None else now_mono + self.timeout
        captured = _capture_relay_scope()
        trace = captured[1].get('trace_id') if captured else None
        if not isinstance(trace, str) or not _TRACE.fullmatch(trace):
            trace = secrets.token_hex(16)
        identifier, lease = secrets.token_hex(16), secrets.token_hex(24)
        # JSON-copy plain messages only; runtime attributes never enter worker payloads.
        copied = _loads(_dump(messages))
        if not isinstance(copied, list):
            raise ValueError('대화 입력 형식을 확인해 주세요.')
        observation = getattr(messages, 'runtime_dispatch_observation', None)
        if hasattr(messages, '__dict__'):
            messages.provider_dispatched = False
        if isinstance(observation, dict):
            observation['dispatched'] = False
        def enqueue(state, now):
            if state['draining']:
                raise ValueError('Gemma 연결기를 점검 중입니다. 잠시 후 다시 시도해 주세요.')
            if not self._online(state, now):
                raise ValueError('운영자 PC의 Gemma 연결을 기다리고 있습니다.')
            if model not in state['models']:
                raise ValueError('선택한 Gemma 모델을 운영자 PC에서 사용할 수 없습니다.')
            if contract is not None and contract not in state['capabilities']:
                raise ValueError('운영자 PC의 연결기가 이 대화 생성 계약을 지원하지 않습니다.')
            if len(state['jobs']) >= 2:
                raise ValueError('Gemma가 다른 질문에 답하고 있습니다. 잠시 후 다시 시도해 주세요.')
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ValueError('이번 대화의 모델 처리 시간을 초과했습니다.')
            job = {'lease': lease, 'messages': copied, 'model': model, 'trace_id': trace,
                   'contract': contract, 'created': now, 'expires': now + min(150, remaining),
                   'claimed': False, 'sequence': 0, 'text': '', 'done': False, 'error': False,
                   'worker_observation': {}, 'deliveries': {}}
            state['jobs'][identifier] = job
            return job
        offset, claimed, first_delta, queued = 0, False, False, False
        try:
            job = self._mutate(enqueue)
            queued = True
            self._event(captured, identifier, job, 'relay_queued')
            while True:
                if time.monotonic() >= deadline:
                    raise ValueError('Gemma 응답 대기 시간이 지났습니다. 잠시 후 다시 시도해 주세요.')
                job = self._snapshot()['jobs'].get(identifier)
                if job is None:
                    raise ValueError('Gemma 작업이 만료되거나 취소됐습니다.')
                if job['claimed'] and not claimed:
                    claimed = True
                    self._event(captured, identifier, job, 'relay_claimed',
                                queue_ms=round(max(0, time.time() - job['created']) * 1000, 3))
                worker = job['worker_observation']
                if worker.get('model_job') == model and worker.get('worker_input_fingerprint'):
                    if hasattr(messages, '__dict__'):
                        messages.provider_dispatched = True
                    if isinstance(observation, dict):
                        observation['dispatched'] = True
                chunk = job['text'][offset:]
                if chunk:
                    offset = len(job['text'])
                    if not first_delta:
                        first_delta = True
                        self._event(captured, identifier, job, 'relay_first_delta', output_chars=offset)
                    yield chunk
                if job['error']:
                    self._event(captured, identifier, job, 'relay_error', output_chars=offset)
                    raise ValueError('PC의 Gemma 응답이 중단됐습니다. 연결 상태를 확인해 주세요.')
                if job['done']:
                    self._event(captured, identifier, job, 'relay_done', output_chars=offset)
                    return
                time.sleep(min(_INTERVAL, max(0, deadline - time.monotonic())))
        except GeneratorExit:
            if queued:
                self._event(captured, identifier, job, 'relay_cancelled', partial_output=bool(offset))
            raise
        finally:
            # Also remove a possibly committed enqueue whose response was lost.
            # Redis outage may prevent cleanup; its bounded job/state TTL remains.
            try:
                self._remove(identifier)
            except ValueError:
                try:
                    _relay_event(captured, 'relay_cleanup_unconfirmed', job_id=identifier,
                                 generation_contract=contract,
                                 error_kind='shared_cleanup_failed', failure_stage='cleanup')
                except Exception:
                    pass
