"""Persistent open-ended chat, followed by an explicit research lookup."""
import copy
import hashlib
import json
import re
import time
import uuid
from .attachments import Attachments
from .chat_models import ChatModels
from .service import now, validate_text


class Conversation:
    def __init__(self,service,models=None):
        self.service=service;self.store=service.store
        self.models=models or ChatModels()
        self.attachments=Attachments(self.store.directory)
        # A process restart cannot resume an old HTTP stream.
        if any(s.get('pending') for s in self.store.read()['sessions']):
            def recover(state):
                for s in state['sessions']:
                    if s.get('pending'):
                        s['messages'].append({'role':'assistant','text':'서버가 재시작되어 응답이 중단됐어요. 다시 시도할 수 있습니다.','status':'error','turn_id':s['pending']})
                        s['pending']=None
            self.store.transaction(recover)

    def history(self):
        return [{'id':s['id'],'title':s['original'][:60],'updated':s['updated'],'model_id':s.get('model_id')}
                for s in reversed(self.store.read()['sessions']) if s.get('kind')=='chat']

    def get(self,sid):
        s=self.service.session(sid)
        if s.get('kind')!='chat':raise ValueError('이 대화는 이전 시연 화면에서 확인해 주세요.')
        return s

    def model_messages(self,session,option):
        messages=[]
        for m in session['messages']:
            if m.get('status') in ('error','cancelled'):continue
            content=m['text'];images=[]
            for ref in m.get('attachments',[]):
                item=self.attachments.load(ref['id'])
                if item['image']:
                    if not option['vision']:raise ValueError('이 대화에는 이미지가 있습니다. 이미지 지원 모델을 선택하거나 새 대화를 시작해 주세요.')
                    images.append(item['image'])
                else:
                    content+='\n\n[첨부 자료 · '+item['name']+(' · 앞부분만 읽음' if item['truncated'] else '')+']\n'+item['text']+'\n[첨부 끝]'
            row={'role':m['role'],'content':content}
            if images:row['images']=images
            messages.append(row)
        if sum(len(m['content']) for m in messages)>22000:
            raise ValueError('이 대화의 모델 입력 범위를 넘었습니다. 첨부를 줄이거나 필요한 부분을 새 대화에 넣어 주세요.')
        return messages

    def begin(self,payload):
        text=validate_text(payload.get('text',''),16000,True)
        ids=payload.get('attachments',[])
        if not isinstance(ids,list) or len(ids)>4 or any(not isinstance(x,str) for x in ids) or len(set(ids))!=len(ids):raise ValueError('첨부는 한 번에 4개까지 선택해 주세요.')
        items=[self.attachments.load(x) for x in ids]
        if not text and not items:raise ValueError('메시지를 입력하거나 파일을 첨부해 주세요.')
        option=self.models.get(payload.get('model_id'))
        if any(x['image'] for x in items) and not option['vision']:
            raise ValueError('선택한 모델은 이미지를 읽지 못합니다. 이미지 지원 모델을 선택하거나 문서로 첨부해 주세요.')
        turn_id=payload.get('turn_id','')
        if not isinstance(turn_id,str) or not re.fullmatch(r'[a-zA-Z0-9-]{16,80}',turn_id):raise ValueError('메시지 식별자를 확인해 주세요.')
        digest=hashlib.sha256(json.dumps([text,ids,option['id']],ensure_ascii=False).encode()).hexdigest()
        sid=payload.get('session_id')
        def start(state):
            s=next((x for x in state['sessions'] if x['id']==sid),None) if sid else next((x for x in state['sessions'] if x.get('kind')=='chat' and any(m.get('turn_id')==turn_id for m in x['messages'])),None)
            if sid and not s:raise ValueError('대화를 찾을 수 없습니다.')
            if s and s.get('kind')!='chat':raise ValueError('새 대화를 시작해 주세요.')
            if not s:
                s={'id':uuid.uuid4().hex,'kind':'chat','created':now(),'updated':now(),'original':text or items[0]['name'],
                   'messages':[],'turns':0,'mode':'advice','asker':'lab','slots':{'target':'','conditions':'','resources':'','deadline':'','goal':''},
                   'result':None,'ready':False,'followup':None,'can_propose':False,'pending':None}
                state['sessions'].append(s)
            existing=next((m for m in s['messages'] if m.get('turn_id')==turn_id and m['role']=='user'),None)
            if existing and existing.get('digest')!=digest:raise ValueError('다른 내용으로 이미 사용한 메시지 식별자입니다.')
            completed=next((m for m in s['messages'] if m.get('turn_id')==turn_id and m['role']=='assistant' and m.get('status')=='complete'),None)
            if completed:return copy.deepcopy(s),None,True
            if s.get('pending'):raise ValueError('이 대화에 응답 중인 메시지가 있습니다. 완료 후 보내 주세요.')
            if existing and next(m for m in reversed(s['messages']) if m['role']=='user')['turn_id']!=turn_id:
                raise ValueError('이후 대화가 있어 이 메시지를 다시 생성할 수 없습니다. 새 메시지로 요청해 주세요.')
            s['messages']=[m for m in s['messages'] if not(m.get('turn_id')==turn_id and m['role']=='assistant')]
            if not existing:
                s['messages'].append({'role':'user','input_text':text,'text':text or '첨부한 자료를 함께 검토해 주세요.','turn_id':turn_id,'digest':digest,'attachments':[self.attachments.public(x) for x in items]})
                s['turns']+=1
            s['pending']=turn_id;s['model_id']=option['id'];s['ready']=False;s['result']=None;s['updated']=now()
            messages=self.model_messages(s,option)
            return copy.deepcopy(s),messages,False
        return (*self.store.transaction(start),option)

    def finish(self,sid,turn_id,reply,status,option,error,elapsed):
        def save(state):
            s=next(x for x in state['sessions'] if x['id']==sid)
            if s.get('pending')!=turn_id:return copy.deepcopy(s)
            s['messages'].append({'role':'assistant','text':reply,'status':status,'error':error,'turn_id':turn_id,'model':option['name'],'model_id':option['id'],'elapsed_ms':round(elapsed*1000)})
            s['pending']=None;s['updated']=now();s['can_propose']=s['turns']>=2 and status=='complete'
            return copy.deepcopy(s)
        return self.store.transaction(save)

    def stream(self,payload):
        session,messages,cached,option=self.begin(payload)
        if cached:
            yield {'type':'done','session':session};return
        reply='';status='cancelled';error='';started=time.monotonic()
        try:
            yield {'type':'start','session':session}
            for piece in self.models.stream(option['id'],messages):
                reply+=piece
                yield {'type':'delta','text':piece}
            if not reply.strip():raise ValueError('모델이 빈 응답을 반환했습니다. 다시 시도해 주세요.')
            status='complete'
        except GeneratorExit:raise
        except Exception as exc:
            status='error';error=str(exc) if isinstance(exc,ValueError) else '응답 생성 중 오류가 발생했습니다. 다시 시도해 주세요.'
        finally:
            session=self.finish(session['id'],payload['turn_id'],reply,status,option,error,time.monotonic()-started)
        yield {'type':'done' if status=='complete' else 'error','session':session,'error':error}

    def prepare(self,payload):
        sid=payload.get('session_id')
        def update(state):
            s=next((x for x in state['sessions'] if x['id']==sid and x.get('kind')=='chat'),None)
            if not s or s.get('pending'):raise ValueError('응답이 끝난 대화에서 사람 찾기를 시작해 주세요.')
            parts=[]
            for m in s['messages']:
                if m['role']!='user':continue
                parts.append(m['text'])
                for ref in m.get('attachments',[]):
                    item=self.attachments.load(ref['id'])
                    if item['text']:parts.append('[사용자 첨부 자료 · '+item['name']+']\n'+item['text'])
            query='\n\n'.join(parts)
            s['mode']=self.service.engine.mode_for(query)
            s['asker']='site' if s['mode']=='site_request' else 'lab'
            s['proposal_context']=query[:12000]
            s['slots']['goal']=' / '.join(m['text'] for m in s['messages'] if m['role']=='user')[:1600]
            s['result']=self.service.engine.recommend(query,s['mode'])
            s['ready']=True;s['updated']=now()
            return copy.deepcopy(s)
        return self.store.transaction(update)
