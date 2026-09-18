/* A private draft: explicit edits and document choices, with no model calls. */
(() => {
  "use strict";
  const $ = id => document.getElementById(id);
  const labels = {name:"표시 이름",organization:"소속·부서",role:"현재 역할",bio:"짧은 소개",skills:"다뤄본 분야·기술",interests:"관심 분야",career:"경력·프로젝트 설명"};
  const careerLabels = {title:"경력·프로젝트명",organization:"소속·조직",period:"기간",role:"맡은 역할",description:"한 일과 적용 조건"};
  const choices = {accept:"채택",edit:"수정해서 채택",exclude:"제외",defer:"나중에 검토"};
  const reviewed = {pending:"미검토",accepted:"채택됨",edited_accepted:"수정 후 채택됨",excluded:"제외됨",deferred:"보류됨",withdrawn:"근거 변경 · 재확인 필요",redacted:"관련 자료 삭제됨"};
  let view=null, token="", draft=null, busy=false, conflict=null, uncertain=null, action=null;
  let previewRequest=null, previewGeneration=0;
  const selections=new Map(), deletionRetries=new Map(), dialogOpeners=new Map();
  const clone=value=>JSON.parse(JSON.stringify(value));
  const requestId=()=>crypto.randomUUID().replaceAll("-","");
  const text=value=>value==null?"":typeof value==="string"?value:JSON.stringify(value,null,2);
  const date=value=>value?new Intl.DateTimeFormat("ko-KR",{dateStyle:"medium",timeStyle:"short"}).format(new Date(value)):"아직 저장하지 않음";
  function node(tag,cls,value){const n=document.createElement(tag);if(cls)n.className=cls;if(value!==undefined)n.textContent=value;return n;}
  function button(label,fn,cls="text-button"){const b=node("button",cls,label);b.type="button";b.dataset.lock="";b.addEventListener("click",fn);return b;}
  function empty(message){return node("p","empty-note",message);}
  function announce(message){$("pageStatus").textContent=message;}
  function clearError(){$("pageError").hidden=true;$("pageError").replaceChildren();}
  function showError(message,retry){const box=$("pageError");box.replaceChildren(node("p","",message));if(retry){const b=button("같은 요청으로 다시 확인",retry,"secondary-button");delete b.dataset.lock;box.append(b);}box.hidden=false;box.focus();}
  function cleanCareers(rows){return rows.map(row=>{const value={};if(row.id)value.id=row.id;for(const k of Object.keys(careerLabels))value[k]=row[k]||"";return value;});}
  function manualChanges(){if(!view||!draft)return {fields:{},careers:false};const fields={};for(const k of Object.keys(view.profile.fields))if(draft.fields[k]!==view.profile.fields[k])fields[k]=draft.fields[k];return {fields,careers:JSON.stringify(cleanCareers(draft.careers))!==JSON.stringify(cleanCareers(view.profile.careers))};}
  function hasChanges(){const c=manualChanges();return Object.keys(c.fields).length+(c.careers?1:0)+selections.size;}
  function fieldOrigin(key){const p=view.profile.provenance[key];if(!p)return "근거 미제공";const origin={user_input:"직접 입력",source_claim:"자료에서 추출",user_edited_source:"자료를 바탕으로 직접 수정"}[p.origin]||"출처 확인 필요";const status={linked_claim:"근거 연결됨",not_provided:"근거 미제공",requires_review:"근거 재확인 필요",source_deleted:"연결 자료 삭제됨"}[p.evidence_status]||"근거 상태 확인 필요";return `${origin} · ${status}`;}
  function updateControls(){const locked=busy||!view||!!uncertain;$("profileFields").disabled=locked;document.querySelectorAll("[data-lock]").forEach(el=>el.disabled=locked);$("saveProfile").disabled=locked||!hasChanges()||!!conflict;$("changeCount").textContent=hasChanges()?`변경 ${hasChanges()}개 · 아직 저장하지 않음`:"변경 없음";$("saveProfile").firstChild.textContent=busy?"처리 중 ":`변경 ${hasChanges()||""}${hasChanges()?"개 ":""}저장 `;if(draft){$("previewName").textContent=draft.fields.name.trim()||"당신의 이름";$("previewRole").textContent=[draft.fields.organization,draft.fields.role].filter(Boolean).join("\n")||"지금 하는 일부터 적어보세요.";}}
  async function api(path,payload){const options={credentials:"same-origin",cache:"no-store"};if(payload!==undefined)Object.assign(options,{method:"POST",headers:{"Content-Type":"application/json","X-Rndplz-Token":token},body:JSON.stringify(payload)});let response,data;try{response=await fetch(path,options);}catch(_){const e=new Error("전송 결과를 확인하지 못했습니다. 입력은 그대로 두었습니다.");e.uncertain=payload!==undefined;throw e;}try{data=await response.json();}catch(_){const e=new Error("서버 응답을 확인하지 못했습니다. 입력은 그대로 두었습니다.");e.uncertain=payload!==undefined;throw e;}if(!response.ok){const e=new Error(typeof data.error==="string"?data.error:"요청을 처리하지 못했습니다. 입력은 그대로 두었습니다.");e.status=response.status;e.code=data.code;e.uncertain=payload!==undefined&&response.status>=500;throw e;}return data;}
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
    const live=new Set(data.suggestions.filter(p=>["pending","excluded","deferred"].includes(p.decision)).map(p=>p.id));
    for(const id of selections.keys())if(!live.has(id))selections.delete(id);
    render();
    if(removed)announce(`삭제된 자료에서 나온 편집 ${removed}개를 지웠습니다. 독립적으로 작성한 입력은 유지했습니다.`);
  }
  function render(){
    $("scopeNotice").textContent=view.scope.notice;$("saveScope").textContent=(view.scope.kind==="visitor_private"?"이 방문자의 초안":"로컬 작업의 초안")+"에 저장 · 외부 비공유";
    $("savedVersion").textContent=view.profile.id?`초안 v${view.profile.version}\n마지막 저장 ${date(view.profile.updated_at)}`:"저장된 프로필 없음";
    $("uploadLimits").textContent=`${view.limits.formats.map(x=>x.toUpperCase()).join(" · ")} / 파일당 ${Math.round(view.limits.file_bytes/1024/1024)} MiB / 최대 ${view.limits.sources}개. 이미지·OCR 미지원.`;
    $("sourceFile").accept=view.limits.formats.map(x=>"."+x).join(",");
    renderFields();renderCareers();renderSources();renderSuggestions();renderHistory();updateControls();
  }
  function editableField(key,label,value,{wide=false,multiline=false,max=2000,onInput,id,origin,reset}={}){
    const wrap=node("div","profile-field"+(wide?" wide":"")),lab=node("label","",label);lab.htmlFor=id;
    const input=node(multiline?"textarea":"input");input.id=id;input.name=key;input.value=value;input.maxLength=max;if(multiline)input.rows=key==="bio"?3:4;else input.type="text";
    input.addEventListener("input",()=>{onInput(input.value);updateControls();});wrap.append(lab,input);
    if(origin!==undefined){const meta=node("div","field-meta");meta.append(node("span","",origin));if(reset)meta.append(button("저장값으로 되돌리기",reset));wrap.append(meta);}return wrap;
  }
  function renderFields(){for(const [container,keys] of [["basicFields",["name","organization","role","bio"]],["expertiseFields",["skills","interests"]]]){$(container).replaceChildren(...keys.map(k=>editableField(k,labels[k],draft.fields[k],{id:"field-"+k,wide:["name","bio","skills","interests"].includes(k),multiline:["bio","skills","interests"].includes(k),max:view.limits.fields[k],origin:fieldOrigin(k),onInput:value=>{draft.fields[k]=value;},reset:()=>{draft.fields[k]=view.profile.fields[k];renderFields();renderSuggestions();updateControls();}})));}}
  function renderCareers(){const list=$("careerRows");list.replaceChildren();if(!draft.careers.length)list.append(empty("아직 적은 경력이 없어요. 프로젝트 하나부터 시작해도 좋습니다."));draft.careers.forEach((row,index)=>{const section=node("article","career-row");const head=node("div","career-heading");head.append(node("h3","",`경력·프로젝트 ${index+1}`),button("이 경력 제외",()=>{draft.careers.splice(index,1);renderCareers();renderSuggestions();updateControls();$("addCareer").focus();}));section.append(head);const grid=node("div","field-grid");for(const [k,label] of Object.entries(careerLabels))grid.append(editableField(k,label,row[k]||"",{id:`career-${row._key}-${k}`,wide:k==="title"||k==="description",multiline:k==="description",max:view.limits.career_fields[k],onInput:value=>{row[k]=value;}}));section.append(grid,node("p","section-help",row.id?fieldOrigin("career:"+row.id):"직접 입력 · 아직 저장하지 않음"));list.append(section);});}
  function renderSources(){const list=$("sourceList");list.replaceChildren();if(!view.sources.length)list.append(empty("등록한 자료가 없습니다. 자료 없이도 프로필을 직접 작성할 수 있어요."));for(const source of view.sources){const row=node("article","source-row"),head=node("div","source-heading"),state={active:source.truncated?"일부 읽음":"텍스트 읽음",unlinked:"연결 해제됨",replaced:"다른 자료로 교체됨",deleting:"삭제 처리 중",deleted:"삭제됨"}[source.status]||"상태 확인 필요";head.append(node("h3","",source.name),node("span","source-state",state));row.append(head);
      if(!["deleted","deleting"].includes(source.status)){row.append(node("p","source-meta",`자료 v${source.version} · ${date(source.created_at)} · 추출문 ${Number(source.characters||0).toLocaleString()}자\n${source.truncated?"일부 텍스트만 저장되었습니다. 읽지 못한 내용은 반영하지 않습니다. ":""}원본 미보관 · 위치는 추출문 기준 · 이 초안에서만 열람`));const actions=node("div","source-actions");actions.append(button("읽은 내용 보기",e=>previewSource(source,e.currentTarget)));if(source.status==="active")actions.append(button("작성할 항목 찾기",()=>suggest([source.id],true)),button("연결 해제",()=>confirmSource(source,"unlink")),button("새 자료로 교체",()=>confirmSource(source,"replace")));actions.append(button("읽은 내용 삭제",()=>confirmSource(source,"delete"),"text-button danger"));row.append(actions);const impacted=source.impact?.profile_items||[];if(impacted.length)row.append(node("p","source-meta","연결된 항목: "+impacted.map(itemLabel).join(", ")));}
      else if(source.status==="deleting"){row.append(node("p","source-meta","초안의 파생내용과 열람은 이미 차단됐습니다. 저장 파일 정리를 마치지 못했습니다."));const retry=deletionRetries.get(source.id);if(retry)row.append(button("삭제 처리 다시 시도",()=>perform(retry)));else row.append(button("삭제 처리 다시 시도",()=>mutation("source-action",{id:source.id,action:"delete"})));}list.append(row);}}
  function itemLabel(key){if(key.startsWith("career:")){const row=view.profile.careers.find(r=>r.id===key.slice(7));return row?.title||"경력·프로젝트";}if(key.startsWith("source:"))return "근거 자료";return labels[key]||key;}
  function option(value,label){const o=node("option","",label);o.value=value;return o;}
  function compare(current,proposed,currentLabel="현재 저장값",proposedLabel="제안 값"){const box=node("div","comparison");for(const [label,value] of [[currentLabel,current],[proposedLabel,proposed]]){const col=node("div");col.append(node("h4","",label),node("pre","",text(value)||"미입력"));box.append(col);}return box;}
  function currentValue(selected){if(!selected?.field)return "적용할 항목을 선택하면 현재 값이 보입니다.";if(selected.field==="career")return selected.item_id?(view.profile.careers.find(x=>x.id===selected.item_id)?.description||""):"새 경력의 설명으로 추가";return view.profile.fields[selected.field]||"";}
  function renderSuggestions(){const list=$("suggestionList");list.replaceChildren();const pending=view.suggestions.filter(p=>["pending","deferred","excluded"].includes(p.decision));$("reviewCount").textContent=String(pending.length);$("refreshSuggestions").hidden=!pending.length;if(!view.suggestions.length){list.append(empty("자료의 ‘작성할 항목 찾기’를 누르면 문서의 문장을 여기서 비교할 수 있어요."));return;}
    for(const [index,p] of view.suggestions.entries()){const card=node("article","suggestion-card"),head=node("div","suggestion-head");card.id="suggestion-"+p.id;head.append(node("h3","",`자료 문장 ${index+1}`),node("span","",reviewed[p.decision]||"미검토"));card.append(head);const source=view.sources.find(s=>s.id===p.source_id);if(["redacted","withdrawn"].includes(p.decision)){card.append(node("p","review-done",p.decision==="redacted"?"관련 자료가 삭제되어 이 내용은 표시하지 않습니다.":"자료의 연결 또는 버전이 바뀌어 채택할 수 없습니다."));list.append(card);continue;}
      card.append(node("p","source-meta",`${source?.name||"자료"} · 자료 v${p.source_version} · 추출문 ${p.location?.line||1}줄, 문자 ${Number(p.location?.start||0)+1}–${p.location?.end||0}`),node("blockquote","",p.quote||""));
      if(["accepted","edited_accepted"].includes(p.decision)){card.append(node("p","review-done",`${itemLabel(p.target||p.field||"")} · ${view.scope.reviewer_label} · 본인·경력 확인과 별개`));list.append(card);continue;}
      const selected=selections.get(p.id)||{decision:"",field:"",value:p.after||"",item_id:""};
      const controls=node("div","suggestion-controls");const fieldLabel=node("label","","적용할 항목"),fieldSelect=node("select");fieldSelect.id="target-"+p.id;fieldLabel.htmlFor=fieldSelect.id;fieldSelect.dataset.lock="";fieldSelect.append(option("","아직 분류하지 않음"),...Object.entries(labels).map(([k,v])=>option(k,v)));fieldSelect.value=selected.field;fieldLabel.append(fieldSelect);
      const choiceLabel=node("label","","검토 선택"),choiceSelect=node("select");choiceSelect.id="choice-"+p.id;choiceLabel.htmlFor=choiceSelect.id;choiceSelect.dataset.lock="";choiceSelect.append(option("","선택 안 함 · 미채택"),...Object.entries(choices).map(([k,v])=>option(k,v)));choiceSelect.value=selected.decision;choiceLabel.append(choiceSelect);controls.append(fieldLabel,choiceLabel);card.append(controls);
      const comparisons=compare(currentValue(selected),selected.decision==="edit"?selected.value:p.after);card.append(comparisons);
      const editWrap=node("div","edit-value"),editLabel=node("label","","수정한 제안 값"),editInput=node("textarea");editInput.id="edit-"+p.id;editLabel.htmlFor=editInput.id;editInput.rows=4;editInput.value=selected.value;editInput.maxLength=selected.field==="career"?4000:view.limits.fields[selected.field]||4000;editInput.dataset.lock="";editWrap.hidden=selected.decision!=="edit";editWrap.append(editLabel,editInput);card.append(editWrap);
      const careerWrap=node("div","edit-value"),careerLabel=node("label","","적용할 경력"),careerSelect=node("select");careerSelect.id="career-target-"+p.id;careerLabel.htmlFor=careerSelect.id;careerSelect.dataset.lock="";careerSelect.append(option("","새 경력으로 추가"),...view.profile.careers.map((row,i)=>option(row.id,row.title||`경력 ${i+1}`)));careerSelect.value=selected.item_id||"";careerWrap.hidden=selected.field!=="career";careerWrap.append(careerLabel,careerSelect);card.append(careerWrap);
      const stale=node("p","stale-note",p.base_version!==view.profile.version?"후보 생성 뒤 저장값이 바뀌었습니다. 위의 ‘최신 저장값으로 후보 다시 비교’를 눌러 확인해 주세요.":"선택 후 아래 저장 버튼을 눌러야 반영됩니다.");card.append(stale);
      function remember(){if(selected.decision)selections.set(p.id,selected);else selections.delete(p.id);updateComparison();editWrap.hidden=selected.decision!=="edit";careerWrap.hidden=selected.field!=="career";updateControls();}
      // Keep the comparison node stable so typing never loses focus.
      function updateComparison(){const fresh=compare(currentValue(selected),selected.decision==="edit"?selected.value:p.after);comparisons.replaceChildren(...fresh.childNodes);return comparisons;}
      fieldSelect.addEventListener("change",()=>{selected.field=fieldSelect.value;selected.item_id="";careerSelect.value="";editInput.maxLength=selected.field==="career"?4000:view.limits.fields[selected.field]||4000;remember();});choiceSelect.addEventListener("change",()=>{selected.decision=choiceSelect.value;remember();});careerSelect.addEventListener("change",()=>{selected.item_id=careerSelect.value;remember();});editInput.addEventListener("input",()=>{selected.value=editInput.value;remember();});list.append(card);
    }
  }
  function renderHistory(){$("historyCount").textContent=String(view.history.length);const list=$("historyList");list.replaceChildren();if(!view.history.length)list.append(empty("저장과 자료 검토를 마치면 변경 기록이 남습니다."));for(const h of [...view.history].reverse()){const row=node("article","history-entry");row.append(node("strong","",`${itemLabel(h.field||"")} · v${h.version}`),node("p","source-meta",`${date(h.at)} · ${view.scope.reviewer_label}`));if(h.redacted)row.append(node("p","","관련 자료가 삭제되어 이전·이후 내용은 표시하지 않습니다."));else if(h.before!=null||h.after!=null)row.append(compare(h.before,h.after,"변경 전","변경 후"));else row.append(node("p","",{delete_source:"자료와 파생내용 삭제",unlink_source:"자료 연결 변경",remove_item:"항목 제외"}[h.action]||"자료 상태 변경"));list.append(row);}}
  async function perform(request){if(busy)return;busy=true;clearError();$("actionError").hidden=true;updateControls();try{const data=await api("/api/self-profile/"+request.route,request.payload);uncertain=null;if(request.route==="save")selections.clear();adopt(data,{preserve:request.route!=="save"});if(request.route==="source-action"){
        if(request.payload.action==="delete"){if(data.operation?.deletion_pending)deletionRetries.set(request.payload.id,request);else deletionRetries.delete(request.payload.id);$("sourceText").textContent="";if($("sourceDialog").open)$("sourceDialog").close();renderSources();}
        if($("actionDialog").open)$("actionDialog").close();action=null;
      }
      const messages={save:"선택한 변경을 초안에 저장했습니다.",upload:data.operation?.duplicate?"이미 등록한 같은 자료입니다. 기존 자료를 그대로 사용합니다.":"자료의 읽힌 내용을 저장했습니다. ‘작성할 항목 찾기’로 검토를 시작하세요.",suggest:"현재 저장값을 기준으로 후보를 열었습니다. 필요한 문장을 선택해 주세요.","source-action":data.operation?.deletion_pending?"열람과 파생내용은 차단됐습니다. 저장 파일 삭제는 다시 시도해 주세요.":"자료 변경을 반영했습니다."};announce(messages[request.route]);if(request.route==="upload")$("sourceFile").value="";if(request.focusReview){$("review").focus();$("review").scrollIntoView({block:"start",behavior:"auto"});}return data;
    }catch(e){if(e.uncertain){uncertain=request;if($("actionDialog").open)$("actionDialog").close();showError(e.message+" 중복 적용을 막기 위해 같은 요청으로 다시 확인해 주세요.",()=>perform(uncertain));}else{uncertain=null;showError(e.message);if(e.status===409){conflict={ready:false};$("conflictPanel").hidden=false;$("conflictActions").hidden=true;$("conflictComparison").replaceChildren();if($("actionDialog").open)$("actionDialog").close();}if($("actionDialog").open){$("actionError").textContent=e.message;$("actionError").hidden=false;}}}finally{busy=false;updateControls();}}
  function mutation(route,payload,extra={}){if(conflict){showError("최신 저장값과 작성 중 입력을 먼저 비교해 주세요.");return;}return perform({route,payload:{...payload,base_version:view.profile.version,request_id:requestId()},...extra});}
  async function suggest(ids,focusReview=false){if(busy||uncertain)return;if(conflict){showError("저장 충돌의 최신 값을 먼저 확인해 주세요.");return;}return mutation("suggest",{source_ids:ids},{focusReview});}
  function openDialog(id,opener=document.activeElement){dialogOpeners.set(id,opener);$(id).showModal();}
  async function previewSource(source,opener){
    const request={sourceId:source.id,generation:++previewGeneration};previewRequest=request;
    const isCurrent=()=>previewRequest===request&&$("sourceDialog").open&&view.sources.some(s=>s.id===request.sourceId&&!["deleted","deleting"].includes(s.status));
    $("sourceTitle").textContent=source.name+" · 읽은 내용";$("sourceInfo").textContent="추출문을 불러오고 있어요.";$("sourceText").textContent="";openDialog("sourceDialog",opener);
    try{const data=await api("/api/self-profile/source?id="+encodeURIComponent(source.id));if(!isCurrent())return;$("sourceInfo").textContent=`원본 미보관 · 저장된 추출문 기준 · ${data.source.truncated?"일부 읽음":"텍스트 읽음"}`;$("sourceText").textContent=data.text;}
    catch(e){if(isCurrent())$("sourceInfo").textContent=e.message;}
  }
  function confirmSource(source,kind){action={source,kind};$("actionTitle").textContent={delete:"읽은 내용과 파생항목을 삭제할까요?",unlink:"자료의 근거 연결을 해제할까요?",replace:"새 자료로 근거를 교체할까요?"}[kind];$("actionDescription").textContent={delete:"현재 초안에 저장한 추출문과 이 자료에서 나온 값·경력·제안·이전값을 삭제합니다. 자료 기반 경력은 행 전체가 삭제됩니다. 원본 파일은 보관하지 않습니다.",unlink:"추출문은 계속 볼 수 있습니다. 연결된 프로필 값은 남지만 근거 재확인 상태가 되며, 이 자료의 후보는 철회됩니다.",replace:"이미 등록한 새 자료와 버전 관계를 만듭니다. 현재 프로필 값은 그대로 두고 근거를 재확인 상태로 바꿉니다. 새 자료는 별도로 검토해야 합니다."}[kind];const impact=source.impact||{};$("actionImpact").textContent=`${source.name}\n연결 항목 ${(impact.profile_items||[]).length}개: ${(impact.profile_items||[]).map(itemLabel).join(", ")||"없음"}\n관련 후보 ${impact.suggestions||0}개 · 변경 기록 ${impact.history_entries||0}개${kind==="delete"?"\n독립적으로 직접 작성한 항목은 유지합니다. 다른 곳에 이미 전달한 사본의 삭제를 뜻하지 않습니다.":""}`;$("replacementField").hidden=kind!=="replace";$("replacementSource").replaceChildren(option("","새 자료 선택"),...view.sources.filter(s=>s.id!==source.id&&s.status==="active").map(s=>option(s.id,s.name)));$("actionError").hidden=true;$("confirmAction").textContent={delete:"영향 확인 · 삭제",unlink:"연결 해제",replace:"영향 확인 · 교체"}[kind];openDialog("actionDialog");}
  $("confirmAction").addEventListener("click",()=>{if(!action)return;const payload={id:action.source.id,action:action.kind};if(action.kind==="replace"){payload.replacement_id=$("replacementSource").value;if(!payload.replacement_id){$("actionError").textContent="대신 연결할 자료를 선택해 주세요. 새 파일은 먼저 등록해야 합니다.";$("actionError").hidden=false;return;}}mutation("source-action",payload);});
  document.querySelectorAll("[data-close]").forEach(b=>b.addEventListener("click",()=>{if(!busy)$(b.dataset.close).close();}));for(const id of ["sourceDialog","actionDialog"]){$(id).addEventListener("cancel",e=>{if(busy)e.preventDefault();});$(id).addEventListener("close",()=>{if(id==="sourceDialog"&&!$(id).open){previewRequest=null;$("sourceText").textContent="";$("sourceInfo").textContent="";}const opener=dialogOpeners.get(id);if(opener?.isConnected)opener.focus();else $("sourceFile").focus();});}
  $("addCareer").addEventListener("click",()=>{if(draft.careers.length>=view.limits.careers){showError(`경력은 ${view.limits.careers}개까지 추가할 수 있습니다.`);return;}const row={_key:requestId(),...Object.fromEntries(Object.keys(careerLabels).map(k=>[k,""]))};draft.careers.push(row);renderCareers();updateControls();$("career-"+row._key+"-title").focus();});
  $("profileForm").addEventListener("submit",event=>{event.preventDefault();if(busy||uncertain||conflict||!view)return;const changed=manualChanges(),payload={fields:changed.fields,decisions:[]},targets=new Set(Object.keys(changed.fields));if(changed.careers)payload.careers=cleanCareers(draft.careers);
    for(const [id,selected] of selections){const p=view.suggestions.find(p=>p.id===id),d={id,decision:selected.decision};if(["accept","edit"].includes(d.decision)){if(!selected.field){showError("채택할 문장을 적용할 항목부터 선택해 주세요.");$("target-"+id).focus();return;}if(p.base_version!==view.profile.version){showError("후보의 기준이 오래되었습니다. ‘최신 저장값으로 후보 다시 비교’를 눌러 주세요.");$("refreshSuggestions").focus();return;}const target=selected.field==="career"?(selected.item_id?"career:"+selected.item_id:"new:"+id):selected.field;if(targets.has(target)||(changed.careers&&selected.field==="career"&&selected.item_id)){showError("같은 항목의 직접 편집과 자료 선택이 겹칩니다. 한쪽 변경을 취소하고 최종 값 하나를 선택해 주세요.");return;}targets.add(target);d.field=selected.field;if(selected.item_id)d.item_id=selected.item_id;if(selected.decision==="edit")d.value=selected.value;const value=selected.decision==="edit"?selected.value:p.after,limit=selected.field==="career"?4000:view.limits.fields[selected.field];if(value.length>limit){showError(`${labels[selected.field]}은 ${limit}자까지 저장할 수 있습니다. ‘수정해서 채택’으로 줄여 주세요.`);return;}}payload.decisions.push(d);}if(hasChanges())mutation("save",payload);});
  $("sourceFile").addEventListener("change",async event=>{const file=event.target.files[0];if(!file||busy||uncertain||!view)return;if(!view.limits.formats.includes(file.name.split(".").pop().toLowerCase())){showError("텍스트·PDF·DOCX 문서를 선택해 주세요. 이미지와 OCR은 지원하지 않습니다.");return;}if(file.size===0||file.size>view.limits.file_bytes){showError("빈 자료이거나 파일 용량 제한을 넘었습니다.");return;}busy=true;updateControls();announce("자료에서 텍스트를 읽고 있습니다.");try{const data=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(String(reader.result).split(",")[1]);reader.onerror=()=>reject(new Error("파일을 읽지 못했습니다. 선택한 파일을 다시 확인해 주세요."));reader.readAsDataURL(file);});busy=false;await mutation("upload",{name:file.name,data});}catch(e){showError(e.message);}finally{busy=false;updateControls();}});
  $("refreshSuggestions").addEventListener("click",()=>{const ids=[...new Set(view.suggestions.filter(p=>["pending","excluded","deferred"].includes(p.decision)&&view.sources.some(s=>s.id===p.source_id&&s.status==="active")).map(p=>p.source_id))];if(ids.length)suggest(ids);});
  $("refreshConflict").addEventListener("click",async()=>{if(busy)return;busy=true;updateControls();try{const latest=await api("/api/self-profile");adopt(latest);conflict={ready:true};const box=$("conflictComparison");box.replaceChildren();for(const [k,value] of Object.entries(manualChanges().fields)){const heading=node("h3","",labels[k]);box.append(heading,compare(latest.profile.fields[k],value,"최신 저장값","작성 중인 내 입력"));}if(manualChanges().careers)box.append(node("h3","","경력·프로젝트"),compare(latest.profile.careers,cleanCareers(draft.careers),"최신 저장값","작성 중인 내 입력"));if(!box.childNodes.length)box.append(empty("직접 입력의 차이는 없습니다. 남겨둔 자료 선택도 다시 비교해 주세요."));$("conflictActions").hidden=false;announce("최신 값을 읽었습니다. 작성 중 입력과 비교한 뒤 아래에서 선택해 주세요.");}catch(e){showError(e.message);}finally{busy=false;updateControls();}});
  $("keepEdits").addEventListener("click",()=>{if(!conflict?.ready)return;const ids=new Set(view.profile.careers.map(r=>r.id));if(draft.careers.some(r=>r.id&&!ids.has(r.id))){showError("저장소에서 삭제된 경력이 편집 중 목록에 남아 있습니다. 해당 경력을 제외하거나 최신 저장값을 사용해 주세요.");return;}conflict=null;$("conflictPanel").hidden=true;clearError();renderSuggestions();updateControls();announce("내 수정을 유지했습니다. 자료 후보는 최신 기준으로 다시 비교한 뒤 명시적으로 저장하세요.");});
  $("useLatest").addEventListener("click",()=>{if(!conflict?.ready)return;draft=draftFrom(view.profile);selections.clear();conflict=null;$("conflictPanel").hidden=true;clearError();render();announce("확인한 최신 저장값을 사용합니다.");});
  window.addEventListener("beforeunload",event=>{if(hasChanges()||uncertain){event.preventDefault();event.returnValue="";}});
  async function load(){busy=true;updateControls();try{const data=await api("/api/self-profile");adopt(data,{preserve:false});announce(data.profile.id?"저장한 초안을 불러왔습니다.":"아직 저장한 프로필이 없습니다. 직접 작성하거나 자료를 추가해 보세요.");}catch(e){showError(e.message);const retry=button("프로필 다시 불러오기",load,"secondary-button");delete retry.dataset.lock;$("pageError").append(retry);}finally{busy=false;updateControls();}}
  load();
})();
