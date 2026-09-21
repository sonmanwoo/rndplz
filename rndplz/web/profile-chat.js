/* Private profile editing in the conversation. No model or public-person writes. */
(() => {
  "use strict";
  const FIELDS = {name:"표시 이름",organization:"소속·부서",role:"현재 역할",bio:"짧은 소개",skills:"전문분야",interests:"관심 분야"};
  const CAREER = {title:"경력·프로젝트명",organization:"소속·조직",period:"기간",role:"맡은 역할",description:"한 일과 적용 조건"};
  const text = value => value == null ? "" : typeof value === "string" ? value : JSON.stringify(value, null, 2);
  const copy = value => JSON.parse(JSON.stringify(value));
  const uid = () => crypto.randomUUID().replaceAll("-", "");
  const cleanCareer = value => ({...(value.id ? {id:value.id} : {}),...Object.fromEntries(Object.keys(CAREER).map(k => [k,value[k] || ""]))});
  const eligible = row => ["pending","deferred","excluded"].includes(row.decision);
  function el(tag, cls, value) { const n = document.createElement(tag); if(cls)n.className="profile-chat-"+cls; if(value!==undefined)n.textContent=text(value); return n; }
  function option(value,label) { const n=el("option",null,label); n.value=value; return n; }
  function create({host,getToken=()=>"",getSessionId=()=>null,onSession=()=>{},onBusy=()=>{},onError=()=>{},onClose=()=>{}}) {
    if(!host)throw new Error("프로필 표시 영역이 필요합니다.");
    const prefix="profile-chat-"+uid(), selected=new Map(), cancelActions=new Set(["cancel-editor","cancel-selection","cancel-delete"]);
    let view=null,opened=false,busy=false,activeMutation=false,uncertain=null,error=null,conflict=null,editor=null,editorRevision=0,selectionRevision=0;
    let accountNavigationPending=false,accountInvalidated=false;
    let generation=0,readTicket=0,sourceTicket=0,focusReceipt=null,reviewVisible=false,reply="",deleteSource=null,errorRequest=null;
    const wrap=el("section","panel"),status=el("p","status"),errors=el("div","error"),summary=el("div","summary"),editorBox=el("details","editor"),editorBody=el("div","editor-body"),all=el("details","all"),allBody=el("div","all-body"),review=el("section","review"),receipts=el("section","receipts"),conflicts=el("section","conflict");
    wrap.setAttribute("aria-label","대화 속 내 프로필");status.setAttribute("role","status");status.setAttribute("aria-live","polite");errors.setAttribute("role","alert");errors.tabIndex=-1;
    editorBox.append(el("summary",null,"항목 직접 수정"),editorBody);all.append(el("summary",null,"전체 정보와 자료 펼치기"),allBody);
    wrap.append(status,errors,summary,editorBox,conflicts,review,receipts,all);host.append(wrap);host.hidden=true;
    const sourceDialog=el("dialog","source-dialog"),sourceHeading=el("h2",null,"읽은 자료"),sourceInfo=el("p","note"),sourceText=el("pre","source-text");
    let sourceOpener=null;
    sourceDialog.append(sourceHeading,sourceInfo,sourceText,button("닫기",()=>sourceDialog.close(),"close-source",true));host.append(sourceDialog);
    sourceDialog.addEventListener("close",()=>{sourceTicket++;sourceText.textContent="";if(opened&&sourceOpener?.isConnected&&!sourceOpener.disabled)sourceOpener.focus();});
    function button(label,fn,action,free=false) { const b=el("button","button",label);b.type="button";b.dataset.profileAction=action;if(!free)b.dataset.profileLock="";b.addEventListener("click",event=>{if(cancelActions.has(action)&&(activeMutation||uncertain)){showError(new Error("저장 결과를 아직 확인하지 못했습니다. 입력과 선택은 유지하며, 이 작업을 취소한 것은 아닙니다."));return;}fn(event);});return b; }
    function field(label,input,key) { const box=el("label","field",label);input.id=prefix+"-"+key;input.dataset.profileKey=key;box.htmlFor=input.id;box.append(input);return box; }
    function note(value) { return el("p","note",value); }
    function actions(...nodes) { const n=el("div","actions");n.append(...nodes);return n; }
    function notify(fn,arg) { try{fn(arg);}catch(_){} }
    function controls() {
      for(const n of wrap.querySelectorAll("[data-profile-lock]"))n.disabled=accountNavigationPending||busy||!!uncertain||!view;
      for(const n of wrap.querySelectorAll('[data-profile-action="apply"], [data-profile-action="save-editor"]'))n.disabled=accountNavigationPending||busy||!!uncertain||!!conflict||!view;
      for(const n of wrap.querySelectorAll('[data-profile-action="cancel-editor"], [data-profile-action="cancel-selection"], [data-profile-action="cancel-delete"]'))n.disabled=activeMutation||!!uncertain;
      wrap.setAttribute("aria-busy",String(busy));notify(onBusy,accountNavigationPending||busy||!!uncertain);
      status.textContent=busy?"프로필 요청을 처리하고 있어요. 저장 완료 응답을 기다려 주세요.":error||uncertain||conflict?"":reply;
    }
    function showError(e) { error=e;notify(onError,e);paintError(); }
    function paintError() {
      errors.replaceChildren();errors.hidden=!error&&!uncertain;
      if(error)errors.append(el("p",null,error.message));
      if(errorRequest?.body.text)errors.append(note("처리하려던 요청: "+errorRequest.body.text));
      if(uncertain){errors.append(note("저장 결과가 불명확합니다. 입력과 요청을 그대로 두었어요. 같은 요청으로 확인하면 중복 적용을 막을 수 있습니다."),button("같은 요청으로 다시 확인",()=>perform(uncertain),"retry",true));}
      else if(error&&!view)errors.append(button("프로필 다시 읽기",()=>open(),"retry-read",true));
      controls();
    }
    function profileCommand(value) {
      if(!value||typeof value!=="object"||Array.isArray(value)||!["set","add","remove"].includes(value.action)||!Object.prototype.hasOwnProperty.call(FIELDS,value.field)||typeof value.value!=="string")return null;
      return {action:value.action,field:value.field,value:value.value};
    }
    async function api(path,body) {
      if(accountNavigationPending||accountInvalidated)throw new Error("계정이 바뀌고 있어요. 새 화면에서 다시 확인해 주세요.");
      let response,data;
      try { response=await fetch(path,{credentials:"same-origin",cache:"no-store",...(body===undefined?{}:{method:"POST",headers:{"Content-Type":"application/json","X-Rndplz-Token":getToken()||""},body:JSON.stringify(body)})}); }
      catch(_){const e=new Error("연결 결과를 확인하지 못했습니다. 작성 중인 내용은 유지했습니다.");e.uncertain=body!==undefined;throw e;}
      try{data=await response.json();}catch(_){const e=new Error("응답 내용을 확인하지 못했습니다. 작성 중인 내용은 유지했습니다.");e.status=response.status;e.uncertain=body!==undefined;throw e;}
      if(accountInvalidated)throw new Error("이전 계정의 응답을 적용하지 않았습니다.");
      if(!response.ok){const e=new Error(typeof data.error==="string"?data.error:"프로필 요청을 처리하지 못했습니다.");e.status=response.status;e.code=data.code;e.uncertain=body!==undefined&&response.status>=500;if(response.status===409&&body?.action==="text")e.profileCommand=profileCommand(data.profile_command);throw e;}
      return data;
    }
    function profileView(data) { const v=data.profile_view||data;if(!v.profile||!Number.isSafeInteger(v.profile.version))throw new Error("프로필 저장 버전을 확인하지 못했습니다.");return v; }
    function targetValue(v,key) { return key.startsWith("career:")?v.profile.careers.find(c=>c.id===key.slice(7))||null:v.profile.fields[key]||""; }
    function same(a,b) { return JSON.stringify(a)===JSON.stringify(b); }
    function prune(previous,next) {
      const available=new Map((next.sources||[]).map(s=>[s.id,s]));
      const gone=new Set((previous?.sources||[]).filter(s=>!available.has(s.id)||["deleted","deleting"].includes(available.get(s.id).status)).map(s=>s.id));
      if(editor&&(previous?.profile.provenance?.[editor.key]?.source_ids||[]).some(id=>gone.has(id)))editor=null;
      const valid=new Map((next.suggestions||[]).map(p=>[p.id,p]));
      for(const [id] of selected){const p=valid.get(id);if(!p||!eligible(p)||gone.has(p.source_id))selected.delete(id);}
      if(deleteSource&&!available.has(deleteSource.id))deleteSource=null;
      if(sourceDialog.open&&gone.size){sourceTicket++;sourceText.textContent="";sourceDialog.close();}
    }
    function adopt(next) {
      if(view&&next.profile.version<view.profile.version)return false;
      prune(view,next);view=next;return true;
    }
    function captureFocus() { const n=document.activeElement;if(!wrap.contains(n))return null;return {key:n.dataset.profileKey,action:n.dataset.profileAction,id:n.closest("[data-suggestion-id]")?.dataset.suggestionId,start:n.selectionStart,end:n.selectionEnd,node:n}; }
    function restoreFocus(f) {
      if(!f||!opened||!(document.activeElement===document.body||document.activeElement===f.node))return;
      const nodes=[...wrap.querySelectorAll("[data-profile-key],[data-profile-action]")];
      const n=nodes.find(n=>(f.key?n.dataset.profileKey===f.key:n.dataset.profileAction===f.action)&&(!f.id||n.closest("[data-suggestion-id]")?.dataset.suggestionId===f.id));
      if(n&&!n.disabled){n.focus({preventScroll:true});if(typeof f.start==="number"&&typeof n.setSelectionRange==="function")try{n.setSelectionRange(f.start,f.end);}catch(_){}}
    }
    function paint() {
      if(!opened)return;const focus=captureFocus(),expanded=new Set([...wrap.querySelectorAll("details[data-profile-open]")].filter(n=>n.open).map(n=>n.dataset.profileOpen));paintError();if(!view)return;
      paintSummary();paintEditor();paintConflict();paintReview();paintReceipts();paintAll();for(const n of wrap.querySelectorAll("details[data-profile-open]"))n.open=expanded.has(n.dataset.profileOpen);controls();restoreFocus(focus);
    }
    function newRequest(action,payload={},extra={}) {
      const session=getSessionId();return {body:{action,session_id:session||undefined,turn_id:uid(),payload:{...payload,base_version:view.profile.version,request_id:uid()},...extra},session,editRevision:editorRevision,selectionRevision,epoch:generation};
    }
    async function perform(request) {
      if(busy)return null;busy=true;activeMutation=true;error=null;errorRequest=null;controls();paintError();let data=null;
      try {
        const response=await api("/api/self-profile/chat",request.body);let next;try{next=profileView(response);}catch(e){e.uncertain=true;throw e;}data=response;uncertain=null;adopt(next);
        if((getSessionId()||null)===(request.session||null)&&data.session)notify(onSession,data.session);
        reply=typeof data.reply==="string"?data.reply:"프로필 요청을 확인했습니다.";
        if(data.receipt?.version!=null)focusReceipt=data.receipt.version;
        if(["save","text"].includes(request.body.action)){
          if(request.editRevision===editorRevision)editor=null;
          if(request.selectionRevision===selectionRevision&&request.body.action==="save"&&request.body.payload.decisions?.length){for(const item of request.body.payload.decisions)selected.delete(item.id);reviewVisible=(view.suggestions||[]).some(eligible);}
        }
        if(request.body.action==="suggest")reviewVisible=true;
        if(request.body.action==="source-action"){deleteSource=null;sourceTicket++;sourceText.textContent="";if(sourceDialog.open)sourceDialog.close();}
        if(request.body.action==="upload")all.open=true;
        conflict=null;
      } catch(e) {
        errorRequest=request;
        if(e.uncertain)uncertain=request;else uncertain=null;
        if(e.status===409)conflict={base:copy(view),latest:null,choices:new Map(),request,command:e.profileCommand||null,rows:[]};
        showError(e);
      } finally {activeMutation=false;busy=false;paint();controls();}
      if(data&&request.after&&request.epoch===generation&&opened)await request.after(data);
      return data;
    }
    function mutation(action,payload={},extra={}) {
      if(busy||uncertain)return Promise.resolve(null);
      if(conflict){showError(new Error("최신 저장값과 작성 중인 변경을 먼저 비교해 주세요."));return Promise.resolve(null);}
      if(action==="undo"&&(editor||[...selected.values()].some(s=>s.checked))){showError(new Error("작성 중인 변경을 먼저 저장하거나 취소한 뒤 되돌려 주세요. 현재 입력은 유지했습니다."));return Promise.resolve(null);}
      return perform(newRequest(action,payload,extra));
    }
    async function read({preserve=true}={}) {
      const ticket=++readTicket,e=generation;busy=true;controls();
      try {
        const data=await api("/api/self-profile");if(ticket!==readTicket||e!==generation)return null;const next=profileView(data),previous=view;
        if(!preserve){editor=null;selected.clear();}adopt(next);
        if(previous&&next.profile.version!==previous.profile.version&&(editor||selected.size)&&!conflict){conflict={base:copy(previous),latest:next,choices:new Map(),request:null,rows:[]};buildConflict();}
        error=null;reply=next.profile.id?"저장된 내 프로필 초안을 열었어요.":"아직 저장한 프로필이 없어요. 추가할 내용부터 말씀해 주세요.";paint();return next;
      }catch(err){if(ticket===readTicket&&e===generation)showError(err);return null;}
      finally{busy=false;if(opened&&ticket!==readTicket&&!view)showError(new Error("조회 화면이 바뀌었습니다. 프로필을 다시 읽어 주세요."));controls();}
    }
    async function open() {opened=true;generation++;host.hidden=false;if(busy||uncertain){paint();return;}await read();}
    function close() {if(activeMutation||uncertain){showError(new Error(uncertain?"저장 결과가 아직 확인되지 않았습니다. 같은 요청으로 먼저 확인해 주세요.":"저장 요청이 진행 중입니다. 결과를 확인한 뒤 대화를 계속할 수 있어요. 이 요청을 취소한 것은 아닙니다."));paint();return;}const wasOpen=opened;opened=false;generation++;readTicket++;sourceTicket++;if(sourceDialog.open)sourceDialog.close();host.hidden=true;if(busy)notify(onBusy,true);if(wasOpen)notify(onClose);}
    function shouldHandle(value) {
      const t=String(value||"").normalize("NFKC").trim().replace(/[.!]+$/u,"").trim();
      if(/[\n?？"“”‘’`]/u.test(t)||/(?:만약|예를\s*들|가정|하지\s*마|지\s*않|안\s*바꿔|라고)/u.test(t))return false;
      const end=/(?:보여\s*줘|보여주세요|열어\s*줘|확인|조회|(?:수정|편집|갱신|추가|삭제|제거|저장|등록|변경)(?:해\s*줘|해주세요)?|바꿔\s*줘|고쳐\s*줘|지워\s*줘|빼\s*줘|되돌려\s*줘)$/u;
      if(!end.test(t))return false;
      const own=/^(?:내|제)\s*(?:프로필(?:의)?\s*)?(?:프로필|이력|경력|전문\s*분야|기술|스킬|관심\s*분야|역할|직급|직무|소속|부서|표시\s*이름|이름|자기소개|소개)/u;
      const documentRequest=/^(?:이|첨부한|선택한)\s*(?:자료|파일|문서)(?:로|를|을)?\s*(?:내|제)\s*(?:프로필|이력|경력)/u;
      return own.test(t)||documentRequest.test(t);
    }
    async function submit(value,files=[]) {
      if(!shouldHandle(value))return false;
      if(busy||uncertain){showError(new Error("이전 프로필 요청의 결과부터 확인해 주세요."));return true;}
      if(!opened||!view){await open();if(!view)return true;}
      if(files.length){
        if(!/(?:자료|파일|문서)/u.test(value)||!/(?:프로필|내\s*이력|내\s*경력)/u.test(value)||!/(?:갱신|반영|추가|등록|업데이트|수정)/u.test(value)){showError(new Error("파일은 ‘이 자료로 내 프로필 갱신해줘’처럼 목적을 명시해 주세요. 아직 전송하지 않았습니다."));return true;}
        if(files.length>1){showError(new Error("프로필 자료는 한 번에 파일 하나씩 검토해 주세요. 선택한 파일은 아직 전송하지 않았습니다."));return true;}
        await upload(files[0]);return true;
      }
      if(editor||selected.size){showError(new Error("작성 중인 항목이나 자료 선택이 있습니다. 먼저 저장하거나 ‘적용 전 취소’로 정리해 주세요."));return true;}
      await mutation("text",{}, {text:String(value)});return true;
    }
    function compare(before,after,a="현재",b="제안") {const n=el("div","comparison");for(const [label,value] of [[a,before],[b,after]]){const col=el("div");col.append(el("strong",null,label),el("pre",null,text(value)||"미입력"));n.append(col);}return n;}
    function profileScopeSummary(scope={}) {
      const account=scope.kind==="account_private"&&scope.identity_status==="google_authenticated"&&scope.shared===false;
      return {badge:account?"계정의 비공개 프로필":"방문자 전용 초안",
        notice:account?(typeof scope.notice==="string"?scope.notice:"계정의 비공개 프로필입니다. 저장소의 보관 설정을 확인해 주세요."):
          scope.cookie_lifetime_seconds?"이 방문자의 임시 초안 · 쿠키 발급 후 24시간 · 기기 간 복구 없음 · 공개 인물에 반영되지 않음":"이 로컬 저장소의 비공개 초안 · 본인·경력 확인 및 기기 간 복구 없음"};
    }
    function paintSummary() {
      summary.replaceChildren();const scopeCopy=profileScopeSummary(view.scope);const h=el("div","heading");h.append(el("h2",null,"내 프로필"),el("span","badge",scopeCopy.badge));summary.append(h);
      const dl=el("dl","facts");for(const k of ["name","role","skills"])dl.append(el("dt",null,FIELDS[k]),el("dd",null,view.profile.fields[k]||"아직 입력하지 않음"));summary.append(dl);
      summary.append(note(scopeCopy.notice),actions(button("상담 계속",close,"continue",true)));
      if(!view.profile.id)summary.append(note("예: 내 전문분야에 공정 제어 추가해줘"));
    }
    function startEditor(key) {
      editorRevision++;if(key==="career:new")editor={key,before:null,value:cleanCareer({}),baseVersion:view.profile.version};
      else editor={key,before:copy(targetValue(view,key)),value:copy(targetValue(view,key)),baseVersion:view.profile.version};
    }
    function paintEditor() {
      editorBody.replaceChildren();const select=el("select");select.append(option("","수정할 항목 선택"),...Object.entries(FIELDS).map(([k,v])=>option(k,v)),option("career:new","새 경력 한 행 추가"),...view.profile.careers.map((c,i)=>option("career:"+c.id,c.title||`경력 ${i+1}`)));select.value=editor?.key||"";select.dataset.profileLock="";
      select.addEventListener("change",()=>{if(editor&&!same(editor.value,editor.before)){select.value=editor.key;showError(new Error("작성 중인 항목을 먼저 저장하거나 취소해 주세요. 입력은 유지했습니다."));return;}const f=captureFocus();if(select.value)startEditor(select.value);else editor=null;paintEditor();controls();restoreFocus(f);});editorBody.append(field("수정할 항목",select,"editor-target"));
      if(!editor){editorBody.append(note("기본 항목 하나 또는 경력 한 행만 골라 수정할 수 있어요."));return;}
      if(editor.key.startsWith("career:")){
        for(const [k,label] of Object.entries(CAREER)){const input=el(k==="description"?"textarea":"input");input.value=editor.value?.[k]||"";input.maxLength=view.limits.career_fields[k];input.dataset.profileLock="";if(k==="description")input.rows=4;input.addEventListener("input",()=>{editor.value[k]=input.value;editorRevision++;});editorBody.append(field(label,input,"career-"+k));}
      }else{const input=el("textarea");input.rows=editor.key==="bio"?4:2;input.value=editor.value;input.maxLength=view.limits.fields[editor.key];input.dataset.profileLock="";input.addEventListener("input",()=>{editor.value=input.value;editorRevision++;});editorBody.append(field(FIELDS[editor.key],input,"editor-value"));}
      editorBody.append(actions(button("변경 저장",saveEditor,"save-editor"),button("적용 전 취소",()=>{editor=null;editorRevision++;paintEditor();controls();},"cancel-editor",true)));
    }
    async function saveEditor() {
      if(!editor||conflict||busy||uncertain)return;const payload={fields:{},decisions:[]};
      if(same(editor.value,editor.before)){reply="변경한 내용이 없습니다.";controls();return;}
      if(editor.key.startsWith("career:")){
        const id=editor.key.slice(7),rows=view.profile.careers.map(cleanCareer);
        if(id!=="new"&&!rows.some(c=>c.id===id)){showError(new Error("이 경력이 다른 곳에서 삭제됐습니다. 새 경력으로 명시해서 추가해 주세요."));return;}
        payload.careers=id==="new"?[...rows,cleanCareer(editor.value)]:rows.map(c=>c.id===id?cleanCareer({...editor.value,id}):c);
      }else payload.fields[editor.key]=editor.value;
      await mutation("save",payload);
    }
    function selectedValue(p,s) {return s.value===undefined?p.after:s.value;}
    function selectedTarget(s,id) {return s.field==="career"?(s.item_id?"career:"+s.item_id:"new:"+id):s.field;}
    function paintReview() {
      review.replaceChildren();review.hidden=!reviewVisible;if(!reviewVisible)return;
      const pending=(view.suggestions||[]).filter(eligible);review.append(el("h3",null,"자료에서 가져올 내용"),note("문단 후보이며 자동 분류·확정 결과가 아닙니다. 필요한 항목과 적용 위치를 직접 선택해 주세요. 선택한 내용만 한 번에 저장합니다."));
      if(!pending.length){review.append(note("추가할 항목을 확정하지 못했어요. 자료의 읽힌 범위와 원문을 확인해 주세요."));return;}
      const rest=el("details","more");rest.dataset.profileOpen="review-more";rest.append(el("summary",null,`나머지 문단 ${Math.max(0,pending.length-3)}개 펼치기`));
      pending.forEach((p,index)=>{
        const source=(view.sources||[]).find(s=>s.id===p.source_id);if(!source||source.status!=="active")return;
        const s=selected.get(p.id)||{checked:false,field:"",item_id:"",value:p.after};
        const card=el("article","delta");card.dataset.suggestionId=p.id;
        const checkbox=el("input");checkbox.type="checkbox";checkbox.checked=!!s.checked;checkbox.dataset.profileLock="";
        const select=el("select");select.append(option("","아직 분류하지 않음"),...Object.entries(FIELDS).map(([k,v])=>option(k,v)),option("career","경력 설명"));select.value=s.field;select.dataset.profileLock="";
        card.append(field(`문단 ${index+1} 적용`,checkbox,"select-"+p.id),field("적용할 항목",select,"target-"+p.id));
        const target=el("select");target.append(option("","새 경력으로 추가"),...view.profile.careers.map((c,i)=>option(c.id,c.title||`경력 ${i+1}`)));target.value=s.item_id;target.dataset.profileLock="";const targetField=field("적용할 경력",target,"career-target-"+p.id);targetField.hidden=s.field!=="career";card.append(targetField);
        const value=el("textarea");value.value=text(selectedValue(p,s));value.rows=3;value.maxLength=s.field==="career"?4000:view.limits.fields[s.field]||4000;value.dataset.profileLock="";
        const comparison=compare(s.field?targetValue(view,selectedTarget(s,p.id)):"적용 위치를 선택해 주세요.",selectedValue(p,s));card.append(comparison,field("적용할 문장 · 필요하면 수정",value,"value-"+p.id));
        card.append(note(`${source.name} · 추출문 ${p.location?.line||1}줄 · 문자 ${Number(p.location?.start||0)+1}–${p.location?.end||0}`));
        const quote=el("details","quote");quote.dataset.profileOpen="quote-"+p.id;quote.append(el("summary",null,"읽은 원문 보기"),el("blockquote",null,p.quote||""));card.append(quote);
        function remember(){selected.set(p.id,s);selectionRevision++;targetField.hidden=s.field!=="career";const fresh=compare(s.field?targetValue(view,selectedTarget(s,p.id)):"적용 위치를 선택해 주세요.",selectedValue(p,s));comparison.replaceChildren(...fresh.childNodes);value.maxLength=s.field==="career"?4000:view.limits.fields[s.field]||4000;updateApplyLabel();}
        checkbox.addEventListener("change",()=>{s.checked=checkbox.checked;remember();});select.addEventListener("change",()=>{s.field=select.value;s.item_id="";target.value="";remember();});target.addEventListener("change",()=>{s.item_id=target.value;remember();});value.addEventListener("input",()=>{s.value=value.value;remember();});
        (index<3?review:rest).append(card);
      });
      if(pending.length>3)review.append(rest);
      review.append(actions(button("선택한 항목 적용",applySelected,"apply"),button("적용 전 취소",()=>{selected.clear();selectionRevision++;reviewVisible=false;reply="선택을 취소했습니다. 이미 읽은 자료는 남아 있으며 아래 자료에서 따로 삭제할 수 있습니다.";paint();},"cancel-selection",true),button("최신 값으로 후보 다시 비교",refreshSuggestions,"refresh-suggestions")));updateApplyLabel();
    }
    function updateApplyLabel() {const b=review.querySelector('[data-profile-action="apply"]');if(b)b.textContent=`선택한 ${[...selected.values()].filter(s=>s.checked).length}개 적용`;}
    async function applySelected() {
      if(conflict||busy||uncertain)return;
      const decisions=[],targets=new Set();
      for(const [id,s] of selected){if(!s.checked)continue;const p=view.suggestions.find(p=>p.id===id);if(!p||!eligible(p))continue;
        if(!s.field){showError(new Error("선택한 문단의 적용할 항목을 먼저 골라 주세요."));return;}
        if(p.base_version!==view.profile.version){showError(new Error("후보 생성 뒤 저장값이 바뀌었습니다. 최신 값으로 후보를 다시 비교해 주세요."));return;}
        const target=selectedTarget(s,id);if(targets.has(target)){showError(new Error("같은 항목에 여러 문단을 선택했습니다. 반영할 값 한 행만 선택해 주세요."));return;}targets.add(target);
        const value=selectedValue(p,s),limit=s.field==="career"?4000:view.limits.fields[s.field];if(Array.from(value).length>limit){showError(new Error(`${FIELDS[s.field]||"경력 설명"}의 길이를 ${limit}자 이하로 줄여 주세요.`));return;}
        decisions.push({id,decision:value===p.after?"accept":"edit",field:s.field,...(s.item_id?{item_id:s.item_id}:{}),...(value===p.after?{}:{value})});
      }
      if(!decisions.length){showError(new Error("적용할 문단을 하나 이상 선택해 주세요."));return;}
      if(editor){showError(new Error("직접 편집 중인 항목을 먼저 저장하거나 취소해 주세요. 자료 선택은 유지됩니다."));return;}
      await mutation("save",{fields:{},decisions});
    }
    async function refreshSuggestions() {
      const ids=[...new Set((view.suggestions||[]).filter(eligible).filter(p=>view.sources.some(s=>s.id===p.source_id&&s.status==="active")).map(p=>p.source_id))];
      if(!ids.length)return;await mutation("suggest",{source_ids:ids});
    }
    async function upload(file) {
      if(conflict||busy||uncertain)return;
      const formats=view.limits.formats||[],ext=file.name.split(".").pop().toLowerCase(),cap=Math.min(view.limits.file_bytes,1024*1024);
      if(!formats.includes(ext)){showError(new Error("텍스트·PDF·DOCX 자료를 선택해 주세요. 이미지와 OCR은 지원하지 않습니다."));return;}
      if(file.size<1||file.size>cap){showError(new Error("빈 파일은 읽을 수 없고, 프로필 자료는 파일당 최대 1 MiB입니다."));return;}
      const e=generation;busy=true;controls();let encoded;
      try{encoded=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(String(reader.result).split(",")[1]);reader.onerror=()=>reject(new Error("파일을 읽지 못했습니다. 선택한 파일을 확인해 주세요."));reader.readAsDataURL(file);});}catch(err){showError(err);}finally{busy=false;controls();}
      if(!encoded||e!==generation||!opened)return;
      const request=newRequest("upload",{name:file.name,data:encoded});
      request.after=async data=>{const operation=data.profile_view?.operation||data.operation;const id=operation?.source_id;
        if(id){await mutation("suggest",{source_ids:[id]});}else{reply="자료를 읽었습니다. 아래 자료의 ‘문단 비교’를 눌러 검토해 주세요.";paint();}};
      await perform(request);
    }
    function buildConflict() {
      if(!conflict?.latest)return;const rows=[],base=conflict.base,latest=conflict.latest;
      if(conflict.request?.body.action==="text"){
        const command=conflict.command;
        if(command){
          const current=targetValue(latest,command.field);let proposed=command.value;
          if(command.action!=="set"){
            let entries=current.split(/[,\n;]+/u).map(value=>value.trim()).filter(Boolean);const value=command.value.trim();
            if(command.action==="add"&&!entries.includes(value))entries.push(value);
            if(command.action==="remove")entries=entries.filter(entry=>entry!==value);
            proposed=entries.join(", ");
          }
          rows.push({id:"command:"+command.field,key:command.field,before:current,after:proposed,kind:"command"});
        }
        conflict.rows=rows;return;
      }
      if(editor){const key=editor.key;if(!same(targetValue(base,key),targetValue(latest,key)))rows.push({id:"edit:"+key,key,before:targetValue(latest,key),after:editor.value,kind:"editor"});}
      for(const [id,s] of selected){if(!s.checked||!s.field)continue;const key=selectedTarget(s,id);if(key.startsWith("new:"))continue;
        if(!same(targetValue(base,key),targetValue(latest,key)))rows.push({id:"source:"+id,key,before:targetValue(latest,key),after:selectedValue(base.suggestions.find(p=>p.id===id)||{},s),kind:"source",suggestionId:id});}
      conflict.rows=rows;
    }
    async function compareLatest() {
      if(busy||uncertain||!conflict)return;const e=generation,c=conflict;busy=true;controls();
      try{const latest=profileView(await api("/api/self-profile"));if(e!==generation||conflict!==c)return;c.latest=latest;adopt(latest);buildConflict();error=null;}
      catch(err){if(e===generation&&conflict===c)showError(err);}finally{busy=false;paint();controls();}
    }
    function paintConflict() {
      conflicts.replaceChildren();conflicts.hidden=!conflict;if(!conflict)return;
      conflicts.append(el("h3",null,"다른 변경과 비교해 주세요"),note("작성한 값과 자료 선택은 그대로 두었습니다. 달라진 항목마다 최신값을 유지할지, 작성한 값을 쓸지 선택해 주세요."));
      if(conflict.request?.body.text)conflicts.append(note("작성한 요청: "+conflict.request.body.text));
      if(!conflict.latest){conflicts.append(button("최신 저장값과 비교",compareLatest,"compare-latest",true));return;}
      for(const row of conflict.rows){const card=el("article","conflict-row");card.append(el("h4",null,FIELDS[row.key]||"경력·프로젝트"),compare(row.before,row.after,"최신 저장값","작성 중인 값"));
        const select=el("select");select.append(option("","아직 선택하지 않음"),option("latest","최신값 유지"),option("mine","작성한 값 사용"));select.value=conflict.choices.get(row.id)||"";select.addEventListener("change",()=>conflict.choices.set(row.id,select.value));card.append(field("이 항목의 처리",select,"conflict-"+row.id));conflicts.append(card);}
      const retryAction=conflict.request?.body.action,isText=retryAction==="text",canRetry=retryAction&&!['save','text'].includes(retryAction);
      if(!conflict.rows.length)conflicts.append(note(isText?"이 요청의 수정 대상을 확인하지 못했습니다. 원문을 다시 적용하지 않으며 직접 항목을 골라 수정할 수 있습니다.":"수정 대상의 값은 바뀌지 않았습니다. 최신 버전 기준을 확인한 뒤 계속할 수 있습니다."));
      const label=isText&&!conflict.command?"항목 직접 수정으로 계속":canRetry?"비교 확인 · 이 요청 다시 적용":"선택한 비교 결과로 편집 계속";
      conflicts.append(button(label,resolveConflict,"resolve-conflict",true));
    }
    async function resolveConflict() {
      if(!conflict?.latest||busy||uncertain)return;
      if(conflict.rows.some(r=>!conflict.choices.get(r.id))){showError(new Error("달라진 각 항목에서 사용할 값을 선택해 주세요."));return;}
      const prior=conflict.request;
      if(prior?.body.action==="text"){
        const row=conflict.rows.find(item=>item.kind==="command"),mine=row&&conflict.choices.get(row.id)==="mine";
        editor=mine?{key:row.key,before:copy(row.before),value:row.after,baseVersion:view.profile.version}:null;editorRevision++;
        if(mine||!row)editorBox.open=true;
        conflict=null;error=null;errorRequest=null;
        reply=mine?"선택한 값을 편집창에 두었습니다. ‘변경 저장’을 눌러야 반영됩니다.":row?"최신 저장값을 유지했습니다. 원래 요청은 다시 적용하지 않았습니다.":"수정 대상을 확인하지 못해 원래 요청을 다시 적용하지 않았습니다. 직접 수정할 항목을 선택해 주세요.";
        paint();return;
      }
      for(const row of conflict.rows){if(conflict.choices.get(row.id)==="latest"){if(row.kind==="editor")editor=null;else{const s=selected.get(row.suggestionId);if(s)s.checked=false;}}}
      if(editor){editor.before=copy(targetValue(view,editor.key));editor.baseVersion=view.profile.version;}
      conflict=null;error=null;errorRequest=null;reply="비교 결과를 반영했습니다. 아직 저장하지 않았습니다.";paint();
      if(prior&&!["save","text"].includes(prior.body.action)){const retry=newRequest(prior.body.action,prior.body.payload,prior.body.text===undefined?{}:{text:prior.body.text});retry.after=prior.after;await perform(retry);return;}
      if([...selected.values()].some(s=>s.checked))await refreshSuggestions();
    }
    function provenanceLabel(key) {
      const p=view.profile.provenance?.[key];if(!p)return "근거 미제공 · 본인·경력 확인과 별개";
      const origin={user_input:"직접 입력",source_claim:"자료에서 채택",user_edited_source:"자료를 바탕으로 수정"}[p.origin]||"출처 확인 필요";
      const names=(p.source_ids||[]).map(id=>view.sources.find(s=>s.id===id)).filter(s=>s&&!["deleted","deleting"].includes(s.status)).map(s=>s.name);
      return [origin,...names,p.evidence_status==="requires_review"?"근거 재확인 필요":"본인·경력 확인과 별개"].join(" · ");
    }
    function historyLabel(h) {return FIELDS[h.field]||(h.field?.startsWith("career:")?"경력·프로젝트":"자료 변경");}
    function paintReceipts() {
      receipts.replaceChildren();receipts.hidden=focusReceipt==null;if(focusReceipt==null)return;
      const events=(view.history||[]).filter(h=>h.version===Number(focusReceipt));
      const card=el("article","receipt");card.dataset.profileVersion=String(focusReceipt);card.append(el("h3",null,`변경 기록 · v${focusReceipt}`));
      if(!events.length){card.append(note("이 버전에서 표시할 항목 변경은 없습니다. 현재 저장 상태를 기준으로 확인했습니다."));receipts.append(card);return;}
      const details=el("details","changes");details.dataset.profileOpen="receipt-"+focusReceipt;details.append(el("summary",null,"변경 보기"));
      for(const h of events){const row=el("div","delta");row.append(el("strong",null,historyLabel(h)));if(h.redacted)row.append(note("연결 자료가 삭제되어 이전·이후 값은 표시하지 않습니다."));else{row.append(compare(h.before,h.after,"변경 전","변경 후"));const sources=(h.source_ids||[]).map(id=>view.sources.find(s=>s.id===id)).filter(s=>s&&!["deleted","deleting"].includes(s.status));if(sources.length)row.append(note("자료: "+sources.map(s=>s.name).join(" · ")));}details.append(row);}
      const first=events[0];card.append(el("p",null,events.length===1?`${historyLabel(first)} 변경 기록입니다.`:`항목 ${events.length}개의 변경 기록입니다.`));
      if(events.length===1&&!first.redacted&&typeof first.before==="string"&&typeof first.after==="string")card.append(el("p","receipt-line",`${first.before||"미입력"} → ${first.after||"미입력"}`));
      card.append(details);
      if(events.length===1&&first.can_undo===true)card.append(button("되돌리기",()=>mutation("undo",{version:Number(focusReceipt)}),"undo"));
      else card.append(note(first.undo_unavailable_reason||"이 변경은 여기서 되돌리기를 지원하지 않습니다. 항목 직접 수정에서 필요한 내용만 정정해 주세요."));
      receipts.append(card);
    }
    async function showReceipt(version) {focusReceipt=Number(version);if(!Number.isSafeInteger(focusReceipt)||focusReceipt<0){focusReceipt=null;return;}await open();}
    async function previewSource(source,opener) {
      const ticket=++sourceTicket;sourceOpener=opener;sourceHeading.textContent=source.name+" · 읽은 자료";sourceInfo.textContent="추출문을 읽고 있어요.";sourceText.textContent="";if(!sourceDialog.open)sourceDialog.showModal();
      try{const data=await api("/api/self-profile/source?id="+encodeURIComponent(source.id));if(ticket!==sourceTicket||!sourceDialog.open||!opened)return;sourceInfo.textContent=`원본 미보관 · ${data.source?.truncated?"일부 읽음":"저장된 추출문"} · OCR 미지원`;sourceText.textContent=data.text||"읽힌 텍스트가 없습니다.";}catch(err){if(ticket===sourceTicket&&sourceDialog.open)sourceInfo.textContent=err.message;}
    }
    function paintAll() {
      allBody.replaceChildren();for(const [k,label] of Object.entries(FIELDS)){allBody.append(el("h4",null,label),el("p","value",view.profile.fields[k]||"미입력"),note(provenanceLabel(k)));}
      allBody.append(el("h3",null,`경력 · ${view.profile.careers.length}행`));for(const c of view.profile.careers){const row=el("article","career");row.append(el("h4",null,c.title||"제목 미입력"),note([c.organization,c.period,c.role].filter(Boolean).join(" · ")),el("p","value",c.description||""),note(provenanceLabel("career:"+c.id)));allBody.append(row);}
      allBody.append(el("h3",null,"읽은 자료"),note("텍스트·PDF·DOCX · 파일당 최대 1 MiB · 원본 미보관 · OCR 미지원. 문단을 읽는 것과 프로필에 적용하는 것은 별개입니다."));
      const file=el("input");file.type="file";file.accept=(view.limits.formats||[]).map(x=>"."+x).join(",");file.dataset.profileLock="";file.addEventListener("change",()=>{if(file.files?.[0])upload(file.files[0]);});allBody.append(field("내 프로필에 사용할 새 자료",file,"file"));
      for(const source of view.sources||[]){const row=el("article","source");row.dataset.sourceId=source.id;row.append(el("h4",null,source.name),note(({active:"검토 가능",unlinked:"연결 해제됨",replaced:"새 자료로 교체됨",deleting:"삭제 마무리 필요",deleted:"삭제됨"}[source.status]||"자료 상태 확인 필요")+` · ${source.truncated?"일부 읽음":"저장된 추출문 기준"} · 원본 미보관`));
        if(!["deleted","deleting"].includes(source.status)){const preview=button("읽은 내용 보기",()=>previewSource(source,preview),"preview-source");row.append(actions(preview,...(source.status==="active"?[button("문단 비교",()=>mutation("suggest",{source_ids:[source.id]}),"suggest-source")]:[]),button("읽은 자료 삭제",()=>{deleteSource=source;paintAll();controls();},"delete-source")));}
        if(source.status==="deleting")row.append(button("삭제 마무리 다시 시도",()=>mutation("source-action",{id:source.id,action:"delete"}),"finish-delete"));
        if(deleteSource?.id===source.id&&source.status!=="deleted"){const impact=source.impact||{};row.append(note(`이 자료에서 나온 항목 ${(impact.profile_items||[]).length}개, 후보 ${impact.suggestions||0}개와 변경 기록 ${impact.history_entries||0}개도 삭제·가림 처리됩니다. 직접 쓴 독립 항목은 유지됩니다.`),actions(button("영향 확인 · 자료 삭제",()=>mutation("source-action",{id:source.id,action:"delete"}),"confirm-delete"),button("자료 삭제 취소",()=>{deleteSource=null;paintAll();controls();},"cancel-delete",true)));}
        allBody.append(row);
      }
      const history=el("details","history");history.dataset.profileOpen="history";history.append(el("summary",null,`변경 이력 ${(view.history||[]).length}건 펼치기`));
      for(const h of [...(view.history||[])].reverse()){const row=el("div","history-row");row.append(el("span",null,`${historyLabel(h)} · v${h.version}`),button("변경 보기",()=>{focusReceipt=h.version;paintReceipts();controls();},"receipt"));history.append(row);}allBody.append(history);
      if(view.scope?.notice)allBody.append(note(view.scope.notice));
    }
    function accountNavigationState() {
      return {blocked:accountNavigationPending||busy||activeMutation||!!uncertain,
        dirty:!!(editor&&!same(editor.value,editor.before))||selected.size>0};
    }
    window.addEventListener("rndplz:account-navigation",event=>{
      accountNavigationPending=event.detail?.phase!=="cancel";
      if(event.detail?.phase==="invalidate"){
        accountInvalidated=true;generation++;readTicket++;sourceTicket++;opened=false;host.hidden=true;
        if(sourceDialog.open)sourceDialog.close();
      }
      controls();
    });
    return Object.freeze({open,close,shouldHandle,submit,showReceipt,isOpen:()=>opened,hasPendingRequest:()=>!!uncertain,accountNavigationState});
  }
  window.RndProfileChat=Object.freeze({create});
})();
