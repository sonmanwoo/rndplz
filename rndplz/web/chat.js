"use strict";
const $=id=>document.getElementById(id);
const esc=value=>String(value??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
let token="",catalog=[],history=[],session=null,selectedModel="",files=[],busy=false,uploading=false,controller=null,streamText="",optimistic=null,retryPayload=null,letter=null,toastTimer,autoScroll=true,publicMode=false;
let profileBusy=false,profileSubmission=null;
let profileUI=null;
let prepareBusy=false,prepareTicket=0;
const formatted=text=>esc(text).replace(/\*\*([^*\n]+)\*\*/g,"<strong>$1</strong>").replace(/`([^`\n]+)`/g,"<code>$1</code>").replace(/^[-*] /gm,"• ");
async function api(path,body){const response=await fetch(path,body===undefined?{}:{method:"POST",headers:{"Content-Type":"application/json","X-RnDplz-Token":token},body:JSON.stringify(body)});const data=await response.json();if(!response.ok){const failure=new Error(data.error||"요청을 처리하지 못했어요.");failure.code=data.code;throw failure;}return data;}
function error(message=""){$("composerError").textContent=message;$("composerError").hidden=!message;}
function toast(message){clearTimeout(toastTimer);$("toast").textContent=message;$("toast").hidden=false;toastTimer=setTimeout(()=>$ ("toast").hidden=true,5500);}
function modal(id,returnFocus=document.activeElement){
 document.querySelectorAll("dialog[open]").forEach(d=>d.close());const dialog=$(id);dialog.returnFocus=returnFocus;
 if(!dialog.focusReturnBound){dialog.addEventListener("close",()=>{if(!document.querySelector("dialog[open]")&&dialog.returnFocus?.isConnected)dialog.returnFocus.focus();});dialog.focusReturnBound=true;}
 dialog.showModal();
}
function option(){return catalog.find(m=>m.id===selectedModel);}
function modelOptions(data,preferred){publicMode=!!data.public;if(publicMode){$("configForm").hidden=true;$("localStatus").closest(".local-status").querySelector("small").textContent="대화와 제안은 방문자별로 분리됩니다. 무료 시연 기록은 서버 재시작 때 사라질 수 있습니다.";$("settingsDialog").querySelector("p.subtle").textContent="운영자가 연결한 모델을 사용합니다. AI 미연결 시 기록 탐색 안내만 제공됩니다.";$("letterDialog").querySelector("p.subtle").textContent="이 방문자의 제안함에 시연 기록으로 저장됩니다. 실제 수신자에게 연락하지 않습니다.";}catalog=data.models;const previous=preferred||selectedModel;selectedModel=previous&&catalog.some(m=>m.id===previous&&m.enabled)?previous:data.default||"";$("modelSelect").innerHTML=catalog.map(m=>'<option value="'+esc(m.id)+'"'+(m.id===selectedModel?' selected':'')+(!m.enabled&&m.provider==="bridge"?' disabled':'')+'>'+esc(m.provider==="ollama"?m.name+" · 로컬":m.name)+'</option>').join("")||'<option value="">연결할 모델 없음</option>';$("localStatus").textContent=publicMode?"공개 서비스 · 방문자별 대화":catalog.filter(m=>m.local).length?"Ollama · 설치 모델 "+catalog.filter(m=>m.local).length+"개":"Ollama에 연결할 수 없어요";controls();}
function controls(){const m=option(),locked=busy||profileBusy||prepareBusy,profileIntent=profileUI?.shouldHandle($("message").value);$("sendButton").disabled=locked||uploading||(!m?.enabled&&!profileIntent)||(!$("message").value.trim()&&!files.length);$("sendButton").hidden=busy;$("stopButton").hidden=!busy;$("modelSelect").disabled=locked;$("attachButton").disabled=locked||uploading;$("message").disabled=locked;$("newButton").disabled=locked;$("historyButton").disabled=locked;$("settingsButton").disabled=locked;$("profileButton").disabled=locked;$("profileButton").setAttribute("aria-expanded",String(!!profileUI?.isOpen()));$("modelHint").textContent=profileIntent?"내 프로필에서 처리합니다. 모델에는 전송하지 않습니다.":uploading?"첨부파일을 전송하고 있어요…":m?.provider==="guide"?"AI 미연결 · 입력한 내용으로 연구 기록을 탐색합니다.":m?.provider==="bridge"?"운영자 PC의 Gemma로 이 대화와 첨부 내용을 처리합니다.":m?.local?"이 기기의 모델과 대화합니다.":m?.enabled?"선택한 API로 이 대화와 첨부 내용을 전송합니다.":"설정에서 모델을 연결해 주세요.";}
function resizeInput(){$("message").style.height="auto";$("message").style.height=Math.min(200,$("message").scrollHeight)+"px";controls();}
function fileChips(items,removable=false){return items.map(f=>'<span class="file-chip"><button type="button" data-action="preview-file" data-id="'+f.id+'" title="읽은 첨부 내용 보기">▤ '+esc(f.name)+(f.truncated?' <small>앞부분</small>':"")+'</button>'+(removable?'<button type="button" class="remove" data-action="remove-file" data-id="'+f.id+'" aria-label="'+esc(f.name)+' 첨부 제거">×</button>':"")+'</span>').join("");}
function renderFiles(){$("attachmentList").hidden=!files.length;$("attachmentList").innerHTML=fileChips(files,true);controls();}
function scrollBottom(){if(autoScroll)requestAnimationFrame(()=>window.scrollTo({top:document.documentElement.scrollHeight,behavior:"instant"}));}
function discoveryReady(s=session){return !!s&&typeof s.id==="string"&&!!s.id&&!s.ready&&!s.pending&&s.discovery?.ready===true&&typeof s.discovery.revision==="string"&&!!s.discovery.revision;}
function canPrepareDiscovery(){return discoveryReady()&&!busy&&!profileBusy&&!uploading&&!prepareBusy;}
async function prepareDiscovery(button,keyboard=false){
 if(!canPrepareDiscovery())return;
 const before=session,sid=before.id,revision=before.discovery.revision,ticket=++prepareTicket;
 const current=()=>ticket===prepareTicket&&session===before&&session?.id===sid&&session?.discovery?.revision===revision;
 const returnFocus=keyboard&&document.activeElement===button;let focusMoved=false;
 const focusElsewhere=e=>{if(e.target!==document.body&&!button.contains(e.target))focusMoved=true;};
 const pointerElsewhere=e=>{if(!button.contains(e.target))focusMoved=true;};
 const windowBlur=()=>{focusMoved=true;};
 document.addEventListener("focusin",focusElsewhere);document.addEventListener("pointerdown",pointerElsewhere);window.addEventListener("blur",windowBlur);
 let adopted=false,invalidated=false;prepareBusy=true;error();controls();button.disabled=true;button.textContent="관련 기록을 찾고 있어요…";
 try{
  const prepared=await api("/api/chat/prepare",{session_id:sid,discovery_revision:revision});
  if(!current())return;
  if(prepared?.id!==sid||prepared.discovery?.revision!==revision)throw new Error("대화 조건이 바뀌었습니다. 현재 조건을 확인한 뒤 다시 수소문해 주세요.");
  session=prepared;adopted=true;autoScroll=false;
 }catch(e){if(current()){error(e.message);if(e.code==="discovery_not_ready"||e.message==="현재 조건을 새 메시지로 확인한 뒤 수소문을 눌러 주세요."){session.discovery={...session.discovery,ready:false};invalidated=true;}}}
 finally{
  document.removeEventListener("focusin",focusElsewhere);document.removeEventListener("pointerdown",pointerElsewhere);window.removeEventListener("blur",windowBlur);
  if(ticket===prepareTicket){
   prepareBusy=false;controls();
   if(adopted){render();if(!$("proposalZone").hidden)$("proposalZone").scrollIntoView({block:"start",behavior:RndCraft.quiet()?"instant":"smooth"});}
   else if(current()){if(invalidated)render();else if(button.isConnected){button.disabled=!canPrepareDiscovery();button.textContent="현재 정보로 수소문";}else render();}
   if(returnFocus&&(adopted||current())&&!focusMoved&&document.hasFocus()&&(document.activeElement===document.body||document.activeElement===button)){
    const target=adopted||invalidated||!button.isConnected?$("message"):button;
    if(!target.disabled)target.focus({preventScroll:true});
   }
  }
 }
}
function render(){
 const messages=[...(session?.messages||[])];if(optimistic)messages.push(optimistic);
 const started=messages.length>0||profileUI?.isOpen();$("main").className=started?"welcome is-chat":"welcome";$("thread").hidden=!started;
 $("thread").innerHTML=messages.map(m=>m.role==="user"?'<article class="message user">'+esc(m.text)+(m.attachments?.length?'<div class="message-files">'+fileChips(m.attachments)+'</div>':"")+'</article>':'<article class="message assistant'+(m.status==="error"?' error-message':'')+'"><div class="message-meta"><span class="avatar">✳</span><span>'+esc(m.model||"수소문")+'</span></div><div class="message-body">'+formatted(m.text||"")+'</div>'+(m.status==="error"?'<p class="response-error">'+esc(m.error||"응답이 중단됐어요. 다시 시도할 수 있습니다.")+'</p><button class="retry" data-action="retry" data-id="'+esc(m.turn_id)+'">다시 시도</button>':m.status==="cancelled"?'<p class="response-note">응답을 중지했어요. 위 내용은 완성되지 않은 답변입니다.</p>':"")+(m.kind==="self_profile"?'<button type="button" class="text-button" data-action="profile-receipt" data-version="'+esc(m.profile_receipt?.version??"")+'">'+(m.profile_receipt?"변경 보기":"내 프로필 열기")+'</button>':"")+'</article>').join("");
 if(busy)$("thread").innerHTML+='<article class="message assistant"><div class="message-meta"><span class="avatar">✳</span><span>'+esc(option()?.name||"수소문")+'</span></div><div class="message-body">'+(streamText?formatted(streamText):'<span class="typing">답변을 준비하고 있어요</span>')+'</div></article>';
 if(canPrepareDiscovery())$("thread").innerHTML+='<div class="continue-actions"><button type="button" class="primary" data-action="prepare" title="지금까지 대화에서 확인한 조건과 등록 근거로 사람을 찾아봅니다. 실제로 연락하지 않습니다.">현재 정보로 수소문</button></div>';
 renderCandidates();controls();scrollBottom();
}

const canPropose=c=>Boolean(c)&&c.proposal_allowed!==false&&!c.lookup_only;
function checkProposalSelection(ids){
 if(!Array.isArray(ids)||!ids.length)throw new Error("현재 근거로 제안할 인물을 선택해 주세요.");
 for(const id of ids){const c=session?.result?.candidates.find(x=>x.id===id);if(!canPropose(c))throw new Error(c?.proposal_unavailable_reason||"현재 시연 범위의 인물과 근거로 다시 찾아 주세요.");}
}
function extraRecordSources(e){
 return (Array.isArray(e.metadata_sources)?e.metadata_sources:[]).filter(x=>safeUrl(x.url)).map(x=>'<p><a href="'+esc(x.url)+'" target="_blank" rel="noopener noreferrer">'+esc(x.title||x.label||(/correction/i.test(x.basis||x.type||'')?'정정 출처':'추가 확인 출처'))+' ↗</a></p>').join('');
}

function renderCandidates(){
 const zone=$("proposalZone");zone.hidden=!session?.ready||busy;if(zone.hidden)return;
 const result=session.result,lookup=result.intent==="person_lookup",choosing=result.intent==="person_choice",profileCount=result.candidates.filter(c=>c.profile_only).length,profileOnly=profileCount>0&&profileCount===result.candidates.length;
 let html='<div class="collection-heading"><div><span class="micro">PEOPLE / RECORDS</span><h2>'+esc(choosing?'어느 분을 말씀하시나요?':lookup?'이름으로 찾은 기록입니다.':profileOnly?'등록 기술·관심에서 찾았습니다.':profileCount?'기록과 등록 항목에서 찾았습니다.':'이 경험에서, 연결을 시작해요.')+'</h2><p>'+esc(lookup?'등록 이력을 보여드립니다. 요청한 일의 적합성을 확정하는 추천은 아닙니다.':choosing?'소속과 이름을 확인해 선택해 주세요.':profileCount?'등록 기술·관심과 수행 기록을 구분해 표시합니다. 등록 항목만 일치한 분은 이력 조회만 가능합니다.':'먼저 근거를 살펴보고, 조건을 더 알려주시면 함께 좁혀볼게요.')+'</p></div><span class="collection-count">'+String((choosing?(result.choices||[]):result.candidates).length).padStart(2,"0")+'</span></div>';
 if(result.scope_note)html+='<p class="subtle small">'+esc(result.scope_note)+'</p>';
 if(choosing){
  html+='<div class="candidate-list">'+(result.choices||[]).map(c=>'<article class="candidate"><h3>'+esc(c.name)+'</h3><p>'+esc(c.org)+'</p>'+(c.virtual?'<p>가상 현장 인물</p>':'')+'<button class="primary" data-action="person-select" data-id="'+esc(c.id)+'"'+(c.in_current_pool===false?' disabled':'')+'>이 사람의 이력 보기</button></article>').join('')+'</div>';
 }
 if(!result.candidates.length)html+='<div class="empty-result">'+esc(result.empty_message||'현재 열람 가능한 자료에서 근거를 찾지 못했습니다.')+'</div>';
 if(result.mode==="resource_request"&&result.candidates.some(canPropose)&&!lookup)html+='<button class="secondary" data-action="route-letter">경로별 제안문 준비하기 ↗</button>';
 html+='<div class="candidate-list">'+result.candidates.map((c,i)=>{
 const initials=c.name.split(/\s+/).filter(Boolean).slice(0,2).map(n=>n[0]).join("");
 const evidence=c.evidence?.[0]||{scope:'등록 프로필',title:'연결된 근거 기록 없음',boundary:'이 프로필만으로 수행 경험을 확인할 수 없습니다.'};
 const nobel=RndCraft.isLaureate(c.profile),personal=RndCraft.isPersonalIllustration(c.profile),lookupOnly=lookup||!canPropose(c);
 const art=c.profile?.curated||c.profile?.portrait||nobel||personal?RndCraft.portrait(c.profile,c.name):'<div class="profile-glyph" aria-hidden="true"><span class="initials">'+esc(initials)+'</span></div>';
 return '<article class="candidate holo-card'+(nobel?' laureate-card':'')+'" data-person-id="'+esc(c.id)+'" data-tilt'+RndCraft.laureateAttributes(c.profile)+' style="--deal:'+i+'"><div class="sticker-top"><span>No. '+String(i+1).padStart(2,"0")+'</span><span>RESEARCH / PEOPLE</span></div>'+(nobel?RndCraft.nameBlock(c)+art+RndCraft.awardSummary(c.profile)+RndCraft.effectControls(c.profile,c.name):personal?RndCraft.nameBlock(c,'h3','personal-name')+art+RndCraft.personalPortraitNote(c.profile):RndCraft.nameBlock(c,'h3','researcher-name')+art)+(c.proposal_unavailable_reason?'<p class="candidate-boundary">'+esc(c.proposal_unavailable_reason)+'</p>':'')+'<span class="scope-sticker">'+esc(c.virtual?"가상 현장 기록":evidence.scope)+'</span><p class="candidate-reason">'+esc(c.route_role||c.reason)+'</p><div class="evidence">'+esc(evidence.title)+'</div><small class="candidate-boundary">'+esc(evidence.boundary)+'</small><div class="candidate-actions"><button class="text-button" data-action="person" data-id="'+esc(c.id)+'">근거 펼쳐보기</button>'+(lookupOnly?'':'<button class="primary" data-action="letter" data-id="'+esc(c.id)+'">편지 쓰기 ↗</button>')+'</div><div class="candidate-footer"><span>H:문 — CONNECT BY EXPERIENCE</span><span>↗</span></div></article>';
 }).join("")+'</div><p class="subtle small">등록 자료 범위의 기록입니다. 개인 수행·현재 소속·연락 의향은 별도 확인이 필요합니다.</p>';
 zone.innerHTML=html;
}
function updateHistory(){if(!session)return;const row={id:session.id,title:session.original.slice(0,60),updated:session.updated};history=[row,...history.filter(s=>s.id!==row.id)];}
async function send(payload){
 if(busy||uploading||prepareBusy)return;prepareTicket++;error();streamText="";busy=true;autoScroll=true;controller=new AbortController();retryPayload=payload;
 if(!session?.messages.some(m=>m.turn_id===payload.turn_id&&m.role==="user"))optimistic={role:"user",text:payload.text||"첨부한 자료를 함께 검토해 주세요.",attachments:files};
 render();let accepted=false;
 try{
  const response=await fetch("/api/chat",{method:"POST",headers:{"Content-Type":"application/json","X-RnDplz-Token":token},body:JSON.stringify(payload),signal:controller.signal});
  if(!response.ok){const data=await response.json();throw new Error(data.error||"대화를 시작하지 못했어요.");}
  const reader=response.body.getReader(),decoder=new TextDecoder();let buffer="",finished=false;
  const event=line=>{if(!line.trim())return;const data=JSON.parse(line);
   if(data.type==="start"){session=data.session;accepted=true;optimistic=null;$("message").value="";files=[];renderFiles();window.history.replaceState(null,"","/?chat="+session.id);}
   if(data.type==="delta")streamText+=data.text;
   if(data.type==="done"||data.type==="error"){session=data.session;finished=true;busy=false;streamText="";optimistic=null;updateHistory();if(data.type==="error")error(data.error);}
   render();
  };
  while(true){const {value,done}=await reader.read();if(done)break;buffer+=decoder.decode(value,{stream:true});let end;while((end=buffer.indexOf("\n"))>=0){event(buffer.slice(0,end));buffer=buffer.slice(end+1);}}
  buffer+=decoder.decode();if(buffer.trim())event(buffer);
  if(!finished)throw new Error("응답 연결이 끝났어요. 저장된 대화를 확인하고 다시 시도해 주세요.");
 }catch(e){
  if(e.name==="AbortError"){error("응답을 중지하고 있어요…");}
  else error(e.message);
  if(accepted&&session){
   for(let i=0;i<30;i++){
    const saved=await api("/api/chat/session?id="+session.id).catch(()=>null);
    if(saved&&!saved.pending){session=saved;break;}
    await new Promise(resolve=>setTimeout(resolve,700));
   }
   if(session.pending)error("모델 응답 정리를 기다리고 있어요. 잠시 후 이전 대화에서 다시 열어 주세요.");
  }
 }finally{busy=false;optimistic=null;streamText="";controller=null;resizeInput();render();if(!session?.pending)$("message").focus();}
}
function newChat(){if(busy||profileBusy||uploading||prepareBusy)return;prepareTicket++;profileUI.close();session=null;files=[];optimistic=null;retryPayload=null;$("message").value="";window.history.replaceState(null,"","/");error();autoScroll=true;renderFiles();render();resizeInput();$("message").focus();}
function dataUrl(file){return new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result.split(",")[1]);reader.onerror=()=>reject(new Error("파일을 읽지 못했어요."));reader.readAsDataURL(file);});}
async function upload(list){
 if(busy||profileBusy||uploading||prepareBusy)return;error();if(files.length+list.length>4){error("파일은 한 번에 4개까지 첨부할 수 있어요.");return;}
 try{for(const file of list){if(file.size>(publicMode?1024*1024:8*1024*1024))throw new Error(publicMode?"공개 시연은 파일당 1MB까지 첨부할 수 있어요.":"파일당 8MB까지 첨부할 수 있어요.");files.push({id:"pending-"+crypto.randomUUID(),name:file.name,file});}}
 catch(e){error(e.message);}finally{$("fileInput").value="";renderFiles();}
}
async function submitComposer(){
 if(busy||profileBusy||uploading||prepareBusy)return;
 const text=$("message").value.trim();if(!text&&!files.length)return;
 if(profileUI.shouldHandle(text)){
  if(files.some(f=>!f.file)){error("앞서 일반 대화용으로 전송한 파일은 제거하고 프로필용 파일을 다시 선택해 주세요.");return;}
  profileSubmission={text:$("message").value,ids:files.map(f=>f.id)};
  try{await profileUI.submit(text,files.map(f=>f.file));}catch(e){error(e.message);}finally{if(!profileUI.hasPendingRequest())profileSubmission=null;render();resizeInput();}
  return;
 }
 uploading=true;controls();
 try{
  for(let i=0;i<files.length;i++){const f=files[i];if(f.file){files[i]=await api("/api/attachments",{name:f.name,data:await dataUrl(f.file)});renderFiles();}}
 }catch(e){error(e.message);return;}finally{uploading=false;controls();}
 await send({text,session_id:session?.id,attachments:files.map(f=>f.id),model_id:selectedModel,turn_id:crypto.randomUUID()});
}
function safeUrl(url){try{return ["https:","http:"].includes(new URL(url).protocol);}catch{return false;}}
async function showPerson(id,opener=document.activeElement){
 const stored=session?.result?.candidates.find(c=>c.id===id);
 const historical=Boolean(stored&&session?.result?.historical_result);
 const p=historical?stored:await api("/api/person?id="+encodeURIComponent(id));
 const profile=RndCraft.profileDetails(p),candidate=session?.result?.candidates.find(c=>c.id===id);
 const historicalNotice=historical?'<p class="subtle small">이전 응답 당시 선택 근거</p>'+
  (session.result.scope_note?'<p class="subtle small">'+esc(session.result.scope_note)+'</p>':'')+
  (p.proposal_unavailable_reason?'<p class="candidate-boundary">'+esc(p.proposal_unavailable_reason)+'</p>':''):'';
 const profileNotice=!historical&&candidate?.profile_only?'<p class="small">'+esc(candidate.reason)+'</p><p class="subtle small">전체 등록 이력 · 이번 조건의 수행 근거로 확인된 목록 아님</p>':'';
 $("detailContent").innerHTML=historicalNotice+profileNotice+(profile||'<h2>'+esc(p.name)+'</h2><p class="subtle">'+esc(p.org)+'</p>')+'<p class="small">'+(historical?"저장된 응답의 일부 근거이며 현재 전체 등록 이력이 아닙니다.":p.virtual?"시연용 가상 인물":p.evidence?.length?"전체 등록 이력 · 개인 수행·본인 확인·연락 의향 미확인":"등록 프로필 · 연결된 수행 기록 없음")+'</p>'+(p.evidence||[]).map(e=>'<section class="detail-record"><h3>'+esc(e.title)+'</h3><p>'+esc(e.date)+" · "+esc(e.role)+" · "+esc(e.scope)+'</p><p>'+esc(e.boundary)+'</p>'+(safeUrl(e.url)?'<a href="'+esc(e.url)+'" target="_blank" rel="noopener noreferrer">원문 출처 ↗</a>':"")+extraRecordSources(e)+'</section>').join("");
 modal("detailDialog",opener);
}
async function openLetter(ids){
 checkProposalSelection(ids);const drafts=await Promise.all(ids.map(id=>api("/api/draft",{session_id:session.id,candidate_id:id})));letter={ids,drafts,key:crypto.randomUUID(),sessionId:session.id,index:0,bodies:Object.fromEntries(drafts.map(d=>[d.candidate.id,d.body]))};renderLetter();modal("letterDialog");}
function renderLetter(){const d=letter.drafts[letter.index];$("letterTitle").textContent=d.candidate.name+"님에게";$("letterBody").value=letter.bodies[d.candidate.id];$("letterError").textContent="";let switcher=$("recipientSelect");if(switcher)switcher.remove();if(letter.ids.length>1){switcher=document.createElement("select");switcher.id="recipientSelect";switcher.setAttribute("aria-label","경로별 수신자");switcher.innerHTML=letter.drafts.map((x,i)=>'<option value="'+i+'"'+(i===letter.index?' selected':'')+'>'+esc((i+1)+". "+x.candidate.name)+'</option>').join("");$("letterBody").before(switcher);switcher.addEventListener("change",()=>{keepLetter();letter.index=Number(switcher.value);renderLetter();});}}
function keepLetter(){const id=letter.ids[letter.index];if(letter.bodies[id]!==$("letterBody").value){letter.bodies[id]=$("letterBody").value;letter.key=crypto.randomUUID();}}
async function saveLetter(state){const button=state==="sent"?$("proposeButton"):$("draftButton");button.disabled=true;$("draftButton").disabled=true;$("proposeButton").disabled=true;try{keepLetter();const saved=await api("/api/proposals",{session_id:letter.sessionId,candidate_ids:letter.ids,bodies:letter.bodies,state,idempotency_key:letter.key});$("letterDialog").close();const recipientName=letter.drafts[0].candidate.name;letter=null;if(state==="sent")RndCraft.deliver(recipientName,saved.length);else toast(saved.length+"건을 제안함에 "+(state==="draft"?"초안으로":"시연 기록으로")+" 저장했어요.");}catch(e){$("letterError").textContent=e.message;}finally{$("draftButton").disabled=false;$("proposeButton").disabled=false;}}
profileUI=RndProfileChat.create({host:$("profileChatHost"),getToken:()=>token,getSessionId:()=>session?.id||null,
 onBusy:value=>{profileBusy=value;controls();},
 onClose:()=>{autoScroll=false;render();$("message").focus({preventScroll:true});},
 onSession:value=>{
  session=value;updateHistory();window.history.replaceState(null,"","/?chat="+session.id);
  if(profileSubmission){if($("message").value===profileSubmission.text)$("message").value="";files=files.filter(f=>!profileSubmission.ids.includes(f.id));renderFiles();profileSubmission=null;}
  autoScroll=false;render();resizeInput();
 }});
$ ("profileButton").addEventListener("click",async()=>{if(busy||profileBusy||prepareBusy)return;error();autoScroll=false;await profileUI.open();render();$("profileChatHost").scrollIntoView({block:"start",behavior:"instant"});});
$ ("chatForm").addEventListener("submit",e=>{e.preventDefault();submitComposer();});
$ ("message").addEventListener("input",resizeInput);
$ ("message").addEventListener("keydown",e=>{if(e.key==="Enter"&&!e.shiftKey&&!e.isComposing){e.preventDefault();if(!$("sendButton").disabled)$("chatForm").requestSubmit();}});
$ ("stopButton").addEventListener("click",()=>controller?.abort());
$ ("newButton").addEventListener("click",newChat);
$ ("attachButton").addEventListener("click",()=>$ ("fileInput").click());
$ ("fileInput").addEventListener("change",e=>upload([...e.target.files]));
$ ("modelSelect").addEventListener("change",e=>{const chosen=catalog.find(m=>m.id===e.target.value);if(!chosen?.enabled){$("modelSelect").value=selectedModel;if(chosen?.provider==="bridge"){toast("이 Gemma는 연결 대기 중입니다. 사용 가능한 모델을 선택해 주세요.");return;}$("provider").value=chosen?.provider||"openai";modal("settingsDialog");return;}selectedModel=chosen.id;controls();error();});
$ ("settingsButton").addEventListener("click",()=>modal("settingsDialog"));
$ ("historyButton").addEventListener("click",()=>{$("historyList").innerHTML=history.length?history.map(h=>'<button class="history-item" data-action="history" data-id="'+h.id+'">'+esc(h.title)+'<small>'+new Date(h.updated).toLocaleString("ko-KR")+'</small></button>').join(""):'<p class="subtle">첫 대화를 시작해 보세요.</p>';modal("historyDialog");});
$ ("refreshModels").addEventListener("click",async()=>{try{modelOptions(await api("/api/chat/models?refresh=1"),selectedModel);toast("사용 가능한 모델 목록을 갱신했어요.");}catch(e){error(e.message);}});
$ ("configForm").addEventListener("submit",async e=>{e.preventDefault();$("saveConfig").disabled=true;$("configMessage").textContent="";try{const provider=$("provider").value;const data=await api("/api/chat/configure",{provider,model:$("apiModel").value,key:$("apiKey").value});$("apiKey").value="";modelOptions(data,provider);$("configMessage").textContent="설정을 저장했어요. 다음 메시지부터 선택한 API로 보냅니다.";}catch(e){$("configMessage").textContent=e.message;}finally{$("saveConfig").disabled=false;}});
$ ("draftButton").addEventListener("click",()=>saveLetter("draft"));
$ ("proposeButton").addEventListener("click",()=>saveLetter("sent"));
document.addEventListener("click",async e=>{const button=e.target.closest("button");if(!button)return;if(button.classList.contains("close")){button.closest("dialog").close();return;}const action=button.dataset.action,id=button.dataset.id;if(!action||busy||profileBusy||prepareBusy)return;
 try{
  if(action==="profile-receipt"){autoScroll=false;if(button.dataset.version)await profileUI.showReceipt(Number(button.dataset.version));else await profileUI.open();render();$("profileChatHost").scrollIntoView({block:"start",behavior:"instant"});}
  else if(action==="remove-file"){files=files.filter(f=>f.id!==id);renderFiles();}
  else if(action==="preview-file"){const pending=files.find(f=>f.id===id&&f.file);if(pending){$("fileTitle").textContent=pending.name;$("fileInfo").textContent="전송 대기 · 메시지를 보낼 때 일반 대화 또는 프로필 용도로 처리합니다.";$("filePreview").textContent="파일 크기: "+pending.file.size.toLocaleString()+" bytes";modal("fileDialog");return;}const item=await api("/api/attachment?id="+id);$("fileTitle").textContent=item.name;$("fileInfo").textContent=item.kind==="image"?"이미지 지원 모델에서만 대화에 사용할 수 있어요.":"읽은 텍스트 "+item.characters.toLocaleString()+"자"+(item.truncated?" · 길이 제한으로 앞부분만 읽었습니다.":"");$("filePreview").innerHTML=item.image?'<img alt="첨부 이미지" src="data:'+item.mime+';base64,'+item.image+'">':'<pre>'+esc(item.text)+'</pre>';modal("fileDialog");}
  else if(action==="history"){prepareTicket++;profileUI.close();session=await api("/api/chat/session?id="+id);if(catalog.some(m=>m.id===session.model_id&&m.enabled)){selectedModel=session.model_id;$("modelSelect").value=selectedModel;}files=[];$("message").value="";renderFiles();$("historyDialog").close();window.history.replaceState(null,"","/?chat="+id);autoScroll=true;render();}
  else if(action==="retry"){const user=session.messages.find(m=>m.turn_id===id&&m.role==="user");const assistant=session.messages.find(m=>m.turn_id===id&&m.role==="assistant");selectedModel=assistant?.model_id||session.model_id;$("modelSelect").value=selectedModel;await send({text:user.input_text??user.text,session_id:session.id,attachments:(user.attachments||[]).map(f=>f.id),model_id:selectedModel,turn_id:id,...(user.person_id?{person_id:user.person_id}:{})});}
  else if(action==="prepare")await prepareDiscovery(button,e.detail===0);
  else if(action==="person-select"){const choice=session.result?.choices?.find(c=>c.id===id);if(!choice)throw new Error("표시된 인물을 다시 선택해 주세요.");await send({text:choice.name+"의 이력 보여줘",person_id:id,session_id:session.id,model_id:selectedModel,turn_id:crypto.randomUUID()});}
  else if(action==="person")await showPerson(id,button);
  else if(action==="letter")await openLetter([id]);
  else if(action==="route-letter"){const ids=session?.result?.intent==="person_lookup"?[]:(session?.result?.candidates||[]).filter(canPropose).map(c=>c.id);if(ids.length)await openLetter(ids);}
 }catch(e){error(e.message);button.disabled=false;}
});
window.addEventListener("scroll",()=>{autoScroll=document.documentElement.scrollHeight-innerHeight-scrollY<160;},{passive:true});
(async()=>{try{const data=await api("/api/chat/bootstrap");token=data.token;history=data.history;modelOptions(data);const id=new URLSearchParams(location.search).get("chat");if(id){session=await api("/api/chat/session?id="+encodeURIComponent(id));if(catalog.some(m=>m.id===session.model_id&&m.enabled)){selectedModel=session.model_id;$("modelSelect").value=selectedModel;}}render();resizeInput();if(new URLSearchParams(location.search).has("settings"))modal("settingsDialog");}catch(e){error(e.message);}})();
