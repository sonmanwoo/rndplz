(function(root,factory){
 if(typeof module==="object"&&module.exports)module.exports=factory;else root.createPeopleMapView=factory;
})(typeof globalThis!=="undefined"?globalThis:this,function(C,GraphFactory){
 "use strict";
 const esc=x=>String(x==null?"":x).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
 const safeUrl=x=>typeof x==="string"&&/^https:\/\//i.test(x)?x:null;
 const selectedPerson=s=>C.visiblePeople(s).find(p=>p.id===s.selectedId)||null;
 const title=p=>p.name||"이름 미기재";
 const topicName=id=>(C.topics.find(t=>t.id===id)||{}).name||id;
 const historical=p=>{const profile=p.sourceProfile||{};return profile.display_type==="historical_researcher"||profile.current_status?.category==="deceased"||profile.affiliation_status==="deceased";};
 const historicalNotice="역사적 연구 자료 · 실제 자문 가능 대상 아님";
 function personDistinction(p){
  const nobel=Array.isArray(p.awards)&&p.awards.some(item=>{
   const award=item&&item.sourceAward;
   if(!award||award.name!=="Nobel Prize"||award.recognition_kind!=="nobel"||typeof award.facts_url!=="string")return false;
   try{const url=new URL(award.facts_url);return url.protocol==="https:"&&(url.hostname==="nobelprize.org"||url.hostname==="www.nobelprize.org")&&!url.username&&!url.password&&!url.port;}catch{return false;}
  }),team=p.sourcePerson?.team_member===true;
  const teamIds=Array.isArray(p.sourcePerson?.team_project_ids)?p.sourcePerson.team_project_ids:[],projects=Array.isArray(p.sourceProfile?.projects)?p.sourceProfile.projects:[];
  const teamTitles=projects.filter(project=>project&&teamIds.includes(project.id)&&typeof project.title==="string").map(project=>project.title.trim()).filter(Boolean);
  const teamLabel=team?([...new Set(teamTitles)].join(" · ")||"우리 팀"):"";
  return {nobel,team,teamLabel,classes:(nobel?" mp-person-nobel":"")+(team?" mp-person-team":""),labels:[nobel?"노벨상 수상자":"",teamLabel].filter(Boolean)};
 }
 const portraitPath=p=>p.portrait&&/^\/portraits\/[a-z0-9-]+\.(png|jpg|jpeg)$/i.test(p.portrait.path||"")?p.portrait.path.replace(/\.(?:png|jpe?g)$/i,'-thumb.webp'):null;
 const recordType=r=>r.typeLabel||r.type||"기록";
 const recordRole=r=>r.role||"역할 미기재";
 const recordDate=r=>r.recordDate||"자료 날짜 미기재";
 const checked=(s,p)=>C.selectedEvidence(s,p);
 const currentCapability=s=>C.capabilities.find(c=>c.id===s.capability)||null;
 const shortScope=(s,p)=>C.capabilityLink(s,p)?.scope||p.sourceProfile?.tagline||C.visibleEvidence(s,p)[0]?.title||"연결된 근거를 확인해 주세요";
 const PAGE_SIZE=25;
 const G=(GraphFactory||globalThis.createPeopleMapGraph)(C);

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
 function projectParticipants(raw){
  if(raw.kind!=="project_record"||!Array.isArray(raw.project_participants))return "";
  const seen=new Set(),links=[];
  for(const participant of raw.project_participants){
   if(!participant||typeof participant.id!=="string"||typeof participant.display_name!=="string"||!participant.display_name.trim()||seen.has(participant.id)||!C.people.some(p=>p.id===participant.id))continue;
   seen.add(participant.id);
   links.push('<button type="button" class="text-button" data-map-open="person" data-id="'+esc(participant.id)+'" aria-label="'+esc(participant.display_name+' 인물 상세 보기')+'">'+esc(participant.display_name)+' ↗</button>');
  }
  return links.length?'<div class="mp-project-participants"><p>함께한 사람 · 사용자 제공 참여 정보</p>'+links.join(' ')+'</div>':"";
 }
 function recordCard(r,s,index){
  const link=safeUrl(r.sourceUrl),details=[],raw=r.sourceRecord||{};
  if(r.period)details.push('<dt>참여 기간</dt><dd>'+esc(r.period)+'</dd>');
  else if(raw.kind==="career_record")details.push('<dt>기재 기간</dt><dd>'+esc(r.recordDate||"미기재")+' · 제공 자료 기준</dd>');
  else details.push('<dt>참여 기간</dt><dd>미기재 · 자료 날짜와 구분</dd>');
  if(r.organization)details.push('<dt>자료상 소속</dt><dd>'+esc(r.organization)+'</dd>');
  const source=link?'<a class="source-link" href="'+esc(link)+'" target="_blank" rel="noopener noreferrer">'+esc(r.sourceLabel||"원 출처 열기")+' ↗</a>':'<span class="micro">'+esc(r.sourceLabel||"원 출처 링크 미기재")+'</span>';
  return '<article class="record-card" data-record="'+esc(r.id)+'"><div class="section-label"><span>'+esc(recordType(r))+(raw.virtual?' · 기존 가상 기록':'')+'</span><span>'+(raw.kind==="career_record"?'기재 기간 · ':'자료 날짜 · ')+esc(recordDate(r))+'</span></div><h3>'+esc(r.title||"제목 미기재")+'</h3><p class="role-line">'+esc(recordRole(r))+'</p>'+(r.summary?'<p class="record-summary">'+esc(r.summary)+'</p>':'')+(raw.boundary?'<p class="record-boundary">'+esc(raw.boundary)+'</p>':'')+'<dl class="facts">'+details.join("")+'</dl>'+projectParticipants(raw)+((r.topics||[]).length?'<div class="record-topics">'+r.topics.map(t=>'<span>'+esc(topicName(t))+'</span>').join("")+'</div>':'')+'<details class="source-details"><summary>출처와 표시 범위</summary>'+source+additionalRecordSources(raw)+(r.provenance?'<p>'+displayValue(r.provenance)+'</p>':'')+(raw.evidence_label?'<p>자료 분류: '+esc(raw.evidence_label)+'</p>':'')+(raw.classification_basis?'<p>분류 근거: '+esc(raw.classification_basis)+'</p>':'')+(raw.access?'<p>원자료 접근 표기: '+esc(raw.access)+'</p>':'')+(raw.checked_at?'<p>자료 확인 시점: '+esc(raw.checked_at)+'</p>':'')+(raw.corresponding?'<p>교신저자 표기 있음</p>':'')+'<p>기록에 나온 연결과 역할을 보여줍니다. 현재의 수행 역량·자문 가능 여부를 확정하지 않습니다.</p></details><button type="button" class="text-button" data-map-open="record" data-id="'+esc(r.id)+'">기록 원문 상세 보기 ↗</button><label class="evidence-check"><input type="checkbox" id="evidence-'+index+'" data-evidence="'+esc(r.id)+'"'+(s.evidenceIds.includes(r.id)?' checked':'')+'>이 근거를 질문 준비에 포함</label></article>';
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
  const active=s.selectedId===p.id,records=C.visibleEvidence(s,p),path=portraitPath(p),distinction=personDistinction(p),scope=shortScope(s,p);
  const label=[title(p),...distinction.labels,scope,'근거 '+records.length+'개 보기',p.virtual?'가상 사례':''].filter(Boolean).join(' · ');
  return '<button type="button" class="mp-person'+distinction.classes+'" data-person="'+esc(p.id)+'" aria-pressed="'+active+'" aria-controls="person-detail" aria-label="'+esc(label)+'"><span class="mp-portrait"><span class="mp-initial" aria-hidden="true">'+esc(Array.from(title(p))[0]||"")+'</span>'+(path?'<img src="'+esc(path)+'" alt="" loading="lazy" decoding="async" width="108" height="144">':'')+'</span><span class="mp-person-text"><strong class="mp-person-name">'+esc(title(p))+'</strong><span class="mp-person-field">'+esc(scope)+'</span><span class="mp-person-records">'+(distinction.team?'<span class="mp-list-team-marker" aria-hidden="true">'+esc(distinction.teamLabel)+'</span> · ':'')+'근거 '+records.length+'개 보기'+(p.virtual?' · 가상 사례':'')+'</span></span><span class="mp-person-arrow" aria-hidden="true">↗</span></button>';
 }
 function renderLegacyMap(s){
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
 function fieldColor(key){
  const colors=['#56783c','#84743b','#396f69','#55749a','#48808a','#9a6741','#87634b','#866688','#687942'];
  let hash=0;for(const char of key)hash=(hash*31+char.charCodeAt(0))>>>0;return colors[hash%colors.length];
 }
 function renderMap(s){
  if(s.view==='organization')return renderLegacyMap(s);
  const graph=G.graph(s),selected=selectedPerson(s);
  const nodes=graph.nodes.map(n=>{
   if(n.type==='person'){
    const p=graph.visible.find(p=>p.id===n.id),path=portraitPath(p),scope=shortScope(s,p),distinction=personDistinction(p);
    const label=[title(p),...distinction.labels,scope,'근거 '+C.visibleEvidence(s,p).length+'개 보기',p.virtual?'가상 사례':'','인물과 근거 보기'].filter(Boolean).join(' · ');
    return '<button type="button" class="mp-spatial-node mp-spatial-person'+distinction.classes+'" data-map-node="'+esc(n.key)+'" data-person="'+esc(p.id)+'" aria-pressed="'+(s.selectedId===p.id)+'" aria-controls="person-detail" aria-label="'+esc(label)+'" title="'+esc(title(p)+' · '+scope)+'"><span class="mp-face-shell"><span class="mp-node-face">'+(path?'<img src="'+esc(path)+'" alt="" decoding="async" width="150" height="200">':'<span aria-hidden="true">'+esc(Array.from(title(p))[0])+'</span>')+'</span>'+(distinction.team?'<span class="mp-team-marker" aria-hidden="true">'+esc(distinction.teamLabel)+'</span>':'')+'</span><span class="mp-node-name">'+esc(title(p))+'</span><span class="mp-node-field">'+esc(scope)+'</span></button>';
   }
   const filter=n.filter||{type:'CAPABILITY',value:n.id};
   return '<button type="button" class="mp-spatial-node mp-spatial-field" style="--field-color:'+fieldColor(n.key)+'" data-map-node="'+esc(n.key)+'" data-map-filter="'+esc(filter.type)+'" data-map-filter-value="'+esc(filter.value)+'" aria-controls="people-map" aria-pressed="'+(filter.type==='TOPIC'?s.topic===filter.value:s.capability===filter.value)+'"><span>'+esc(n.label)+'</span><small>'+(filter.type==='TOPIC'?'자료 주제':'역량 연결')+'</small></button>';
  }).join('');
  const edges=graph.edges.map(e=>'<path class="mp-spatial-edge" style="--field-color:'+fieldColor(e.from)+'" data-from="'+esc(e.from)+'" data-to="'+esc(e.to)+'" data-record-ids="'+esc(e.recordIds.join(','))+'"></path>').join('');
  return '<div class="mp-graph-shell mobile-show-map"><div class="mp-selection-tools"><span id="mp-selection-label">'+(selected?esc(title(selected))+' 선택':'인물을 선택하면 연결 근거가 열립니다.')+'</span><button type="button" data-map-action="show-detail"'+(!selected?' hidden':'')+'>근거 패널로 이동 ↓</button><button type="button" data-map-action="clear-selection"'+(!selected?' hidden':'')+'>선택 해제</button><button type="button" class="mp-mobile-toggle" data-map-action="mobile-view" aria-controls="mp-mobile-people mp-graph-stage">리스트 보기</button></div><div id="mp-mobile-people" class="mp-mobile-people">'+(graph.visible.length?graph.visible.map(p=>personCard(p,s)).join(''):'<p class="mp-empty">현재 조건에 연결된 인물이 없습니다. <button type="button" data-map-action="clear-all">조건 모두 해제</button></p>')+'</div><div id="mp-graph-stage" class="mp-graph-stage'+(graph.visible.length<=2?' compact':'')+'" tabindex="0" role="group" aria-label="분야와 사람의 연결 지도" aria-describedby="mp-graph-help"><svg class="mp-spatial-edges" aria-hidden="true" focusable="false">'+edges+'</svg><div class="mp-spatial-nodes">'+nodes+'</div>'+(!graph.visible.length?'<p class="mp-empty">현재 조건에 연결된 인물이 없습니다. <button type="button" data-map-action="clear-all">조건 모두 해제</button></p>':'')+'</div><div class="mp-graph-controls"><button type="button" data-map-camera="out" aria-label="지도 축소">−</button><output id="mp-zoom-level" aria-label="확대 비율">100%</output><button type="button" data-map-camera="in" aria-label="지도 확대">+</button><button type="button" data-map-camera="fit">화면 맞춤</button><p id="mp-graph-help" class="mp-graph-help">드래그로 이동 · + / − 확대 · 방향키 이동 · Home 화면 맞춤. 전체 보기에서 글자가 작으면 확대해 주세요.</p></div></div>';
 }
 function mount(doc,host){
  const win=doc.defaultView,$=id=>host.querySelector('#'+id);
  let state=C.initialState(),graph=null,frame=0,mobileMap=true,lastPerson=null;
  const camera={x:0,y:0,scale:1},pointers=new Map();let drag=null,pinch=null,dragged=false;
  const clamp=(v,a,b)=>Math.max(a,Math.min(b,v));
  const observer=win.ResizeObserver?new win.ResizeObserver(()=>schedule()):null;
  function legacyLines(){
   const map=host.querySelector('.mp-graph'),node=map?.querySelector('.mp-capability-node'),svg=map?.querySelector('.mp-lines');
   if(!map||!node||!svg)return;
   const bounds=map.getBoundingClientRect(),from=node.getBoundingClientRect();if(!bounds.width||!bounds.height)return;
   svg.setAttribute('viewBox',`0 0 ${bounds.width} ${bounds.height}`);svg.replaceChildren();
   map.querySelectorAll('[data-person]').forEach(button=>{
    const to=button.getBoundingClientRect(),path=doc.createElementNS('http://www.w3.org/2000/svg','path'),y=to.top+to.height/2-bounds.top,x=to.left-bounds.left;
    if(from.right<=to.left){const sx=from.right-bounds.left,sy=from.top+from.height/2-bounds.top,mid=sx+(x-sx)/2;path.setAttribute('d',`M ${sx} ${sy} C ${mid} ${sy}, ${mid} ${y}, ${x} ${y}`);}
    else{const sx=from.left+12-bounds.left,sy=from.bottom-bounds.top;path.setAttribute('d',`M ${sx} ${sy} V ${y} H ${x}`);}
    path.setAttribute('class',button.dataset.person===state.selectedId?'mp-line-active':'mp-line');svg.append(path);
   });
  }
  function cameraApply(){
   const stage=$('mp-graph-stage');if(!stage||!graph)return;
   const nodes=new Map(graph.nodes.map(n=>[n.key,n]));
   for(const el of stage.querySelectorAll('[data-map-node]')){
    const n=nodes.get(el.dataset.mapNode);if(!n)continue;
    el.style.width=n.width+'px';el.style.height=n.height+'px';
    el.style.transform='translate('+(camera.x+n.x*camera.scale)+'px,'+(camera.y+n.y*camera.scale)+'px) translate(-50%,-50%) scale('+camera.scale+')';
   }
   for(const el of stage.querySelectorAll('.mp-spatial-edge')){
    const a=nodes.get(el.dataset.from),b=nodes.get(el.dataset.to);if(!a||!b)continue;
    el.setAttribute('d','M'+(camera.x+a.x*camera.scale)+','+(camera.y+a.y*camera.scale)+' L'+(camera.x+b.x*camera.scale)+','+(camera.y+b.y*camera.scale));
   }
   $('mp-zoom-level').textContent=Math.round(camera.scale*100)+'%';
  }
  function fit(){
   if(state.view==='organization'){legacyLines();return;}
   const stage=$('mp-graph-stage');if(!stage||!stage.clientWidth||!stage.clientHeight||!graph)return;
   if(!graph.nodes.length){camera.x=stage.clientWidth/2;camera.y=stage.clientHeight/2;camera.scale=1;cameraApply();return;}
   const left=Math.min(...graph.nodes.map(n=>n.x-n.width/2)),right=Math.max(...graph.nodes.map(n=>n.x+n.width/2)),top=Math.min(...graph.nodes.map(n=>n.y-n.height/2)),bottom=Math.max(...graph.nodes.map(n=>n.y+n.height/2));
   camera.scale=clamp(Math.min((stage.clientWidth-44)/Math.max(right-left,180),(stage.clientHeight-44)/Math.max(bottom-top,140)),.15,1.1);
   camera.x=stage.clientWidth/2-(left+right)/2*camera.scale;camera.y=stage.clientHeight/2-(top+bottom)/2*camera.scale;cameraApply();
  }
  function schedule(){if(!frame)frame=win.requestAnimationFrame(()=>{frame=0;fit();});}
  function zoom(factor,at){
   const stage=$('mp-graph-stage');if(!stage)return;
   const p=at||{x:stage.clientWidth/2,y:stage.clientHeight/2},old=camera.scale;
   camera.scale=clamp(old*factor,.15,3);camera.x=p.x-(p.x-camera.x)*camera.scale/old;camera.y=p.y-(p.y-camera.y)*camera.scale/old;cameraApply();
  }
  function emphasis(hover){
   const key=hover||(state.selectedId?'person:'+state.selectedId:null),related=new Set(key?[key]:[]);
   for(const edge of graph?.edges||[])if(edge.from===key||edge.to===key){related.add(edge.from);related.add(edge.to);}
   for(const el of host.querySelectorAll('[data-map-node]'))el.classList.toggle('related',related.has(el.dataset.mapNode));
   for(const el of host.querySelectorAll('[data-person]'))el.setAttribute('aria-pressed',String(el.dataset.person===state.selectedId));
   for(const el of host.querySelectorAll('.mp-spatial-edge'))el.classList.toggle('active',!!key&&(el.dataset.from===key||el.dataset.to===key));
  }
  function detail(){
   const selected=selectedPerson(state),container=$('person-detail');
   container.innerHTML=renderDetail(state);container.hidden=!selected;
   const label=$('mp-selection-label');if(label)label.textContent=selected?title(selected)+' 선택':'인물을 선택하면 연결 근거가 열립니다.';
   for(const button of host.querySelectorAll('[data-map-action="show-detail"],[data-map-action="clear-selection"]'))button.hidden=!selected;
   emphasis();if(state.view==='organization')legacyLines();
  }
  function mobile(){
   host.querySelector('.mp-graph-shell')?.classList.toggle('mobile-show-map',mobileMap);
   const button=host.querySelector('[data-map-action="mobile-view"]');
   if(button)button.textContent=mobileMap?'리스트 보기':'연결 지도 보기';
  }
  function render(){
   const people=C.visiblePeople(state),capability=currentCapability(state),ids=new Set(people.flatMap(p=>C.visibleEvidence(state,p).map(r=>r.id)));
   graph=state.view==='organization'?null:G.graph(state);
   $('capability-controls').innerHTML=renderCapabilities(state);$('people-map').innerHTML=renderMap(state);
   $('people-map-content').dataset.mpCount=String(people.length);
   $('map-title').textContent=capability?.label||'연구 경험의 연결';
   $('map-explanation').textContent=(capability?.description||'이름과 자료 주제로 찾거나 역량을 골라 연결 근거를 살펴보세요.')+(state.view==='organization'?' 자료에 기재된 소속이며 현재 재직이나 협업 관계를 뜻하지 않습니다.':'');
   $('map-count').textContent=people.length+'명 · 연결 기록 '+ids.size+'개';
   $('results-summary').textContent=people.length+'명'+(capability?' · '+capability.label:'')+(state.query?' · 이름 “'+state.query+'”':'')+(state.topic?' · '+topicName(state.topic):'');
   $('view-control').value=state.view;$('topic-controls').value=state.topic;if($('name-search').value!==state.query)$('name-search').value=state.query;
   detail();mobile();pointers.clear();drag=null;pinch=null;
   observer?.disconnect();const stage=$('mp-graph-stage');if(stage)observer?.observe(stage);schedule();
  }
  const filtering=new Set(['QUERY','TOPIC','SCOPE','CAPABILITY','CLEAR_FILTERS','PAGE','VIEW']);
  function dispatch(action){state=C.reduce(state,action);if(filtering.has(action.type))render();else detail();}
  function clearSelection(restore){const id=state.selectedId;dispatch({type:'CLOSE_DETAIL'});if(restore){const candidates=[...host.querySelectorAll('[data-person]')].filter(b=>b.dataset.person===(id||lastPerson));candidates.find(b=>b.getClientRects().length)?.focus({preventScroll:true});}}
  $('topic-controls').innerHTML='<option value="">전체 주제</option>'+C.topics.map(t=>'<option value="'+esc(t.id)+'">'+esc(t.name)+'</option>').join('');
  $('scope-note').textContent='전체 등록 '+C.people.length+'명 · '+C.counts.records+'개 기록을 유지합니다.';
  host.addEventListener('error',event=>{
   const image=event.target;if(!image.matches?.('.mp-portrait img,.mp-node-face img'))return;
   const face=image.parentElement;image.remove();face.classList.add('mp-portrait-failed');face.textContent='그림 없음';face.setAttribute('aria-label','초상을 불러오지 못했습니다. 이름과 근거로 탐색할 수 있습니다.');
  },true);
  host.addEventListener('input',event=>{const t=event.target;if(t.id==='name-search'){dispatch({type:'QUERY',value:t.value});return;}const types={problem:'PROBLEM',draft:'DRAFT',aiText:'AI_TEXT'};if(types[t.dataset.field])state=C.reduce(state,{type:types[t.dataset.field],value:t.value});});
  host.addEventListener('change',event=>{const t=event.target;if(t.id==='topic-controls')dispatch({type:'TOPIC',value:t.value});else if(t.id==='view-control')dispatch({type:'VIEW',value:t.value});else if(t.dataset.evidence){const id=t.id;dispatch({type:'EVIDENCE',id:t.dataset.evidence,checked:t.checked});$(id)?.focus({preventScroll:true});}else if(t.id==='include-ai'){dispatch({type:'INCLUDE_AI',value:t.checked});$('include-ai')?.focus({preventScroll:true});}});
  host.addEventListener('click',event=>{
   const button=event.target.closest('button');if(!button||!host.contains(button))return;
   if(button.dataset.mapCamera){if(button.dataset.mapCamera==='fit')fit();else zoom(button.dataset.mapCamera==='in'?1.2:1/1.2);return;}
   if(button.dataset.mapFilter){const type=button.dataset.mapFilter,value=button.dataset.mapFilterValue,field=type==='TOPIC'?'topic':'capability';dispatch({type,value:state[field]===value?'':value});const target=[...host.querySelectorAll('[data-map-filter]')].find(b=>b.dataset.mapFilter===type&&b.dataset.mapFilterValue===value);(target||$('mp-graph-stage'))?.focus({preventScroll:true});}
   else if(button.hasAttribute('data-capability')){const id=button.dataset.capability;dispatch({type:'CAPABILITY',value:state.capability===id?'':id});[...host.querySelectorAll('[data-capability]')].find(b=>b.dataset.capability===id)?.focus({preventScroll:true});}
   else if(button.dataset.person){if(dragged)return;lastPerson=button.dataset.person;dispatch({type:'SELECT',id:lastPerson});}
   else if(button.hasAttribute('data-page')){dispatch({type:'PAGE',value:Number(button.dataset.page)});$('map-title').scrollIntoView({block:'start',behavior:'auto'});}
   else if(button.id==='clear-filters'||button.dataset.mapAction==='clear-all'){dispatch({type:'CLEAR_FILTERS'});$('name-search').focus({preventScroll:true});}
   else if(['close','clear-selection'].includes(button.dataset.mapAction))clearSelection(true);
   else if(button.dataset.mapAction==='show-detail'){$('detail-title')?.focus({preventScroll:true});$('person-detail').scrollIntoView({block:'start',behavior:'auto'});}
   else if(button.dataset.mapAction==='mobile-view'){mobileMap=!mobileMap;mobile();fit();}
   else if(button.dataset.mapAction==='ack-draft'){dispatch({type:'ACK_DRAFT_CONTEXT'});$('draft')?.focus({preventScroll:true});}
   else if(button.dataset.mapAction==='reset-draft'){dispatch({type:'RESET_DRAFT'});$('draft')?.focus({preventScroll:true});}
  });
  host.addEventListener('pointerover',e=>{const node=e.target.closest('[data-map-node]');if(node)emphasis(node.dataset.mapNode);});
  host.addEventListener('pointerout',e=>{const node=e.target.closest('[data-map-node]');if(node&&!node.contains(e.relatedTarget))emphasis();});
  host.addEventListener('focusin',e=>{const node=e.target.closest('[data-map-node]');if(node)emphasis(node.dataset.mapNode);});
  host.addEventListener('focusout',e=>{if(e.target.closest('[data-map-node]'))emphasis();});
  host.addEventListener('keydown',e=>{
   if(e.target.matches('input,textarea,select'))return;
   if(e.key==='Escape'&&state.selectedId){e.preventDefault();clearSelection(true);return;}
   if(e.target.id!=='mp-graph-stage')return;
   const moves={ArrowLeft:[45,0],ArrowRight:[-45,0],ArrowUp:[0,45],ArrowDown:[0,-45]};
   if(moves[e.key]){e.preventDefault();camera.x+=moves[e.key][0];camera.y+=moves[e.key][1];cameraApply();}
   else if(['+','=','-','Home'].includes(e.key)){e.preventDefault();if(e.key==='Home')fit();else zoom(e.key==='-'?1/1.2:1.2);}
  });
  host.addEventListener('wheel',e=>{const stage=e.target.closest('#mp-graph-stage');if(!stage)return;e.preventDefault();const r=stage.getBoundingClientRect();zoom(e.deltaY<0?1.08:1/1.08,{x:e.clientX-r.left,y:e.clientY-r.top});},{passive:false});
  host.addEventListener('pointerdown',e=>{
   const stage=e.target.closest('#mp-graph-stage');if(!stage||e.button>0)return;
   pointers.set(e.pointerId,{x:e.clientX,y:e.clientY});dragged=false;
   if(pointers.size===2){const[a,b]=[...pointers.values()];pinch=Math.hypot(a.x-b.x,a.y-b.y);drag=null;stage.setPointerCapture(e.pointerId);}
   else if(!e.target.closest('button')){drag={id:e.pointerId,x:e.clientX,y:e.clientY,startX:e.clientX,startY:e.clientY};stage.setPointerCapture(e.pointerId);}
  });
  host.addEventListener('pointermove',e=>{
   if(!pointers.has(e.pointerId))return;const stage=$('mp-graph-stage');if(!stage)return;
   pointers.set(e.pointerId,{x:e.clientX,y:e.clientY});
   if(pointers.size===2){const[a,b]=[...pointers.values()],distance=Math.hypot(a.x-b.x,a.y-b.y),r=stage.getBoundingClientRect();if(pinch>0)zoom(distance/pinch,{x:(a.x+b.x)/2-r.left,y:(a.y+b.y)/2-r.top});pinch=distance;dragged=true;}
   else if(drag?.id===e.pointerId){if(Math.hypot(e.clientX-drag.startX,e.clientY-drag.startY)>4)dragged=true;if(dragged){camera.x+=e.clientX-drag.x;camera.y+=e.clientY-drag.y;cameraApply();stage.classList.add('dragging');}drag.x=e.clientX;drag.y=e.clientY;}
  });
  function end(e){pointers.delete(e.pointerId);if(drag?.id===e.pointerId)drag=null;pinch=null;$('mp-graph-stage')?.classList.remove('dragging');win.setTimeout(()=>{dragged=false;},0);}
  host.addEventListener('pointerup',end);host.addEventListener('pointercancel',end);
  win.addEventListener('blur',()=>{pointers.clear();drag=null;pinch=null;dragged=false;$('mp-graph-stage')?.classList.remove('dragging');});
  win.addEventListener('resize',schedule);render();
  return {getState:()=>({...state,evidenceIds:[...state.evidenceIds]})};
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
