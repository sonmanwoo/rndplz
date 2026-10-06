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
  const teamLabel=team?"우리 팀":"";
  return {nobel,team,teamLabel,classes:(nobel?" mp-person-nobel":"")+(team?" mp-person-team":""),labels:[nobel?"노벨상 수상자":"",teamLabel].filter(Boolean)};
 }
 const portraitPath=p=>p.portrait&&/^\/portraits\/[a-z0-9-]+\.(png|jpg|jpeg)$/i.test(p.portrait.path||"")?p.portrait.path.replace(/\.(?:png|jpe?g)$/i,'-thumb.webp'):null;
 const recordType=r=>r.typeLabel||r.type||"기록";
 const recordRole=r=>r.role||"역할 미기재";
 const recordDate=r=>r.recordDate||"자료 날짜 미기재";
 const checked=(s,p)=>C.selectedEvidence(s,p);
 const currentCapability=s=>C.capabilities.find(c=>c.id===s.capability)||null;
 const shortScope=(s,p)=>(currentCapability(s)?.kind==='project'?null:C.capabilityLink(s,p)?.scope)||p.sourceProfile?.tagline||C.visibleEvidence(s,p)[0]?.title||"연결된 근거를 확인해 주세요";
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
 // Links the person provided to introduce themselves (a personal site, a scroll resume): shown as
 // plain outbound links, never fetched, embedded or treated as evidence.
 function renderIntroLinks(p){
  const links=Array.isArray(p.sourceProfile?.links)?p.sourceProfile.links:[];
  const items=links.map(link=>{const url=safeUrl(link?.url);if(!url)return "";const label=typeof link.label==="string"&&link.label.trim()?link.label.trim():"소개 페이지";
   return '<a class="source-link mp-intro-link" href="'+esc(url)+'" target="_blank" rel="noopener noreferrer"'+(typeof link.note==="string"&&link.note?' title="'+esc(link.note)+'"':'')+'>'+esc(label)+' ↗</a>';}).filter(Boolean);
  return items.length?'<p class="mp-intro-links"><span class="mp-intro-label">본인이 소개하는 자료</span>'+items.join(' · ')+'</p>':"";
 }
 function renderProfile(p){
  const raw=p.sourceProfile||{},keys={tagline:"프로필 한 줄",biography:"소개",skills:"프로필에 기재된 기술",skill_groups:"기술 묶음",interests:"관심 주제",timeline:"제공 이력",projects:"기재 프로젝트",education:"학력",sources:"프로필 출처",portrait_note:"일러스트 참고 정보",profile_note:"프로필 표시 범위",current_role:"기재된 현재 역할",role:"기재 역할",source_type:"정보 제공 방식",checked_at:"자료 확인 시점",profile_observed_as_of:"공개 프로필 관측일 · 재직 확인 아님",limit:"해석 범위",employment_verification:"재직 확인 상태",collaboration_availability:"자문 가능 여부",contact_consent:"연락 동의 상태"};
  const rows=Object.entries(keys).filter(([key])=>raw[key]!=null&&raw[key]!==""&&(!Array.isArray(raw[key])||raw[key].length));
  if(!rows.length)return "";
  return '<details class="profile-info"><summary>프로필에 제공된 내용과 출처</summary>'+rows.map(([key,label])=>'<p><strong>'+label+'</strong></p>'+displayValue(raw[key])).join("")+'</details>';
 }



 function renderCapabilities(s){
  return C.capabilities.map((c,index)=>'<button type="button" class="mp-capability" data-capability="'+esc(c.id)+'" aria-pressed="'+(s.capability===c.id)+'" aria-controls="people-map person-detail"><span class="mp-capability-index">'+String(index+1).padStart(2,"0")+'</span><span class="mp-capability-label">'+esc(c.label)+(c.kind==='project'?'<small class="mp-capability-kind">프로젝트 참여</small>':'')+'</span><span class="mp-capability-count">'+C.visiblePeople({...s,capability:c.id}).length+'명</span></button>').join("");
 }
 function personCard(p,s){
  const active=s.selectedId===p.id,records=C.visibleEvidence(s,p),path=portraitPath(p),distinction=personDistinction(p),scope=shortScope(s,p);
  const label=[title(p),...distinction.labels,scope,'근거 '+records.length+'개 보기',p.virtual?'가상 사례':''].filter(Boolean).join(' · ');
  return '<button type="button" class="mp-person'+distinction.classes+'" data-person="'+esc(p.id)+'" data-map-open="person" data-id="'+esc(p.id)+'" aria-haspopup="dialog" aria-pressed="'+active+'" aria-controls="detailDialog" aria-label="'+esc(label)+'"><span class="mp-portrait"><span class="mp-initial" aria-hidden="true">'+esc(Array.from(title(p))[0]||"")+'</span>'+(path?'<img src="'+esc(path)+'" alt="" loading="lazy" decoding="async" width="108" height="144">':'')+'</span><span class="mp-person-text"><strong class="mp-person-name">'+esc(title(p))+'</strong><span class="mp-person-field">'+esc(scope)+'</span><span class="mp-person-records">'+(distinction.team?'<span class="mp-list-team-marker" aria-hidden="true">'+esc(distinction.teamLabel)+'</span> · ':'')+'근거 '+records.length+'개 보기'+(p.virtual?' · 가상 사례':'')+'</span></span><span class="mp-person-arrow" aria-hidden="true">↗</span></button>';
 }
 function renderLegacyMap(s){
  const people=C.visiblePeople(s),capability=currentCapability(s),page=Math.min(s.page||0,Math.max(0,Math.ceil(people.length/PAGE_SIZE)-1)),shown=people.slice(page*PAGE_SIZE,(page+1)*PAGE_SIZE);
  if(!people.length)return '<p class="mp-empty">현재 조건에 연결된 인물이 없습니다. <button type="button" data-map-action="clear-all">조건 모두 해제</button></p>';
  let cards=shown.map(p=>personCard(p,s)).join('');
  if(s.view==='organization'){
   const groups=new Map();shown.forEach(p=>{const org=p.organizationGroupName||p.organization||'소속 미기재';if(!groups.has(org))groups.set(org,[]);groups.get(org).push(p);});
   cards=[...groups].map(([org,group])=>'<section class="mp-org-group"><h3>자료상 '+esc(org)+'</h3>'+group.map(p=>personCard(p,s)).join('')+'</section>').join('');
  }
  let html='<div class="mp-graph"><svg class="mp-lines" aria-hidden="true" focusable="false"></svg><div class="mp-capability-node"><span class="mp-node-mark">↗</span><span class="mp-node-eyebrow">'+(capability?.kind==='project'?'선택한 프로젝트':capability?'선택한 역량':'등록 자료')+'</span><strong class="mp-node-title">'+esc(capability?.label||"등록된 연구 경험")+'</strong><span class="mp-node-count">'+people.length+'명의 연결 기록</span></div><div class="mp-people">'+cards+'</div></div>';
  if(people.length>PAGE_SIZE)html+='<div class="mp-pager"><button type="button" data-page="'+(page-1)+'"'+(!page?' disabled':'')+'>이전</button><span>'+(page*PAGE_SIZE+1)+'–'+Math.min(people.length,(page+1)*PAGE_SIZE)+' / '+people.length+'명</span><button type="button" data-page="'+(page+1)+'"'+((page+1)*PAGE_SIZE>=people.length?' disabled':'')+'>다음</button></div>';
  return html;
 }
 function renderDetail(s){
  const p=selectedPerson(s);
  if(!p)return '<p class="mp-section-label">선택한 사람의 연결 근거</p><h2 class="mp-evidence-title">인물을 선택해 주세요</h2><p class="mp-empty">연결된 기록과 그 자료의 범위를 살펴볼 수 있어요.</p>';
  const records=C.visibleEvidence(s,p);
  let html='<p class="mp-section-label">선택한 사람의 연결 근거</p><h2 id="detail-title" class="mp-evidence-title" tabindex="-1">'+esc(title(p))+'</h2><p class="mp-evidence-scope">'+esc(shortScope(s,p))+'</p><div class="mp-detail-links"><button type="button" data-map-open="person" data-id="'+esc(p.id)+'">인물 상세 보기 ↗</button><button type="button" data-map-action="close">선택 닫기</button></div>';
  html+=renderIntroLinks(p);
  if(historical(p))html+='<p class="mp-record-limit">'+historicalNotice+'</p>';
  if(!records.length)return html+'<p class="mp-empty">현재 조건에 연결된 기록이 없습니다. 경험이 없다는 뜻은 아닙니다.</p>';
  html+='<div class="mp-evidence-list">'+records.map((r,i)=>'<details class="mp-record"'+(!i?' open':'')+'><summary class="mp-record-summary"><span class="mp-record-meta">'+esc(recordType(r))+' · '+esc(recordDate(r))+'</span><strong class="mp-record-title">'+esc(r.title||"제목 미기재")+'</strong><span class="mp-record-toggle">근거 읽기</span></summary><div class="mp-record-body">'+recordCard(r,s,i)+'</div></details>').join("")+'</div>';
  return html+renderQuestion(s,p)+renderAssetSources(p)+renderProfile(p);
 }
 function fieldColor(key){
  const colors=['#56783c','#84743b','#396f69','#55749a','#48808a','#9a6741','#87634b','#866688','#687942'];
  let hash=0;for(const char of key)hash=(hash*31+char.charCodeAt(0))>>>0;const index=hash%colors.length;return 'var(--map-color-'+index+','+colors[index]+')';
 }
 function renderMap(s){
  if(s.view==='organization')return renderLegacyMap(s);
  const graph=G.graph(s),selected=selectedPerson(s);
  const nodes=graph.nodes.map(n=>{
   if(n.type==='person'){
    const p=graph.visible.find(p=>p.id===n.id),path=portraitPath(p),scope=shortScope(s,p),distinction=personDistinction(p);
    const label=[title(p),...distinction.labels,scope,'근거 '+C.visibleEvidence(s,p).length+'개 보기',p.virtual?'가상 사례':'','인물과 근거 보기'].filter(Boolean).join(' · ');
    return '<button type="button" class="mp-spatial-node mp-spatial-person'+distinction.classes+'" data-map-node="'+esc(n.key)+'" data-person="'+esc(p.id)+'" data-map-open="person" data-id="'+esc(p.id)+'" aria-haspopup="dialog" aria-pressed="'+(s.selectedId===p.id)+'" aria-controls="detailDialog" aria-label="'+esc(label)+'" title="'+esc(title(p)+' · '+scope)+'"><span class="mp-face-shell"><span class="mp-node-face">'+(path?'<img src="'+esc(path)+'" alt="" decoding="async" width="150" height="200">':'<span aria-hidden="true">'+esc(Array.from(title(p))[0])+'</span>')+'</span>'+(distinction.team?'<span class="mp-team-marker" aria-hidden="true">'+esc(distinction.teamLabel)+'</span>':'')+'</span><span class="mp-node-name">'+esc(title(p))+'</span><span class="mp-node-field">'+esc(scope)+'</span></button>';
   }
   const filter=n.filter||{type:'CAPABILITY',value:n.id};
   return '<button type="button" class="mp-spatial-node mp-spatial-field" style="--field-color:'+fieldColor(n.key)+'" data-map-node="'+esc(n.key)+'" data-map-filter="'+esc(filter.type)+'" data-map-filter-value="'+esc(filter.value)+'" aria-controls="people-map" aria-pressed="'+(filter.type==='TOPIC'?s.topic===filter.value:s.capability===filter.value)+'"><span>'+esc(n.label)+'</span><small>'+(n.kind==='project'?'프로젝트 참여':filter.type==='TOPIC'?'자료 주제':'역량 연결')+'</small></button>';
  }).join('');
  const edges=graph.edges.map(e=>'<path class="mp-spatial-edge" style="--field-color:'+fieldColor(e.from)+'" data-from="'+esc(e.from)+'" data-to="'+esc(e.to)+'" data-record-ids="'+esc(e.recordIds.join(','))+'"></path>').join('');
  return '<div class="mp-graph-shell mobile-show-map"><div class="mp-selection-tools"><span id="mp-selection-label">'+(selected?esc(title(selected))+' 선택':'인물을 선택하면 연결 근거가 열립니다.')+'</span><button type="button" data-map-action="show-detail"'+(!selected?' hidden':'')+'>근거 패널로 이동 ↓</button><button type="button" data-map-action="clear-selection"'+(!selected?' hidden':'')+'>선택 해제</button><button type="button" class="mp-mobile-toggle" data-map-action="mobile-view" aria-controls="mp-mobile-people mp-graph-stage">리스트 보기</button></div><div id="mp-mobile-people" class="mp-mobile-people">'+(graph.visible.length?graph.visible.map(p=>personCard(p,s)).join(''):'<p class="mp-empty">현재 조건에 연결된 인물이 없습니다. <button type="button" data-map-action="clear-all">조건 모두 해제</button></p>')+'</div><div id="mp-graph-stage" class="mp-graph-stage'+(graph.visible.length<=2?' compact':'')+'" tabindex="0" role="group" aria-label="분야와 사람의 연결 지도" aria-describedby="mp-graph-help"><svg class="mp-spatial-edges" aria-hidden="true" focusable="false">'+edges+'</svg><div class="mp-spatial-nodes">'+nodes+'</div>'+(!graph.visible.length?'<p class="mp-empty">현재 조건에 연결된 인물이 없습니다. <button type="button" data-map-action="clear-all">조건 모두 해제</button></p>':'')+'</div><div class="mp-graph-controls"><button type="button" data-map-camera="out" aria-label="지도 축소">−</button><output id="mp-zoom-level" aria-label="확대 비율">100%</output><button type="button" data-map-camera="in" aria-label="지도 확대">+</button><button type="button" data-map-camera="fit">화면 맞춤</button><p id="mp-graph-help" class="mp-graph-help">카드를 끌어 옮기면 주변 카드가 다시 자리를 잡아요 · 빈 곳을 끌면 지도 이동 · 휠·+/− 확대 · Home 화면 맞춤 · 왼쪽 위 그래프 설정(톱니)에서 필터·색·장력 조절</p></div></div>';
 }
 // Graph settings (people-map-live.js): filter, colour groups, display and forces, kept in this browser.
 const LIVE_SLIDERS=[
  {key:'textZoom',label:'이름이 보이는 배율',min:0,max:1,step:.05,section:'look',format:v=>v?Math.round(v*100)+'% 이상':'항상'},
  {key:'nodeSize',label:'카드 크기',min:.5,max:1.6,step:.05,section:'look',format:v=>Math.round(v*100)+'%'},
  {key:'lineWidth',label:'연결선 두께',min:.3,max:3,step:.1,section:'look',format:v=>v.toFixed(1)},
  {key:'center',label:'중심 장력',min:0,max:3,step:.05,section:'force',format:v=>v.toFixed(2)},
  {key:'repel',label:'반발력',min:0,max:8,step:.25,section:'force',format:v=>v.toFixed(2)},
  {key:'link',label:'링크 장력',min:0,max:2,step:.05,section:'force',format:v=>v.toFixed(2)},
  {key:'distance',label:'링크 거리',min:60,max:400,step:10,section:'force',format:v=>String(v)}];
 const LIVE_TOGGLES=[
  {key:'capabilities',label:'역량 알약',section:'filter'},{key:'topics',label:'자료 주제 알약',section:'filter'},
  {key:'projects',label:'프로젝트 알약',section:'filter'},{key:'orphans',label:'연결 없는 카드',section:'filter'},
  {key:'labels',label:'이름 표시',section:'look'},{key:'edges',label:'연결선 표시',section:'look'}];
 const GROUP_COLORS=['#c4683a','#3b7db3','#8b5cb4','#2f8c68','#b38a2b','#c0456f'];
 const PREFS_KEY='rndplz.map.graph.v1';
 function mount(doc,host){
  const win=doc.defaultView,$=id=>host.querySelector('#'+id),Live=win.RndPeopleMapLive;
  if(!Live)throw new TypeError('Load people-map-live.js before mounting the research map.');
  let state=C.initialState(),graph=null,frame=0,mobileMap=true,lastPerson=null;
  const camera={x:0,y:0,scale:1},pointers=new Map();let drag=null,pinch=null,dragged=false;
  const clamp=(v,a,b)=>Math.max(a,Math.min(b,v));
  const observer=win.ResizeObserver?new win.ResizeObserver(()=>schedule()):null;
  // Cards keep their positions across filters, settle by force and can be dragged; the fixed layout only seeds them.
  const live=new Map(),statics=new Map(),infos=new Map(),peopleById=new Map(C.people.map(p=>[p.id,p]));
  let prefs=loadPrefs(),shown=null,lastTest=()=>true,mode='global',localRoot=null,depth=2,groupTests=[],nodeEls=[],edgeEls=[];
  let autoFit=true,fitted=false,lastSize='',loop=0,lastFrame=0,counts='',phase='',flash='',flashTimer=0,selectedBefore=null,lastTap=null;
  const sim=new Live.Simulation(prefs),ui=liveControls();
  const quiet=()=>doc.body.classList.contains('no-motion')||win.matchMedia('(prefers-reduced-motion: reduce)').matches;
  function loadPrefs(){
   const out={...Live.DEFAULTS,groups:[]};
   try{
    const saved=JSON.parse(win.localStorage.getItem(PREFS_KEY)||'null');
    if(saved&&typeof saved==='object'){
     for(const s of LIVE_SLIDERS)if(Number.isFinite(saved[s.key]))out[s.key]=clamp(saved[s.key],s.min,s.max);
     for(const t of LIVE_TOGGLES)if(typeof saved[t.key]==='boolean')out[t.key]=saved[t.key];
     if(typeof saved.filter==='string')out.filter=saved.filter.slice(0,300);
     if(Array.isArray(saved.groups))out.groups=saved.groups.filter(g=>g&&typeof g.query==='string'&&/^#[0-9a-f]{6}$/i.test(g.color)).slice(0,12).map(g=>({query:g.query.slice(0,200),color:g.color}));
    }
   }catch{}
   return out;
  }
  function savePrefs(){try{win.localStorage.setItem(PREFS_KEY,JSON.stringify(prefs));}catch{}}
  function info(n){
   let item=infos.get(n.key);if(item)return item;
   if(n.type==='person'){const p=peopleById.get(n.id);item={kind:'person',label:p.name,org:p.organization||'',text:p.searchKey};}
   else{const source=(n.kind==='topic'?C.topics:C.capabilities).find(x=>x.id===n.id)||{};item={kind:n.kind,label:n.label,org:'',text:source.description||''};}
   infos.set(n.key,item);return item;
  }
  // Which cards and links the settings leave on the map; the model's own search and capability come first.
  function display(){
   const on={person:true,capability:prefs.capabilities,topic:prefs.topics,project:prefs.projects};
   let test=lastTest;
   try{test=Live.compileFilter(prefs.filter);lastTest=test;ui.error('');}catch(error){ui.error(error.message);}
   let keys=new Set(graph.nodes.filter(n=>on[n.kind]&&test(info(n))).map(n=>n.key));
   let links=graph.edges.filter(e=>keys.has(e.from)&&keys.has(e.to));
   let root=mode==='local'&&keys.has(localRoot)?localRoot:null;
   if(mode==='local'&&!root){mode='global';syncBar();}
   if(root){const near=Live.reach(root,depth,links);keys=new Set([...keys].filter(k=>near.has(k)));links=links.filter(e=>keys.has(e.from)&&keys.has(e.to));}
   if(!prefs.orphans){const linked=new Set(links.flatMap(e=>[e.from,e.to]));keys=new Set([...keys].filter(k=>linked.has(k)||k===root));}
   return {keys,links,root};
  }
  function relayout(reseed){
   if(!graph)return;
   shown=display();
   const placed=new Set(),nodes=[];
   for(const n of graph.nodes){
    if(!shown.keys.has(n.key))continue;
    let node=live.get(n.key);
    if(node&&!reseed)placed.add(n.key);else{node={key:n.key,x:NaN,y:NaN,vx:0,vy:0};live.set(n.key,node);}
    const compact=n.type==='person'&&!prefs.labels;
    node.w=(compact?64:n.width)*prefs.nodeSize;node.h=(compact?64:n.height)*prefs.nodeSize;nodes.push(node);
   }
   // A card new to the map starts beside the cards it links to, otherwise at its fixed-layout place.
   nodes.forEach((node,index)=>{
    if(Number.isFinite(node.x))return;
    const near=shown.links.filter(e=>e.from===node.key||e.to===node.key).map(e=>e.from===node.key?e.to:e.from).filter(k=>placed.has(k)).map(k=>live.get(k)),n=statics.get(node.key);
    if(near.length){node.x=near.reduce((s,m)=>s+m.x,0)/near.length+Math.cos(index*2.4)*40;node.y=near.reduce((s,m)=>s+m.y,0)/near.length+Math.sin(index*2.4)*40;}
    else{node.x=n.x;node.y=n.y;}
   });
   const stage=$('mp-graph-stage');sim.aspect=stage&&stage.clientHeight?stage.clientWidth/stage.clientHeight:1.6;
   sim.setGraph(nodes,shown.links);if(quiet())settle();
   for(const [el,key] of nodeEls)el.style.display=shown.keys.has(key)?'':'none';
   for(const [el,from,to] of edgeEls)el.style.display=shown.keys.has(from)&&shown.keys.has(to)?'':'none';
   const kinds={person:0,capability:0,topic:0,project:0};for(const key of shown.keys)kinds[statics.get(key).kind]++;
   counts=['인물 '+kinds.person,'역량 '+kinds.capability,kinds.topic?'주제 '+kinds.topic:'',kinds.project?'프로젝트 '+kinds.project:'','연결 '+shown.links.length].filter(Boolean).join(' · ');
   $('graph-empty-note')?.remove();
   if(stage&&!shown.keys.size&&graph.nodes.length)stage.insertAdjacentHTML('beforeend','<p id="graph-empty-note" class="mp-empty mp-live-empty">그래프 설정의 조건에 맞는 카드가 없어요. 왼쪽 위 그래프 설정에서 필터를 바꿔 보세요.</p>');
   autoFit=true;start();
  }
  function settle(){for(let i=0;i<500&&sim.alpha>.003;i++)sim.tick();}
  function start(){if(!loop)loop=win.requestAnimationFrame(step);}
  function step(now){
   loop=0;if(!shown||!$('mp-graph-stage'))return;
   const still=quiet(),moving=sim.active&&(!still||Boolean(drag?.pinned));
   if(moving&&!doc.hidden){const ticks=clamp(Math.round((now-lastFrame)/16.7),1,3);for(let i=0;i<ticks;i++)sim.tick();}
   lastFrame=now;
   let easing=false;
   if(autoFit){const to=fitTarget();if(to){const k=still||!fitted?1:.14;for(const p of ['x','y','scale'])camera[p]+=(to[p]-camera[p])*k;fitted=true;easing=Math.abs(to.scale-camera.scale)>.001||Math.hypot(to.x-camera.x,to.y-camera.y)>.5;}}
   cameraApply();
   phase=drag?.pinned?'카드 이동 중':moving?'균형을 찾는 중':'배치 안정';status();
   if(moving||easing)start();
  }
  function status(){
   const root=shown?.root&&statics.get(shown.root),text=flash||[root?root.label+' 주변 '+depth+'단계':'',counts,phase].filter(Boolean).join(' · ');
   if(ui.status.textContent!==text)ui.status.textContent=text;
  }
  function note(message){flash=message;status();win.clearTimeout(flashTimer);flashTimer=win.setTimeout(()=>{flash='';status();},2800);}
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
   const stage=$('mp-graph-stage');if(!stage||!shown)return;
   const size=prefs.nodeSize;
   for(const [el,key] of nodeEls){
    const n=live.get(key);if(!n||!shown.keys.has(key))continue;
    el.style.width=n.w/size+'px';el.style.height=n.h/size+'px';
    el.style.transform='translate('+(camera.x+n.x*camera.scale)+'px,'+(camera.y+n.y*camera.scale)+'px) translate(-50%,-50%) scale('+camera.scale*size+')';
   }
   for(const [el,from,to] of edgeEls){
    const a=live.get(from),b=live.get(to);if(!a||!b||!shown.keys.has(from)||!shown.keys.has(to))continue;
    el.setAttribute('d','M'+(camera.x+a.x*camera.scale)+','+(camera.y+a.y*camera.scale)+' L'+(camera.x+b.x*camera.scale)+','+(camera.y+b.y*camera.scale));
   }
   stage.classList.toggle('mp-names-faded',Boolean(prefs.textZoom)&&camera.scale<prefs.textZoom);
   $('mp-zoom-level').textContent=Math.round(camera.scale*100)+'%';
  }
  // The camera that shows every card on the map, below the graph tools at the top of the stage.
  function fitTarget(){
   const stage=$('mp-graph-stage');if(!stage||!stage.clientWidth||!stage.clientHeight||!shown)return null;
   const nodes=[...shown.keys].map(key=>live.get(key)),area=stage.getBoundingClientRect(),top=56;
   // Leave out what the open settings panel (left) and a person card docked beside the map (right) cover.
   const card=doc.querySelector('#detailDialog.docked[open]:not(.sheet)')?.getBoundingClientRect(),panel=ui.isOpen()&&stage.clientWidth>560?ui.panel.getBoundingClientRect():null;
   const inLeft=panel?clamp(panel.right-area.left+8,0,stage.clientWidth/2):0,inRight=card&&card.left>area.left+200?clamp(area.right-card.left+8,0,stage.clientWidth/2):0;
   const width=stage.clientWidth-inLeft-inRight,height=stage.clientHeight;
   if(!nodes.length)return {x:inLeft+width/2,y:height/2,scale:1};
   const left=Math.min(...nodes.map(n=>n.x-n.w/2)),right=Math.max(...nodes.map(n=>n.x+n.w/2)),upper=Math.min(...nodes.map(n=>n.y-n.h/2)),lower=Math.max(...nodes.map(n=>n.y+n.h/2));
   const scale=clamp(Math.min((width-44)/Math.max(right-left,180),(height-top-22)/Math.max(lower-upper,140)),.15,1.1);
   return {scale,x:inLeft+width/2-(left+right)/2*scale,y:top+(height-top-22)/2-(upper+lower)/2*scale};
  }
  function fit(){if(state.view==='organization'){legacyLines();return;}autoFit=true;start();}
  function schedule(){if(!frame)frame=win.requestAnimationFrame(()=>{
   frame=0;if(state.view==='organization'){legacyLines();return;}
   const stage=$('mp-graph-stage'),size=stage?stage.clientWidth+'x'+stage.clientHeight:'';
   if(size!==lastSize){lastSize=size;if(autoFit)fitted=false;}
   start();
  });}
  function zoom(factor,at){
   const stage=$('mp-graph-stage');if(!stage)return;
   const p=at||{x:stage.clientWidth/2,y:stage.clientHeight/2},old=camera.scale;autoFit=false;
   camera.scale=clamp(old*factor,.15,3);camera.x=p.x-(p.x-camera.x)*camera.scale/old;camera.y=p.y-(p.y-camera.y)*camera.scale/old;cameraApply();
  }
  const world=(e,stage)=>{const r=stage.getBoundingClientRect();return {x:(e.clientX-r.left-camera.x)/camera.scale,y:(e.clientY-r.top-camera.y)/camera.scale};};
  function emphasis(hover){
   const key=hover||(state.selectedId?'person:'+state.selectedId:null),related=new Set(key?[key]:[]);
   for(const edge of shown?.links||[])if(edge.from===key||edge.to===key){related.add(edge.from);related.add(edge.to);}
   for(const el of host.querySelectorAll('[data-map-node]'))el.classList.toggle('related',related.has(el.dataset.mapNode));
   for(const el of host.querySelectorAll('[data-person]'))el.setAttribute('aria-pressed',String(el.dataset.person===state.selectedId));
   for(const el of host.querySelectorAll('.mp-spatial-edge'))el.classList.toggle('active',!!key&&(el.dataset.from===key||el.dataset.to===key));
  }
  function detail(){
   const selected=selectedPerson(state),container=$('person-detail');
   container.innerHTML=renderDetail(state);container.hidden=!selected;
   const label=$('mp-selection-label');if(label)label.textContent=selected?title(selected)+' 선택':'인물을 선택하면 연결 근거가 열립니다.';
   for(const button of host.querySelectorAll('[data-map-action="show-detail"],[data-map-action="clear-selection"]'))button.hidden=!selected;
   if(state.selectedId&&state.selectedId!==selectedBefore){
    // The person card docks over the right of the window, where the settings would sit.
    ui.open(false);
    if(mode==='local'&&graph&&localRoot!=='person:'+state.selectedId){localRoot='person:'+state.selectedId;relayout(false);}
   }
   selectedBefore=state.selectedId;
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
   statics.clear();if(graph)graph.nodes.forEach(n=>statics.set(n.key,n));
   $('capability-controls').innerHTML=renderCapabilities(state);$('people-map').innerHTML=renderMap(state);
   const stage=$('mp-graph-stage');
   nodeEls=stage?[...stage.querySelectorAll('[data-map-node]')].map(el=>[el,el.dataset.mapNode]):[];
   edgeEls=stage?[...stage.querySelectorAll('.mp-spatial-edge')].map(el=>[el,el.dataset.from,el.dataset.to]):[];
   if(stage){stage.append(ui.bar,ui.panel);host.querySelector('.mp-graph-controls')?.append(ui.status);look();colorize();relayout(false);}
   $('people-map-content').dataset.mpCount=String(people.length);
   $('map-title').textContent=capability?.label||'연구 경험의 연결';
   $('map-explanation').textContent=(capability?.description||'이름·기술·이력으로 검색하거나 역량을 골라 연결 근거를 살펴보세요.')+(state.view==='organization'?' 자료에 기재된 소속이며 현재 재직이나 협업 관계를 뜻하지 않습니다.':'');
   const peopleCount=capability?.kind==='project'&&(state.query||state.topic)?people.length+'/'+capability.people.length:people.length;
   $('map-count').textContent=peopleCount+'명 · 연결 기록 '+ids.size+'개';
   $('results-summary').textContent=peopleCount+'명'+(capability?' · '+capability.label:'')+(state.query?' · 검색 “'+state.query+'”':'')+(state.topic?' · '+topicName(state.topic):'');
   $('view-control').value=state.view;$('topic-controls').value=state.topic;if($('name-search').value!==state.query)$('name-search').value=state.query;
   detail();mobile();pointers.clear();drag=null;pinch=null;
   observer?.disconnect();if(stage)observer?.observe(stage);schedule();
  }
  // Display switches that change only how the cards look.
  function look(){
   const stage=$('mp-graph-stage');if(!stage)return;
   stage.classList.toggle('mp-names-off',!prefs.labels);stage.classList.toggle('mp-edges-off',!prefs.edges);
   stage.style.setProperty('--mp-edge-scale',String(prefs.lineWidth));
  }
  function compileGroups(){groupTests=prefs.groups.flatMap(g=>{try{return g.query.trim()?[{color:g.color,test:Live.compileFilter(g.query)}]:[];}catch{return [];}});}
  function colorize(){
   const color=key=>{const n=statics.get(key);if(!n)return null;const item=info(n),group=groupTests.find(g=>g.test(item));return group?group.color:null;};
   for(const [el,key] of nodeEls){
    const value=color(key);
    if(el.classList.contains('mp-spatial-person')){el.classList.toggle('mp-grouped',Boolean(value));if(value)el.style.setProperty('--group-color',value);else el.style.removeProperty('--group-color');}
    else el.style.setProperty('--field-color',value||fieldColor(key));
   }
   for(const [el,from] of edgeEls)el.style.setProperty('--field-color',color(from)||fieldColor(from));
  }
  function setMode(next,root){
   if(next==='local'){
    root=root||(state.selectedId?'person:'+state.selectedId:localRoot);
    if(!root||!shown?.keys.has(root)){note('주변 그래프는 맵에서 인물을 먼저 고른 뒤 볼 수 있어요.');return;}
    localRoot=root;
   }
   mode=next;syncBar();relayout(false);
  }
  function syncBar(){
   for(const button of ui.bar.querySelectorAll('[data-live-mode]'))button.setAttribute('aria-pressed',String(button.dataset.liveMode===mode));
   ui.bar.querySelector('.mp-live-depth').hidden=mode!=='local';
  }
  function liveControls(){
   const bar=doc.createElement('div'),panel=doc.createElement('section'),status=doc.createElement('p');
   bar.className='mp-live-bar';status.className='mp-live-status';
   bar.innerHTML='<div class="mp-live-modes" role="group" aria-label="그래프 범위"><button type="button" data-live-mode="global" aria-pressed="true">전체 그래프</button><button type="button" data-live-mode="local" aria-pressed="false" title="선택한 인물과 이어진 카드만 · 인물을 빠르게 두 번 눌러도 돼요">주변 그래프</button></div><label class="mp-live-depth" hidden>깊이 <select data-live-depth aria-label="주변 그래프 연결 깊이"><option value="1">1단계</option><option value="2" selected>2단계</option><option value="3">3단계</option></select></label><button type="button" class="mp-live-gear" data-live-toggle aria-expanded="false" aria-controls="mp-live-panel" aria-label="그래프 설정" title="그래프 설정"><svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg></button>';
   const toggle=t=>'<label class="mp-live-toggle"><span>'+esc(t.label)+'</span><input type="checkbox" role="switch" data-live-pref="'+t.key+'"></label>';
   const slider=s=>'<div class="mp-live-slider"><label for="mp-live-'+s.key+'">'+esc(s.label)+'</label><output for="mp-live-'+s.key+'" data-live-out="'+s.key+'"></output><input id="mp-live-'+s.key+'" type="range" min="'+s.min+'" max="'+s.max+'" step="'+s.step+'" data-live-pref="'+s.key+'"></div>';
   const part=section=>LIVE_TOGGLES.filter(t=>t.section===section).map(toggle).join('')+LIVE_SLIDERS.filter(s=>s.section===section).map(slider).join('');
   panel.id='mp-live-panel';panel.className='mp-live-panel';panel.hidden=true;panel.setAttribute('aria-label','그래프 설정');
   panel.innerHTML='<div class="mp-live-head"><strong>그래프 설정</strong><button type="button" data-live-reset aria-label="그래프 설정을 기본값으로" title="기본값으로">↺</button><button type="button" data-live-close aria-label="그래프 설정 닫기">×</button></div>'+
    '<details open><summary>필터</summary><input type="text" data-live-pref="filter" maxlength="300" placeholder="예: type:사람 촉매 -org:대학" aria-label="그래프 필터" spellcheck="false" autocomplete="off"><p class="mp-live-error" role="alert" hidden></p><details class="mp-live-syntax"><summary>검색 문법</summary><p>낱말 · "띄어 쓴 말" · AND · OR · -제외 · 괄호<br>type:사람 · 역량 · 주제 · 프로젝트<br>name:이름 · org:소속 (종류: · 이름: · 소속:도 돼요)</p></details>'+part('filter')+'</details>'+
    '<details open><summary>그룹</summary><div data-live-groups></div><button type="button" class="mp-live-wide" data-live-add-group>+ 새 그룹</button><p class="mp-live-note">조건에 맞는 카드와 알약에 색을 입혀요. 여러 그룹에 맞으면 위쪽 색을 씁니다.</p></details>'+
    '<details open><summary>표시</summary>'+part('look')+'</details>'+
    '<details open><summary>장력</summary>'+part('force')+'<button type="button" class="mp-live-wide" data-live-reheat>다시 정렬</button></details>'+
    '<p class="mp-live-note">설정은 이 브라우저에만 저장돼요. 카드의 위치와 거리는 숙련도나 순위를 뜻하지 않습니다.</p>';
   const filterInput=panel.querySelector('[data-live-pref="filter"]'),errorLine=panel.querySelector('.mp-live-error'),gear=bar.querySelector('.mp-live-gear');
   function output(s){panel.querySelector('[data-live-out="'+s.key+'"]').textContent=s.format(prefs[s.key]);}
   function groups(){
    panel.querySelector('[data-live-groups]').innerHTML=prefs.groups.map((g,i)=>'<div class="mp-live-group"><input type="text" value="'+esc(g.query)+'" data-live-group="'+i+'" maxlength="200" placeholder="예: org:GS칼텍스" aria-label="그룹 '+(i+1)+' 조건" spellcheck="false" autocomplete="off"><input type="color" value="'+esc(g.color)+'" data-live-group-color="'+i+'" aria-label="그룹 '+(i+1)+' 색"><button type="button" data-live-group-remove="'+i+'" aria-label="그룹 '+(i+1)+' 지우기">×</button></div>').join('');
   }
   function sync(){
    filterInput.value=prefs.filter;
    for(const t of LIVE_TOGGLES)panel.querySelector('[data-live-pref="'+t.key+'"]').checked=prefs[t.key];
    for(const s of LIVE_SLIDERS){panel.querySelector('[data-live-pref="'+s.key+'"]').value=String(prefs[s.key]);output(s);}
    groups();compileGroups();
   }
   function open(show){const was=!panel.hidden;panel.hidden=!show;gear.setAttribute('aria-expanded',String(show));if(was!==show&&autoFit)start();}
   function groupsChanged(){compileGroups();colorize();savePrefs();}
   panel.addEventListener('input',e=>{
    const t=e.target,key=t.dataset.livePref,s=LIVE_SLIDERS.find(x=>x.key===key);
    if(key==='filter'){prefs.filter=t.value;relayout(false);if(errorLine.hidden)savePrefs();}
    else if(s){
     prefs[key]=Number(t.value);output(s);savePrefs();
     if(s.section==='force'){sim.configure(prefs);if(quiet())settle();autoFit=true;start();}
     else if(key==='nodeSize')relayout(false);
     else{look();cameraApply();}
    }
    else if(t.dataset.liveGroup!=null){
     const group=prefs.groups[Number(t.dataset.liveGroup)];if(!group)return;group.query=t.value;
     try{Live.compileFilter(t.value);t.removeAttribute('aria-invalid');}catch{t.setAttribute('aria-invalid','true');}
     groupsChanged();
    }
    else if(t.dataset.liveGroupColor!=null){const group=prefs.groups[Number(t.dataset.liveGroupColor)];if(group){group.color=t.value;groupsChanged();}}
   });
   panel.addEventListener('change',e=>{
    const key=e.target.dataset.livePref,t=LIVE_TOGGLES.find(x=>x.key===key);if(!t)return;
    prefs[key]=e.target.checked;savePrefs();look();
    if(t.section==='filter'||key==='labels')relayout(false);else cameraApply();
   });
   function click(e){
    const b=e.target.closest('button');if(!b)return;
    if(b.dataset.liveMode)setMode(b.dataset.liveMode);
    else if(b.hasAttribute('data-live-toggle'))open(panel.hidden);
    else if(b.hasAttribute('data-live-close')){open(false);gear.focus({preventScroll:true});}
    else if(b.hasAttribute('data-live-reset')){prefs={...Live.DEFAULTS,groups:[]};savePrefs();sync();sim.configure(prefs);look();colorize();relayout(false);note('그래프 설정을 기본값으로 되돌렸어요.');}
    else if(b.hasAttribute('data-live-reheat'))relayout(true);
    else if(b.hasAttribute('data-live-add-group')){
     if(prefs.groups.length>=12)return;
     prefs.groups.push({query:'',color:GROUP_COLORS[prefs.groups.length%GROUP_COLORS.length]});groups();groupsChanged();
     panel.querySelector('[data-live-groups]').lastElementChild?.querySelector('input')?.focus({preventScroll:true});
    }
    else if(b.dataset.liveGroupRemove!=null){prefs.groups.splice(Number(b.dataset.liveGroupRemove),1);groups();groupsChanged();}
   }
   bar.addEventListener('click',click);panel.addEventListener('click',click);
   bar.addEventListener('change',e=>{if(e.target.matches('[data-live-depth]')){depth=Number(e.target.value);relayout(false);}});
   sync();
   return {bar,panel,status,open,isOpen:()=>!panel.hidden,focusGear:()=>gear.focus({preventScroll:true}),
    error(message){errorLine.hidden=!message;errorLine.textContent=message;if(message)filterInput.setAttribute('aria-invalid','true');else filterInput.removeAttribute('aria-invalid');}};
  }
  function letGo(){if(drag?.pinned)sim.release(drag.node);drag=null;}
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
   const button=event.target.closest('button');if(!button||!host.contains(button)||button.closest('.mp-live-bar,.mp-live-panel'))return;
   if(dragged&&button.closest('#mp-graph-stage')){event.preventDefault();event.stopPropagation();return;}
   if(button.dataset.mapCamera){if(button.dataset.mapCamera==='fit')fit();else zoom(button.dataset.mapCamera==='in'?1.2:1/1.2);return;}
   if(button.dataset.mapFilter){const type=button.dataset.mapFilter,value=button.dataset.mapFilterValue,field=type==='TOPIC'?'topic':'capability';dispatch({type,value:state[field]===value?'':value});const target=[...host.querySelectorAll('[data-map-filter]')].find(b=>b.dataset.mapFilter===type&&b.dataset.mapFilterValue===value);(target||$('mp-graph-stage'))?.focus({preventScroll:true});}
   else if(button.hasAttribute('data-capability')){const id=button.dataset.capability;dispatch({type:'CAPABILITY',value:state.capability===id?'':id});[...host.querySelectorAll('[data-capability]')].find(b=>b.dataset.capability===id)?.focus({preventScroll:true});}
   else if(button.dataset.person){if(dragged){event.preventDefault();event.stopPropagation();return;}lastPerson=button.dataset.person;dispatch({type:'SELECT',id:lastPerson});}
   else if(button.hasAttribute('data-page')){dispatch({type:'PAGE',value:Number(button.dataset.page)});$('map-title').scrollIntoView({block:'start',behavior:'auto'});}
   else if(button.id==='clear-filters'||button.dataset.mapAction==='clear-all'){dispatch({type:'CLEAR_FILTERS'});$('name-search').focus({preventScroll:true});}
   else if(['close','clear-selection'].includes(button.dataset.mapAction))clearSelection(true);
   else if(button.dataset.mapAction==='show-detail'){$('detail-title')?.focus({preventScroll:true});$('person-detail').scrollIntoView({block:'start',behavior:'auto'});}
   else if(button.dataset.mapAction==='mobile-view'){mobileMap=!mobileMap;mobile();fit();}
   else if(button.dataset.mapAction==='ack-draft'){dispatch({type:'ACK_DRAFT_CONTEXT'});$('draft')?.focus({preventScroll:true});}
   else if(button.dataset.mapAction==='reset-draft'){dispatch({type:'RESET_DRAFT'});$('draft')?.focus({preventScroll:true});}
  });
  host.addEventListener('dragstart',e=>{if(e.target.closest?.('#mp-graph-stage'))e.preventDefault();});
  host.addEventListener('pointerover',e=>{const node=e.target.closest('[data-map-node]');if(node)emphasis(node.dataset.mapNode);});
  host.addEventListener('pointerout',e=>{const node=e.target.closest('[data-map-node]');if(node&&!node.contains(e.relatedTarget))emphasis();});
  host.addEventListener('focusin',e=>{const node=e.target.closest('[data-map-node]');if(node)emphasis(node.dataset.mapNode);});
  host.addEventListener('focusout',e=>{if(e.target.closest('[data-map-node]'))emphasis();});
  host.addEventListener('keydown',e=>{
   if(e.key==='Escape'&&ui.isOpen()&&e.target.closest?.('.mp-live-panel,.mp-live-bar')){e.preventDefault();e.stopPropagation();ui.open(false);ui.focusGear();return;}
   if(e.target.matches('input,textarea,select'))return;
   if(e.key==='Escape'&&state.selectedId){e.preventDefault();clearSelection(true);return;}
   if(e.target.id!=='mp-graph-stage')return;
   const moves={ArrowLeft:[45,0],ArrowRight:[-45,0],ArrowUp:[0,45],ArrowDown:[0,-45]};
   if(moves[e.key]){e.preventDefault();autoFit=false;camera.x+=moves[e.key][0];camera.y+=moves[e.key][1];cameraApply();}
   else if(['+','=','-','Home'].includes(e.key)){e.preventDefault();if(e.key==='Home')fit();else zoom(e.key==='-'?1/1.2:1.2);}
  });
  host.addEventListener('wheel',e=>{const stage=e.target.closest('#mp-graph-stage');if(!stage||e.target.closest('.mp-live-panel,.mp-live-bar'))return;e.preventDefault();const r=stage.getBoundingClientRect();zoom(e.deltaY<0?1.08:1/1.08,{x:e.clientX-r.left,y:e.clientY-r.top});},{passive:false});
  // A press on a card drags that card (the rest of the map gives way); a press on empty paper pans.
  host.addEventListener('pointerdown',e=>{
   const stage=e.target.closest('#mp-graph-stage');if(!stage||e.button>0||e.target.closest('.mp-live-panel,.mp-live-bar'))return;
   pointers.set(e.pointerId,{x:e.clientX,y:e.clientY});dragged=false;
   if(pointers.size===2){const[a,b]=[...pointers.values()];pinch=Math.hypot(a.x-b.x,a.y-b.y);letGo();stage.setPointerCapture(e.pointerId);}
   else{
    const onNode=Boolean(e.target.closest('button')),key=e.target.closest('[data-map-node]')?.dataset.mapNode,node=key&&live.get(key),at=world(e,stage);
    drag={id:e.pointerId,x:e.clientX,y:e.clientY,startX:e.clientX,startY:e.clientY,captured:!onNode,node:node?key:null,dx:node?node.x-at.x:0,dy:node?node.y-at.y:0,pinned:false};
    if(!onNode)stage.setPointerCapture(e.pointerId);
   }
  });
  host.addEventListener('pointermove',e=>{
   if(!pointers.has(e.pointerId))return;const stage=$('mp-graph-stage');if(!stage)return;
   pointers.set(e.pointerId,{x:e.clientX,y:e.clientY});
   if(pointers.size===2){const[a,b]=[...pointers.values()],distance=Math.hypot(a.x-b.x,a.y-b.y),r=stage.getBoundingClientRect();if(pinch>0)zoom(distance/pinch,{x:(a.x+b.x)/2-r.left,y:(a.y+b.y)/2-r.top});pinch=distance;dragged=true;}
   else if(drag?.id===e.pointerId){
    if(Math.hypot(e.clientX-drag.startX,e.clientY-drag.startY)>4)dragged=true;
    if(dragged&&!drag.captured){drag.captured=true;try{stage.setPointerCapture(e.pointerId);}catch{}}
    if(dragged&&drag.node){const at=world(e,stage);sim.pin(drag.node,at.x+drag.dx,at.y+drag.dy);drag.pinned=true;autoFit=false;stage.classList.add('moving-card');start();}
    else if(dragged){autoFit=false;camera.x+=e.clientX-drag.x;camera.y+=e.clientY-drag.y;cameraApply();stage.classList.add('dragging');}
    drag.x=e.clientX;drag.y=e.clientY;
   }
  });
  function end(e){
   pointers.delete(e.pointerId);
   if(drag?.id===e.pointerId){
    const {pinned,node}=drag;letGo();
    if(pinned){if(quiet())settle();start();}
    // Two quick presses on a person show only the cards around them (Obsidian's local graph). The
    // person button is disabled while its card loads, so the browser's dblclick cannot be relied on.
    else if(!dragged&&node&&node.startsWith('person:')){const now=win.performance.now();if(lastTap&&lastTap.node===node&&now-lastTap.at<450){lastTap=null;setMode('local',node);}else lastTap={node,at:now};}
   }
   pinch=null;$('mp-graph-stage')?.classList.remove('dragging','moving-card');win.setTimeout(()=>{dragged=false;},0);
  }
  host.addEventListener('pointerup',end);host.addEventListener('pointercancel',end);
  win.addEventListener('blur',()=>{pointers.clear();letGo();pinch=null;dragged=false;$('mp-graph-stage')?.classList.remove('dragging','moving-card');start();});
  doc.addEventListener('visibilitychange',()=>{if(!doc.hidden){lastFrame=win.performance.now();start();}});
  win.addEventListener('resize',schedule);render();
  // How a listed person was found: the searched words, and the records behind the chosen capability or topic.
  function found(id){
   const person=C.visiblePeople(state).find(p=>p.id===id);if(!person)return null;
   const capability=currentCapability(state),link=C.capabilityLink(state,person);
   return {terms:C.searchTerms(state.query),team:person.sourcePerson?.team_member===true,
    capability:capability&&link?{label:capability.label,recordIds:[...link.recordIds]}:null,
    topic:state.topic?{label:topicName(state.topic),recordIds:person.records.filter(r=>r.topics.includes(state.topic)).map(r=>r.id)}:null};
  }
  // Pan just enough that a person's node is not under a panel covering the right or bottom of the window.
  function reveal(id,right,bottom){
   const node=[...host.querySelectorAll('[data-map-node]')].find(el=>el.dataset.mapNode==='person:'+id),stage=$('mp-graph-stage');
   if(!node||!stage||!graph)return;
   autoFit=false;
   const r=node.getBoundingClientRect(),area=stage.getBoundingClientRect();
   const covered=Math.max(0,r.bottom-(win.innerHeight-bottom-24)),still=win.matchMedia('(prefers-reduced-motion: reduce)').matches;
   const dx=clamp(r.right-(win.innerWidth-right-24),0,Math.max(0,r.left-area.left-12)),dy=Math.min(covered,Math.max(0,r.top-area.top-12));
   // Under a bottom sheet the map itself is mostly covered: scroll the page for what panning cannot give.
   if(covered>dy)win.scrollBy({top:covered-dy,behavior:still?'auto':'smooth'});
   if(!dx&&!dy)return;
   // A short eased move keeps the user's place on the map; no animation when reduced motion is asked for.
   const from={x:camera.x,y:camera.y},start=win.performance.now();
   const step=now=>{const t=still?1:Math.min(1,(now-start)/220),eased=1-(1-t)*(1-t);camera.x=from.x-dx*eased;camera.y=from.y-dy*eased;cameraApply();if(t<1)win.requestAnimationFrame(step);};
   step(start);
  }
  // Phones: zoom onto a person (at least 70%) and centre them in the map area left above a bottom sheet.
  function focus(id,bottom){
   const stage=$('mp-graph-stage'),n=shown?.keys.has('person:'+id)?live.get('person:'+id):null;if(!stage||!n)return;
   autoFit=false;
   const top=stage.getBoundingClientRect().top;if(Math.abs(top-8)>4)win.scrollBy(0,top-8);
   const area=stage.getBoundingClientRect(),visible=Math.max(area.top+80,Math.min(area.bottom,win.innerHeight-bottom-8));
   const scale=clamp(Math.max(camera.scale,.7),.15,1),to={x:area.width/2-n.x*scale,y:(Math.max(area.top,0)+visible)/2-area.top-n.y*scale,scale};
   const from={...camera},start=win.performance.now(),still=win.matchMedia('(prefers-reduced-motion: reduce)').matches;
   const step=now=>{const t=still?1:Math.min(1,(now-start)/240),e=1-(1-t)*(1-t);for(const k of ['x','y','scale'])camera[k]=from[k]+(to[k]-from[k])*e;cameraApply();if(t<1)win.requestAnimationFrame(step);};
   step(start);
  }
  // The person before/after this one among the people the map currently shows.
  function neighbor(id,step){
   const people=C.visiblePeople(state).filter(p=>!shown||shown.keys.has('person:'+p.id)),index=people.findIndex(p=>p.id===id);
   return people.length&&index>=0?people[(index+step+people.length)%people.length].id:null;
  }
  function select(id){lastPerson=id;dispatch({type:'SELECT',id});}
  return {getState:()=>({...state,evidenceIds:[...state.evidenceIds]}),found,reveal,focus,neighbor,select};
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
  message.textContent="연구 맵을 불러오는 중이에요.";retry.hidden=true;status.hidden=false;content.hidden=true;
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
