"""Authenticated outgoing worker for a local Gemma model. No local ingress port."""
import argparse
import collections
import hmac
import json
import secrets
import threading
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlparse
from .chat_models import ChatModels
from .models import NoRedirect


class GemmaRelay:
    def __init__(self, token, model='gemma4:e4b', timeout=150):
        self.token, self.model, self.timeout = token, model, timeout
        self.condition = threading.Condition()
        self.jobs = {}
        self.seen = 0

    def authorized(self, token):
        return bool(self.token) and hmac.compare_digest(self.token, token)

    @property
    def online(self): return bool(self.token) and time.monotonic() - self.seen < 90

    def poll(self):
        with self.condition:
            self.seen = time.monotonic()
            for identifier, job in self.jobs.items():
                if not job['claimed']:
                    job['claimed'] = True
                    return {'id': identifier, 'lease': job['lease'], 'messages': job['messages'], 'model': self.model}
            self.condition.wait(5)
            self.seen = time.monotonic()
            for identifier, job in self.jobs.items():
                if not job['claimed']:
                    job['claimed'] = True
                    return {'id': identifier, 'lease': job['lease'], 'messages': job['messages'], 'model': self.model}
            return None

    def deliver(self, payload):
        with self.condition:
            job = self.jobs.get(payload.get('id'))
            if not job or not job['claimed'] or not hmac.compare_digest(job['lease'], str(payload.get('lease',''))):
                raise ValueError('유효하지 않은 작업입니다.')
            self.seen = time.monotonic()
            sequence = payload.get('sequence')
            if not isinstance(sequence, int) or sequence < 0: raise ValueError('작업 순서 오류')
            if sequence < job['sequence']: return # Idempotent acknowledgement retry.
            if sequence != job['sequence'] or job['done']: raise ValueError('작업 순서 오류')
            chunk = payload.get('text','')
            if not isinstance(chunk,str) or job['length']+len(chunk)>24000: raise ValueError('응답 길이 초과')
            job['sequence'] += 1
            job['length'] += len(chunk)
            if chunk: job['chunks'].append(chunk)
            job['done'] = bool(payload.get('done'))
            job['error'] = bool(payload.get('error'))
            self.condition.notify_all()

    def stream(self, messages):
        with self.condition:
            if not self.online: raise ValueError('운영자 PC의 Gemma 연결을 기다리고 있습니다.')
            if len(self.jobs)>=2: raise ValueError('Gemma가 다른 질문에 답하고 있습니다. 잠시 후 다시 시도해 주세요.')
            identifier=secrets.token_hex(16)
            job={'messages':messages,'lease':secrets.token_hex(24),'claimed':False,'chunks':collections.deque(),
                 'sequence':0,'length':0,'done':False,'error':False}
            self.jobs[identifier]=job
            self.condition.notify_all()
        deadline=time.monotonic()+self.timeout
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
                if time.monotonic()>=deadline: raise ValueError('Gemma 응답 대기 시간이 지났습니다. 잠시 후 다시 시도해 주세요.')
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
            job=post('poll',{}).get('job')
            if not job: continue
            if job.get('model')!=config.get('model','gemma4:e4b'): raise ValueError('모델 설정 불일치')
            seq=0;buffer='';last=time.monotonic()
            try:
                for chunk in model.stream('ollama:'+job['model'],job['messages']):
                    buffer+=chunk
                    if len(buffer)>=60 or time.monotonic()-last>=.5:
                        post('result',{'id':job['id'],'lease':job['lease'],'sequence':seq,'text':buffer})
                        seq+=1;buffer='';last=time.monotonic()
                post('result',{'id':job['id'],'lease':job['lease'],'sequence':seq,'text':buffer,'done':True})
                print('Gemma 응답 전달 완료',flush=True)
            except Exception:
                try: post('result',{'id':job['id'],'lease':job['lease'],'sequence':seq,'done':True,'error':True})
                except Exception: pass
                print('Gemma 작업 중단 · 요청 본문과 비밀 값은 기록하지 않습니다.',flush=True)
        except KeyboardInterrupt: return
        except Exception:
            print('연결 재시도 대기',flush=True)
            time.sleep(5)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--config',required=True);args=p.parse_args()
    run_worker(json.loads(Path(args.config).read_text(encoding='utf-8')))
