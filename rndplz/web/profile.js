/* A private draft: typed edits, and documents the company AI turns into card proposals. */
(() => {
  "use strict";
  const $ = id => document.getElementById(id);
  const labels = {name:"표시 이름",organization:"소속·부서",role:"현재 역할",bio:"짧은 소개",skills:"다뤄본 분야·기술",interests:"관심 분야",career:"경력·프로젝트 설명"};
  const careerLabels = {title:"경력·프로젝트명",organization:"소속·조직",period:"기간",role:"맡은 역할",description:"한 일과 적용 조건"};
  let view=null, token="", draft=null, busy=false, conflict=null, uncertain=null, action=null;
  let accountNavigationPending=false,accountInvalidated=false;
  let digest=null, digestTicket=0; // the company AI's card proposal for one document
  // A bound account edits its research-map card: the card as saving would show it, one block open at a time.
  let cardPerson=null, cardEditing=null, cardBefore=null, cardSeq=0, cardTimer=0, cardError="";
  const deletionRetries=new Map(), dialogOpeners=new Map();
  const clone=value=>JSON.parse(JSON.stringify(value));
  const requestId=()=>crypto.randomUUID().replaceAll("-","");
  const text=value=>value==null?"":typeof value==="string"?value:JSON.stringify(value,null,2);
  const date=value=>value?new Intl.DateTimeFormat("ko-KR",{dateStyle:"medium",timeStyle:"short"}).format(new Date(value)):"아직 저장하지 않음";
  function node(tag,cls,value){const n=document.createElement(tag);if(cls)n.className=cls;if(value!==undefined)n.textContent=value;return n;}
  function button(label,fn,cls="text-button"){const b=node("button",cls,label);b.type="button";b.dataset.lock="";b.addEventListener("click",fn);return b;}
  function empty(message){return node("p","empty-note",message);}
  function announce(message){$("pageStatus").textContent=message;}
  function clearError(){for(const id of ["pageError","sourceError"]){$(id).hidden=true;$(id).replaceChildren();}}
  // Adding and reading a document happen in the documents section at the bottom: their progress and errors show
  // there (sourceStatus/sourceError), not at the top of the page where nobody is looking.
  function sourceNote(message){$("sourceStatus").textContent=message;}
  function showError(message,retry,box=$("pageError")){box.replaceChildren(node("p","",message));if(retry){const b=button("같은 요청으로 다시 확인",retry,"secondary-button");delete b.dataset.lock;box.append(b);}box.hidden=false;box.focus();}
  function sourceFail(message,retry){sourceNote("");showError(message,retry,$("sourceError"));}
  function cleanCareers(rows){return rows.map(row=>{const value={};if(row.id)value.id=row.id;for(const k of Object.keys(careerLabels))value[k]=row[k]||"";return value;});}
  function manualChanges(){if(!view||!draft)return {fields:{},careers:false};const fields={};for(const k of Object.keys(view.profile.fields))if(draft.fields[k]!==view.profile.fields[k])fields[k]=draft.fields[k];return {fields,careers:JSON.stringify(cleanCareers(draft.careers))!==JSON.stringify(cleanCareers(view.profile.careers))};}
  function hasChanges(){const c=manualChanges();return Object.keys(c.fields).length+(c.careers?1:0);}
  function fieldOrigin(key){const p=view.profile.provenance[key];if(!p)return "근거 미제공";const origin={user_input:"직접 입력",public_card:"연구맵 카드에서 가져옴",source_claim:"자료에서 추출",user_edited_source:"자료를 바탕으로 직접 수정"}[p.origin]||"출처 확인 필요";const status={linked_claim:"근거 연결됨",not_provided:"근거 미제공",requires_review:"근거 재확인 필요",source_deleted:"연결 자료 삭제됨"}[p.evidence_status]||"근거 상태 확인 필요";return `${origin} · ${status}`;}
  function updateControls(){const locked=accountNavigationPending||busy||!view||!!uncertain;$("profileFields").disabled=locked;document.querySelectorAll("[data-lock]").forEach(el=>el.disabled=locked);$("saveProfile").disabled=locked||!hasChanges()||!!conflict;$("changeCount").textContent=hasChanges()?`변경 ${hasChanges()}개 · 아직 저장하지 않음`:"변경 없음";$("saveProfile").firstChild.textContent=busy?"처리 중 ":`변경 ${hasChanges()||""}${hasChanges()?"개 ":""}저장 `;if(draft){$("previewName").textContent=draft.fields.name.trim()||"당신의 이름";$("previewRole").textContent=[draft.fields.organization,draft.fields.role].filter(Boolean).join("\n")||"지금 하는 일부터 적어보세요.";}}
  async function api(path,payload){if(accountNavigationPending||accountInvalidated)throw new Error("계정이 바뀌고 있어요. 새 화면에서 다시 확인해 주세요.");const options={credentials:"same-origin",cache:"no-store"};if(payload!==undefined)Object.assign(options,{method:"POST",headers:{"Content-Type":"application/json","X-Rndplz-Token":token},body:JSON.stringify(payload)});let response,data;try{response=await fetch(path,options);}catch(_){const e=new Error("전송 결과를 확인하지 못했습니다. 입력은 그대로 두었습니다.");e.uncertain=payload!==undefined;throw e;}try{data=await response.json();}catch(_){const e=new Error("서버 응답을 확인하지 못했습니다. 입력은 그대로 두었습니다.");e.uncertain=payload!==undefined;throw e;}if(accountInvalidated)throw new Error("이전 계정의 응답을 적용하지 않았습니다.");if(!response.ok){const e=new Error(typeof data.error==="string"?data.error:"요청을 처리하지 못했습니다. 입력은 그대로 두었습니다.");e.status=response.status;e.code=data.code;e.uncertain=payload!==undefined&&response.status>=500;throw e;}return data;}
  function draftFrom(profile){return {fields:clone(profile.fields),careers:profile.careers.map(row=>({...row,_key:row.id}))};}
  function mergeCareerEdits(previous,edited,latest,derived){
    const base=new Map(previous.map(row=>[row.id,row])), local=new Map(edited.filter(row=>row.id).map(row=>[row.id,row]));
    const dirty=row=>Object.keys(careerLabels).filter(key=>(row[key]||"")!==(base.get(row.id)?.[key]||""));
    const merged=[], seen=new Set();let removed=0;
    for(const row of latest){
      seen.add(row.id);
      if(base.has(row.id)&&!local.has(row.id))continue; // Preserve the editor's explicit row removal.
      const edit=local.get(row.id);
      if(!edit||!base.has(row.id)){merged.push({...row,_key:row.id});continue;}
      const keys=dirty(edit), value={...row,_key:row.id};
      if(derived("career:"+row.id)){if(keys.length)removed++;}
      else for(const key of keys)value[key]=edit[key]||"";
      merged.push(value);
    }
    for(const row of edited){
      if(!row.id){merged.push({...row});continue;}
      if(seen.has(row.id))continue;
      if(derived("career:"+row.id)){removed++;continue;}
      // Retain a locally edited deleted row for the existing explicit conflict guard.
      if(base.has(row.id)&&dirty(row).length)merged.push({...row});
    }
    return {rows:merged,removed};
  }
  function adopt(data,{preserve=true}={}){
    const old=view, changes=manualChanges(), oldDraft=draft;
    if(data.token)token=data.token;
    view=data;draft=draftFrom(data.profile);
    let removed=0;
    if(preserve&&oldDraft){
      const available=new Map(data.sources.map(s=>[s.id,s]));
      const gone=new Set(old.sources.filter(s=>!available.has(s.id)||["deleted","deleting"].includes(available.get(s.id).status)).map(s=>s.id));
      const derived=key=>(old.profile.provenance[key]?.source_ids||[]).some(id=>gone.has(id));
      for(const [k,value] of Object.entries(changes.fields)){if(derived(k)){removed++;continue;}draft.fields[k]=value;}
      if(changes.careers){const merged=mergeCareerEdits(old.profile.careers,oldDraft.careers,data.profile.careers,derived);draft.careers=merged.rows;removed+=merged.removed;}
    }
    render();
    if(removed)announce(`삭제된 자료에서 나온 편집 ${removed}개를 지웠습니다. 독립적으로 작성한 입력은 유지했습니다.`);
  }
  function renderScope(){
    const scope=view.scope||{},card=scope.kind==="person_card"&&scope.identity_status==="google_authenticated",account=card||(scope.kind==="account_private"&&scope.identity_status==="google_authenticated"&&scope.shared===false),visitor=scope.kind==="visitor_private";
    const badge=card?"연구맵 카드":account?"계정의 비공개 프로필":"시연 초안",person=typeof scope.person_label==="string"?scope.person_label:"";
    $("profileScopeBadge").textContent=badge;$("profileScopeLink").textContent=card?(person?"「"+person+"」 카드와 연결":"공개 인물과 연결"):"공개 인물과 미연결";
    $("profileScopeStamp").setAttribute("aria-label","내 프로필 · "+badge+" · "+$("profileScopeLink").textContent);
    // A bound account is the map card itself (the administrator linked it at approval), not an unchecked draft.
    $("identityTag").textContent=card?"연구맵 카드와 연결됨":"본인 연결 미확인";
    const note=$("identityFootnote");note.dataset.plain??=note.innerHTML;
    if(card)note.textContent="저장하면 연구맵의 "+(person?"「"+person+"」 ":"")+"카드에 바로 보입니다.";else note.innerHTML=note.dataset.plain;
    $("scopeHeading").textContent=card?"연구맵 공개 카드와 연결된 프로필입니다.":account?"계정의 비공개 프로필입니다.":visitor?"이 방문자의 초안에만 저장합니다.":"로컬 작업 저장소의 초안입니다.";
    $("scopeNotice").textContent=typeof scope.notice==="string"?scope.notice:"저장 범위 안내를 확인하지 못했습니다.";
    $("saveScope").textContent=card?"연구맵 공개 카드에 저장 · 모든 방문자에게 보임":(account?"본인 계정의 비공개 프로필":visitor?"이 방문자의 초안":"로컬 작업의 초안")+"에 저장 · 외부 비공유";
    $("scopeDetailsTitle").textContent=account?"계정 저장과 자료 처리 안내":"임시 저장과 자료 처리 안내";
    $("scopeStorageNotice").textContent=card?"저장 범위와 보관 조건은 위 서버 안내를 따릅니다. 연구맵 카드와의 연결은 관리자가 계정 승인 때 정했습니다.":account?"저장 범위와 보관 조건은 위 서버 안내를 따릅니다. Google 로그인은 경력 진위나 공개 인물과의 연결을 확인하지 않습니다.":visitor?"영구 보관이나 기기 간 복구를 지원하지 않습니다. 공개 시연의 방문자 쿠키는 발급 후 24시간 유효하며, 접근 만료가 서버 자료 삭제를 뜻하지는 않습니다.":"이 로컬 작업 저장소의 초안입니다. 계정 본인 확인·기기 간 복구·영구 보관 기능은 없습니다.";
  }
  function render(){
    renderScope();
    $("savedVersion").textContent=view.profile.id?`초안 v${view.profile.version}\n마지막 저장 ${date(view.profile.updated_at)}`:"저장된 프로필 없음";
    $("uploadLimits").textContent=`PDF · DOCX · 텍스트 문서, 파일당 ${Math.round(view.limits.file_bytes/1048576)} MB까지. 이미지·스캔 문서는 읽지 못해요.`;
    $("sourceFile").accept=view.limits.formats.map(x=>"."+x).join(",");
    renderFields();cardEditing=null;renderCareers();renderCardMode();renderSources();renderDigest();renderHistory();updateControls();
  }
  const cardMode=()=>view?.scope?.kind==="person_card"&&view.scope.identity_status==="google_authenticated";
  // Card blocks and the draft values they show. Skill chips and skill groups are both the skills list.
  const CARD_BLOCKS={identity:{label:"이름·소속",fields:["name","organization","role"]},bio:{label:"약력",fields:["bio"]},skills:{label:"대표 기술",fields:["skills"]},
    skillGroups:{label:"다룰 수 있는 일",fields:["skills"]},careers:{label:"이력의 발자취",careers:true},interests:{label:"관심 분야",fields:["interests"]},
    projects:{label:"프로젝트 이력",locked:true},education:{label:"교육 이력",locked:true}};
  const CARD_HEADINGS={"이력의 발자취":"careers","프로젝트 이력":"projects","교육 이력":"education","다룰 수 있는 일":"skillGroups","관심 분야":"interests"};
  function renderCardMode(){
    const on=cardMode();document.body.classList.toggle("card-mode",on);$("cardEditor").hidden=!on;
    document.querySelectorAll("[data-card-number]").forEach(el=>{el.dataset.formNumber??=el.textContent;el.textContent=on?el.dataset.cardNumber:el.dataset.formNumber;});
    if(on)scheduleCard(0);
  }
  function scheduleCard(delay=250){if(!cardMode())return;clearTimeout(cardTimer);cardTimer=setTimeout(refreshCard,delay);}
  async function refreshCard(){
    const seq=++cardSeq,changes=manualChanges(),payload={fields:changes.fields,decisions:[]};if(changes.careers)payload.careers=cleanCareers(draft.careers);
    try{const data=await api("/api/self-profile/card-preview",payload);if(seq!==cardSeq)return;cardPerson=data.card;cardError="";}
    catch(e){if(seq!==cardSeq)return;cardError="카드 미리보기를 만들지 못했어요. "+e.message;}
    renderCard();
  }
  function blockKey(el){
    if(el.matches(".researcher-name,.personal-name,.laureate-name"))return "identity";
    if(el.matches(".researcher-bio"))return "bio";
    if(el.matches(".researcher-skills"))return "skills";
    if(el.tagName==="H3")return CARD_HEADINGS[el.textContent.trim()]||null;
    if(el.matches(".researcher-detail-hero,.scope-note,details,.personal-portrait-note,.laureate-award,.researcher-sources"))return null;
    return undefined;
  }
  function blockChanged(cfg){
    return cfg.careers?manualChanges().careers:(cfg.fields||[]).some(k=>draft.fields[k]!==view.profile.fields[k]);
  }
  function savedValues(cfg){
    const box=node("div","card-asis-body");
    if(cfg.careers)for(const row of view.profile.careers)box.append(node("p","",[row.period,row.title].filter(Boolean).join(" · ")+(row.description?"\n"+row.description:"")));
    else for(const k of cfg.fields)if(draft.fields[k]!==view.profile.fields[k]||cfg.fields.length===1)box.append(node("p","",(cfg.fields.length>1?labels[k]+": ":"")+(view.profile.fields[k]||"미입력")));
    if(!box.childNodes.length)box.append(node("p","","저장된 값과 같아요."));
    return box;
  }
  function renderCard(){
    const host=$("cardView");if(!host||!cardMode())return;
    if(!cardPerson||!window.RndCraft){host.replaceChildren(empty(cardError||"연구맵 카드를 불러오고 있어요."));return;}
    if(cardEditing&&host.querySelector(".card-block-editor"))return; // keep the open editor; the card follows when it closes
    host.innerHTML=RndCraft.profileDetails(cardPerson);
    const groups=[];let current=null;
    for(const el of [...host.children]){const key=blockKey(el);if(key!==undefined||!current){current={key:key??null,nodes:[]};groups.push(current);}current.nodes.push(el);}
    for(const [key,text] of [["careers","＋ 이력 추가"],["interests","＋ 관심 분야 추가"]])if(!groups.some(g=>g.key===key)){const h=node("h3","",CARD_BLOCKS[key].label),p=node("p","card-empty",text);groups.push({key,nodes:[h,p]});}
    host.replaceChildren(...groups.map(group=>cardBlock(group)));
    if(cardError)host.prepend(node("p","profile-error",cardError));
    if(cardEditing){renderCareers();host.querySelector(".card-block-editor input,.card-block-editor textarea")?.focus();}
  }
  function cardBlock({key,nodes}){
    const cfg=CARD_BLOCKS[key],block=node("div","card-block");
    if(!cfg){block.append(...nodes);return block;}
    block.dataset.block=key;
    if(cardEditing===key){block.classList.add("is-editing");block.append(blockEditor(cfg));return block;}
    if(key==="bio"&&!nodes[0].textContent.trim())nodes[0].replaceChildren(node("span","card-empty","＋ 약력 적기"));
    if(cfg.locked){block.classList.add("is-locked");block.append(...nodes,node("p","card-locked-note",cfg.label+"은 아직 여기서 고칠 수 없어요."));return block;}
    block.classList.add("is-editable");
    const edit=button("수정",()=>openBlock(key),"card-edit");edit.setAttribute("aria-label",cfg.label+" 수정");block.append(edit);
    if(blockChanged(cfg)){
      block.classList.add("is-changed");const asis=node("details","card-asis");asis.append(node("summary","","저장 전 변경 · 지금 값(As is) 보기"),savedValues(cfg));block.append(asis);
    }
    block.append(...nodes);
    block.addEventListener("click",e=>{if(e.target.closest("a,summary,details,button")||$("profileFields").disabled)return;openBlock(key);});
    return block;
  }
  async function openBlock(key){if(cardEditing===key)return;if(cardEditing){cardEditing=null;await refreshCard();}cardEditing=key;cardBefore=blockValues(CARD_BLOCKS[key]);renderCard();}
  function blockValues(cfg){return cfg.careers?clone(draft.careers):Object.fromEntries(cfg.fields.map(k=>[k,draft.fields[k]]));}
  // × (or Escape) leaves the block as it was when it opened and shows the card again.
  function cancelBlock(){const cfg=CARD_BLOCKS[cardEditing];if(cfg&&cardBefore){if(cfg.careers)draft.careers=cardBefore;else Object.assign(draft.fields,cardBefore);}cardEditing=null;cardBefore=null;renderCard();updateControls();}
  function closeBlock(){cardEditing=null;cardBefore=null;$("cardView").querySelector(".card-block-editor")?.closest(".card-block")?.classList.add("is-applying");refreshCard();}
  function blockEditor(cfg){
    const box=node("div","card-block-editor"),head=node("div","card-editor-head"),close=button("×",cancelBlock,"close-button");
    close.setAttribute("aria-label",cfg.label+" 수정 취소하고 닫기");close.title="수정 취소";head.append(node("h3","",cfg.label+" 수정"),close);box.append(head);
    if(cfg.careers){const rows=node("div");rows.id="cardCareerRows";box.append(rows,button("＋ 경력·프로젝트 추가",addCareerRow,"add-row"));}
    else{
      const grid=node("div","field-grid");
      for(const k of cfg.fields)grid.append(editableField(k,labels[k],draft.fields[k],{id:"card-field-"+k,wide:true,multiline:["bio","skills","interests"].includes(k),max:view.limits.fields[k],origin:fieldOrigin(k),onInput:value=>{draft.fields[k]=value;}}));
      box.append(grid);
      if(cfg.fields.some(k=>k==="skills"||k==="interests"))box.append(node("p","section-help","한 줄에 하나씩 적어 주세요."+(cfg.fields.includes("skills")?" 묶음에 없던 새 기술은 위쪽 대표 기술 칩으로 보여요.":"")));
    }
    const actions=node("div","button-row");
    actions.append(button("카드에 반영해 보기",closeBlock,"primary-button"),button("이 항목 되돌리기",()=>{if(cfg.careers)draft.careers=draftFrom(view.profile).careers;else for(const k of cfg.fields)draft.fields[k]=view.profile.fields[k];$("cardView").querySelector(".card-block-editor")?.remove();renderCard();updateControls();},"secondary-button"));
    box.append(actions,node("p","section-help","저장 버튼을 누르기 전까지 연구맵에는 보이지 않아요."));
    box.addEventListener("keydown",e=>{if(e.key==="Escape"){e.preventDefault();cancelBlock();}});
    return box;
  }
  function editableField(key,label,value,{wide=false,multiline=false,max=2000,onInput,id,origin,reset}={}){
    const wrap=node("div","profile-field"+(wide?" wide":"")),lab=node("label","",label);lab.htmlFor=id;
    const input=node(multiline?"textarea":"input");input.id=id;input.name=key;input.value=value;input.maxLength=max;if(multiline)input.rows=key==="bio"?3:4;else input.type="text";
    input.addEventListener("input",()=>{onInput(input.value);updateControls();});wrap.append(lab,input);
    if(origin!==undefined){const meta=node("div","field-meta");meta.append(node("span","",origin));if(reset)meta.append(button("저장값으로 되돌리기",reset));wrap.append(meta);}return wrap;
  }
  function renderFields(){for(const [container,keys] of [["basicFields",["name","organization","role","bio"]],["expertiseFields",["skills","interests"]]]){$(container).replaceChildren(...keys.map(k=>editableField(k,labels[k],draft.fields[k],{id:"field-"+k,wide:["name","bio","skills","interests"].includes(k),multiline:["bio","skills","interests"].includes(k),max:view.limits.fields[k],origin:fieldOrigin(k),onInput:value=>{draft.fields[k]=value;},reset:()=>{draft.fields[k]=view.profile.fields[k];renderFields();updateControls();}})));}}
  function renderCareers(){const list=cardMode()?$("cardCareerRows"):$("careerRows");if(!list)return;list.replaceChildren();if(!draft.careers.length)list.append(empty("아직 적은 경력이 없어요. 프로젝트 하나부터 시작해도 좋습니다."));draft.careers.forEach((row,index)=>{const section=node("article","career-row");const head=node("div","career-heading");head.append(node("h3","",`경력·프로젝트 ${index+1}`),button("이 경력 제외",()=>{draft.careers.splice(index,1);renderCareers();updateControls();$("addCareer").focus();}));section.append(head);const grid=node("div","field-grid");for(const [k,label] of Object.entries(careerLabels))grid.append(editableField(k,label,row[k]||"",{id:`career-${row._key}-${k}`,wide:k==="title"||k==="description",multiline:k==="description",max:view.limits.career_fields[k],onInput:value=>{row[k]=value;}}));section.append(grid,node("p","section-help",row.id?fieldOrigin("career:"+row.id):"직접 입력 · 아직 저장하지 않음"));list.append(section);});}
  function renderSources(){const list=$("sourceList");list.replaceChildren();const shown=view.sources.filter(s=>s.status!=="deleted");
    for(const source of shown){const row=node("article","source-row"),head=node("div","source-heading");head.append(node("h3","",source.name),node("span","source-state",date(source.created_at)));row.append(head);
      if(source.status==="deleting"){row.append(node("p","source-meta","삭제를 마치지 못했어요. 다시 시도해 주세요."));const retry=deletionRetries.get(source.id);row.append(button("삭제 다시 시도",()=>retry?perform(retry):mutation("source-action",{id:source.id,action:"delete"})));}
      else{const actions=node("div","source-actions");if(source.status==="active")actions.append(button("제안 보기",()=>readSource(source)));actions.append(button("자료 삭제",()=>confirmSource(source),"text-button danger"));row.append(actions);}
      list.append(row);}}
  function itemLabel(key){if(key.startsWith("career:")){const row=view.profile.careers.find(r=>r.id===key.slice(7));return row?.title||"경력·프로젝트";}if(key.startsWith("source:"))return "근거 자료";return labels[key]||key;}
  function compare(current,proposed,currentLabel="현재 저장값",proposedLabel="제안 값"){const box=node("div","comparison");for(const [label,value] of [[currentLabel,current],[proposedLabel,proposed]]){const col=node("div");col.append(node("h4","",label),node("pre","",text(value)||"미입력"));box.append(col);}return box;}
  // ---- A document the company AI read: the card as it is (left) beside what it proposes (right).
  // Every proposed piece starts included and is pressed to leave it out; the kept ones go into the
  // draft like typed edits, so nothing reaches the card until 변경 저장.
  const listItems=value=>String(value||"").split(String(value||"").includes("\n")?"\n":/[,;]+/).map(v=>v.trim()).filter(Boolean);
  const listJoin=(entries,like)=>entries.join(String(like||"").includes("\n")||entries.some(e=>e.includes(","))?"\n":", ");
  const careerLine=c=>[c.period,c.title].filter(Boolean).join(" · ");
  const DIGEST_ROWS=[["bio","약력"],["skills","대표 기술"],["interests","관심 분야"],["careers","이력의 발자취"]];
  function digestRows(p){return DIGEST_ROWS.filter(([key])=>key==="bio"?!!p?.bio_addition:(p?.[key]||[]).length>0);}
  const withAddition=(bio,addition)=>[String(bio||"").trim(),addition].filter(Boolean).join(" ");
  // A long document keeps the company AI reading longer than a phone holds a silent request open, so the server
  // answers "reading" and the page asks again every 2 s; an ask lost on the way is asked again (the reading goes on).
  async function askDigest(id,stillWanted){
    let dropped=0;
    for(;;){
      try{const data=await api("/api/self-profile/digest",{source_id:id});if(data?.status!=="reading")return data;dropped=0;}
      catch(e){if(e.status||!e.uncertain||++dropped>3)throw e;}
      if(!stillWanted())return null;
      await new Promise(resolve=>setTimeout(resolve,2000));
    }
  }
  async function readSource(source){
    if(busy||uncertain||!view)return;const ticket=++digestTicket;busy=true;clearError();
    digest={loading:true,name:source.name,seconds:0};renderDigest();updateControls();
    $("digestView").scrollIntoView({block:"nearest",behavior:"auto"});
    sourceNote("사내 AI가 자료를 읽고 카드에 맞게 정리하고 있어요. 긴 문서는 1~2분 걸려요.");
    const began=Date.now(),tick=setInterval(()=>{if(ticket!==digestTicket||!digest?.loading)return clearInterval(tick);digest.seconds=Math.round((Date.now()-began)/1000);renderDigest();},1000);
    try{const data=await askDigest(source.id,()=>ticket===digestTicket);
      if(!data||ticket!==digestTicket)return;
      digest={...data,skip:new Set()};renderDigest();$("digestView").scrollIntoView({block:"start",behavior:"auto"});$("digestView").focus({preventScroll:true});
      sourceNote(digestRows(data.proposal).length?"제안을 만들었어요. 지금 카드와 나란히 보고 넣을 것만 남겨 주세요.":"이 자료에서 카드에 더할 새 내용을 찾지 못했어요.");}
    catch(e){if(ticket!==digestTicket)return;digest=null;renderDigest();sourceFail(e.message+(e.status?"":" 읽기는 서버에서 이어지니, 잠시 뒤 올린 자료의 ‘제안 보기’를 눌러 주세요."));}
    finally{clearInterval(tick);busy=false;updateControls();}
  }
  function closeDigest(){digestTicket++;digest=null;renderDigest();sourceNote("제안을 닫았어요. 올린 자료의 ‘제안 보기’로 다시 열 수 있어요.");}
  // A proposed piece: pressing it leaves it out or back in; ✎ beside it edits its words in place.
  function proposalItem(id,content,cls){
    const wrap=node("span","digest-item"+(cls.includes("digest-chip")?"":" is-block"));
    const item=node("button",cls);item.type="button";item.dataset.lock="";
    if(typeof content==="string")item.textContent=content;else item.append(...content);
    const show=()=>{const on=!digest.skip.has(id);item.setAttribute("aria-pressed",String(on));item.title=on?"누르면 넣지 않아요":"누르면 다시 넣어요";};
    item.addEventListener("click",()=>{if(digest.skip.has(id))digest.skip.delete(id);else digest.skip.add(id);show();});show();
    const pen=button("✎",()=>{digest.editing=id;renderDigest();},"digest-edit");pen.title="고치기";pen.setAttribute("aria-label","이 제안 고치기");
    wrap.append(item,pen);return wrap;
  }
  // The editor that replaces a piece while it is edited; an edited piece goes in (it was worth fixing).
  function proposalEditor(id,fields,save){
    const form=node("div","digest-editor"),inputs={};
    for(const f of fields){const label=node("label","",f.label),input=node(f.rows?"textarea":"input");if(f.rows)input.rows=f.rows;else input.type="text";
      input.value=f.value||"";input.maxLength=f.max;label.append(input);inputs[f.key]=input;form.append(label);}
    const close=()=>{digest.editing=null;renderDigest();};
    const done=()=>{const values=Object.fromEntries(Object.entries(inputs).map(([k,input])=>[k,input.value.trim()]));if(save(values)!==false)digest.skip.delete(id);close();};
    form.addEventListener("keydown",e=>{if(e.key==="Escape"){e.preventDefault();close();}else if(e.key==="Enter"&&e.target.tagName==="INPUT"){e.preventDefault();done();}});
    const actions=node("div","digest-editor-actions");actions.append(button("고치기 완료",done,"primary-button"),button("취소",close,"secondary-button"));form.append(actions);
    setTimeout(()=>form.querySelector("input,textarea")?.focus(),0);
    return form;
  }
  function renderDigest(){
    const host=$("digestView");host.replaceChildren();host.hidden=!digest;if(!digest)return;
    const head=node("div","digest-head"),title=node("div");title.append(node("h3","",`「${digest.name}」에서 찾은 내용`));head.append(title);host.append(head);
    if(digest.loading){host.setAttribute("aria-busy","true");const note=node("p","digest-summary","사내 AI가 읽고 있어요");if(digest.seconds){const time=node("span","",` · ${digest.seconds}초`);time.setAttribute("aria-hidden","true");note.append(time);}title.append(note);return;}
    host.removeAttribute("aria-busy");
    const p=digest.proposal||{},close=button("×",closeDigest,"close-button");close.setAttribute("aria-label","제안 닫기");head.append(close);
    if(p.summary)title.append(node("p","digest-summary",p.summary));
    const rows=digestRows(p);
    if(!rows.length){host.append(empty("이 자료에서 카드에 더할 새 내용을 찾지 못했어요."));return;}
    host.append(node("p","section-help","오른쪽에서 강조된 항목이 카드에 들어가요. 넣지 않을 항목은 눌러서 빼고, ✎로 내용을 고칠 수 있어요."));
    for(const [key,label] of rows){
      const row=node("section","digest-row"),now=node("div","digest-col"),next=node("div","digest-col is-next");
      row.append(node("h4","digest-label",label));now.append(node("span","digest-side","지금 카드"));next.append(node("span","digest-side","AiU 제안"));
      if(key==="bio"){now.append(node("p","digest-text",draft.fields.bio||"비어 있어요"));next.append(digest.editing==="bio"?proposalEditor("bio",[{key:"text",label:"덧붙일 문장",value:p.bio_addition,rows:4,max:view.limits.fields.bio}],v=>v.text?(p.bio_addition=v.text,true):false)
          :proposalItem("bio","＋ "+p.bio_addition,"digest-add digest-text"));
        if(draft.fields.bio)next.append(node("p","digest-none","지금 약력 뒤에 덧붙여요."));}
      else if(key==="careers"){
        const rowsNow=draft.careers.filter(c=>c.title);
        if(!rowsNow.length)now.append(node("p","digest-none","비어 있어요"));
        for(const c of rowsNow)now.append(node("p","digest-career",careerLine(c)));
        p.careers.forEach((c,i)=>{const meta=[c.organization,c.role].filter(Boolean).join(" · "),id="career:"+i;
          if(digest.editing===id){next.append(proposalEditor(id,Object.entries(careerLabels).map(([k,label])=>({key:k,label,value:c[k],max:view.limits.career_fields[k],rows:k==="description"?4:0})),
            v=>v.title?(p.careers[i]={...c,...v},true):false));return;}
          next.append(proposalItem(id,[node("strong","",careerLine(c)),...(meta?[node("small","",meta)]:[]),node("span","",c.description)],"digest-add digest-career"));});
        if(rowsNow.length)next.append(node("p","digest-none",`지금 이력 ${rowsNow.length}개는 그대로 둬요.`));
      }else{
        const current=listItems(draft.fields[key]),chips=node("div","digest-chips"),nextChips=node("div","digest-chips");
        if(!current.length)chips.append(node("span","digest-none","비어 있어요"));
        for(const v of current)chips.append(node("span","digest-chip",v));
        p[key].forEach((v,i)=>{const id=key+":"+i;
          nextChips.append(digest.editing===id?proposalEditor(id,[{key:"value",label:label+" 고치기",value:v,max:60}],e=>e.value?(p[key][i]=e.value,true):false)
            :proposalItem(id,v,"digest-add digest-chip"));});
        now.append(chips);next.append(nextChips);
        if(current.length)next.append(node("p","digest-none",`지금 ${current.length}개는 그대로 두고 더해요.`));
      }
      const cols=node("div","digest-cols");cols.append(now,next);row.append(cols);host.append(row);
    }
    const actions=node("div","button-row");actions.append(button("남긴 제안을 카드에 넣기",applyDigest,"primary-button"),button("넣지 않고 닫기",closeDigest,"secondary-button"));
    host.append(actions,node("p","section-help",`넣은 뒤에도 아래 ‘변경 저장’을 눌러야 ${cardMode()?"연구맵에 보여요":"저장돼요"}.`));
  }
  function applyDigest(){
    if(!digest?.proposal||busy)return;const p=digest.proposal,keep=id=>!digest.skip.has(id);let count=0;
    if(p.bio_addition&&keep("bio")){draft.fields.bio=withAddition(draft.fields.bio,p.bio_addition);count++;}
    for(const key of ["skills","interests"]){const current=listItems(draft.fields[key]),known=new Set(current.map(v=>v.toLowerCase()));
      const added=(p[key]||[]).filter((v,i)=>keep(key+":"+i)&&!known.has(v.toLowerCase()));if(added.length){draft.fields[key]=listJoin([...current,...added],draft.fields[key]);count+=added.length;}}
    (p.careers||[]).forEach((c,i)=>{if(!keep("career:"+i)||draft.careers.length>=view.limits.careers)return;draft.careers.push({_key:requestId(),...Object.fromEntries(Object.keys(careerLabels).map(k=>[k,c[k]||""]))});count++;});
    digestTicket++;digest=null;renderDigest();
    if(!count){sourceNote("넣을 제안을 남기지 않아 카드는 그대로예요.");return;}
    cardEditing=null;cardBefore=null;renderFields();renderCareers();updateControls();
    if(cardMode())scheduleCard(0);(cardMode()?$("cardEditor"):$("basics")).scrollIntoView({block:"start",behavior:"auto"});
    sourceNote(`제안 ${count}개를 카드에 넣었어요. 확인한 뒤 ‘변경 저장’을 눌러야 ${cardMode()?"연구맵에 보여요":"저장돼요"}.`);
  }
  function renderHistory(){$("historyCount").textContent=String(view.history.length);const list=$("historyList");list.replaceChildren();if(!view.history.length)list.append(empty("저장과 자료 검토를 마치면 변경 기록이 남습니다."));for(const h of [...view.history].reverse()){const row=node("article","history-entry");row.append(node("strong","",`${itemLabel(h.field||"")} · v${h.version}`),node("p","source-meta",`${date(h.at)} · ${view.scope.reviewer_label}`));if(h.redacted)row.append(node("p","","관련 자료가 삭제되어 이전·이후 내용은 표시하지 않습니다."));else if(h.before!=null||h.after!=null)row.append(compare(h.before,h.after,"변경 전","변경 후"));else row.append(node("p","",{delete_source:"자료와 파생내용 삭제",unlink_source:"자료 연결 변경",remove_item:"항목 제외"}[h.action]||"자료 상태 변경"));list.append(row);}}
  async function perform(request){if(busy)return;busy=true;clearError();const local=request.route==="upload"||request.route==="source-action",note=local?sourceNote:announce,fail=local?sourceFail:showError;$("actionError").hidden=true;updateControls();try{const data=await api("/api/self-profile/"+request.route,request.payload);uncertain=null;adopt(data,{preserve:request.route!=="save"});if(request.route==="source-action"){
        if(request.payload.action==="delete"){if(data.operation?.deletion_pending)deletionRetries.set(request.payload.id,request);else deletionRetries.delete(request.payload.id);if(digest?.source_id===request.payload.id){digestTicket++;digest=null;renderDigest();}renderSources();}
        if($("actionDialog").open)$("actionDialog").close();action=null;
      }
      const messages={save:cardMode()?"저장했어요. 연구맵 카드에도 바로 반영했어요.":"선택한 변경을 초안에 저장했습니다.",upload:data.operation?.duplicate?"이미 올린 같은 자료예요. 그 자료로 제안을 보여 드릴게요.":"자료를 받았어요.","source-action":data.operation?.deletion_pending?"읽은 내용은 더 쓰지 않아요. 저장 파일 삭제는 다시 시도해 주세요.":"자료를 삭제했어요."};note(messages[request.route]);return data;
    }catch(e){if(e.uncertain){uncertain=request;if($("actionDialog").open)$("actionDialog").close();fail(e.message+" 중복 적용을 막기 위해 같은 요청으로 다시 확인해 주세요.",()=>perform(uncertain));}else{uncertain=null;fail(e.message);if(e.status===409){conflict={ready:false};$("conflictPanel").hidden=false;$("conflictActions").hidden=true;$("conflictComparison").replaceChildren();if($("actionDialog").open)$("actionDialog").close();}if($("actionDialog").open){$("actionError").textContent=e.message;$("actionError").hidden=false;}}}finally{busy=false;updateControls();}}
  function mutation(route,payload,extra={}){if(conflict){showError("최신 저장값과 작성 중 입력을 먼저 비교해 주세요.");return;}return perform({route,payload:{...payload,base_version:view.profile.version,request_id:requestId()},...extra});}
  function openDialog(id,opener=document.activeElement){dialogOpeners.set(id,opener);$(id).showModal();}
  function confirmSource(source){action={source};$("actionTitle").textContent="자료를 삭제할까요?";$("actionDescription").textContent="읽은 내용과 이 자료로 만든 제안을 지웁니다. 카드에 넣어 저장한 내용은 그대로 남아요. 원본 파일은 처음부터 보관하지 않았어요.";const linked=(source.impact?.profile_items||[]).map(itemLabel);$("actionImpact").textContent=source.name+(linked.length?`\n예전에 이 자료와 연결해 채택한 항목도 함께 지워져요: ${linked.join(", ")}`:"");$("actionError").hidden=true;$("confirmAction").textContent="자료 삭제";openDialog("actionDialog");}
  $("confirmAction").addEventListener("click",()=>{if(action)mutation("source-action",{id:action.source.id,action:"delete"});});
  document.querySelectorAll("[data-close]").forEach(b=>b.addEventListener("click",()=>{if(!busy)$(b.dataset.close).close();}));for(const id of ["actionDialog"]){$(id).addEventListener("cancel",e=>{if(busy)e.preventDefault();});$(id).addEventListener("close",()=>{const opener=dialogOpeners.get(id);if(opener?.isConnected)opener.focus();else $("sourceFile").focus();});}
  function addCareerRow(){if(draft.careers.length>=view.limits.careers){showError(`경력은 ${view.limits.careers}개까지 추가할 수 있습니다.`);return;}const row={_key:requestId(),...Object.fromEntries(Object.keys(careerLabels).map(k=>[k,""]))};draft.careers.push(row);renderCareers();updateControls();$("career-"+row._key+"-title").focus();}
  $("addCareer").addEventListener("click",addCareerRow);
  $("profileForm").addEventListener("submit",event=>{event.preventDefault();if(busy||uncertain||conflict||!view)return;const changed=manualChanges(),payload={fields:changed.fields,decisions:[]};if(changed.careers)payload.careers=cleanCareers(draft.careers);if(hasChanges())mutation("save",payload);});
  // Documents go in 512 KB pieces like chat attachments (one 8 MB request failed from a phone);
  // the profile then claims the staged file by its upload id and the company AI reads it.
  async function sendPieces(file){
    if(!crypto.subtle)throw new Error("이 브라우저에서 파일 무결성 확인을 사용할 수 없어요.");
    let raw;try{raw=await file.arrayBuffer();}catch(_){throw new Error("파일을 읽지 못했습니다. 선택한 파일을 확인해 주세요.");}
    const hash=await crypto.subtle.digest("SHA-256",raw),sha256=Array.from(new Uint8Array(hash),b=>b.toString(16).padStart(2,"0")).join("");
    const begin=await api("/api/attachments/begin",{name:file.name,size:raw.byteLength,sha256});
    const id=begin?.upload_id,size=begin?.chunk_bytes,count=begin?.chunk_count;
    if(!/^[a-f0-9]{32}$/.test(id||"")||!Number.isSafeInteger(size)||size<1||count!==Math.ceil(raw.byteLength/size))throw new Error("파일 분할 전송 설정을 확인하지 못했어요.");
    try{
      for(let index=0;index<count;index++){
        sourceNote(`자료를 보내고 있어요 (${Math.round(index/count*100)}%)`);
        const bytes=new Uint8Array(raw,index*size,Math.min(size,raw.byteLength-index*size));let text="";
        for(let i=0;i<bytes.length;i+=32768)text+=String.fromCharCode.apply(null,bytes.subarray(i,i+32768));
        const got=await api("/api/attachments/chunk",{upload_id:id,index,data:btoa(text)});
        if(got?.upload_id!==id||got.index!==index||got.received!==true)throw new Error("파일 조각의 전송 결과를 확인하지 못했어요.");
      }
    }catch(e){api("/api/attachments/cancel",{upload_id:id}).catch(()=>{});throw e;}
    return id;
  }
  $("sourceFile").addEventListener("change",async event=>{const file=event.target.files[0];event.target.value="";if(!file||busy||uncertain||!view)return;
    if(!view.limits.formats.includes(file.name.split(".").pop().toLowerCase())){sourceFail("PDF·DOCX·텍스트 문서를 선택해 주세요. 이미지와 스캔 문서는 읽지 못해요.");return;}
    if(file.size===0||file.size>view.limits.file_bytes){sourceFail(`빈 파일이거나 ${Math.round(view.limits.file_bytes/1048576)} MB를 넘었어요.`);return;}
    busy=true;clearError();updateControls();let uploadId=null;
    try{uploadId=await sendPieces(file);}catch(e){sourceFail(e.message);}finally{busy=false;updateControls();}
    if(!uploadId)return;
    const data=await mutation("upload",{upload_id:uploadId}),id=data?.operation?.source_id,source=id&&view.sources.find(s=>s.id===id);
    if(source)readSource(source);
  });
  $("refreshConflict").addEventListener("click",async()=>{if(busy)return;busy=true;updateControls();try{const latest=await api("/api/self-profile");adopt(latest);conflict={ready:true};const box=$("conflictComparison");box.replaceChildren();for(const [k,value] of Object.entries(manualChanges().fields)){const heading=node("h3","",labels[k]);box.append(heading,compare(latest.profile.fields[k],value,"최신 저장값","작성 중인 내 입력"));}if(manualChanges().careers)box.append(node("h3","","경력·프로젝트"),compare(latest.profile.careers,cleanCareers(draft.careers),"최신 저장값","작성 중인 내 입력"));if(!box.childNodes.length)box.append(empty("직접 입력의 차이는 없습니다. 남겨둔 자료 선택도 다시 비교해 주세요."));$("conflictActions").hidden=false;announce("최신 값을 읽었습니다. 작성 중 입력과 비교한 뒤 아래에서 선택해 주세요.");}catch(e){showError(e.message);}finally{busy=false;updateControls();}});
  $("keepEdits").addEventListener("click",()=>{if(!conflict?.ready)return;const ids=new Set(view.profile.careers.map(r=>r.id));if(draft.careers.some(r=>r.id&&!ids.has(r.id))){showError("저장소에서 삭제된 경력이 편집 중 목록에 남아 있습니다. 해당 경력을 제외하거나 최신 저장값을 사용해 주세요.");return;}conflict=null;$("conflictPanel").hidden=true;clearError();updateControls();announce("내 수정을 유지했습니다. 확인한 뒤 다시 저장해 주세요.");});
  $("useLatest").addEventListener("click",()=>{if(!conflict?.ready)return;draft=draftFrom(view.profile);conflict=null;$("conflictPanel").hidden=true;clearError();render();announce("확인한 최신 저장값을 사용합니다.");});
  window.addEventListener("rndplz:before-account-navigation",event=>{
    event.detail.checkedScopes.push("profile");
    if(accountNavigationPending||busy||uncertain){event.preventDefault();event.detail.message="프로필 처리 결과를 먼저 확인해 주세요. 입력과 선택은 유지했습니다.";return;}
    if(hasChanges())event.detail.dirty=true;
  });
  window.addEventListener("rndplz:account-navigation",event=>{
    accountNavigationPending=event.detail?.phase!=="cancel";
    if(event.detail?.phase==="invalidate"){accountInvalidated=true;digestTicket++;token="";}
    updateControls();
  });
  window.addEventListener("beforeunload",event=>{if(!accountNavigationPending&&(hasChanges()||uncertain)){event.preventDefault();event.returnValue="";}});
  async function load(){busy=true;updateControls();try{const data=await api("/api/self-profile");adopt(data,{preserve:false});announce(data.profile.id?"저장한 초안을 불러왔습니다.":"아직 저장한 프로필이 없습니다. 직접 작성하거나 자료를 추가해 보세요.");}catch(e){showError(e.message);const retry=button("프로필 다시 불러오기",load,"secondary-button");delete retry.dataset.lock;$("pageError").append(retry);}finally{busy=false;updateControls();}}
  load();
})();
