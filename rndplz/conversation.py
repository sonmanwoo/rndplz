"""Persistent conversation with grounded identity and research lookup actions."""
import copy
import hashlib
import json
import re
import time
import uuid
from .attachments import Attachments
from .chat_models import ChatModels
from .chat_actions import ChatActions
from .service import now, validate_text


class Conversation:
    def __init__(self,service,models=None):
        self.service=service;self.store=service.store
        self.models=models or ChatModels()
        self.actions=ChatActions(service)
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

    def request_context(self, session, for_prepare=False):
        """Compile current user requirements, with replacements and quoted origins.

        This is request context, never person evidence. Ambiguous references are
        returned as questions; callers must resolve them before recommending.
        """
        active = {}; issues = {}; documents = {}; archive = {}; activated = set()
        messages = session.get('messages', [])
        number = re.compile(r'(?<![\w.])\d+(?:,\d{3})*(?:\.\d+)?\s*(?:만\s*원|원|개월|시간|주|일|도|℃|°C|장|개|건|명|%)?|(?<=[가-힣])\d+(?:\.\d+)?\s*(?:만\s*원|원|개월|시간|주|일|도|℃|°C|장|개|건|명|%)?')
        labels = re.compile(r'라벨(?:링)?|이미지|사진|데이터|시료|샘플|예산|기간|기한|온도')
        keys = {'라벨':'label_count','라벨링':'label_count','이미지':'image_count','사진':'image_count',
                '데이터':'data_count','시료':'sample_count','샘플':'sample_count','예산':'budget',
                '기간':'duration','기한':'duration','온도':'temperature'}
        titles = {'label_count':'라벨','image_count':'이미지','data_count':'데이터','sample_count':'시료',
                  'budget':'예산','duration':'기간','temperature':'온도','equipment':'장비','control_method':'제어 방법'}
        correction = re.compile(r'아니라|아니고|대신|말고|→|->|정정|수정|변경|바꿔|늘려|줄여')

        def put(key, text, source, position, value=None):
            prior = active.get(key)
            if prior and prior['position'] > position:
                return
            if prior and prior['source']['kind'] == source['kind'] == 'user_document' and prior['text'] != text and prior['source'].get('attachment_id') != source.get('attachment_id'):
                issues[key] = f'첨부 문서의 {titles.get(key, "같은 조건")} 값이 서로 달라요. 어떤 값을 사용할까요?'
                return
            if source['kind'] != 'user_document':
                issues.pop(key, None)
            active[key] = {'text':text, 'source':source, 'position':position, 'value':value}

        def consume(clause, source, position):
            clause = clause.strip(' \t-•*')
            if not clause or re.search(r'^(?:만약|가정|예를\s*들어)', clause):
                return
            # Mentioning a rejected option does not assert its numbers as facts.
            if re.search(r'(?:채택|동의|수락|확정|선택|적용)(?:하)?지\s*않|(?:채택|동의|수락|확정|선택|적용)(?:한|된)?\s*(?:게|것이|건)?\s*아니|(?:채택|동의|수락|확정|선택|적용)(?:은|는|를)?\s*안\s*(?:했|해|하)|거절했|받아들이지', clause):
                return
            if re.search(r'미정|정하지\s*않|정한\s*(?:게|것이)\s*없|아직\s*모르',clause):
                for label in labels.findall(clause):
                    active.pop(keys[label],None); issues.pop(keys[label],None)
                return
            # Quoted suggestions are not an explicit acceptance of conditions.
            if re.search(r'(?:모델|AI|너|네|당신)(?:가|이|는|의)?\s*.{0,12}(?:제안|추천|가정)|(?:라고|라고만)\s*(?:제안|추천|말했|했는데)', clause, re.I):
                return
            # Document instructions cannot alter dialogue control or profile facts.
            if source['kind'] == 'user_document' and re.search(r'<\s*/?system|시스템\s*지시|지시.*무시|person_confirmed|individual_performance_verified', clause, re.I):
                return
            origin = {**source, 'quote':clause}
            found = list(number.finditer(clause)); accepted = []; previous_key = None; previous_end = 0; ambiguous_quantity = False
            for match in found:
                literal = match.group().strip(); numeric = re.match(r'[\d,.]+', literal).group().replace(',', '')
                unit = re.sub(r'^[\d,.]+\s*', '', literal).replace(' ', '')
                before = clause[previous_end:match.start()]
                label = list(labels.finditer(before))
                key = keys[label[-1].group()] if label else None
                if key is None and unit in ('도','℃','°C'): key = 'temperature'
                if key is None and unit in ('주','일','개월','시간'): key = 'duration'
                if key is None and unit in ('원','만원'): key = 'budget'
                if key is None and previous_key and correction.search(before): key = previous_key
                if key is None and correction.search(clause):
                    same = [k for k,v in active.items() if v.get('value') == numeric]
                    if len(same) == 1: key = same[0]
                    elif not same:
                        counts = [k for k in active if k.endswith('_count')]
                        if len(counts) == 1 and unit in ('장','개','건','명'): key = counts[0]
                if key is None:
                    if unit in ('장','개','건','명'):
                        ambiguous_quantity = True
                        issues['quantity'] = f'{literal}는 어떤 대상의 수량인가요? 대상과 새 수량을 함께 알려 주세요.'
                    previous_end = match.end(); previous_key = None
                    continue
                qualifiers = re.findall(r'최대|최소|상한|하한|이하|이상|미만|초과|이내|약', before)
                trailing = re.match(r'\s*(이하|이상|미만|초과|이내)',clause[match.end():])
                if trailing: qualifiers.append(trailing.group(1))
                if not qualifiers and correction.search(clause):
                    previous = next((v[1] for v in reversed(accepted) if v[0]==key), active.get(key,{}).get('text',''))
                    qualifiers = re.findall(r'최대|최소|상한|하한|이하|이상|미만|초과|이내|약',previous)
                rendered = (' '.join(dict.fromkeys(qualifiers))+' ' if qualifiers else '')+numeric+unit
                subject = before[:label[-1].start()] if label else (before if unit in ('도','℃','°C') and not correction.search(before) else '')
                subject = re.sub(r'^(?:이고|이고요|이며|인데|그리고|및|\s)+', '', subject).strip()
                subject = re.sub(r'최대|최소|상한|하한|이하|이상|미만|초과|이내|약', '', subject).strip()
                if not subject or correction.search(subject):
                    subject = next((v[3] for v in reversed(accepted) if v[0]==key),active.get(key,{}).get('subject',''))
                accepted.append((key, rendered, numeric, subject))
                previous_key = key; previous_end = match.end()
            for key, rendered, value, subject in accepted:
                put(key, (subject+' ' if subject else '')+titles[key]+' '+rendered, origin, position, value)
                if key in active and active[key]['position']==position:active[key]['subject']=subject
            if any(key.endswith('_count') for key,*_ in accepted) and not ambiguous_quantity:
                issues.pop('quantity', None)
            controls = re.findall(r'(?<![a-z])(?:PID|MPC|APC)(?![a-z])', clause, re.I)
            if controls and re.search(r'어떨|할까|비교|어느|둘\s*중', clause):
                return
            if controls:
                if len(set(x.upper() for x in controls)) == 1 or correction.search(clause):
                    if not re.search(r'어떨|할까|비교|어느|둘\s*중', clause):
                        rendered = '제어 방법 '+controls[-1].upper() if correction.search(clause) else clause
                        put('control_method', rendered, origin, position)
                else:
                    issues['control_method'] = '제어 방법은 어느 것으로 정했나요? 사용할 방법을 하나로 알려 주세요.'
            equipment = re.search(r'(?:장비|설비|GPU)(?:가|는|도|을)?\s*(?:없(?:어|음|습니다|고)?|미보유|보유(?:함)?|있(?:어|음|습니다|고)?)', clause, re.I)
            if equipment:
                put('equipment', equipment.group(), origin, position)
            if accepted or controls or equipment:
                # Keep the topic words, but never retain obsolete numeric literals.
                residue = number.sub('', clause)
                residue = re.sub(r'(?<![a-z])(?:PID|MPC|APC)(?![a-z])', '', residue, flags=re.I)
                if equipment: residue = residue.replace(equipment.group(), '')
                residue = re.sub(r'라벨(?:링)?|이미지|사진|데이터|시료|샘플|예산|기간|기한|온도', '', residue)
                residue = re.sub(r'\b(?:은|는|이|가|을|를|로|으로|에서|동안|중|이고|입니다|있어|있어요|있습니다|만|정정|수정|변경)\b', ' ', residue)
                residue = re.sub(r'\s+', ' ', residue).strip(' .:;→-')
                if not accepted and not controls and not correction.search(clause) and len(residue) >= 4:
                    put('text:'+residue, residue, origin, position)
                return
            if re.fullmatch(r'(?:안녕(?:하세요)?|고마워(?:요)?|감사합니다|좋아(?:요)?|네|응|알겠어)[.!\s]*', clause):
                return
            if re.search(r'(?:사람|전문가|연구자|검색).*(?:아직|나중|말고|하지\s*마|유보)|(?:아직|나중).*(?:찾|검색)', clause):
                return
            if re.fullmatch(r'(?:앞(?:서)?|이|그|위|현재)?\s*(?:첨부(?:한)?\s*(?:문서|파일|자료)?\s*)?(?:문서|자료|파일|조건|내용|기준)(?:의|에|으로|로|을|를|에\s*맞는)?\s*(?:맞는\s*)?(?:조건(?:으로)?\s*)?(?:전문가|연구자|사람)?\s*(?:를|을)?\s*(?:찾아|찾아줘|찾아주세요|추천|추천해줘|추천해\s*주세요)?[.!?\s]*', clause):
                return
            put('text:'+clause, clause, origin, position)

        def use_document(identifier, accepted_by):
            if identifier in activated:
                return
            info = documents[identifier]
            item = self.attachments.load(identifier)
            activated.add(identifier)
            if item.get('image'):
                issues['document:'+identifier] = '검색 조건이 있는 문서나 텍스트를 지정해 주세요.'
                return
            if item.get('truncated'):
                issues['document:'+identifier] = '첨부가 앞부분만 읽혀 조건이 빠질 수 있어요. 사용할 조건 부분을 짧게 알려 주세요.'
            section = False; clauses = []
            for line in item.get('text','').splitlines():
                clean = line.strip()
                if re.match(r'^#{1,6}\s', clean):
                    section = bool(re.search(r'조건|요청|기준|requirements', clean, re.I))
                    continue
                labelled = bool(re.match(r'(?:필수|제외|요청|검토)?\s*조건\s*[:：]', clean))
                if labelled or (section and re.match(r'^[-*•]\s+', clean)):
                    clauses.append(clean)
            if not clauses:
                clauses = re.split(r'[\n;]+|(?<=[.!?])\s+|(?<!\d),(?!\d)', item.get('text',''))
            for clause in clauses:
                source={'turn_id':info['turn_id'],'kind':'user_document','attachment_id':identifier,'accepted_by':accepted_by}
                consume(clause, source, info['position'])

        for index, message in enumerate(messages):
            if message.get('role') != 'user':
                continue
            text = message.get('input_text', message.get('text','')) or ''
            turn_id = message.get('turn_id', f'user-{index}')
            if self.actions.cancelled(text):
                active.clear(); issues.clear(); activated.clear(); documents.clear()
                continue
            if re.search(r'^아니면\s+|(?:완전히\s*)?(?:다른|새로운|새)\s*(?:주제|문제|과제)|(?:주제|문제|과제)(?:를|을)?\s*(?:바꿔|변경)|(?:앞|이전|기존).{0,6}(?:조건|대화|요청).{0,6}(?:잊|버리|초기화)', text):
                active.clear(); issues.clear(); activated.clear(); documents.clear()
            current_docs=[]
            for ref in message.get('attachments', []):
                identifier=ref.get('id')
                if not identifier:continue
                current_docs.append(identifier)
                documents.setdefault(identifier,{'position':index,'turn_id':turn_id,'name':ref.get('name','')})
                archive.setdefault(identifier, documents[identifier])
            selection = re.search(r'(첫\s*번째|두\s*번째|세\s*번째|[1-9]\s*번(?:째)?)(?:로|를|을)?\s*(?:하자|할게|선택|가자|좋겠)', text)
            if selection:
                prior = messages[index-1] if index else {}
                raw = re.sub(r'\s','',selection.group(1))
                selected = {'첫번째':1,'두번째':2,'세번째':3}.get(raw)
                if selected is None:selected=int(raw[0])
                options = re.findall(r'^\s*(?:[-*]\s*)?([1-9])[.)]\s+(.+)$',prior.get('text',''),re.M) if prior.get('role')=='assistant' and prior.get('status') not in ('error','cancelled') else []
                matches = [value for ordinal,value in options if int(ordinal)==selected]
                if len(options)>=2 and len(matches)==1 and len({ordinal for ordinal,_ in options})==len(options):
                    chosen=matches[0].strip()
                    origin={'turn_id':turn_id,'kind':'user_selection','quote':text,'selection_quote':text,
                            'option_turn_id':prior.get('turn_id',''),'option_quote':chosen}
                    put('selected_option',chosen,origin,index)
                    issues.pop('selection',None)
                else:
                    issues['selection']='어떤 안을 선택한 것인지 이름이나 내용을 한 번만 적어 주세요.'
                continue
            references = bool(re.search(r'첨부|문서|파일|자료', text) and re.search(r'조건|기준|반영|적용|사용', text))
            references = references or bool(current_docs and re.search(r'(?:이|그|위)\s*조건',text))
            if references:
                named=[identifier for identifier,info in archive.items() if info['name'] and info['name'] in text]
                chosen=named or current_docs or list(documents) or list(archive)
                if len(chosen)>1 and not re.search(r'모두|둘\s*다|두\s*(?:첨부|문서|파일)|함께',text) and not named:
                    issues['document_choice']='어느 첨부의 조건을 사용할까요? 파일 이름이나 모두 사용할지 알려 주세요.'
                elif chosen:
                    issues.pop('document_choice',None)
                    for identifier in chosen:
                        documents.setdefault(identifier,archive[identifier])
                        use_document(identifier,turn_id)
                else:
                    issues['document_choice']='이 요청에서 사용할 첨부를 다시 지정해 주세요.'
            for clause in re.split(r'[\n;]+|(?<=[.!?])\s+|(?<!\d),(?!\d)|\s*/\s*|(?:이고|이며|인데)\s+',text):
                consume(clause,{'turn_id':turn_id,'kind':'user_text'},index)
        if for_prepare:
            for identifier in documents:
                use_document(identifier, 'prepare')
        sources = [{'text':entry['text'],**entry['source']} for entry in active.values()]
        query = '\n'.join(entry['text'] for entry in active.values())
        if len(query)>12000:
            issues['size']='검색 조건이 길어요. 이번에 사용할 대상과 중요한 조건만 짧게 정리해 주세요.'
            query=''
        return {'query':query,'sources':sources,'unresolved':list(dict.fromkeys(issues.values()))}

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
        selected=payload.get('person_id')
        if selected is not None and (not isinstance(selected,str) or not 1<=len(selected)<=200):raise ValueError('인물 선택을 확인해 주세요.')
        identity=[text,ids,option['id']]+([selected] if selected else [])
        digest=hashlib.sha256(json.dumps(identity,ensure_ascii=False).encode()).hexdigest()
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
                if selected:s['messages'][-1]['person_id']=selected
            # Decide from the current user request, then compile conditions separately.
            attached_context=any(m.get('attachments') for m in s['messages'] if m['role']=='user')
            people=self.actions.people_request(text)
            # A combined document-fact question still needs the model to read its data.
            document_facts=bool(attached_context and re.search(r'(?:건수|수치|코드|값|요약|차이|계산|몇\s*(?:개|건|명)).{0,30}(?:알려|설명|비교|요약|해\s*줘|해주세요|인지)',text))
            direct_action=selected is not None or not attached_context or self.actions.cancelled(text) or (people and not document_facts)
            context=s.get('search_context') or {}
            search=people or self.actions.search_refinement(context,text)
            request=None;action=None
            if direct_action and (text or selected):
                if search and selected is None and not self.actions.cancelled(text):
                    request=self.request_context(s)
                    s['request_context']=request
                if request and request['unresolved'] and not self.actions.matches(text)[0]:
                    question=request['unresolved'][0]
                    action={'reply':question,'result':None,'context':{'kind':'request_clarification','ids':[],'query':''},'can_propose':False}
                else:
                    action=self.actions.resolve({**s,**({'_request_query':request['query']} if request else {})},text,selected)
            if action is None and self.actions.discussion_request(text) and context.get('kind')=='recommend':
                # Returning to idea exploration does not keep automatic search refinement active.
                s['search_context']={**context,'kind':'discussion'}
            s['pending_action']=action
            s['pending']=turn_id;s['model_id']=option['id'];s['ready']=False;s['result']=None;s['updated']=now()
            messages=[] if action else self.model_messages(s,option)
            return copy.deepcopy(s),messages,False
        return (*self.store.transaction(start),option)

    def finish(self,sid,turn_id,reply,status,option,error,elapsed):
        def save(state):
            s=next(x for x in state['sessions'] if x['id']==sid)
            if s.get('pending')!=turn_id:return copy.deepcopy(s)
            action=s.pop('pending_action',None)
            label='수소문 · 기록 조회' if action else option['name']
            s['messages'].append({'role':'assistant','text':reply,'status':status,'error':error,'turn_id':turn_id,'model':label,'model_id':option['id'],'elapsed_ms':round(elapsed*1000),'source':'records' if action else 'model'})
            s['pending']=None;s['updated']=now();s['can_propose']=s['turns']>=2 and status=='complete' and (s.get('search_context') or {}).get('kind')!='stopped'
            if action and status=='complete':
                s['result']=action['result'];s['ready']=action['result'] is not None
                s['can_propose']=action['can_propose'];s['search_context']=action['context']
                if action.get('query'):
                    s['proposal_context']=action['query'][:12000];s['slots']['goal']=action['query'][:1600]
                s['mode']=action.get('mode','advice');s['asker']='site' if s['mode']=='site_request' else 'lab'
            return copy.deepcopy(s)
        return self.store.transaction(save)

    def stream(self,payload):
        session,messages,cached,option=self.begin(payload)
        if cached:
            yield {'type':'done','session':session};return
        reply='';status='cancelled';error='';started=time.monotonic()
        try:
            yield {'type':'start','session':session}
            action=session.get('pending_action')
            pieces=[action['reply']] if action else self.models.stream(option['id'],messages)
            for piece in pieces:
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
            if (s.get('search_context') or {}).get('kind')=='stopped':raise ValueError('중단한 요청입니다. 새 요청을 입력해 주세요.')
            if s.get('ready') and s.get('result') is not None:return copy.deepcopy(s)
            request=self.request_context(s,for_prepare=True)
            s['request_context']=request
            if request['unresolved']:raise ValueError(request['unresolved'][0])
            query=self.actions.query_for({'_request_query':request['query']},'')
            s['mode']=self.service.engine.mode_for(query)
            s['asker']='site' if s['mode']=='site_request' else 'lab'
            s['proposal_context']=query[:12000]
            s['slots']['goal']=query[:1600]
            action=self.actions.recommend({'_request_query':query},query)
            s['result']=action['result'];s['search_context']=action['context']
            s['can_propose']=action['can_propose']
            s['ready']=True;s['updated']=now()
            return copy.deepcopy(s)
        return self.store.transaction(update)
