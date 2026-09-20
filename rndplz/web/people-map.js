(function(root,factory){
 if(typeof module==="object"&&module.exports)module.exports=factory;else root.createPeopleMapView=factory;
})(typeof globalThis!=="undefined"?globalThis:this,function(C){
 "use strict";
 const esc=x=>String(x==null?"":x).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
 const safeUrl=x=>typeof x==="string"&&/^https:\/\//i.test(x)?x:null;
 const selectedPerson=s=>C.visiblePeople(s).find(p=>p.id===s.selectedId)||null;
 const title=p=>p.name||"이름 미기재";
 const topicName=id=>(C.topics.find(t=>t.id===id)||{}).name||id;
 const historical=p=>{const profile=p.sourceProfile||{};return profile.display_type==="historical_researcher"||profile.current_status?.category==="deceased"||profile.affiliation_status==="deceased";};
 const historicalNotice="역사적 연구 자료 · 실제 자문 가능 대상 아님";
 const portraitPath=p=>p.portrait&&/^\/portraits\/[a-z0-9-]+\.(png|jpg|jpeg)$/i.test(p.portrait.path||"")?p.portrait.path:null;
 const recordType=r=>r.typeLabel||r.type||"기록";
 const recordRole=r=>r.role||"역할 미기재";
 const recordDate=r=>r.recordDate||"자료 날짜 미기재";
 const checked=(s,p)=>C.selectedEvidence(s,p);
 const currentCapability=s=>C.capabilities.find(c=>c.id===s.capability)||null;
 const shortScope=(s,p)=>C.capabilityLink(s,p)?.scope||p.sourceProfile?.tagline||C.visibleEvidence(s,p)[0]?.title||"연결된 근거를 확인해 주세요";
 const PAGE_SIZE=25;

  function additionalRecordSources(raw){
  const sources=Array.isArray(raw.metadata_sources)?raw.metadata_sources:[];
  const links=sources.map((source)=>{
   const item=source&&typeof source==="object"?source:{},url=safeUrl(typeof source==="string"?source:item.url);
   if(!url)return "";
   const marker=[item.basis,item.type,item.title,item.label].filter(value=>typeof value==="string").join(" ");
   const label=/\bcorrection\b|정정/i.test(marker)?"정정 출처":"추가 출처";
   return '<a class="source-link" href="'+esc(url)+'" target="_blank" rel="noopener noreferrer"'+(typeof item.title==="string"?' title="'+esc(item.title)+'"':'')+'>'+label+' ↗</a>';
  }).filter(Boolean);
  return links.length?'<div class="asset-source-field">'+links.join(" · ")+'</div>':"";
 }
 function recordCard(r,s,index){
  const link=safeUrl(r.sourceUrl),details=[],raw=r.sourceRecord||{};
  if(r.period)details.push('<dt>참여 기간</dt><dd>'+esc(r.period)+'</dd>');
  else if(raw.kind==="career_record")details.push('<dt>기재 기간</dt><dd>'+esc(r.recordDate||"미기재")+' · 제공 자료 기준</dd>');
  else details.push('<dt>참여 기간</dt><dd>미기재 · 자료 날짜와 구분</dd>');
  if(r.organization)details.push('<dt>자료상 소속</dt><dd>'+esc(r.organization)+'</dd>');
  const source=link?'<a class="source-link" href="'+esc(link)+'" target="_blank" rel="noopener noreferrer">'+esc(r.sourceLabel||"원 출처 열기")+' ↗</a>':'<span class="micro">'+esc(r.sourceLabel||"원 출처 링크 미기재")+'</span>';
  return '<article class="record-card" data-record="'+esc(r.id)+'"><div class="section-label"><span>'+esc(recordType(r))+(raw.virtual?' · 기존 가상 기록':'')+'</span><span>'+(raw.kind==="career_record"?'기재 기간 · ':'자료 날짜 · ')+esc(recordDate(r))+'</span></div><h3>'+esc(r.title||"제목 미기재")+'</h3><p class="role-line">'+esc(recordRole(r))+'</p>'+(r.summary?'<p class="record-summary">'+esc(r.summary)+'</p>':'')+(raw.boundary?'<p class="record-boundary">'+esc(raw.boundary)+'</p>':'')+'<dl class="facts">'+details.join("")+'</dl>'+((r.topics||[]).length?'<div class="record-topics">'+r.topics.map(t=>'<span>'+esc(topicName(t))+'</span>').join("")+'</div>':'')+'<details class="source-details"><summary>출처와 표시 범위</summary>'+source+additionalRecordSources(raw)+(r.provenance?'<p>'+displayValue(r.provenance)+'</p>':'')+(raw.evidence_label?'<p>자료 분류: '+esc(raw.evidence_label)+'</p>':'')+(raw.classification_basis?'<p>분류 근거: '+esc(raw.classification_basis)+'</p>':'')+(raw.access?'<p>원자료 접근 표기: '+esc(raw.access)+'</p>':'')+(raw.checked_at?'<p>자료 확인 시점: '+esc(raw.checked_at)+'</p>':'')+(raw.corresponding?'<p>교신저자 표기 있음</p>':'')+'<p>기록에 나온 연결과 역할을 보여줍니다. 현재의 수행 역량·자문 가능 여부를 확정하지 않습니다.</p></details><button type="button" class="text-button" data-map-open="record" data-id="'+esc(r.id)+'">기록 원문 상세 보기 ↗</button><label class="evidence-check"><input type="checkbox" id="evidence-'+index+'" data-evidence="'+esc(r.id)+'"'+(s.evidenceIds.includes(r.id)?' checked':'')+'>이 근거를 질문 준비에 포함</label></article>';
 }
 function renderQuestion(s,p){
  const selected=checked(s,p),isHistorical=historical(p);
  let html='<section class="detail-section"><div class="question-form"><div class="section-label"><span>'+(isHistorical?'03 · 자료 검토 준비':'03 · 대화 준비')+'</span><span>'+(isHistorical?'역사적 연구 자료':'첫 15분')+'</span></div><h3>'+(isHistorical?'자료에서 무엇을 확인할까요?':'무엇부터 물어볼까요?')+'</h3>'+(isHistorical?'<p class="detail-meta">'+historicalNotice+' · 기존 자료를 바탕으로 질문을 편집하며 실제 요청을 보내지 않습니다.</p>':'');
  if(!selected.length)return html+'<p class="gated">읽어본 근거 중 질문에 포함할 자료를 직접 골라주세요. 여러 자료를 함께 선택할 수 있습니다.</p></div></section>';
  html+='<p class="question-target">'+(isHistorical?'자료의 연구자':'질문 대상')+' <strong>'+esc(title(p))+'</strong> · 근거 <strong>'+selected.length+'</strong>개</p><ul class="selected-evidence-list">'+selected.map(r=>'<li>'+esc(r.title)+'</li>').join("")+'</ul>';
  if(s.draftNeedsReview)html+='<div class="context-review" role="status"><p>선택 근거가 바뀌었습니다. 직접 쓴 초안이 지금 자료와 맞는지 확인해 주세요.</p><button type="button" data-map-action="ack-draft" class="text-button">변경한 근거로 초안 확인</button><button type="button" data-map-action="reset-draft" class="text-button">선택한 근거로 다시 시작</button></div>';
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
   if(portrait.reference_note)body+='<p>참고 자료 설명: '+esc(portrait.reference_note)+'</p>';
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
  const raw=p.sourceProfile||{},keys={tagline:"프로필 한 줄",biography:"소개",skills:"프로필에 기재된 기술",skill_groups:"기술 묶음",interests:"관심 주제",timeline:"제공 이력",projects:"기재 프로젝트",education:"학력",sources:"프로필 출처",portrait_note:"일러스트 참고 정보",profile_note:"프로필 표시 범위",current_role:"기재된 현재 역할",role:"기재 역할",source_type:"정보 제공 방식",checked_at:"자료 확인 시점",profile_observed_as_of:"공개 프로필 관측일 · 재직 확인 아님",limit:"해석 범위",employment_verification:"재직 확인 상태",collaboration_availability:"자문 가능 여부",contact_consent:"연락 동의 상태"};
  const rows=Object.entries(keys).filter(([key])=>raw[key]!=null&&raw[key]!==""&&(!Array.isArray(raw[key])||raw[key].length));
  if(!rows.length)return "";
  return '<details class="profile-info"><summary>프로필에 제공된 내용과 출처</summary>'+rows.map(([key,label])=>'<p><strong>'+label+'</strong></p>'+displayValue(raw[key])).join("")+'</details>';
 }



 function renderCapabilities(s){
  return C.capabilities.map((c,index)=>'<button type="button" class="mp-capability" data-capability="'+esc(c.id)+'" aria-pressed="'+(s.capability===c.id)+'" aria-controls="people-map person-detail"><span class="mp-capability-index">'+String(index+1).padStart(2,"0")+'</span><span class="mp-capability-label">'+esc(c.label)+'</span><span class="mp-capability-count">'+C.visiblePeople({...s,capability:c.id}).length+'명</span></button>').join("");
 }
 function personCard(p,s){
  const active=s.selectedId===p.id,records=C.visibleEvidence(s,p),path=active&&portraitPath(p);
  return '<button type="button" class="mp-person" data-person="'+esc(p.id)+'" aria-pressed="'+active+'" aria-controls="person-detail"><span class="mp-portrait"><span class="mp-initial" aria-hidden="true">'+esc(Array.from(title(p))[0]||"")+'</span>'+(path?'<img src="'+esc(path)+'" alt="" loading="lazy" decoding="async" width="108" height="144">':'')+'</span><span class="mp-person-text"><strong class="mp-person-name">'+esc(title(p))+'</strong><span class="mp-person-field">'+esc(shortScope(s,p))+'</span><span class="mp-person-records">근거 '+records.length+'개 보기'+(p.virtual?' · 가상 사례':'')+'</span></span><span class="mp-person-arrow" aria-hidden="true">↗</span></button>';
 }
 function renderMap(s){
  const people=C.visiblePeople(s),capability=currentCapability(s),page=Math.min(s.page||0,Math.max(0,Math.ceil(people.length/PAGE_SIZE)-1)),shown=people.slice(page*PAGE_SIZE,(page+1)*PAGE_SIZE);
  if(!people.length)return '<p class="mp-empty">현재 조건에 연결된 인물이 없습니다. <button type="button" data-map-action="clear-all">조건 모두 해제</button></p>';
  let cards=shown.map(p=>personCard(p,s)).join('');
  if(s.view==='organization'){
   const groups=new Map();shown.forEach(p=>{const org=p.organizationGroupName||p.organization||'소속 미기재';if(!groups.has(org))groups.set(org,[]);groups.get(org).push(p);});
   cards=[...groups].map(([org,group])=>'<section class="mp-org-group"><h3>자료상 '+esc(org)+'</h3>'+group.map(p=>personCard(p,s)).join('')+'</section>').join('');
  }
  let html='<div class="mp-graph"><svg class="mp-lines" aria-hidden="true" focusable="false"></svg><div class="mp-capability-node"><span class="mp-node-mark">↗</span><span class="mp-node-eyebrow">'+(capability?'선택한 역량':'등록 자료')+'</span><strong class="mp-node-title">'+esc(capability?.label||"등록된 연구 경험")+'</strong><span class="mp-node-count">'+people.length+'명의 연결 기록</span></div><div class="mp-people">'+cards+'</div></div>';
  if(people.length>PAGE_SIZE)html+='<div class="mp-pager"><button type="button" data-page="'+(page-1)+'"'+(!page?' disabled':'')+'>이전</button><span>'+(page*PAGE_SIZE+1)+'–'+Math.min(people.length,(page+1)*PAGE_SIZE)+' / '+people.length+'명</span><button type="button" data-page="'+(page+1)+'"'+((page+1)*PAGE_SIZE>=people.length?' disabled':'')+'>다음</button></div>';
  return html;
 }
 function renderDetail(s){
  const p=selectedPerson(s);
  if(!p)return '<p class="mp-section-label">선택한 사람의 연결 근거</p><h2 class="mp-evidence-title">인물을 선택해 주세요</h2><p class="mp-empty">연결된 기록과 그 자료의 범위를 살펴볼 수 있어요.</p>';
  const records=C.visibleEvidence(s,p);
  let html='<p class="mp-section-label">선택한 사람의 연결 근거</p><h2 id="detail-title" class="mp-evidence-title" tabindex="-1">'+esc(title(p))+'</h2><p class="mp-evidence-scope">'+esc(shortScope(s,p))+'</p><div class="mp-detail-links"><button type="button" data-map-open="person" data-id="'+esc(p.id)+'">인물 상세 보기 ↗</button><button type="button" data-map-action="close">선택 닫기</button></div>';
  if(historical(p))html+='<p class="mp-record-limit">'+historicalNotice+'</p>';
  if(!records.length)return html+'<p class="mp-empty">현재 조건에 연결된 기록이 없습니다. 경험이 없다는 뜻은 아닙니다.</p>';
  html+='<div class="mp-evidence-list">'+records.map((r,i)=>'<details class="mp-record"'+(!i?' open':'')+'><summary class="mp-record-summary"><span class="mp-record-meta">'+esc(recordType(r))+' · '+esc(recordDate(r))+'</span><strong class="mp-record-title">'+esc(r.title||"제목 미기재")+'</strong><span class="mp-record-toggle">근거 읽기</span></summary><div class="mp-record-body">'+recordCard(r,s,i)+'</div></details>').join("")+'</div>';
  return html+renderQuestion(s,p)+renderAssetSources(p)+renderProfile(p);
 }
 function mount(doc,host){
  const win=doc.defaultView,$=id=>host.querySelector('#'+id);
  let state=C.initialState(),frame=0;
  const first=C.visiblePeople(state)[0];if(first)state=C.reduce(state,{type:"SELECT",id:first.id});
  function drawLines(){
   const graph=host.querySelector('.mp-graph'),node=graph?.querySelector('.mp-capability-node'),svg=graph?.querySelector('.mp-lines');
   if(!graph||!node||!svg)return;
   const bounds=graph.getBoundingClientRect(),from=node.getBoundingClientRect();if(!bounds.width||!bounds.height)return;
   svg.setAttribute('viewBox',`0 0 ${bounds.width} ${bounds.height}`);svg.replaceChildren();
   graph.querySelectorAll('[data-person]').forEach(button=>{
    const to=button.getBoundingClientRect(),path=doc.createElementNS('http://www.w3.org/2000/svg','path'),y=to.top+to.height/2-bounds.top,x=to.left-bounds.left;
    if(from.right<=to.left){const sx=from.right-bounds.left,sy=from.top+from.height/2-bounds.top,mid=sx+(x-sx)/2;path.setAttribute('d',`M ${sx} ${sy} C ${mid} ${sy}, ${mid} ${y}, ${x} ${y}`);}
    else{const sx=from.left+12-bounds.left,sy=from.bottom-bounds.top;path.setAttribute('d',`M ${sx} ${sy} V ${y} H ${x}`);}
    path.setAttribute('class',button.dataset.person===state.selectedId?'mp-line-active':'mp-line');svg.append(path);
   });
  }
  function schedule(){if(!frame)frame=win.requestAnimationFrame(()=>{frame=0;drawLines();});}
  function render(){
   const people=C.visiblePeople(state),capability=currentCapability(state),ids=new Set(people.flatMap(p=>C.visibleEvidence(state,p).map(r=>r.id)));
   $('capability-controls').innerHTML=renderCapabilities(state);$('people-map').innerHTML=renderMap(state);$('person-detail').innerHTML=renderDetail(state);
   $('people-map-content').dataset.mpCount=String(people.length);
   $('map-title').textContent=capability?.label||'등록된 연구 경험';$('map-explanation').textContent=(capability?.description||'이름과 자료 주제로 찾거나 왼쪽에서 역량을 골라보세요.')+(state.view==='organization'?' 자료에 기재된 소속으로 묶으며 현재 재직이나 협업 관계를 뜻하지 않습니다.':'');
   $('map-count').textContent=people.length+'명 · 연결 기록 '+ids.size+'개';
   $('results-summary').textContent=people.length+'명'+(capability?' · '+capability.label:'')+(state.query?' · 이름 “'+state.query+'”':'')+(state.topic?' · '+topicName(state.topic):'');
   $('view-control').value=state.view;$('topic-controls').value=state.topic;if($('name-search').value!==state.query)$('name-search').value=state.query;
   schedule();
  }
  function dispatch(action){
   state=C.reduce(state,action);
   if(['QUERY','TOPIC','SCOPE','CAPABILITY','CLEAR_FILTERS','PAGE'].includes(action.type)){
    const visible=C.visiblePeople(state),page=state.page||0;
    if(!state.selectedId||!visible.slice(page*PAGE_SIZE,(page+1)*PAGE_SIZE).some(p=>p.id===state.selectedId)){const next=visible[page*PAGE_SIZE];if(next)state=C.reduce(state,{type:'SELECT',id:next.id});}
   }
   render();
  }
  $('topic-controls').innerHTML='<option value="">전체 주제</option>'+C.topics.map(t=>'<option value="'+esc(t.id)+'">'+esc(t.name)+'</option>').join('');
  $('scope-note').textContent='전체 등록 '+C.people.length+'명 · '+C.counts.records+'개 기록을 유지합니다.';
  host.addEventListener('error',event=>{if(event.target.matches?.('.mp-portrait img'))event.target.remove();},true);
  host.addEventListener('input',event=>{const t=event.target;if(t.id==='name-search'){dispatch({type:'QUERY',value:t.value});return;}const types={problem:'PROBLEM',draft:'DRAFT',aiText:'AI_TEXT'};if(types[t.dataset.field])state=C.reduce(state,{type:types[t.dataset.field],value:t.value});});
  host.addEventListener('change',event=>{const t=event.target;if(t.id==='topic-controls')dispatch({type:'TOPIC',value:t.value});else if(t.id==='view-control')dispatch({type:'VIEW',value:t.value});else if(t.dataset.evidence){const id=t.id;dispatch({type:'EVIDENCE',id:t.dataset.evidence,checked:t.checked});$(id)?.focus();}else if(t.id==='include-ai'){dispatch({type:'INCLUDE_AI',value:t.checked});$('include-ai')?.focus();}});
  host.addEventListener('click',event=>{
   const button=event.target.closest('button');if(!button||!host.contains(button))return;
   if(button.hasAttribute('data-capability')){const id=button.dataset.capability;dispatch({type:'CAPABILITY',value:state.capability===id?'':id});[...host.querySelectorAll('[data-capability]')].find(b=>b.dataset.capability===id)?.focus();}
   else if(button.dataset.person){dispatch({type:'SELECT',id:button.dataset.person});$('detail-title')?.focus({preventScroll:true});}
   else if(button.hasAttribute('data-page')){dispatch({type:'PAGE',value:Number(button.dataset.page)});$('map-title').scrollIntoView({block:'start',behavior:'auto'});}
   else if(button.id==='clear-filters'||button.dataset.mapAction==='clear-all'){dispatch({type:'CLEAR_FILTERS'});$('name-search').focus();}
   else if(button.dataset.mapAction==='close'){const id=state.selectedId;dispatch({type:'CLOSE_DETAIL'});[...host.querySelectorAll('[data-person]')].find(b=>b.dataset.person===id)?.focus();}
   else if(button.dataset.mapAction==='ack-draft'){dispatch({type:'ACK_DRAFT_CONTEXT'});$('draft')?.focus();}
   else if(button.dataset.mapAction==='reset-draft'){dispatch({type:'RESET_DRAFT'});$('draft')?.focus();}
  });
  win.addEventListener('resize',schedule);const observer=win.ResizeObserver?new win.ResizeObserver(schedule):null;observer?.observe($('people-map-content'));
  render();return {getState:()=>({...state,evidenceIds:[...state.evidenceIds]})};
 }
 return {esc,renderMap,renderDetail,renderQuestion,renderCapabilities,selectedPerson,mount};
});

(function(root){
 "use strict";
 const mounted=new WeakMap(),pending=new WeakMap(),bound=new WeakSet();
 async function ensure(host,request){
  if(mounted.has(host))return mounted.get(host);
  if(pending.has(host))return pending.get(host);
  const status=host.querySelector("#people-map-load"),message=status.querySelector("p"),retry=status.querySelector("button"),content=host.querySelector("#people-map-content");
  if(!bound.has(host)){bound.add(host);retry.addEventListener("click",()=>ensure(host,request));}
  message.textContent="등록된 인물과 근거 자료를 불러오고 있습니다.";retry.hidden=true;status.hidden=false;content.hidden=true;
  const work=(async()=>{
   try{
    const data=await request("/api/people-map");
    if(!data||data.complete!==true||!Array.isArray(data.people)||!data.counts||data.counts.people!==data.people.length||!Array.isArray(data.featured_ids)||data.counts.featured_people!==data.featured_ids.length||data.featured_ids.some(id=>!data.people.some(p=>p&&p.id===id))||data.people.some(p=>!p||typeof p.id!=="string"||!p.id||!Array.isArray(p.evidence)||p.record_count!==p.evidence.length||!Array.isArray(p.topic_ids)||p.evidence.some(e=>!e||typeof e.id!=="string"||!e.id)))throw new Error("incomplete map data");
    if(!host.isConnected)return null;
    const core=root.createPeopleMapModel(data),controller=root.createPeopleMapView(core).mount(host.ownerDocument,host);
    mounted.set(host,controller);content.hidden=false;status.hidden=true;
    return controller;
   }catch(error){
    if(host.isConnected){message.textContent="인물과 근거 자료를 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.";retry.hidden=false;content.hidden=true;status.hidden=false;}
    return null;
   }finally{pending.delete(host);}
  })();
  pending.set(host,work);return work;
 }
 root.RndPeopleMap={ensure};
})(typeof globalThis!=="undefined"?globalThis:this);
