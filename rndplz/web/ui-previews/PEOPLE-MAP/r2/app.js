(function(root,factory){
 const api=factory(typeof module==="object"&&module.exports?require("./model.js"):root.PeopleMapCore);
 if(typeof module==="object"&&module.exports)module.exports=api;else{root.PeopleMapPreview=api;api.mount(document);}
})(typeof globalThis!=="undefined"?globalThis:this,function(C){
 "use strict";
 const esc=x=>String(x==null?"":x).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
 const safeUrl=x=>typeof x==="string"&&/^https:\/\//i.test(x)?x:null;
 const selectedPerson=s=>C.visiblePeople(s).find(p=>p.id===s.selectedId)||null;
 const title=p=>p.name||"이름 미기재";
 const topicName=id=>(C.topics.find(t=>t.id===id)||{}).name||id;
 const virtual=p=>p.virtual?'<span class="virtual-tag">기존 가상 사례</span>':"";
 const PAGE_SIZE=25;
 const org=p=>p.organization||"소속 미기재";
 const portraitPath=p=>p.portrait&&/^\/portraits\/[a-z0-9-]+\.png$/i.test(p.portrait.path||"")?p.portrait.path:null;
 const awards=p=>(p.awards||[]).filter(a=>a.label).map(a=>'<span class="award-mark">'+esc(a.label)+(a.year&&!String(a.label).includes(String(a.year))?' · '+esc(a.year):'')+'</span>').join("");
 const avatar=p=>portraitPath(p)?'<span class="avatar portrait-mini"><img src="'+esc(portraitPath(p))+'" alt="" loading="lazy"></span>':'<span class="avatar neutral" aria-hidden="true">'+esc(title(p).slice(0,1))+'</span>';
 const recordType=r=>r.typeLabel||r.type||"기록";
 const recordRole=r=>r.role||"역할 미기재";
 const recordDate=r=>r.recordDate||"자료 날짜 미기재";
 const checked=(s,p)=>C.selectedEvidence(s,p);
 function renderTopics(s){
   return '<button type="button" data-topic="" aria-pressed="'+(!s.topic)+'">전체 주제</button>'+C.topics.map(t=>'<button type="button" data-topic="'+esc(t.id)+'" aria-pressed="'+(s.topic===t.id)+'">'+esc(t.name)+'</button>').join("");
 }
 function renderRoster(s){
  const people=C.visiblePeople(s);
  if(!people.length)return '<div class="list-empty">현재 조건에 맞는 인물이 없습니다.<br><button type="button" class="text-button" data-action="clear-all">조건 모두 해제 →</button></div>';
  const page=Math.min(s.page||0,Math.max(0,Math.ceil(people.length/PAGE_SIZE)-1)),shown=people.slice(page*PAGE_SIZE,(page+1)*PAGE_SIZE);
  return '<p class="list-range">'+(page*PAGE_SIZE+1)+'–'+Math.min((page+1)*PAGE_SIZE,people.length)+'번째 / 조건 결과 '+people.length+'명</p>'+shown.map(p=>'<button type="button" class="person-row" data-person="'+esc(p.id)+'" id="row-'+esc(p.id)+'" aria-pressed="'+(s.selectedId===p.id)+'">'+avatar(p)+'<span class="row-copy"><strong>'+esc(title(p))+'</strong>'+virtual(p)+'<small>'+esc(s.view==="organization"?org(p):((C.visibleEvidence(s,p)[0]||{}).typeLabel||"연결된 기록 없음"))+'</small></span><span class="row-arrow" aria-hidden="true">↗</span></button>').join("")+(people.length>PAGE_SIZE?'<div class="list-pages"><button type="button" data-page="'+(page-1)+'"'+(page===0?' disabled':'')+'>← 이전</button><span>'+(page+1)+' / '+Math.ceil(people.length/PAGE_SIZE)+'</span><button type="button" data-page="'+(page+1)+'"'+((page+1)*PAGE_SIZE>=people.length?' disabled':'')+'>다음 →</button></div>':'');
 }
 function personCard(p,s){
  const records=C.visibleEvidence(s,p),hasAward=(p.awards||[]).length>0;
  return '<button type="button" class="map-person real-person'+(hasAward?' with-award':'')+'" data-person="'+esc(p.id)+'" aria-pressed="'+(s.selectedId===p.id)+'" aria-label="'+esc(title(p))+' 연결 근거 보기"><span class="real-name"><strong>'+esc(title(p))+'</strong>'+virtual(p)+'<span class="person-team">'+esc(org(p))+'</span></span>'+(portraitPath(p)?'<span class="portrait-frame"><img src="'+esc(portraitPath(p))+'" alt="'+esc(title(p))+' '+esc(p.portrait.label||"공개 인물 일러스트")+'" loading="lazy"></span><span class="portrait-caption">'+(p.portrait.generated?'AI 생성 일러스트':esc(p.portrait.label||"공개 이미지"))+'</span>':'<span class="portrait-placeholder">'+avatar(p)+'</span>')+awards(p)+'<span class="experience-title">'+esc(records[0]?records[0].title:"연결된 기록 없음")+'</span><span class="period">이 조건의 연결 근거 '+records.length+'개</span></button>';
 }
 function line(label,id){return '<div class="relation" data-relation-person="'+esc(id)+'"><svg viewBox="0 0 180 57" preserveAspectRatio="none" aria-hidden="true"><path d="M90 0V57"/></svg><span>'+esc(label)+'</span></div>';}
 function groups(s){
  const map=new Map();
  for(const p of C.visiblePeople(s)){
   const keys=s.view==="organization"?[org(p)]:[...new Set(C.visibleEvidence(s,p).flatMap(r=>r.topics||[]))];
   if(!keys.length)keys.push("주제 미기재");
   for(const key of keys){if(!map.has(key))map.set(key,[]);map.get(key).push(p);}
  }
  return [...map].sort((a,b)=>a[0].localeCompare(b[0],"ko"));
 }
 function renderMap(s){
  const people=C.visiblePeople(s);
  if(!people.length)return '<div class="empty-result"><div class="empty-symbol" aria-hidden="true">∅</div><h3>현재 조건에 맞는 인물이 없습니다.</h3><p>이름과 자료 주제 조건을 바꾸어 찾아보세요.</p><button type="button" class="text-button" data-action="'+(s.topic?'clear-topic':'clear-all')+'">'+(s.topic?'주제 조건만 해제':'조건 모두 해제')+' →</button></div>';
  if(people.length<=6)return '<div class="small-result-label">'+people.length+'명 · 같은 조건의 이름과 근거</div><div class="map-grid actual-small">'+people.map(p=>'<section class="map-group '+((p.awards||[]).length?'gold':'')+'"><div class="group-label"><span>'+esc(s.view==="organization"?org(p):(s.topic?topicName(s.topic):"연결된 공개 기록"))+'</span></div>'+line(s.view==="organization"?"자료에 기재된 소속":recordRole(C.visibleEvidence(s,p)[0]||{}),p.id)+personCard(p,s)+'</section>').join("")+'</div>';
  const all=groups(s),showAll=(s.expandedGroups||[]).includes("__all_groups__"),shown=showAll?all:all.slice(0,6);
  return '<p class="cluster-help">먼저 묶음을 펼쳐보세요. 모든 이름은 왼쪽 목록에서 바로 찾을 수 있습니다.</p><div class="cluster-grid">'+shown.map(([key,members],i)=>{
   const gid=s.view+":"+key,expanded=(s.expandedGroups||[]).includes(gid),allMembers=(s.expandedGroups||[]).includes(gid+":all"),viewMembers=allMembers?members:members.slice(0,6);
   return '<section class="cluster '+(["","blue","gold"][i%3])+'"><button type="button" class="cluster-heading" data-group="'+esc(gid)+'" aria-expanded="'+expanded+'"><span><small>'+esc(s.view==="organization"?"자료상 소속":"논문·기록 주제")+'</small><strong>'+esc(s.view==="organization"?key:topicName(key))+'</strong></span><span class="cluster-count">'+members.length+'<small>명</small>'+(members.some(p=>p.virtual)?'<small>가상 '+members.filter(p=>p.virtual).length+'명 포함</small>':'')+'</span></button>'+(expanded?'<div class="cluster-members">'+viewMembers.map(p=>'<button type="button" class="cluster-person" data-person="'+esc(p.id)+'" aria-pressed="'+(s.selectedId===p.id)+'">'+avatar(p)+'<span>'+esc(title(p))+virtual(p)+'</span><span aria-hidden="true">↗</span></button>').join("")+(members.length>6?'<button type="button" class="text-button" data-group="'+esc(gid+':all')+'">'+(allMembers?'6명만 보기':'이 묶음 '+members.length+'명 모두 보기')+'</button>':'')+'</div>':'')+'</section>';
  }).join("")+'</div>'+(all.length>6?'<button type="button" class="text-button group-more" data-group="__all_groups__">'+(showAll?'주제 묶음 접기':'묶음 '+all.length+'개 모두 보기')+'</button>':'')+'<p class="cluster-note">주제가 여러 개인 사람은 여러 묶음에 나타날 수 있습니다. 전체 인원은 같은 ID를 한 번만 셉니다.</p>';
 }
 function recordCard(r,s,index){
  const link=safeUrl(r.sourceUrl),details=[],raw=r.sourceRecord||{};
  if(r.period)details.push('<dt>참여 기간</dt><dd>'+esc(r.period)+'</dd>');
  else if(raw.kind==="career_record")details.push('<dt>기재 기간</dt><dd>'+esc(r.recordDate||"미기재")+' · 제공 자료 기준</dd>');
  else details.push('<dt>참여 기간</dt><dd>미기재 · 자료 날짜와 구분</dd>');
  if(r.organization)details.push('<dt>자료상 소속</dt><dd>'+esc(r.organization)+'</dd>');
  const source=link?'<a class="source-link" href="'+esc(link)+'" target="_blank" rel="noopener noreferrer">'+esc(r.sourceLabel||"원 출처 열기")+' ↗</a>':'<span class="micro">'+esc(r.sourceLabel||"원 출처 링크 미기재")+'</span>';
  return '<article class="record-card" data-record="'+esc(r.id)+'"><div class="section-label"><span>'+esc(recordType(r))+(raw.virtual?' · 기존 가상 기록':'')+'</span><span>'+(raw.kind==="career_record"?'기재 기간 · ':'자료 날짜 · ')+esc(recordDate(r))+'</span></div><h3>'+esc(r.title||"제목 미기재")+'</h3><p class="role-line">'+esc(recordRole(r))+'</p>'+(r.summary?'<p class="record-summary">'+esc(r.summary)+'</p>':'')+(raw.boundary?'<p class="record-boundary">'+esc(raw.boundary)+'</p>':'')+'<dl class="facts">'+details.join("")+'</dl>'+((r.topics||[]).length?'<div class="record-topics">'+r.topics.map(t=>'<span>'+esc(topicName(t))+'</span>').join("")+'</div>':'')+'<details class="source-details"><summary>출처와 표시 범위</summary>'+source+(r.provenance?'<p>'+displayValue(r.provenance)+'</p>':'')+(raw.evidence_label?'<p>자료 분류: '+esc(raw.evidence_label)+'</p>':'')+(raw.classification_basis?'<p>분류 근거: '+esc(raw.classification_basis)+'</p>':'')+(raw.access?'<p>원자료 접근 표기: '+esc(raw.access)+'</p>':'')+(raw.checked_at?'<p>자료 확인 시점: '+esc(raw.checked_at)+'</p>':'')+(raw.corresponding?'<p>교신저자 표기 있음</p>':'')+'<p>기록에 나온 연결과 역할을 보여줍니다. 현재의 수행 역량·자문 가능 여부를 확정하지 않습니다.</p></details><label class="evidence-check"><input type="checkbox" id="evidence-'+index+'" data-evidence="'+esc(r.id)+'"'+(s.evidenceIds.includes(r.id)?' checked':'')+'>이 근거를 질문 준비에 포함</label></article>';
 }
 function renderQuestion(s,p){
  const selected=checked(s,p);
  let html='<section class="detail-section"><div class="question-form"><div class="section-label"><span>03 · 대화 준비</span><span>첫 15분</span></div><h3>무엇부터 물어볼까요?</h3>';
  if(!selected.length)return html+'<p class="gated">읽어본 근거 중 질문에 포함할 자료를 직접 골라주세요. 여러 자료를 함께 선택할 수 있습니다.</p></div></section>';
  html+='<p class="question-target">질문 대상 <strong>'+esc(title(p))+'</strong> · 근거 <strong>'+selected.length+'</strong>개</p><ul class="selected-evidence-list">'+selected.map(r=>'<li>'+esc(r.title)+'</li>').join("")+'</ul>';
  if(s.draftNeedsReview)html+='<div class="context-review" role="status"><p>선택 근거가 바뀌었습니다. 직접 쓴 초안이 지금 자료와 맞는지 확인해 주세요.</p><button type="button" data-action="ack-draft" class="text-button">변경한 근거로 초안 확인</button><button type="button" data-action="reset-draft" class="text-button">선택한 근거로 다시 시작</button></div>';
  html+='<label class="form-label" for="problem">지금 확인하고 싶은 문제</label><textarea id="problem" data-field="problem" maxlength="2000" placeholder="나의 상황과 확인할 조건">'+esc(s.problem)+'</textarea><label class="form-label" for="draft">질문 초안 · 직접 수정</label><textarea id="draft" class="draft-area" data-field="draft" maxlength="6000">'+esc(s.draft)+'</textarea><details class="ai-options"'+(s.includeAi?' open':'')+'><summary>AI 자료도 참고하기 · 선택 사항</summary><p class="ai-explainer">AI 자료 없이도 준비할 수 있습니다. 가져온 원답과 확인할 가정을 나누어 적어주세요.</p><label class="evidence-check"><input type="checkbox" id="include-ai"'+(s.includeAi?' checked':'')+'>내가 가진 AI 자료를 함께 검토</label>'+(s.includeAi?'<label class="form-label" for="ai-text">AI 원답 · 내가 가져오는 선택 자료</label><textarea id="ai-text" data-field="aiText" maxlength="10000" placeholder="원답과 출처·버전을 직접 적어주세요.">'+esc(s.aiText)+'</textarea>':'')+'</details><p class="draft-foot">이 페이지 안에서만 편집합니다. 저장되거나 상대에게 전달되지 않습니다.</p></div></section>';
  return html;
 }

 function displayValue(value){
  if(value==null||value==="")return "";
  if(Array.isArray(value))return '<ul>'+value.map(x=>'<li>'+displayValue(x)+'</li>').join("")+'</ul>';
  if(typeof value==="object"){
   const labels={title:"제목",name:"이름",role:"역할",year:"연도",date:"자료 날짜·기재기간",period:"기재기간",start:"시작",end:"종료",org:"자료상 소속",organization:"자료상 소속",institution:"기관",description:"기재 내용",summary:"기재 요약",degree:"학위",field:"분야",url:"출처",label:"표시",source:"출처",note:"자료 설명",status:"기재 상태",verified:"확인 여부",items:"항목",skills:"기재 기술"};
   return Object.entries(value).map(([k,v])=>'<div class="profile-field"><span>'+esc(labels[k]||k)+'</span> '+(k==="url"&&safeUrl(v)?'<a href="'+esc(v)+'" target="_blank" rel="noopener noreferrer">출처 열기 ↗</a>':displayValue(v))+'</div>').join("");
  }
  return safeUrl(value)?'<a href="'+esc(value)+'" target="_blank" rel="noopener noreferrer">출처 열기 ↗</a>':esc(String(value));
 }
 function renderAssetSources(p){
  const profile=p.sourceProfile||{},portrait=profile.portrait,award=profile.award;
  if(!portrait&&!award)return "";
  let body="";
  if(portrait){
   body+='<p><strong>기존 인물 일러스트</strong></p><p>'+esc(portrait.generated_credit||portrait.label||"기존 공개 초상")+'</p>';
   for(const key of ["reference","reference_url","photo_url","credit","license","generated_license","change_note"]){
    if(portrait[key])body+='<div class="asset-source-field">'+displayValue(portrait[key])+'</div>';
   }
  }
  if(award){
   body+='<p><strong>명시된 수상 이력</strong></p><p>'+esc(award.label_ko||award.name||"수상")+'</p>';
   if(award.summary)body+='<p>'+esc(award.summary)+'</p>';
   const link=safeUrl(award.facts_url||award.verified_source);
   if(link)body+='<a href="'+esc(link)+'" target="_blank" rel="noopener noreferrer">공식 수상 출처 ↗</a>';
   body+='<p>수상 사실을 표시하며, 이 화면의 후보 순위나 모든 연결 기록의 평가로 사용하지 않습니다.</p>';
  }
  return '<details class="profile-info asset-sources"><summary>일러스트·수상 출처</summary>'+body+'</details>';
 }
 function renderProfile(p){
  const raw=p.sourceProfile||{},keys={tagline:"프로필 한 줄",biography:"소개",skills:"프로필에 기재된 기술",skill_groups:"기술 묶음",interests:"관심 주제",timeline:"제공 이력",projects:"기재 프로젝트",education:"학력",sources:"프로필 출처",portrait_note:"일러스트 참고 정보",profile_note:"프로필 표시 범위",current_role:"기재된 현재 역할",role:"기재 역할",source_type:"정보 제공 방식",checked_at:"자료 확인 시점",limit:"해석 범위",employment_verification:"재직 확인 상태",collaboration_availability:"자문 가능 여부",contact_consent:"연락 동의 상태"};
  const rows=Object.entries(keys).filter(([key])=>raw[key]!=null&&raw[key]!==""&&(!Array.isArray(raw[key])||raw[key].length));
  if(!rows.length)return "";
  return '<details class="profile-info"><summary>프로필에 제공된 내용과 출처</summary>'+rows.map(([key,label])=>'<p><strong>'+label+'</strong></p>'+displayValue(raw[key])).join("")+'</details>';
 }

 function renderDetail(s){
  const p=selectedPerson(s);
  if(!p)return '<div class="detail-empty"><span class="eyebrow small">02 · PERSON & EVIDENCE</span><div class="empty-mark" aria-hidden="true">↗</div><h2>이름과 연결된 기록,<br>함께 읽어보세요.</h2><p>사람을 선택하면 공개된 논문·제공 기록과 그 연결 역할을 볼 수 있습니다.</p><div class="journey"><ul><li><span>01</span>이름·자료 주제로 찾기</li><li><span>02</span>역할과 원 출처 읽기</li><li><span>03</span>선택한 근거로 질문 준비</li></ul></div></div>';
  const records=C.visibleEvidence(s,p);
  let html='<div class="detail-topline"><span class="eyebrow small">02 · PERSON & EVIDENCE</span><button type="button" class="close-detail" data-action="close">목록으로 ↩</button></div><div class="detail-head" data-detail-person="'+esc(p.id)+'"><div class="detail-name">'+avatar(p)+'<h2 id="detail-title" tabindex="-1">'+esc(title(p))+'</h2></div>'+virtual(p)+'<p class="detail-team">'+esc(org(p))+'</p><p class="detail-meta">'+esc(p.organizationNote||"자료에 기재된 소속 · 현재 여부 미확인")+'</p>'+awards(p)+(portraitPath(p)?'<div class="detail-full-portrait"><img src="'+esc(portraitPath(p))+'" alt="'+esc(title(p))+' '+esc(p.portrait.label||'공개 일러스트')+'"></div><p class="detail-meta">'+(p.portrait.generated?'AI 생성 인물 일러스트':esc(p.portrait.label||"기존 공개 이미지"))+'</p>':'')+'</div>'+renderAssetSources(p)+renderProfile(p);
  if(!records.length) return html+'<section class="detail-section zero-record"><h3>현재 조건의 연결 기록 없음</h3><p>이 화면의 자료 범위에서 표시할 기록이 없습니다. 경험이나 역량이 없다는 뜻이 아닙니다.</p></section>';
  html+='<section class="detail-section records-section"><div class="section-label"><span>연결된 근거 '+records.length+'개</span><span>전체 '+p.records.length+'개 중</span></div><p class="evidence-context">논문은 저자 기재, 제공 기록은 그 자료에 명시된 역할로 읽습니다.</p>'+(p.recordCount!==p.records.length?'<p class="evidence-context">원자료 연결 '+p.recordCount+'회 · 고유 근거 '+p.records.length+'개. 같은 인물·기록의 중복 연결은 묶어 표시합니다.</p>':'')+records.map((r,i)=>recordCard(r,s,i)).join("")+'</section>';
  return html+renderQuestion(s,p);
 }
 function mount(doc){
  let state=C.initialState();const first=C.visiblePeople(state)[0];if(first)state=C.reduce(state,{type:"SELECT",id:first.id});const $=id=>doc.getElementById(id);
  function render(){
   const visible=C.visiblePeople(state);
   $("people-list").innerHTML=renderRoster(state);$("people-map").innerHTML=renderMap(state);$("person-detail").innerHTML=renderDetail(state);
   $("results-summary").innerHTML='<strong>'+visible.length+'</strong>명 · '+(state.scope==="all"?'전체 풀':'대표 모음')+' 조건 결과'+(state.topic?' · '+esc(topicName(state.topic)):'')+(state.query?' · 이름 “'+esc(state.query)+'”':'');
   $("map-title").textContent=state.view==="organization"?"자료에 나온 소속으로":"기록 주제로 이어지는 사람";
   $("map-explanation").textContent=state.view==="organization"?"원 자료에 기재된 소속으로 묶습니다. 현재 소속 확인이나 협업 관계를 뜻하지 않습니다.":"논문·제공 기록의 주제로 묶습니다. 주제 연결은 업무 수행이나 실력 순위가 아닙니다.";
   $("list-order").textContent=state.scope==="all"?"원자료 순서":"공개 모음 순서";
   doc.querySelectorAll("[data-scope]").forEach(e=>e.setAttribute("aria-pressed",String(e.dataset.scope===state.scope)));
   doc.querySelectorAll("[data-topic]").forEach(e=>e.setAttribute("aria-pressed",String(e.dataset.topic===state.topic)));
   doc.querySelectorAll("[data-view]").forEach(e=>e.setAttribute("aria-pressed",String(e.dataset.view===state.view)));
   if($("name-search").value!==state.query)$("name-search").value=state.query;
  }
  function dispatch(action){state=C.reduce(state,action);render();}
  $("topic-controls").innerHTML=renderTopics(state);
  const counts=C.counts||{};
  $("scope-note").textContent="전체 "+C.people.length+"명 중 대표 "+(counts.featured_people||0)+"명 · 기존 가상 "+(counts.virtual_people||0)+"명은 전체 풀에 별도 표시";
  doc.addEventListener("input",e=>{const t=e.target;if(t.id==="name-search"){dispatch({type:"QUERY",value:t.value});return;}const types={problem:"PROBLEM",draft:"DRAFT",aiText:"AI_TEXT"};if(types[t.dataset.field])state=C.reduce(state,{type:types[t.dataset.field],value:t.value});});
  doc.addEventListener("change",e=>{const t=e.target;if(t.dataset.evidence){const id=t.id;dispatch({type:"EVIDENCE",id:t.dataset.evidence,checked:t.checked});$(id)?.focus();}if(t.id==="include-ai"){dispatch({type:"INCLUDE_AI",value:t.checked});$("include-ai")?.focus();}});
  doc.addEventListener("click",e=>{const b=e.target.closest("button");if(!b)return;
   if(b.dataset.person){dispatch({type:"SELECT",id:b.dataset.person});$("detail-title")?.focus({preventScroll:true});if(typeof matchMedia==="function"&&matchMedia("(max-width:1180px)").matches)$("person-detail").scrollIntoView({block:"start",behavior:"auto"});}
   else if(b.hasAttribute("data-topic")){dispatch({type:"TOPIC",value:b.dataset.topic});}
   else if(b.dataset.scope){dispatch({type:"SCOPE",value:b.dataset.scope});}
   else if(b.hasAttribute("data-page")){dispatch({type:"PAGE",value:Number(b.dataset.page)});$("people-list").scrollTop=0;$("people-list").focus();}
   else if(b.dataset.view){dispatch({type:"VIEW",value:b.dataset.view});}
   else if(b.dataset.group){const gid=b.dataset.group;dispatch({type:"TOGGLE_GROUP",id:gid});[...doc.querySelectorAll("[data-group]")].find(el=>el.dataset.group===gid)?.focus();}
   else if(b.id==="clear-filters"||b.dataset.action==="clear-all"){dispatch({type:"CLEAR_FILTERS"});$("name-search").focus();}
   else if(b.dataset.action==="clear-topic"){dispatch({type:"CLEAR_TOPIC"});$("name-search").focus();}
   else if(b.dataset.action==="close"){const id=state.selectedId;dispatch({type:"CLOSE_DETAIL"});($("row-"+id)||$("people-list")).focus();}
   else if(b.dataset.action==="ack-draft"){dispatch({type:"ACK_DRAFT_CONTEXT"});$("draft")?.focus();}
   else if(b.dataset.action==="reset-draft"){dispatch({type:"RESET_DRAFT"});$("draft")?.focus();}
  });
  render();return {getState:()=>({...state,evidenceIds:[...state.evidenceIds]})};
 }
 return {esc,renderProfile,renderTopics,renderRoster,renderMap,renderDetail,renderQuestion,selectedPerson,groups,mount};
});
