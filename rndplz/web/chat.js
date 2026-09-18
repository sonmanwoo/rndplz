"use strict";
const $=id=>document.getElementById(id);
const esc=value=>String(value??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
let token="",catalog=[],history=[],session=null,selectedModel="",files=[],busy=false,uploading=false,controller=null,streamText="",optimistic=null,retryPayload=null,letter=null,toastTimer,autoScroll=true,publicMode=false;
const formatted=text=>esc(text).replace(/\*\*([^*\n]+)\*\*/g,"<strong>$1</strong>").replace(/`([^`\n]+)`/g,"<code>$1</code>").replace(/^[-*] /gm,"• ");
async function api(path,body){const response=await fetch(path,body===undefined?{}:{method:"POST",headers:{"Content-Type":"application/json","X-RnDplz-Token":token},body:JSON.stringify(body)});const data=await response.json();if(!response.ok)throw new Error(data.error||"요청을 처리하지 못했어요.");return data;}
function error(message=""){$("composerError").textContent=message;$("composerError").hidden=!message;}
function toast(message){clearTimeout(toastTimer);$("toast").textContent=message;$("toast").hidden=false;toastTimer=setTimeout(()=>$ ("toast").hidden=true,5500);}
function modal(id){document.querySelectorAll("dialog[open]").forEach(d=>d.close());$(id).showModal();}
function option(){return catalog.find(m=>m.id===selectedModel);}
function modelOptions(data,preferred){publicMode=!!data.public;if(publicMode){$("configForm").hidden=true;$("localStatus").closest(".local-status").querySelector("small").textContent="대화와 제안은 방문자별로 분리됩니다. 무료 시연 기록은 서버 재시작 때 사라질 수 있습니다.";$("settingsDialog").querySelector("p.subtle").textContent="운영자가 연결한 모델을 사용합니다. AI 미연결 시 기록 탐색 안내만 제공됩니다.";$("letterDialog").querySelector("p.subtle").textContent="이 방문자의 제안함에 시연 기록으로 저장됩니다. 실제 수신자에게 연락하지 않습니다.";}catalog=data.models;selectedModel=preferred&&catalog.some(m=>m.id===preferred&&m.enabled)?preferred:data.default||"";$("modelSelect").innerHTML=catalog.map(m=>'<option value="'+esc(m.id)+'"'+(m.id===selectedModel?' selected':'')+'>'+esc(m.provider==="ollama"?m.name+" · 로컬":m.name)+'</option>').join("")||'<option value="">연결할 모델 없음</option>';$("localStatus").textContent=publicMode?"공개 서비스 · 방문자별 대화":catalog.filter(m=>m.local).length?"Ollama · 설치 모델 "+catalog.filter(m=>m.local).length+"개":"Ollama에 연결할 수 없어요";controls();}
function controls(){const m=option();$("sendButton").disabled=busy||uploading||!m?.enabled||(!$("message").value.trim()&&!files.length);$("sendButton").hidden=busy;$("stopButton").hidden=!busy;$("modelSelect").disabled=busy;$("attachButton").disabled=busy||uploading;$("message").disabled=busy;$("newButton").disabled=busy;$("historyButton").disabled=busy;$("settingsButton").disabled=busy;$("modelHint").textContent=uploading?"첨부파일을 읽고 있어요…":m?.provider==="guide"?"AI 미연결 · 입력한 내용으로 연구 기록을 탐색합니다.":m?.provider==="bridge"?"운영자 PC의 Gemma로 이 대화와 첨부 내용을 처리합니다.":m?.local?"이 기기의 모델과 대화합니다.":m?.enabled?"선택한 API로 이 대화와 첨부 내용을 전송합니다.":"설정에서 모델을 연결해 주세요.";}
function resizeInput(){$("message").style.height="auto";$("message").style.height=Math.min(200,$("message").scrollHeight)+"px";controls();}
function fileChips(items,removable=false){return items.map(f=>'<span class="file-chip"><button type="button" data-action="preview-file" data-id="'+f.id+'" title="읽은 첨부 내용 보기">▤ '+esc(f.name)+(f.truncated?' <small>앞부분</small>':"")+'</button>'+(removable?'<button type="button" class="remove" data-action="remove-file" data-id="'+f.id+'" aria-label="'+esc(f.name)+' 첨부 제거">×</button>':"")+'</span>').join("");}
function renderFiles(){$("attachmentList").hidden=!files.length;$("attachmentList").innerHTML=fileChips(files,true);controls();}
function scrollBottom(){if(autoScroll)requestAnimationFrame(()=>window.scrollTo({top:document.documentElement.scrollHeight,behavior:"instant"}));}
function render(){
 const messages=[...(session?.messages||[])];if(optimistic)messages.push(optimistic);
 const started=messages.length>0;$("main").className=started?"welcome is-chat":"welcome";$("thread").hidden=!started;
 $("thread").innerHTML=messages.map(m=>m.role==="user"?'<article class="message user">'+esc(m.text)+(m.attachments?.length?'<div class="message-files">'+fileChips(m.attachments)+'</div>':"")+'</article>':'<article class="message assistant'+(m.status==="error"?' error-message':'')+'"><div class="message-meta"><span class="avatar">✳</span><span>'+esc(m.model||"수소문")+'</span></div><div class="message-body">'+formatted(m.text||"")+'</div>'+(m.status==="error"?'<p class="response-error">'+esc(m.error||"응답이 중단됐어요. 다시 시도할 수 있습니다.")+'</p><button class="retry" data-action="retry" data-id="'+esc(m.turn_id)+'">다시 시도</button>':m.status==="cancelled"?'<p class="response-note">응답을 중지했어요. 위 내용은 완성되지 않은 답변입니다.</p>':"")+'</article>').join("");
 if(busy)$("thread").innerHTML+='<article class="message assistant"><div class="message-meta"><span class="avatar">✳</span><span>'+esc(option()?.name||"수소문")+'</span></div><div class="message-body">'+(streamText?formatted(streamText):'<span class="typing">답변을 준비하고 있어요</span>')+'</div></article>';
 if(session?.can_propose&&!session.ready&&!busy)$("thread").innerHTML+='<div class="continue-actions"><button class="primary" data-action="prepare">이 내용으로 사람 찾기 ↗</button></div>';
 renderCandidates();controls();scrollBottom();
}
function renderCandidates(){
 const zone=$("proposalZone");zone.hidden=!session?.ready||busy;if(zone.hidden)return;
 const result=session.result;
 let html='<div class="collection-heading"><div><span class="micro">PEOPLE / COLLECTED FOR YOUR QUESTION</span><h2>이 경험에서, 연결을 시작해요.</h2><p>기록을 살펴보고 함께 이야기하고 싶은 사람을 골라보세요.</p></div><span class="collection-count">'+String(result.candidates.length).padStart(2,"0")+'</span></div>';
 if(!result.candidates.length)html+='<div class="empty-result">지금 자료에서는 근거가 있는 후보를 찾지 못했어요.<br>대상을 더 설명하거나 다른 조건으로 대화를 이어갈 수 있습니다.</div>';
 if(result.mode==="resource_request"&&result.candidates.length)html+='<button class="secondary" data-action="route-letter">경로별 제안문 준비하기 ↗</button>';
 html+='<div class="candidate-list">'+result.candidates.map((c,i)=>{
 const initials=c.name.split(/\s+/).filter(Boolean).slice(0,2).map(n=>n[0]).join("");
 return '<article class="candidate holo-card" data-tilt style="--deal:'+i+'"><div class="sticker-top"><span>No. '+String(i+1).padStart(2,"0")+'</span><span>RESEARCH / PEOPLE</span></div>'+(c.profile?.portrait?RndCraft.portrait(c.profile,c.name):'<div class="profile-glyph" aria-hidden="true"><span class="initials">'+esc(initials)+'</span></div>')+'<h3>'+esc(c.name)+'</h3><p class="candidate-org">'+esc(c.org)+'</p><span class="scope-sticker">'+esc(c.virtual?"가상 현장 기록":c.evidence[0].scope)+'</span><p class="candidate-reason">'+esc(c.route_role||c.reason)+'</p><div class="evidence">'+esc(c.evidence[0].title)+'</div><small class="candidate-boundary">'+esc(c.evidence[0].boundary)+'</small><div class="candidate-actions"><button class="text-button" data-action="person" data-id="'+esc(c.id)+'">근거 펼쳐보기</button><button class="primary" data-action="letter" data-id="'+esc(c.id)+'">편지 쓰기 ↗</button></div><div class="candidate-footer"><span>H:문 — CONNECT BY EXPERIENCE</span><span>↗</span></div></article>';
 }).join("")+'</div><p class="subtle small">참여 기록으로 찾은 연결입니다. 개인 수행·현재 연락 의향은 확인이 필요합니다.</p>';
 zone.innerHTML=html;
}
function updateHistory(){if(!session)return;const row={id:session.id,title:session.original.slice(0,60),updated:session.updated};history=[row,...history.filter(s=>s.id!==row.id)];}
async function send(payload){
 if(busy||uploading)return;error();streamText="";busy=true;autoScroll=true;controller=new AbortController();retryPayload=payload;
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
function newChat(){if(busy)return;session=null;files=[];optimistic=null;retryPayload=null;$("message").value="";window.history.replaceState(null,"","/");error();autoScroll=true;renderFiles();render();resizeInput();$("message").focus();}
function dataUrl(file){return new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result.split(",")[1]);reader.onerror=()=>reject(new Error("파일을 읽지 못했어요."));reader.readAsDataURL(file);});}
async function upload(list){
 if(busy||uploading)return;error();if(files.length+list.length>4){error("파일은 한 번에 4개까지 첨부할 수 있어요.");return;}
 uploading=true;controls();
 try{for(const file of list){if(file.size>(publicMode?1024*1024:8*1024*1024))throw new Error(publicMode?"공개 시연은 파일당 1MB까지 첨부할 수 있어요.":"파일당 8MB까지 첨부할 수 있어요.");const saved=await api("/api/attachments",{name:file.name,data:await dataUrl(file)});files.push(saved);renderFiles();if(saved.truncated)toast(file.name+"의 앞부분을 읽었어요. 첨부를 눌러 읽은 범위를 확인해 주세요.");}}
 catch(e){error(e.message);}finally{uploading=false;$("fileInput").value="";controls();}
}
function safeUrl(url){try{return ["https:","http:"].includes(new URL(url).protocol);}catch{return false;}}
async function showPerson(id){const p=await api("/api/person?id="+encodeURIComponent(id));$("detailContent").innerHTML='<h2>'+esc(p.name)+'</h2><p class="subtle">'+esc(p.org)+'</p><p class="small">'+(p.virtual?"시연용 가상 인물":"참여 기록 확인 · 개인 수행·본인 확인·연락 의향 미확인")+'</p>'+p.evidence.map(e=>'<section class="detail-record"><h3>'+esc(e.title)+'</h3><p>'+esc(e.date)+" · "+esc(e.role)+" · "+esc(e.scope)+'</p><p>'+esc(e.boundary)+'</p>'+(safeUrl(e.url)?'<a href="'+esc(e.url)+'" target="_blank" rel="noopener noreferrer">원문 출처 ↗</a>':"")+'</section>').join("");modal("detailDialog");}
async function openLetter(ids){const drafts=await Promise.all(ids.map(id=>api("/api/draft",{session_id:session.id,candidate_id:id})));letter={ids,drafts,key:crypto.randomUUID(),sessionId:session.id,index:0,bodies:Object.fromEntries(drafts.map(d=>[d.candidate.id,d.body]))};renderLetter();modal("letterDialog");}
function renderLetter(){const d=letter.drafts[letter.index];$("letterTitle").textContent=d.candidate.name+"님에게";$("letterBody").value=letter.bodies[d.candidate.id];$("letterError").textContent="";let switcher=$("recipientSelect");if(switcher)switcher.remove();if(letter.ids.length>1){switcher=document.createElement("select");switcher.id="recipientSelect";switcher.setAttribute("aria-label","경로별 수신자");switcher.innerHTML=letter.drafts.map((x,i)=>'<option value="'+i+'"'+(i===letter.index?' selected':'')+'>'+esc((i+1)+". "+x.candidate.name)+'</option>').join("");$("letterBody").before(switcher);switcher.addEventListener("change",()=>{keepLetter();letter.index=Number(switcher.value);renderLetter();});}}
function keepLetter(){const id=letter.ids[letter.index];if(letter.bodies[id]!==$("letterBody").value){letter.bodies[id]=$("letterBody").value;letter.key=crypto.randomUUID();}}
async function saveLetter(state){const button=state==="sent"?$("proposeButton"):$("draftButton");button.disabled=true;$("draftButton").disabled=true;$("proposeButton").disabled=true;try{keepLetter();const saved=await api("/api/proposals",{session_id:letter.sessionId,candidate_ids:letter.ids,bodies:letter.bodies,state,idempotency_key:letter.key});$("letterDialog").close();const recipientName=letter.drafts[0].candidate.name;letter=null;if(state==="sent")RndCraft.deliver(recipientName,saved.length);else toast(saved.length+"건을 제안함에 "+(state==="draft"?"초안으로":"시연 기록으로")+" 저장했어요.");}catch(e){$("letterError").textContent=e.message;}finally{$("draftButton").disabled=false;$("proposeButton").disabled=false;}}
$ ("chatForm").addEventListener("submit",e=>{e.preventDefault();if(!$("message").value.trim()&&!files.length)return;send({text:$("message").value.trim(),session_id:session?.id,attachments:files.map(f=>f.id),model_id:selectedModel,turn_id:crypto.randomUUID()});});
$ ("message").addEventListener("input",resizeInput);
$ ("message").addEventListener("keydown",e=>{if(e.key==="Enter"&&!e.shiftKey&&!e.isComposing){e.preventDefault();if(!$("sendButton").disabled)$("chatForm").requestSubmit();}});
$ ("stopButton").addEventListener("click",()=>controller?.abort());
$ ("newButton").addEventListener("click",newChat);
$ ("attachButton").addEventListener("click",()=>$ ("fileInput").click());
$ ("fileInput").addEventListener("change",e=>upload([...e.target.files]));
$ ("modelSelect").addEventListener("change",e=>{const chosen=catalog.find(m=>m.id===e.target.value);if(!chosen?.enabled){$("provider").value=chosen?.provider||"openai";$("modelSelect").value=selectedModel;modal("settingsDialog");return;}selectedModel=chosen.id;controls();error();});
$ ("settingsButton").addEventListener("click",()=>modal("settingsDialog"));
$ ("historyButton").addEventListener("click",()=>{$("historyList").innerHTML=history.length?history.map(h=>'<button class="history-item" data-action="history" data-id="'+h.id+'">'+esc(h.title)+'<small>'+new Date(h.updated).toLocaleString("ko-KR")+'</small></button>').join(""):'<p class="subtle">첫 대화를 시작해 보세요.</p>';modal("historyDialog");});
$ ("refreshModels").addEventListener("click",async()=>{try{modelOptions(await api("/api/chat/models?refresh=1"),selectedModel);toast("사용 가능한 모델 목록을 갱신했어요.");}catch(e){error(e.message);}});
$ ("configForm").addEventListener("submit",async e=>{e.preventDefault();$("saveConfig").disabled=true;$("configMessage").textContent="";try{const provider=$("provider").value;const data=await api("/api/chat/configure",{provider,model:$("apiModel").value,key:$("apiKey").value});$("apiKey").value="";modelOptions(data,provider);$("configMessage").textContent="설정을 저장했어요. 다음 메시지부터 선택한 API로 보냅니다.";}catch(e){$("configMessage").textContent=e.message;}finally{$("saveConfig").disabled=false;}});
$ ("draftButton").addEventListener("click",()=>saveLetter("draft"));
$ ("proposeButton").addEventListener("click",()=>saveLetter("sent"));
document.addEventListener("click",async e=>{const button=e.target.closest("button");if(!button)return;if(button.classList.contains("close")){button.closest("dialog").close();return;}const action=button.dataset.action,id=button.dataset.id;if(!action||busy)return;
 try{
  if(action==="remove-file"){files=files.filter(f=>f.id!==id);renderFiles();}
  else if(action==="preview-file"){const item=await api("/api/attachment?id="+id);$("fileTitle").textContent=item.name;$("fileInfo").textContent=item.kind==="image"?"이미지 지원 모델에서만 대화에 사용할 수 있어요.":"읽은 텍스트 "+item.characters.toLocaleString()+"자"+(item.truncated?" · 길이 제한으로 앞부분만 읽었습니다.":"");$("filePreview").innerHTML=item.image?'<img alt="첨부 이미지" src="data:'+item.mime+';base64,'+item.image+'">':'<pre>'+esc(item.text)+'</pre>';modal("fileDialog");}
  else if(action==="history"){session=await api("/api/chat/session?id="+id);if(catalog.some(m=>m.id===session.model_id&&m.enabled)){selectedModel=session.model_id;$("modelSelect").value=selectedModel;}files=[];$("message").value="";renderFiles();$("historyDialog").close();window.history.replaceState(null,"","/?chat="+id);autoScroll=true;render();}
  else if(action==="retry"){const user=session.messages.find(m=>m.turn_id===id&&m.role==="user");const assistant=session.messages.find(m=>m.turn_id===id&&m.role==="assistant");selectedModel=assistant?.model_id||session.model_id;$("modelSelect").value=selectedModel;await send({text:user.input_text??user.text,session_id:session.id,attachments:(user.attachments||[]).map(f=>f.id),model_id:selectedModel,turn_id:id});}
  else if(action==="prepare"){button.disabled=true;button.textContent="관련 기록을 찾고 있어요…";session=await api("/api/chat/prepare",{session_id:session.id});autoScroll=false;render();$("proposalZone").scrollIntoView({block:"start",behavior:RndCraft.quiet()?"instant":"smooth"});}
  else if(action==="person")await showPerson(id);
  else if(action==="letter")await openLetter([id]);
  else if(action==="route-letter")await openLetter(session.result.candidates.map(c=>c.id));
 }catch(e){error(e.message);button.disabled=false;}
});
window.addEventListener("scroll",()=>{autoScroll=document.documentElement.scrollHeight-innerHeight-scrollY<160;},{passive:true});
(async()=>{try{const data=await api("/api/chat/bootstrap");token=data.token;history=data.history;modelOptions(data);const id=new URLSearchParams(location.search).get("chat");if(id){session=await api("/api/chat/session?id="+encodeURIComponent(id));if(catalog.some(m=>m.id===session.model_id&&m.enabled)){selectedModel=session.model_id;$("modelSelect").value=selectedModel;}}render();resizeInput();if(new URLSearchParams(location.search).has("settings"))modal("settingsDialog");}catch(e){error(e.message);}})();
