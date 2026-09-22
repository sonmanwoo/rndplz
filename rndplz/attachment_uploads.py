"""Bounded raw-file staging; publication uses the existing attachment path once."""
from __future__ import annotations

import base64
from contextlib import contextmanager
import hashlib
import json
import math
import os
from pathlib import Path
import re
import secrets
import time

from .attachments import AttachmentError, MAX_FILE_BYTES
from .redis_state import _LEASE_MS, _RELEASE, _loads

CHUNK_BYTES = 524288
EXPIRES_IN = 600
_READ = "if redis.call('EXISTS',KEYS[1]) ~= 0 then return {0,false} end return {1,redis.call('GET',KEYS[2]) or false}"
_APPLY = """if redis.call('GET',KEYS[1]) ~= ARGV[1] or redis.call('PTTL',KEYS[1]) <= 0 or redis.call('EXISTS',KEYS[2]) ~= 0 then return 0 end
local ops=cjson.decode(ARGV[2])
for _,op in ipairs(ops) do redis.call(unpack(op)) end
return 1"""


class AttachmentUploadError(AttachmentError):
    def __init__(self, reason):
        messages = {
            'invalid': ('파일 전송 형식을 확인해 주세요.', 400),
            'busy': ('다른 자료 전송이나 대화가 진행 중입니다. 잠시 후 다시 시도해 주세요.', 409),
            'expired': ('파일 전송 시간이 지났습니다. 파일을 다시 선택해 주세요.', 410),
            'incomplete': ('파일 조각이 모두 도착하지 않았습니다.', 409),
            'conflict': ('이미 처리 중이거나 처리한 파일 전송입니다. 자동으로 다시 저장하지 않습니다.', 409),
            'corrupt': ('전송한 파일의 크기나 지문이 일치하지 않습니다.', 400),
            'unavailable': ('파일 전송 저장소를 확인할 수 없습니다. 자동 재전송하지 않습니다.', 503),
        }
        message, self.status = messages[reason]
        self.code = 'attachment_upload_' + reason
        ValueError.__init__(self, message)


def _identifier(value):
    return isinstance(value, str) and re.fullmatch(r'[a-f0-9]{32}', value) is not None


def _payload(value, fields):
    if not isinstance(value, dict) or set(value) != set(fields):
        raise AttachmentUploadError('invalid')
    if 'upload_id' in fields and not _identifier(value['upload_id']):
        raise AttachmentUploadError('invalid')


def _encoded(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':'))


def _public_result(value, meta):
    fields={'id','name','size','truncated','kind','characters'}
    if (not isinstance(value,dict) or not fields<=set(value)<=fields|{'extraction'}
            or not _identifier(value.get('id')) or not isinstance(value.get('name'),str)
            or not 0<len(value['name'])<=240 or type(value.get('size')) is not int
            or value['size']!=meta['size'] or type(value.get('truncated')) is not bool
            or value.get('kind') not in ('image','document')
            or type(value.get('characters')) is not int or not 0<=value['characters']<=16000
            or ('extraction' in value and not isinstance(value['extraction'],dict))
            or len(_encoded(value).encode('utf8'))>32768):
        raise AttachmentUploadError('corrupt')
    return value


class AttachmentUploads:
    def __init__(self, store, attachments):
        self.store, self.attachments = store, attachments
        self.remote = store._shared_store if getattr(store, 'shared', False) else None
        if self.remote is not None:
            if getattr(getattr(attachments, 'backend', None), 'store', None) is not self.remote:
                raise AttachmentUploadError('unavailable')
            self.prefix = self.remote._key_prefix + ':uploads:'
        else:
            if getattr(attachments, 'backend', None) is not None or attachments.directory != store.directory / 'attachments':
                raise AttachmentUploadError('unavailable')
            self.directory = store.directory / 'uploads'
            self.directory.mkdir(parents=True, exist_ok=True)

    def _key(self, name):
        return self.prefix + name if self.remote else str(self.directory / name)

    def _read(self, name, maximum=700000):
        if self.remote:
            value = self.remote._command(['EVAL', _READ, 2, self.remote._revoked_key, self._key(name)])
            if not isinstance(value, list) or len(value) != 2 or type(value[0]) is not int or value[0] != 1:
                raise AttachmentUploadError('unavailable')
            raw = value[1]
        else:
            if self.store.is_revoked():
                raise AttachmentUploadError('unavailable')
            path = Path(self._key(name))
            raw = path.read_text(encoding='utf8') if path.exists() else None
        if raw is not None and (not isinstance(raw, str) or len(raw.encode('utf8')) > maximum):
            raise AttachmentUploadError('corrupt')
        return raw

    @contextmanager
    def _guard(self, *, quota=False):
        token = secrets.token_hex(32)
        deadline = time.monotonic() + 3
        local_lock = None
        acquired = False
        try:
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise AttachmentUploadError('busy')
                if self.remote:
                    result = self.remote._command(['SET', self.remote._lock_key, token, 'NX', 'PX', _LEASE_MS], timeout=remaining)
                    if result == 'OK':
                        acquired = True
                    elif result is not None:
                        raise AttachmentUploadError('unavailable')
                else:
                    local_lock = self.store.directory / 'state.lock'
                    try:
                        fd = os.open(local_lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                        os.close(fd); acquired = True
                    except FileExistsError:
                        pass
                if acquired:
                    break
                time.sleep(min(.03, max(0, deadline-time.monotonic())))
            if self.store.is_revoked():
                raise AttachmentUploadError('unavailable')
            state = self.store.read()
            if any(s.get('pending') for s in state['sessions']):
                raise AttachmentUploadError('busy')
            if quota and self.attachments.count() >= 12:
                raise AttachmentError('count_limit')
            yield token
        except AttachmentError:
            raise
        except Exception:
            raise AttachmentUploadError('unavailable') from None
        finally:
            if acquired:
                if self.remote:
                    try:self.remote._command(['EVAL', _RELEASE, 1, self.remote._lock_key, token])
                    except ValueError:pass
                elif local_lock is not None:
                    local_lock.unlink(missing_ok=True)

    def _apply(self, token, changes):
        """All names are internal UUID-derived keys; no request-supplied commands."""
        if self.remote:
            ops = []
            for name, value, expires in changes:
                ops.append(['DEL', self._key(name)] if value is None else
                           ['SET', self._key(name), value, 'EX', max(1, math.ceil(expires-time.time()))])
            result = self.remote._command(['EVAL', _APPLY, 2, self.remote._lock_key,
                                          self.remote._revoked_key, token, _encoded(ops)])
            if type(result) is not int or result != 1:
                raise AttachmentUploadError('unavailable')
        else:
            if self.store.is_revoked():raise AttachmentUploadError('unavailable')
            for name,value,_ in changes:
                path=Path(self._key(name))
                if value is None:path.unlink(missing_ok=True);continue
                temporary=path.with_name(path.name+'.'+token+'.next')
                try:
                    with temporary.open('x',encoding='utf8') as out:
                        out.write(value);out.flush();os.fsync(out.fileno())
                    os.replace(temporary,path)
                finally:temporary.unlink(missing_ok=True)

    def _meta(self, identifier):
        raw=self._read(identifier+'.meta',65536)
        if raw is None:raise AttachmentUploadError('expired')
        try:m=_loads(raw)
        except Exception:raise AttachmentUploadError('corrupt') from None
        if (not isinstance(m,dict) or set(m)!={'id','name','size','sha256','count','next','expires','phase','claim','result'}
                or m['id']!=identifier or not isinstance(m['name'],str) or not 0<len(m['name'])<=240
                or type(m['size']) is not int or not 0<m['size']<=MAX_FILE_BYTES
                or not isinstance(m['sha256'],str) or re.fullmatch('[a-f0-9]{64}',m['sha256']) is None
                or type(m['count']) is not int or m['count']!=(m['size']+CHUNK_BYTES-1)//CHUNK_BYTES
                or type(m['next']) is not int or not 0<=m['next']<=m['count']
                or type(m['expires']) not in (int,float) or not math.isfinite(m['expires'])
                or m['phase'] not in ('receiving','completing','complete')
                or (m['claim'] is not None and not _identifier(m['claim']))
                or (m['result'] is not None and not isinstance(m['result'],dict))):
            raise AttachmentUploadError('corrupt')
        if m['expires']<=time.time():raise AttachmentUploadError('expired')
        if ((m['phase']=='receiving' and (m['claim'] is not None or m['result'] is not None))
                or (m['phase']!='receiving' and not _identifier(m['claim']))
                or (m['phase']=='completing' and m['result'] is not None)
                or (m['phase']=='complete' and m['result'] is None)):
            raise AttachmentUploadError('corrupt')
        if m['phase']=='complete':_public_result(m['result'],m)
        return m

    def _active(self, token):
        if self.remote:
            raw=self._read('index',2048);ids=[] if raw is None else _loads(raw)
            if not isinstance(ids,list) or len(ids)>2 or len(set(ids))!=len(ids) or not all(_identifier(v) for v in ids):
                raise AttachmentUploadError('corrupt')
        else:
            ids=[p.stem for p in self.directory.glob('*.meta')]
            if not all(_identifier(v) for v in ids):raise AttachmentUploadError('corrupt')
        active=[]
        for identifier in ids:
            try:m=self._meta(identifier)
            except AttachmentUploadError as exc:
                if exc.code!='attachment_upload_expired':raise
                self._apply(token,[(identifier+'.meta',None,0)]+
                            [(identifier+'.'+str(i),None,0) for i in range(20)])
                continue
            if m['phase']!='complete':active.append(identifier)
        return active

    def begin(self,payload):
        _payload(payload,('name','size','sha256'))
        name,size,digest=payload['name'],payload['size'],payload['sha256']
        if (not isinstance(name,str) or not name.strip() or len(name)>240 or any(ord(c)<32 for c in name)
                or type(size) is not int or not 0<size<=MAX_FILE_BYTES
                or not isinstance(digest,str) or re.fullmatch('[a-f0-9]{64}',digest) is None):
            raise AttachmentUploadError('invalid')
        with self._guard(quota=True) as token:
            active=self._active(token)
            if len(active)>=2:raise AttachmentUploadError('busy')
            identifier=secrets.token_hex(16);count=(size+CHUNK_BYTES-1)//CHUNK_BYTES;expires=time.time()+EXPIRES_IN
            m={'id':identifier,'name':name,'size':size,'sha256':digest,'count':count,'next':0,
               'expires':expires,'phase':'receiving','claim':None,'result':None}
            changes=[(identifier+'.meta',_encoded(m),expires)]
            if self.remote:changes.append(('index',_encoded(active+[identifier]),expires))
            self._apply(token,changes)
        return {'upload_id':identifier,'chunk_bytes':CHUNK_BYTES,'chunk_count':count,'expires_in':EXPIRES_IN}

    def chunk(self,payload):
        _payload(payload,('upload_id','index','data'));identifier=payload['upload_id']
        index,data=payload['index'],payload['data']
        if type(index) is not int or not 0<=index<20 or not isinstance(data,str) or not 0<len(data)<=4*((CHUNK_BYTES+2)//3):
            raise AttachmentUploadError('invalid')
        try:raw=base64.b64decode(data,validate=True)
        except Exception:raise AttachmentUploadError('invalid') from None
        if base64.b64encode(raw).decode('ascii')!=data:raise AttachmentUploadError('invalid')
        with self._guard(quota=True) as token:
            m=self._meta(identifier)
            if m['phase']!='receiving' or index!=m['next']:raise AttachmentUploadError('conflict')
            expected=min(CHUNK_BYTES,m['size']-index*CHUNK_BYTES)
            if len(raw)!=expected or expected<=0:raise AttachmentUploadError('corrupt')
            if self._read(identifier+'.'+str(index)) is not None:raise AttachmentUploadError('conflict')
            m['next']+=1
            self._apply(token,[(identifier+'.'+str(index),data,m['expires']),(identifier+'.meta',_encoded(m),m['expires'])])
        return {'upload_id':identifier,'index':index,'received':True}

    def complete(self,payload):
        _payload(payload,('upload_id',));identifier=payload['upload_id']
        with self._guard() as token:
            m=self._meta(identifier)
            if m['phase']=='complete':return m['result']
            if m['phase']!='receiving':raise AttachmentUploadError('conflict')
            if m['next']!=m['count']:raise AttachmentUploadError('incomplete')
            if self.attachments.count()>=12:raise AttachmentError('count_limit')
            m['phase']='completing';m['claim']=secrets.token_hex(16)
            self._apply(token,[(identifier+'.meta',_encoded(m),m['expires'])])
        # Do not hold the shared state lease: RedisAttachments.put acquires it.
        # A claimed attempt is never reset, including uncertain publication errors.
        try:
            chunks=[]
            for i in range(m['count']):
                data=self._read(identifier+'.'+str(i))
                if data is None:raise AttachmentUploadError('corrupt')
                try:raw=base64.b64decode(data,validate=True)
                except Exception:raise AttachmentUploadError('corrupt') from None
                if (base64.b64encode(raw).decode('ascii')!=data or
                        len(raw)!=min(CHUNK_BYTES,m['size']-i*CHUNK_BYTES)):
                    raise AttachmentUploadError('corrupt')
                chunks.append(raw)
            raw=b''.join(chunks)
            if len(raw)!=m['size'] or hashlib.sha256(raw).hexdigest()!=m['sha256']:
                raise AttachmentUploadError('corrupt')
            current=self._meta(identifier)
            if current!=m:raise AttachmentUploadError('conflict')
            body={'name':m['name'],'data':base64.b64encode(raw).decode('ascii')}
            if self.remote:
                result=self.attachments.upload(body)
            else:
                with self._guard(quota=True):
                    if self._meta(identifier)!=m:raise AttachmentUploadError('conflict')
                    result=self.attachments.upload(body)
            _public_result(result,m)
            with self._guard() as token:
                if self._meta(identifier)!=m:raise AttachmentUploadError('conflict')
                m['phase']='complete';m['result']=result
                active=[v for v in self._active(token) if v!=identifier]
                changes=[(identifier+'.meta',_encoded(m),m['expires'])]+[(identifier+'.'+str(i),None,0) for i in range(m['count'])]
                if self.remote:changes.append(('index',_encoded(active),time.time()+EXPIRES_IN))
                self._apply(token,changes)
            return result
        except AttachmentError:raise
        except Exception:raise AttachmentUploadError('unavailable') from None

    def cancel(self,payload):
        _payload(payload,('upload_id',));identifier=payload['upload_id']
        with self._guard() as token:
            try:m=self._meta(identifier)
            except AttachmentUploadError as exc:
                if exc.code!='attachment_upload_expired':raise
                m=None
            if m is not None and m['phase']!='receiving':raise AttachmentUploadError('conflict')
            active=[v for v in self._active(token) if v!=identifier]
            changes=[(identifier+'.meta',None,0)]+[(identifier+'.'+str(i),None,0) for i in range(20)]
            if self.remote:changes.append(('index',_encoded(active),time.time()+EXPIRES_IN))
            self._apply(token,changes)
        return {'cancelled':True}
