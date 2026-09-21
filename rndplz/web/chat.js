"use strict";
const $=id=>document.getElementById(id);
const esc=value=>String(value??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
let token="",catalog=[],history=[],session=null,selectedModel="",files=[],busy=false,uploading=false,controller=null,streamText="",optimistic=null,retryPayload=null,letter=null,toastTimer,autoScroll=true,publicMode=false;
let modelSelectionOrigin="automatic",modelDefault="",modelSelectionEpoch=0,modelCatalogTicket=0;
let profileBusy=false,profileSubmission=null;
let profileUI=null;
let accountNavigationPending=false,accountInvalidated=false;
let prepareBusy=false,prepareTicket=0;
let composerInputRevision=0,composerComposing=false;
function composerClientLocked(){return accountNavigationPending||accountInvalidated||busy||prepareBusy||profileBusy||uploading;}
function composerSendLocked(){return composerClientLocked()||!!session?.pending;}
function setComposerDraft(value){$("message").value=value;composerInputRevision++;}
function consumeComposerDraft(){const text=$("message").value,stagedEdit=briefEditor?.stagedText===text&&composerInputRevision===briefEditor.stagedComposerRevision?briefEditor:null;setComposerDraft("");return {text,revision:composerInputRevision,attachmentIds:[],stagedEdit};}
function restoreComposerDraft(draft){if(draft&&!accountNavigationPending&&!accountInvalidated&&composerInputRevision===draft.revision&&$("message").value===""){setComposerDraft(draft.text);if(draft.stagedEdit&&briefEditor===draft.stagedEdit&&briefEditor.stagedText===draft.text)briefEditor.stagedComposerRevision=composerInputRevision;}}
let drawController=null,drawRenderKey="",drawEpoch=0,animateScoutKey="";
const formatted=text=>esc(text).replace(/\*\*([^*\n]+)\*\*/g,"<strong>$1</strong>").replace(/`([^`\n]+)`/g,"<code>$1</code>").replace(/^[-*] /gm,"• ");
async function api(path,body){if(accountNavigationPending||accountInvalidated)throw new Error("계정이 바뀌고 있어요. 새 화면에서 다시 확인해 주세요.");const response=await fetch(path,body===undefined?{}:{method:"POST",headers:{"Content-Type":"application/json","X-RnDplz-Token":token},body:JSON.stringify(body)});const data=await response.json();if(accountInvalidated)throw new Error("이전 계정의 응답을 적용하지 않았습니다.");if(!response.ok){const failure=new Error(data.error||"요청을 처리하지 못했어요.");failure.code=data.code;failure.retry_available=data.retry_available;if(["scout_source_changed","scout_source_unsupported"].includes(data.code))failure.session=data.session;throw failure;}return data;}
function error(message=""){$("composerError").textContent=message;$("composerError").hidden=!message;}
function toast(message){clearTimeout(toastTimer);$("toast").textContent=message;$("toast").hidden=false;toastTimer=setTimeout(()=>$ ("toast").hidden=true,5500);}
function modal(id,returnFocus=document.activeElement){
 document.querySelectorAll("dialog[open]").forEach(d=>d.close());const dialog=$(id);dialog.returnFocus=returnFocus;
 if(!dialog.focusReturnBound){dialog.addEventListener("close",()=>{if(!document.querySelector("dialog[open]")&&dialog.returnFocus?.isConnected)dialog.returnFocus.focus();});dialog.focusReturnBound=true;}
 dialog.showModal();
}
function option(){return catalog.find(m=>m.id===selectedModel);}
function responseModelLabel(message){return message.source==="guide"?"기록 탐색 안내 · AI 미사용":message.model||"수소문";}
function selectionOrigin(value){return ["automatic","explicit","legacy_unknown"].includes(value)?value:"legacy_unknown";}
function resolveModelSelection(models,defaultId,id,origin){
 origin=selectionOrigin(origin);
 if(id&&origin!=="automatic")return {id,origin};
 const enabled=value=>models.some(m=>m.id===value&&m.enabled),next=enabled(defaultId)?defaultId:models.find(m=>m.enabled)?.id||"";
 if(id&&enabled(id)&&id!=="guide")return {id,origin:"automatic"};
 return {id:next,origin:"automatic"};
}
function renderModelSelect(){
 const missing=selectedModel&&!catalog.some(m=>m.id===selectedModel)?'<option value="'+esc(selectedModel)+'" selected disabled>'+esc(selectedModel)+' · 연결 불가</option>':"";
 $("modelSelect").innerHTML=missing+catalog.map(m=>'<option value="'+esc(m.id)+'"'+(m.id===selectedModel?' selected':'')+(!m.enabled&&m.provider==="bridge"?' disabled':'')+'>'+esc(m.provider==="ollama"?m.name+" · 로컬":m.name)+'</option>').join("")||'<option value="">연결할 모델 없음</option>';
 $("modelSelect").value=selectedModel;
}
function syncModelSelection(){
 if(busy||profileBusy||prepareBusy||uploading)return;
 const next=resolveModelSelection(catalog,modelDefault,selectedModel,modelSelectionOrigin);
 if(next.id!==selectedModel||next.origin!==modelSelectionOrigin){selectedModel=next.id;modelSelectionOrigin=next.origin;renderModelSelect();}
}
function restoreModelSelection(saved,epoch=modelSelectionEpoch){
 if(epoch!==modelSelectionEpoch||typeof saved?.model_id!=="string"||!saved.model_id)return;
 selectedModel=saved.model_id;modelSelectionOrigin=selectionOrigin(saved.model_selection_origin);modelSelectionEpoch++;
 syncModelSelection();renderModelSelect();
}
function modelOptions(data){
 publicMode=!!data.public;
 if(publicMode){$("configForm").hidden=true;$("localStatus").closest(".local-status").querySelector("small").textContent="대화와 제안은 방문자별로 분리됩니다. 무료 시연 기록은 서버 재시작 때 사라질 수 있습니다.";$("settingsDialog").querySelector("p.subtle").textContent="운영자가 연결한 모델을 사용합니다. AI 미연결 시 기록 탐색 안내만 제공됩니다.";$("letterDialog").querySelector("p.subtle").textContent="이 방문자의 제안함에 시연 기록으로 저장됩니다. 실제 수신자에게 연락하지 않습니다.";}
 catalog=data.models;modelDefault=data.default||"";syncModelSelection();renderModelSelect();
 $("localStatus").textContent=publicMode?"공개 서비스 · 방문자별 대화":catalog.filter(m=>m.local).length?"Ollama · 설치 모델 "+catalog.filter(m=>m.local).length+"개":"Ollama에 연결할 수 없어요";controls();
}
async function refreshModelOptions(path="/api/chat/models?refresh=1"){
 const ticket=++modelCatalogTicket,data=await api(path);
 if(ticket!==modelCatalogTicket)return false;
 modelOptions(data);return true;
}
function controls(){syncModelSelection();const m=option(),locked=composerSendLocked(),navigationLocked=composerClientLocked(),profileIntent=profileUI?.shouldHandle($("message").value);$("sendButton").disabled=locked||uploading||(!m?.enabled&&!profileIntent)||(!$("message").value.trim()&&!files.length);$("sendButton").hidden=busy;$("stopButton").hidden=!busy;$("modelSelect").disabled=locked;$("attachButton").disabled=locked||uploading;$("attachmentList").querySelectorAll('[data-action="remove-file"]').forEach(button=>button.disabled=locked);$("message").disabled=accountNavigationPending||accountInvalidated||profileBusy||uploading;$("newButton").disabled=navigationLocked;$("historyButton").disabled=navigationLocked;$("settingsButton").disabled=locked;$("profileButton").disabled=locked;$("profileButton").setAttribute("aria-expanded",String(!!profileUI?.isOpen()));$("modelHint").textContent=profileIntent?"내 프로필에서 처리합니다. 모델에는 전송하지 않습니다.":uploading?"첨부파일을 전송하고 있어요…":(selectedModel&&!m?.enabled)?"선택한 모델을 지금 사용할 수 없어요. 연결 상태를 확인하거나 다른 모델을 선택해 주세요.":m?.provider==="guide"?"기록 탐색 안내 · AI를 사용하지 않습니다.":m?.provider==="bridge"?"운영자 PC의 Gemma로 이 대화와 첨부 내용을 처리합니다.":m?.local?"이 기기의 모델과 대화합니다.":m?.enabled?"선택한 API로 이 대화와 첨부 내용을 전송합니다.":"설정에서 모델을 연결해 주세요.";syncDiscoveryControls();updateBriefNotice();}
function resizeInput(){$("message").style.height="auto";$("message").style.height=Math.min(200,$("message").scrollHeight)+"px";controls();}
function fileChips(items,removable=false){return items.map(f=>'<span class="file-chip"><button type="button" data-action="preview-file" data-id="'+f.id+'" title="읽은 첨부 내용 보기">▤ '+esc(f.name)+(f.truncated?' <small>앞부분</small>':"")+'</button>'+(removable?'<button type="button" class="remove" data-action="remove-file" data-id="'+f.id+'" aria-label="'+esc(f.name)+' 첨부 제거">×</button>':"")+'</span>').join("");}
function renderFiles(){$("attachmentList").hidden=!files.length;$("attachmentList").innerHTML=fileChips(files,true);controls();}
function scrollBottom(){if(autoScroll)requestAnimationFrame(()=>{if(autoScroll&&!briefEditor)window.scrollTo({top:document.documentElement.scrollHeight,behavior:"instant"});});}
// lookup_ready and summary/question describe server-compiled search clues.
// They do not assert that a candidate exists or that a proposal is ready.
function currentDiscovery(s=session){return !!s&&typeof s.id==="string"&&!!s.id&&s.search_context?.kind!=="stopped"&&typeof s.discovery?.lookup_ready==="boolean"&&typeof s.discovery.revision==="string"&&!!s.discovery.revision?s.discovery:null;}
function discoveryReady(s=session){return currentDiscovery(s)?.lookup_ready===true&&!s.pending;}
function discoveryCompletion(s=session){
 const discovery=currentDiscovery(s),result=s?.result;
 if(!discovery?.lookup_ready||s.pending||!s.ready||s.prepared_discovery_revision!==discovery.revision||s.search_context?.kind!=="recommend"||result?.intent!=="recommend"||result.inspection_only||result.historical_result||!Array.isArray(result.candidates))return "";
 const count=result.candidates.length;
 return count?"조회가 완료됐어요. 현재 조건으로 찾은 인물은 "+count+"명이에요.":"조회가 완료됐어요. 현재 조건으로 찾은 인물은 0명이에요.";
}
function recoverableScout(s=session){const r=s?.scout_recovery;return !!s?.id&&r?.available===true&&r.status==="required"&&typeof r.id==="string"&&typeof r.from_revision==="string"&&r.from_revision===s.request_spec?.revision&&s.request_spec?.state==="stale"&&briefHasContent(s.request_spec)&&!s.pending;}
function scoutButtonLabel(){return recoverableScout()?"이 정보로 다시 수소문하기":"이 정보로 수소문하기";}
function canPrepareDiscovery(){return (discoveryReady()&&briefCurrent()||recoverableScout())&&!briefEditor&&!briefFailure&&!busy&&!profileBusy&&!uploading&&!prepareBusy;}
function syncDiscoveryControls(){
 const button=$("currentScoutButton"),scout=$("currentScout");if(!button||!scout)return;
 const available=canPrepareDiscovery();scout.hidden=!available;
 button.disabled=!available;button.textContent=scoutButtonLabel();
 button.setAttribute("aria-busy",String(prepareBusy));
}
function scoutCount(){
 const s=session?.scout,known=s?.count_status==="known"&&Number.isSafeInteger(s.count)&&s.count>=0;
 const label=known?(s.disclosed?"현재 공개된 인물 ":"관련 기록과 연결된 인물 ")+s.count+"명":"아직 인물 수를 확인하지 않았어요.";
 return '<p class="scout-count" role="status">'+esc(label)+(known&&!s.disclosed?'<small>기록 조회 기준 · 요청 적합성은 수소문 후 확인해요.</small>':'')+'</p>';
}
function scoutConditions(){
 const rows=session?.request_spec?.conditions||[];
 return rows.length?'<ul class="scout-conditions">'+rows.map(c=>'<li>'+esc((c.kind==='required'?'필수 · ':'선호 · ')+c.text)+'</li>').join('')+'</ul>':'';
}
function currentScout(){
 const available=canPrepareDiscovery();
 return '<div class="continue-actions" id="currentScout"'+(available?'':' hidden')+'><button type="button" class="primary" id="currentScoutButton" data-action="prepare" title="등록된 인물과 근거를 조회합니다."'+(available?'':' disabled')+'>'+scoutButtonLabel()+'</button></div>';
}

// request_spec is the only accepted brief; this is an unsent editor buffer.
let briefSessionId=null,briefEditor=null,briefFailure=null,briefRenderKey="";
// Render-only signatures, never a second accepted request_spec or edit source.
let briefChangeAnchor=null,briefChangeLabel="";
const briefLabels={purposes:"목적",requested_help:"필요한 도움",conditions:"조건",open_questions:"아직 정하지 않은 점"};
const briefConditionLabel=kind=>({required:"필수",preference:"선호"}[kind]||String(kind||"조건"));
const briefRows=value=>Array.isArray(value)?value.filter(row=>row&&typeof row.text==="string"&&row.text.trim()):[];
// Preserve explicit user restrictions from accepted conditions without reclassifying them.
function briefConditionLines(value){
 const rows=briefRows(value),texts=new Set(rows.map(row=>row.text));
 const quotes=[...new Set(rows.map(row=>row.source_quote).filter(quote=>typeof quote==="string"&&quote.trim()))];
 return [...rows.map(row=>briefConditionLabel(row.kind)+" · "+row.text),...quotes.filter(quote=>!texts.has(quote)).map(quote=>"요청 원문 · "+quote)];
}
function briefFields(spec){
 return {purposes:briefRows(spec?.purposes).map(row=>row.text).join("\n"),requested_help:briefRows(spec?.requested_help).map(row=>row.text).join("\n"),conditions:briefConditionLines(spec?.conditions).join("\n"),open_questions:(Array.isArray(spec?.open_questions)?spec.open_questions:[]).filter(text=>typeof text==="string"&&text.trim()).join("\n")};
}
function briefHasContent(spec){return spec?.has_content===true&&[spec.purposes,spec.requested_help,spec.conditions].some(rows=>briefRows(rows).length>0);}
function briefRevisionCurrent(s=session){
 const spec=s?.request_spec,revision=spec?.revision;
 return !!s?.id&&spec?.state==="current"&&typeof revision==="string"&&!!revision&&revision===s.discovery?.revision&&revision===s.scout?.revision&&!s.pending;
}
function briefCurrent(s=session){return briefHasContent(s?.request_spec)&&briefRevisionCurrent(s);}
function briefState(){
 if(busy||session?.pending||session?.request_spec?.state==="updating")return "updating";
 if(session?.request_spec?.state==="stopped"||session?.scout?.status==="stopped")return "stopped";
 if(briefFailure?.sessionId===session?.id||session?.request_spec?.state==="failed")return "failed";
 return briefCurrent()?"current":"stale";
}
function ensureBriefHost(){
 let host=$("consultBriefHost");if(host)return host;
 host=document.createElement("section");host.id="consultBriefHost";host.className="consult-brief";host.hidden=true;host.setAttribute("aria-labelledby","consultBriefHeading");
 $("thread").after(host);
 host.addEventListener("click",event=>{
  const button=event.target.closest("button[data-brief-action]");if(!button||button.disabled)return;
  if(button.dataset.briefAction==="edit")openBriefEditor();
  if(button.dataset.briefAction==="stage")stageBriefCorrection();
  if(button.dataset.briefAction==="cancel"){
   if(briefEditor?.stagedText&&composerInputRevision===briefEditor.stagedComposerRevision&&$("message").value===briefEditor.stagedText)setComposerDraft(briefEditor.composerBefore);
   briefEditor=null;briefRenderKey="";renderBrief();resizeInput();controls();host.querySelector('[data-brief-action="edit"]')?.focus({preventScroll:true});
  }
 });
 host.addEventListener("input",event=>{
  if(event.target.id!=="consultBriefValue"||!briefEditor)return;
  briefEditor.values[briefEditor.field]=event.target.value;briefEditor.editVersion++;
  if(briefEditor.phase!=="pending")briefEditor.phase="editing";
  updateBriefNotice();syncDiscoveryControls();
 });
 host.addEventListener("change",event=>{
  if(event.target.id!=="consultBriefField"||!briefEditor)return;
  briefEditor.field=event.target.value;$("consultBriefValue").value=briefEditor.values[briefEditor.field];
  $("consultBriefValueLabel").textContent=briefLabels[briefEditor.field];
 });
 return host;
}

function briefStructureSignatures(spec){
 const texts=rows=>JSON.stringify(briefRows(rows).map(row=>row.text).sort());
 return {purposes:texts(spec?.purposes),requested_help:texts(spec?.requested_help),conditions:JSON.stringify(briefConditionLines(spec?.conditions).sort()),open_questions:JSON.stringify((Array.isArray(spec?.open_questions)?spec.open_questions:[]).filter(value=>typeof value==="string").slice().sort())};
}
function trackBriefStructuralChange(){
 const spec=session?.request_spec;
 if(busy||prepareBusy||briefFailure||!briefRevisionCurrent())return;
 if(!briefHasContent(spec)){briefChangeAnchor=null;briefChangeLabel="";return;}
 const completed=[...(session.messages||[])].reverse().find(message=>message.role==="assistant"&&message.status==="complete"&&message.kind!=="self_profile"&&message.audience!=="disclosed");
 if(!completed||typeof completed.turn_id!=="string"||typeof spec.source_turn_id!=="string"||!spec.source_turn_id)return;
 const signatures=briefStructureSignatures(spec),previous=briefChangeAnchor;
 if(!previous){briefChangeAnchor={sourceTurnId:spec.source_turn_id,completedTurnId:completed.turn_id,signatures};briefChangeLabel="";return;}
 const nextTurn=completed.turn_id!==previous.completedTurnId,newSource=spec.source_turn_id!==previous.sourceTurnId;
 if(nextTurn)briefChangeLabel="";
 if(newSource&&completed.turn_id===spec.source_turn_id){
  const changed=Object.keys(briefLabels).filter(key=>signatures[key]!==previous.signatures[key]);
  briefChangeLabel=changed.length?changed.map(key=>briefLabels[key]).join(" · ")+" 항목을 수정했어요.":"";
 }
 // Visible condition quotes count; other quote metadata, ordering and prepare revision alone do not.
 briefChangeAnchor={sourceTurnId:spec.source_turn_id,completedTurnId:completed.turn_id,signatures};
}
function newerAcceptedBriefForEditor(){
 const edit=briefEditor,spec=session?.request_spec;
 return !!edit&&edit.sessionId===session?.id&&!busy&&!briefFailure&&briefRevisionCurrent()&&typeof spec.source_turn_id==="string"&&!!spec.source_turn_id&&spec.source_turn_id!==edit.sourceTurnId&&(spec.source_revision||spec.revision)!==(edit.sourceRevision||edit.revision)&&session.messages?.some(message=>message.role==="assistant"&&message.turn_id===spec.source_turn_id&&message.status==="complete"&&message.kind!=="self_profile"&&message.audience!=="disclosed");
}

function updateBriefNotice(){
 const host=$("consultBriefHost");if(!host||host.hidden)return;
 const state=briefState(),editing=!!briefEditor,latestAccepted=newerAcceptedBriefForEditor();
 const text=state==="updating"?"이전 초안 · 새 내용을 반영하고 있어요.":state==="failed"?"이전 초안 · 변경을 반영하지 못했어요.":state==="stopped"?"수소문을 보류했어요.":editing?(latestAccepted?"새 초안이 도착했어요. 편집을 닫아 최신 내용을 확인하세요.":briefEditor.revision!==session?.request_spec?.revision?"이전 초안을 기준으로 편집 중이에요. 현재 대화와 함께 확인해 주세요.":briefEditor.phase==="staged"?"수정문을 입력창에 넣었어요. 확인한 뒤 보내기를 눌러 주세요.":"편집 중 · 아직 대화에 반영되지 않았어요."):state==="stale"?(session?.scout_recovery?.status==="unsupported"?"이전 검색 범위가 현재 자료에 없어 의뢰서 수정이 필요해요.":session?.request_spec?.stale_reason==="source_changed"?"등록 자료가 바뀌었어요. 의뢰서는 유지되며 같은 정보로 다시 수소문할 수 있어요.":"이전 초안 · 현재 대화에서 다시 확인해 주세요."):"대화에서 정리한 의뢰서 초안이에요.";
 host.querySelector(".consult-brief-status").textContent=text+(!editing&&state==="current"&&briefChangeLabel?" "+briefChangeLabel:"");
 const cancel=host.querySelector('[data-brief-action="cancel"]');if(cancel)cancel.textContent=latestAccepted?"편집 닫고 최신 초안 보기":"취소";
 const locked=busy||profileBusy||prepareBusy||uploading||!!session?.pending;
 host.querySelectorAll("[data-brief-action],#consultBriefField,#consultBriefValue").forEach(control=>{control.disabled=locked;});
 const stage=host.querySelector('[data-brief-action="stage"]');if(stage)stage.disabled=locked||!!profileUI?.isOpen();
}
function renderBrief(){
 const host=ensureBriefHost(),sid=session?.id||null,spec=session?.request_spec;
 if(sid!==briefSessionId){briefSessionId=sid;briefEditor=null;briefFailure=null;briefRenderKey="";briefChangeAnchor=null;briefChangeLabel="";host.replaceChildren();}
 if(briefFailure&&briefRevisionCurrent()&&(spec.revision!==briefFailure.revision||spec.source_turn_id!==briefFailure.sourceTurnId))briefFailure=null;
 if(briefEditor?.turnId&&!busy&&!session?.pending){
  const complete=briefEditor.editVersion===briefEditor.submittedVersion&&briefRevisionCurrent()&&spec.source_turn_id===briefEditor.turnId&&session.messages?.some(message=>message.role==="assistant"&&message.turn_id===briefEditor.turnId&&message.status==="complete");
  if(complete){briefEditor=null;briefFailure=null;briefRenderKey="";}
  else briefEditor.phase="failed";
 }
 trackBriefStructuralChange();
 const legacy=!!spec&&typeof spec.has_content!=="boolean"&&typeof spec.summary==="string"&&!!spec.summary.trim();
 host.hidden=!sid||(!briefHasContent(spec)&&!legacy&&!briefEditor);
 if(host.hidden){host.replaceChildren();briefRenderKey="";return;}
 if(briefEditor&&host.querySelector("#consultBriefEditor")){updateBriefNotice();syncDiscoveryControls();return;}
 const key=JSON.stringify([sid,spec]);
 if(key!==briefRenderKey){
  const fields=briefFields(spec),rows=Object.entries(fields).filter(([,value])=>value);
  host.innerHTML='<div class="consult-brief-heading"><h2 id="consultBriefHeading">의뢰서 초안</h2><button type="button" class="text-button" data-brief-action="edit">수정</button></div><p class="consult-brief-status" role="status"></p><dl class="consult-brief-fields">'+rows.map(([name,value])=>'<div><dt>'+esc(briefLabels[name])+'</dt><dd>'+esc(value)+'</dd></div>').join("")+'</dl>'+(legacy&&!rows.length?'<p class="consult-brief-legacy">'+esc(spec.summary)+'</p>':"")+currentScout();
  briefRenderKey=key;
 }
 updateBriefNotice();syncDiscoveryControls();
}
// Called only by explicit edit opening, never by brief refresh or input events.
function revealBriefEditorField(field){
 const rect=field.getBoundingClientRect(),viewport=window.visualViewport;
 const top=(viewport?.offsetTop||0)+16;
 let bottom=(viewport?.offsetTop||0)+(viewport?.height||window.innerHeight);
 const dock=document.querySelector(".composer-dock");
 if(dock){
  const position=getComputedStyle(dock).position,cover=dock.getBoundingClientRect();
  if((position==="sticky"||position==="fixed")&&cover.bottom>top&&cover.top<bottom&&cover.right>rect.left&&cover.left<rect.right)bottom=Math.min(bottom,cover.top);
 }
 bottom-=16;if(bottom<=top)return;
 const delta=rect.top<top||rect.height>bottom-top?rect.top-top:rect.bottom>bottom?rect.bottom-bottom:0;
 if(delta)window.scrollBy({top:delta,behavior:"instant"});
}
function openBriefEditor(){
 if(!session?.id||busy||profileBusy||prepareBusy||uploading||session.pending)return;
 const values=briefFields(session.request_spec);
 briefEditor={sessionId:session.id,revision:session.request_spec?.revision||null,sourceRevision:session.request_spec?.source_revision||null,sourceTurnId:session.request_spec?.source_turn_id||null,original:{...values},values:{...values},field:Object.keys(values).find(key=>values[key])||"purposes",phase:"editing",editVersion:0,submittedVersion:null,stagedText:null,composerBefore:"",turnId:null};
 const host=ensureBriefHost(),editor=document.createElement("div");editor.id="consultBriefEditor";editor.className="consult-brief-editor";
 editor.innerHTML='<label for="consultBriefField">고칠 항목</label><select id="consultBriefField">'+Object.entries(briefLabels).map(([key,label])=>'<option value="'+key+'"'+(key===briefEditor.field?' selected':'')+'>'+esc(label)+'</option>').join("")+'</select><label id="consultBriefValueLabel" for="consultBriefValue">'+esc(briefLabels[briefEditor.field])+'</label><textarea id="consultBriefValue" rows="3" maxlength="6000" aria-describedby="consultBriefEditHelp"></textarea><p id="consultBriefEditHelp">바꿀 항목만 고쳐 주세요. 내용을 비우면 그 항목을 지우는 요청으로 전달합니다. 조건의 필수·선호 구분도 함께 확인해 주세요.</p><div class="consult-brief-actions"><button type="button" class="secondary" data-brief-action="stage">입력창에 수정문 넣기</button><button type="button" class="text-button" data-brief-action="cancel">취소</button></div><p id="consultBriefEditError" role="alert" hidden></p>';
 host.querySelector('[data-brief-action="edit"]').hidden=true;host.insertBefore(editor,host.querySelector("#currentScout"));
 $("consultBriefValue").value=briefEditor.values[briefEditor.field];updateBriefNotice();syncDiscoveryControls();const field=$("consultBriefValue");field.focus({preventScroll:true});revealBriefEditorField(field);
}
function stageBriefCorrection(){
 const edit=briefEditor;if(!edit||edit.sessionId!==session?.id||busy||profileBusy||prepareBusy||uploading||session.pending||profileUI?.isOpen())return;
 const changed=Object.keys(briefLabels).filter(key=>edit.values[key]!==edit.original[key]);
 const failure=$("consultBriefEditError");failure.hidden=true;
 if(!changed.length){failure.textContent="바꾼 내용이 없어요.";failure.hidden=false;return;}
 const clearedAfterSubmission=!!edit.turnId&&!$("message").value;
 if(edit.stagedText&&$("message").value!==edit.stagedText&&!clearedAfterSubmission){failure.textContent="입력창의 수정문을 직접 고쳤어요. 그 내용을 먼저 보내거나, 편집을 취소한 뒤 다시 시작해 주세요.";failure.hidden=false;return;}
 const correction="의뢰서 수정 요청 (화면에서 편집한 내용)\n아래 항목만 변경하고, 나머지 목적과 조건은 유지해 주세요.\n\n"+changed.map(key=>"["+briefLabels[key]+"]\n기존: "+(edit.original[key]||"미기재")+"\n요청: "+(edit.values[key].trim()?edit.values[key]:"이 항목 삭제")).join("\n\n");
 const before=edit.stagedText?edit.composerBefore:$("message").value;
 const text=(before?before+"\n\n":"")+correction;
 if(text.length>$("message").maxLength){failure.textContent="수정문이 입력창의 허용 길이를 넘어요. 수정 내용을 줄여 주세요.";failure.hidden=false;return;}
 edit.composerBefore=before;edit.stagedText=text;edit.phase="staged";edit.turnId=null;
 setComposerDraft(text);edit.stagedComposerRevision=composerInputRevision;autoScroll=false;resizeInput();controls();updateBriefNotice();$("message").focus({preventScroll:true});
}
function beginBriefSubmission(payload){
 if(!briefEditor||briefEditor.sessionId!==payload.session_id||!briefEditor.stagedText)return null;
 const sameStaged=briefEditor.phase==="staged"&&payload.text===briefEditor.stagedText.trim();
 const sameRetry=briefEditor.phase==="failed"&&payload.text===briefEditor.submittedText;
 if(!sameStaged&&!sameRetry)return null;
 briefEditor.turnId=payload.turn_id;briefEditor.submittedText=payload.text;briefEditor.submittedVersion=briefEditor.editVersion;briefEditor.phase="pending";
 return briefEditor;
}
function failBriefSubmission(edit,sid){
 if(!session||session.id!==sid)return;
 briefFailure={sessionId:sid,revision:session.request_spec?.revision||null,sourceTurnId:session.request_spec?.source_turn_id||null};
 if(edit&&briefEditor===edit)edit.phase="failed";
}

async function prepareDiscovery(button,keyboard=false){
 if(!canPrepareDiscovery())return;
 const before=session,sid=before.id,recovery=recoverableScout(before)?before.scout_recovery:null,revision=recovery?.from_revision||before.discovery.revision,ticket=++prepareTicket;
 const current=()=>ticket===prepareTicket&&session===before&&session?.id===sid&&(recovery?session.scout_recovery?.id===recovery.id:session?.discovery?.revision===revision);
 const returnFocus=keyboard&&document.activeElement===button;let focusMoved=false;
 const focusElsewhere=e=>{if(e.target!==document.body&&!button.contains(e.target))focusMoved=true;};
 const pointerElsewhere=e=>{if(!button.contains(e.target))focusMoved=true;};
 const windowBlur=()=>{focusMoved=true;};
 document.addEventListener("focusin",focusElsewhere);document.addEventListener("pointerdown",pointerElsewhere);window.addEventListener("blur",windowBlur);
 let adopted=false,invalidated=false;prepareBusy=true;error();controls();button.disabled=true;button.textContent="관련 기록을 찾고 있어요…";
 try{
  const prepared=await api("/api/chat/prepare",{session_id:sid,discovery_revision:revision,...(recovery?{recovery_id:recovery.id}:{})});
  if(!current())return;
  if(prepared?.id!==sid||!(recovery?(prepared.scout_recovery?.id===recovery.id&&prepared.scout_recovery.from_revision===revision&&prepared.scout?.disclosed&&prepared.scout.requested_revision===prepared.scout_recovery.target_revision):(prepared.discovery?.revision===revision||prepared.scout?.disclosed&&prepared.scout.requested_revision===revision)))throw new Error("대화 조건이 바뀌었습니다. 현재 조건을 확인한 뒤 다시 수소문해 주세요.");
  session=prepared;animateScoutKey=session.id+":"+session.scout.revision;adopted=true;autoScroll=false;
 }catch(e){if(current()){error(e.message);if(["scout_source_changed","scout_source_unsupported"].includes(e.code)&&e.session?.id===sid&&e.session.request_spec?.source_turn_id===before.request_spec?.source_turn_id&&(e.session.scout_recovery?.from_revision===before.request_spec?.revision||recovery&&e.session.request_spec?.source_revision===before.request_spec?.source_revision)){session=e.session;adopted=true;autoScroll=false;}else if(((e.code==="model_response_unavailable"||e.code==="model_response_budget_exhausted")&&e.retry_available===false)||e.code==="discovery_not_ready"||e.message==="현재 조건을 새 메시지로 확인한 뒤 수소문을 눌러 주세요."){session.discovery={...session.discovery,lookup_ready:false};if(session.scout_recovery)session.scout_recovery={...session.scout_recovery,available:false};invalidated=true;}}}
 finally{
  document.removeEventListener("focusin",focusElsewhere);document.removeEventListener("pointerdown",pointerElsewhere);window.removeEventListener("blur",windowBlur);
  if(ticket===prepareTicket){
   prepareBusy=false;controls();
   if(adopted){render();}
   else if(current()){if(invalidated)render();else if(button.isConnected){button.disabled=!canPrepareDiscovery();button.textContent=scoutButtonLabel();}else render();}
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
 $("thread").innerHTML=messages.map(m=>m.role==="user"?'<article class="message user">'+esc(m.text)+(m.attachments?.length?'<div class="message-files">'+fileChips(m.attachments)+'</div>':"")+'</article>':'<article class="message assistant'+(m.status==="error"?' error-message':'')+'"><div class="message-meta"><span class="avatar"><span class="susomun-ci" aria-hidden="true"><span class="susomun-ci-h">H</span></span></span><span>'+esc(responseModelLabel(m))+'</span>'+(m.historical_assistant?'<span class="response-note">이전 조회</span>':'')+'</div><div class="message-body">'+formatted(m.text||"")+'</div>'+(m.status==="error"?'<p class="response-error">'+esc(m.error||"응답이 중단됐어요. 다시 시도할 수 있습니다.")+'</p><button class="retry" data-action="retry" data-id="'+esc(m.turn_id)+'">다시 시도</button>':m.status==="cancelled"?'<p class="response-note">응답을 중지했어요. 위 내용은 완성되지 않은 답변입니다.</p>':"")+(m.kind==="self_profile"?'<button type="button" class="text-button" data-action="profile-receipt" data-version="'+esc(m.profile_receipt?.version??"")+'">'+(m.profile_receipt?"변경 보기":"내 프로필 열기")+'</button>':"")+'</article>').join("");
 if(busy)$("thread").innerHTML+='<article class="message assistant"><div class="message-meta"><span class="avatar"><span class="susomun-ci" aria-hidden="true"><span class="susomun-ci-h">H</span></span></span><span>'+esc("응답 처리 중")+'</span></div><div class="message-body">'+(streamText?formatted(streamText):'<span class="typing">답변을 준비하고 있어요</span>')+'</div></article>';
 renderBrief();
 renderCandidates();controls();drawController?.refreshBoundary();scrollBottom();
}

const canPropose=c=>Boolean(c)&&c.proposal_allowed!==false&&!c.lookup_only;
function checkProposalSelection(ids){
 if(!Array.isArray(ids)||!ids.length)throw new Error("현재 근거로 제안할 인물을 선택해 주세요.");
 for(const id of ids){const c=session?.result?.candidates.find(x=>x.id===id);if(!canPropose(c))throw new Error(c?.proposal_unavailable_reason||"현재 시연 범위의 인물과 근거로 다시 찾아 주세요.");}
}
function extraRecordSources(e){
 return (Array.isArray(e.metadata_sources)?e.metadata_sources:[]).filter(x=>safeUrl(x.url)).map(x=>'<p><a href="'+esc(x.url)+'" target="_blank" rel="noopener noreferrer">'+esc(x.title||x.label||(/correction/i.test(x.basis||x.type||'')?'정정 출처':'추가 확인 출처'))+' ↗</a></p>').join('');
}

function cardCapability(c){
 const profile=c.profile||{},values=[profile.tagline,...(Array.isArray(profile.skills)?profile.skills:[]),...(Array.isArray(profile.topics)?profile.topics:[]).map(t=>t?.name)];
 // Select a complete registered field, never a clipped sentence or AI reason.
 // Twenty full-width glyphs fit the mobile card's 242px line at 12px.
 return values.filter(v=>typeof v==="string").map(v=>v.replace(/\s+/g," ").trim()).find(v=>v&&Array.from(v).length<=20)||"등록 이력과 근거 보기";
}
function renderCandidates(){
 const zone=$("proposalZone");
 const disclosed=session?.scout?.disclosed===true&&session.scout.revision===session.discovery?.revision;
 zone.hidden=!session?.ready||busy||!disclosed;
 if(zone.hidden){drawEpoch++;drawController?.dispose();drawController=null;drawRenderKey="";zone.replaceChildren();return;}
 const rows=session.result?.candidates||[],key=session.id+":"+session.scout.revision;
 const renderKey=key+":"+JSON.stringify(rows);
 if(renderKey===drawRenderKey)return;
 drawRenderKey=renderKey;const epoch=++drawEpoch;
 drawController?.dispose();drawController=null;
 const animate=animateScoutKey===key;animateScoutKey="";
 zone.classList.add("scout-draw-zone");
 zone.innerHTML='<div class="collection-heading"><div><h2>현재 요청과 연결된 사람</h2><p>카드를 누르면 자세한 이력과 근거를 볼 수 있어요.</p></div><span class="collection-count">'+rows.length+'</span></div><div id="scoutDrawHost"></div>';
 if(!rows.length){$("scoutDrawHost").textContent=session.result?.empty_message||'현재 자료에서 요청을 뒷받침하는 인물을 찾지 못했어요.';if(animate)zone.scrollIntoView({block:"start",behavior:"instant"});return;}
 const records=rows.map(c=>({id:c.id,name:c.profile?.display_name||c.name,portrait:/^\/portraits\/[A-Za-z0-9_.-]+\.(png|jpe?g|webp)$/.test(c.profile?.portrait?.path||'')?c.profile.portrait.path:'',capability:cardCapability(c)}));
 import('/draw.js').then(({initDraw})=>{
  if(epoch!==drawEpoch||drawRenderKey!==renderKey||zone.hidden)return;
  const dock=document.querySelector(".composer-dock");
  drawController=initDraw($("scoutDrawHost"),{bottomBoundary:dock,onBoundaryFit:fits=>dock?.classList.toggle("scout-dock-in-flow",!fits),quiet:()=>!animate||RndCraft.quiet(),onDetail:record=>showPerson(record.id,document.activeElement).catch(exc=>error(exc.message))});
  drawController.show(records,key);
  if(animate)zone.scrollIntoView({block:"start",behavior:"instant"});
 }).catch(()=>{if(epoch===drawEpoch){$("scoutDrawHost").textContent='인물 카드를 불러오지 못했어요. 화면을 새로고침해 주세요.';}});
}
new MutationObserver(()=>drawController?.setQuiet()).observe(document.body,{attributes:true,attributeFilter:['class']});
function updateHistory(){if(!session)return;const row={id:session.id,title:session.original.slice(0,60),updated:session.updated,model_id:session.model_id,model_selection_origin:selectionOrigin(session.model_selection_origin)};history=[row,...history.filter(s=>s.id!==row.id)];}
async function send(payload,submission=null){
 if(composerSendLocked()){restoreComposerDraft(submission);return;}
 const repeated=!!session?.messages.some(m=>m.turn_id===payload.turn_id&&m.role==="user"),epoch=modelSelectionEpoch;
 payload={...payload,model_selection_origin:selectionOrigin(payload.model_selection_origin)};
 const briefSubmission=beginBriefSubmission(payload),briefSubmissionSession=payload.session_id;
 prepareTicket++;error();streamText="";busy=true;autoScroll=true;controller=new AbortController();retryPayload=payload;
 if(!session?.messages.some(m=>m.turn_id===payload.turn_id&&m.role==="user"))optimistic={role:"user",text:payload.text||"첨부한 자료를 함께 검토해 주세요.",attachments:files};
 render();let accepted=false,finished=false;
 try{
  // Only a new request with a known automatic guide choice checks recovery.
  // Replay uses its original model and origin; no old input is auto-resubmitted.
  if(!repeated&&payload.model_id==="guide"&&payload.model_selection_origin==="automatic"){
   if(!await refreshModelOptions("/api/chat/models"))throw new Error("모델 목록이 갱신 중입니다. 선택 상태를 확인한 뒤 보내 주세요.");
   const next=resolveModelSelection(catalog,modelDefault,payload.model_id,payload.model_selection_origin);
   payload={...payload,model_id:next.id,model_selection_origin:next.origin};retryPayload=payload;
   if(epoch===modelSelectionEpoch){selectedModel=next.id;modelSelectionOrigin=next.origin;renderModelSelect();}
  }
  const response=await fetch("/api/chat",{method:"POST",headers:{"Content-Type":"application/json","X-RnDplz-Token":token},body:JSON.stringify(payload),signal:controller.signal});
  if(!response.ok){const data=await response.json();throw new Error(data.error||"대화를 시작하지 못했어요.");}
  const reader=response.body.getReader(),decoder=new TextDecoder();let buffer="";
  const event=line=>{if(!line.trim())return;const data=JSON.parse(line);
   if(data.type==="start"){session=data.session;accepted=true;updateHistory();optimistic=null;if(submission)files=files.filter(f=>!submission.attachmentIds.includes(f.id));renderFiles();window.history.replaceState(null,"","/?chat="+session.id);}
   if(data.type==="delta")streamText+=data.text;
   if(data.type==="done"||data.type==="error"){session=data.session;finished=true;streamText="";optimistic=null;updateHistory();if(data.type==="error")error(data.error);}
   render();
  };
  while(true){const {value,done}=await reader.read();if(done)break;buffer+=decoder.decode(value,{stream:true});let end;while((end=buffer.indexOf("\n"))>=0){event(buffer.slice(0,end));buffer=buffer.slice(end+1);}}
  buffer+=decoder.decode();if(buffer.trim())event(buffer);
  if(!finished)throw new Error("응답 연결이 끝났어요. 저장된 대화를 확인하고 다시 시도해 주세요.");
 }catch(e){
  if(finished){if(e.name!=="AbortError")error(e.message);return;}
  if(!accepted)restoreComposerDraft(submission);
  failBriefSubmission(briefSubmission,briefSubmissionSession);
  if(e.name==="AbortError"){error("응답을 중지하고 있어요…");}
  else error(e.message);
  if(accepted&&session){
   for(let i=0;i<30;i++){
    const saved=await api("/api/chat/session?id="+session.id).catch(()=>null);
    if(saved&&!saved.pending){session=saved;break;}
    await new Promise(resolve=>setTimeout(resolve,700));
   }
   if(session.pending)error("모델 응답 정리를 기다리고 있어요. 잠시 후 이전 대화에서 다시 열어 주세요.");
   else if(e.name==="AbortError"&&session.messages?.some(m=>m.role==="assistant"&&m.turn_id===payload.turn_id&&m.status==="cancelled")&&$("composerError").textContent==="응답을 중지하고 있어요…")error();
  }
 }finally{busy=false;optimistic=null;streamText="";controller=null;resizeInput();render();if(!session?.pending)$("message").focus();}
}
function newChat(){if(composerClientLocked())return;prepareTicket++;profileUI.close();session=null;modelSelectionEpoch++;if(modelSelectionOrigin!=="explicit"){selectedModel="";modelSelectionOrigin="automatic";syncModelSelection();renderModelSelect();}files=[];optimistic=null;retryPayload=null;$("message").value="";window.history.replaceState(null,"","/");error();autoScroll=true;renderFiles();render();resizeInput();$("message").focus();}
function dataUrl(file){return new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result.split(",")[1]);reader.onerror=()=>reject(new Error("파일을 읽지 못했어요."));reader.readAsDataURL(file);});}
async function upload(list){
 if(busy||profileBusy||uploading||prepareBusy)return;error();if(files.length+list.length>4){error("파일은 한 번에 4개까지 첨부할 수 있어요.");return;}
 try{for(const file of list){if(file.size>(publicMode?1024*1024:8*1024*1024))throw new Error(publicMode?"공개 시연은 파일당 1MB까지 첨부할 수 있어요.":"파일당 8MB까지 첨부할 수 있어요.");files.push({id:"pending-"+crypto.randomUUID(),name:file.name,file});}}
 catch(e){error(e.message);}finally{$("fileInput").value="";renderFiles();}
}
async function submitComposer(){
 if(composerSendLocked()||composerComposing)return;
 const text=$("message").value.trim();if(!text&&!files.length)return;
 if(profileUI.shouldHandle(text)){
  if(files.some(f=>!f.file)){error("앞서 일반 대화용으로 전송한 파일은 제거하고 프로필용 파일을 다시 선택해 주세요.");return;}
  profileSubmission={text:$("message").value,revision:composerInputRevision,ids:files.map(f=>f.id)};
  try{await profileUI.submit(text,files.map(f=>f.file));}catch(e){error(e.message);}finally{if(!profileUI.hasPendingRequest())profileSubmission=null;render();resizeInput();}
  return;
 }
 const submittedFiles=[...files],submission=consumeComposerDraft();
 const payload={text,session_id:session?.id,attachments:[],model_id:selectedModel,model_selection_origin:modelSelectionOrigin,turn_id:crypto.randomUUID()};
 uploading=true;resizeInput();
 try{
  for(let i=0;i<submittedFiles.length;i++){const f=submittedFiles[i];if(f.file){const uploaded=await api("/api/attachments",{name:f.name,data:await dataUrl(f.file)});submittedFiles[i]=uploaded;files=files.map(item=>item.id===f.id?uploaded:item);renderFiles();}}
 }catch(e){restoreComposerDraft(submission);error(e.message);resizeInput();return;}finally{uploading=false;controls();}
 submission.attachmentIds=submittedFiles.map(f=>f.id);
 await send({...payload,attachments:[...submission.attachmentIds]},submission);
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
 const profileNotice=!historical&&candidate?.profile_only?'<p class="subtle small">전체 등록 이력 · 이번 조건의 수행 근거로 확인된 목록 아님</p>':'';
 const reasonDetails=typeof candidate?.reason==="string"&&candidate.reason.trim()?'<section class="detail-record"><h3>이번 조회 설명</h3><p>'+esc(candidate.reason)+'</p></section>':'';
 $("detailContent").innerHTML=historicalNotice+profileNotice+(profile||'<h2>'+esc(p.name)+'</h2><p class="subtle">'+esc(p.org)+'</p>')+reasonDetails+'<p class="small">'+(historical?"저장된 응답의 일부 근거이며 현재 전체 등록 이력이 아닙니다.":p.virtual?"시연용 가상 인물":p.evidence?.length?"전체 등록 이력 · 개인 수행·본인 확인·연락 의향 미확인":"등록 프로필 · 연결된 수행 기록 없음")+'</p>'+(p.evidence||[]).map(e=>'<section class="detail-record"><h3>'+esc(e.title)+'</h3><p>'+esc(e.date)+" · "+esc(e.role)+" · "+esc(e.scope)+'</p><p>'+esc(e.boundary)+'</p>'+(safeUrl(e.url)?'<a href="'+esc(e.url)+'" target="_blank" rel="noopener noreferrer">원문 출처 ↗</a>':"")+extraRecordSources(e)+'</section>').join("");
 if(candidate&&canPropose(candidate))$("detailContent").insertAdjacentHTML("beforeend",'<button class="primary" data-action="letter" data-id="'+esc(candidate.id)+'">편지 쓰기 ↗</button>');
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
  if(profileSubmission){if(composerInputRevision===profileSubmission.revision&&$("message").value===profileSubmission.text)setComposerDraft("");files=files.filter(f=>!profileSubmission.ids.includes(f.id));renderFiles();profileSubmission=null;}
  autoScroll=false;render();resizeInput();
 }});
window.addEventListener("rndplz:before-account-navigation",event=>{
 const state=profileUI?.accountNavigationState();event.detail.checkedScopes.push("chat");
 if(!state||accountNavigationPending||busy||profileBusy||uploading||prepareBusy||session?.pending||$("letterDialog").open||state.blocked){
  event.preventDefault();event.detail.message="진행 중인 대화·프로필·제안 작업의 결과를 먼저 확인해 주세요.";return;
 }
 if($("message").value.trim()||files.length||briefEditor||state.dirty)event.detail.dirty=true;
});
window.addEventListener("rndplz:account-navigation",event=>{
 accountNavigationPending=event.detail?.phase!=="cancel";
 if(event.detail?.phase==="invalidate"){
  accountInvalidated=true;prepareTicket++;modelSelectionEpoch++;controller?.abort();token="";
 }
 controls();
});
$ ("profileButton").addEventListener("click",async()=>{if(busy||profileBusy||prepareBusy)return;error();autoScroll=false;await profileUI.open();render();$("profileChatHost").scrollIntoView({block:"start",behavior:"instant"});});
$ ("chatForm").addEventListener("submit",e=>{e.preventDefault();submitComposer();});
$ ("message").addEventListener("input",()=>{composerInputRevision++;resizeInput();});
$ ("message").addEventListener("compositionstart",()=>{composerComposing=true;composerInputRevision++;});
$ ("message").addEventListener("compositionend",()=>{composerComposing=false;composerInputRevision++;controls();});
$ ("message").addEventListener("keydown",e=>{if(e.key==="Enter"&&!e.shiftKey){if(e.isComposing||composerComposing||e.keyCode===229)return;e.preventDefault();if(!composerSendLocked()&&!$("sendButton").disabled)$("chatForm").requestSubmit();}});
$ ("stopButton").addEventListener("click",()=>controller?.abort());
$ ("newButton").addEventListener("click",newChat);
$ ("attachButton").addEventListener("click",()=>$ ("fileInput").click());
$ ("fileInput").addEventListener("change",e=>upload([...e.target.files]));
$ ("modelSelect").addEventListener("change",e=>{const chosen=catalog.find(m=>m.id===e.target.value);if(!chosen?.enabled){$("modelSelect").value=selectedModel;if(chosen?.provider==="bridge"){toast("이 Gemma는 연결 대기 중입니다. 사용 가능한 모델을 선택해 주세요.");return;}$("provider").value=chosen?.provider||"openai";modal("settingsDialog");return;}selectedModel=chosen.id;modelSelectionOrigin="explicit";modelSelectionEpoch++;controls();error();});
$ ("settingsButton").addEventListener("click",()=>modal("settingsDialog"));
$ ("historyButton").addEventListener("click",()=>{$("historyList").innerHTML=history.length?history.map(h=>'<button class="history-item" data-action="history" data-id="'+h.id+'">'+esc(h.title)+'<small>'+new Date(h.updated).toLocaleString("ko-KR")+'</small></button>').join(""):'<p class="subtle">첫 대화를 시작해 보세요.</p>';modal("historyDialog");});
$ ("refreshModels").addEventListener("click",async()=>{try{if(!await refreshModelOptions())return;toast("사용 가능한 모델 목록을 갱신했어요.");}catch(e){error(e.message);}});
$ ("configForm").addEventListener("submit",async e=>{e.preventDefault();$("saveConfig").disabled=true;$("configMessage").textContent="";try{const provider=$("provider").value,epoch=modelSelectionEpoch,ticket=++modelCatalogTicket;const data=await api("/api/chat/configure",{provider,model:$("apiModel").value,key:$("apiKey").value});$("apiKey").value="";if(epoch===modelSelectionEpoch){selectedModel=provider;modelSelectionOrigin="explicit";modelSelectionEpoch++;}if(ticket===modelCatalogTicket)modelOptions(data);else{renderModelSelect();controls();}$("configMessage").textContent="설정을 저장했어요. 다음 메시지에는 현재 선택한 모델을 사용합니다.";}catch(e){$("configMessage").textContent=e.message;}finally{$("saveConfig").disabled=false;}});
$ ("draftButton").addEventListener("click",()=>saveLetter("draft"));
$ ("proposeButton").addEventListener("click",()=>saveLetter("sent"));
document.addEventListener("click",async e=>{const button=e.target.closest("button");if(!button)return;if(button.classList.contains("close")){button.closest("dialog").close();return;}const action=button.dataset.action,id=button.dataset.id;if(!action||composerClientLocked())return;
 try{
  if(action==="profile-receipt"){autoScroll=false;if(button.dataset.version)await profileUI.showReceipt(Number(button.dataset.version));else await profileUI.open();render();$("profileChatHost").scrollIntoView({block:"start",behavior:"instant"});}
  else if(action==="remove-file"){if(composerSendLocked())return;files=files.filter(f=>f.id!==id);renderFiles();}
  else if(action==="preview-file"){const pending=files.find(f=>f.id===id&&f.file);if(pending){$("fileTitle").textContent=pending.name;$("fileInfo").textContent="전송 대기 · 메시지를 보낼 때 일반 대화 또는 프로필 용도로 처리합니다.";$("filePreview").textContent="파일 크기: "+pending.file.size.toLocaleString()+" bytes";modal("fileDialog");return;}const item=await api("/api/attachment?id="+id);$("fileTitle").textContent=item.name;$("fileInfo").textContent=item.kind==="image"?"이미지 지원 모델에서만 대화에 사용할 수 있어요.":"읽은 텍스트 "+item.characters.toLocaleString()+"자"+(item.truncated?" · 길이 제한으로 앞부분만 읽었습니다.":"");$("filePreview").innerHTML=item.image?'<img alt="첨부 이미지" src="data:'+item.mime+';base64,'+item.image+'">':'<pre>'+esc(item.text)+'</pre>';modal("fileDialog");}
  else if(action==="history"){prepareTicket++;profileUI.close();const epoch=modelSelectionEpoch,previousSessionId=session?.id;session=await api("/api/chat/session?id="+id);restoreModelSelection(session,epoch);if(session.id!==previousSessionId){files=[];setComposerDraft("");}renderFiles();$("historyDialog").close();window.history.replaceState(null,"","/?chat="+id);autoScroll=true;render();}
  else if(action==="retry"){const user=session.messages.find(m=>m.turn_id===id&&m.role==="user");const assistant=session.messages.find(m=>m.turn_id===id&&m.role==="assistant");const modelId=assistant?.model_id||session.model_id,origin=selectionOrigin(user.model_selection_origin??assistant?.model_selection_origin);await send({text:user.input_text??user.text,session_id:session.id,attachments:(user.attachments||[]).map(f=>f.id),model_id:modelId,model_selection_origin:origin,turn_id:id,...(user.person_id?{person_id:user.person_id}:{})});}
  else if(action==="prepare")await prepareDiscovery(button,e.detail===0);
  else if(action==="person-select"){const choice=session.result?.choices?.find(c=>c.id===id);if(!choice)throw new Error("표시된 인물을 다시 선택해 주세요.");await send({text:choice.name+"의 이력 보여줘",person_id:id,session_id:session.id,model_id:selectedModel,model_selection_origin:modelSelectionOrigin,turn_id:crypto.randomUUID()});}
  else if(action==="person")await showPerson(id,button);
  else if(action==="letter")await openLetter([id]);
  else if(action==="route-letter"){const ids=session?.result?.intent==="person_lookup"?[]:(session?.result?.candidates||[]).filter(canPropose).map(c=>c.id);if(ids.length)await openLetter(ids);}
 }catch(e){error(e.message);button.disabled=false;}
});
window.addEventListener("scroll",()=>{autoScroll=document.documentElement.scrollHeight-innerHeight-scrollY<160;},{passive:true});
(async()=>{try{const ticket=++modelCatalogTicket,data=await api("/api/chat/bootstrap");token=data.token;history=data.history;if(ticket===modelCatalogTicket)modelOptions(data);const id=new URLSearchParams(location.search).get("chat");if(id){const epoch=modelSelectionEpoch;session=await api("/api/chat/session?id="+encodeURIComponent(id));restoreModelSelection(session,epoch);}render();resizeInput();if(new URLSearchParams(location.search).has("settings"))modal("settingsDialog");}catch(e){error(e.message);}})();
