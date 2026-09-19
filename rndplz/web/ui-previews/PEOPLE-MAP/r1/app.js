(function (root, factory) {
  const api = factory(typeof module === "object" && module.exports ? require("./model.js") : root.PeopleMapCore);
  if (typeof module === "object" && module.exports) module.exports = api;
  else { root.PeopleMapPreview = api; api.mount(document); }
})(typeof globalThis !== "undefined" ? globalThis : this, function (C) {
  "use strict";
  const esc = value => String(value == null ? "" : value).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  const tone = p => ({"PF-DEMO-01":"","PF-DEMO-02":"blue","PF-DEMO-03":"gold","PF-DEMO-04":"neutral"}[p.id] || "");
  const selectedPerson = s => C.visiblePeople(s).find(p => p.id === s.selectedId) || null;
  const avatar = p => '<span class="avatar '+tone(p)+'" aria-hidden="true">'+esc(p.initial)+'</span>';
  const teamText = p => p.team ? ((p.id === "PF-DEMO-02" ? "현재 " : "") + p.team) : "소속 미기재";
  const hasEvidence = (s,p) => !!(p && p.experience && s.evidenceIds.includes(p.experience.evidence.id));
  const buttonPerson = (p,s) => '<button type="button" class="map-person" data-person="'+esc(p.id)+'" aria-pressed="'+(s.selectedId===p.id)+'" aria-label="'+esc(p.name)+' 역할과 근거 보기"><span class="map-person-head">'+avatar(p)+'<span><strong>'+esc(p.name)+'</strong><span class="person-team">'+esc(teamText(p))+'</span></span></span><span class="experience-title">'+esc(p.experience ? p.experience.title : "등록 프로필 · 연결된 기록 없음")+'</span><span class="period">'+esc(p.experience ? p.experience.period : "명부에 등록된 이름으로 찾을 수 있습니다.")+'</span></button>';
  const line = (label,id) => '<div class="relation" data-relation-person="'+esc(id)+'"><svg viewBox="0 0 180 57" preserveAspectRatio="none" aria-hidden="true"><path d="M90 0V57"/></svg><span>'+esc(label)+'</span></div>';
  function renderRoster(s) {
    const visible=C.visiblePeople(s);
    if(!visible.length) return '<p class="list-empty">현재 조건에 맞는 인물이 없습니다.</p>';
    return visible.map(p=>'<button type="button" class="person-row" data-person="'+esc(p.id)+'" id="row-'+esc(p.id)+'" aria-pressed="'+(s.selectedId===p.id)+'">'+avatar(p)+'<span class="row-copy"><strong>'+esc(p.name)+'</strong><small>'+esc(s.view==="organization" ? teamText(p) : (p.experience ? p.experience.role : "연결된 기록 없음"))+'</small></span><span class="row-arrow" aria-hidden="true">↗</span></button>').join("");
  }
  function renderMap(s) {
    const visible=C.visiblePeople(s);
    if(!visible.length) return '<div class="empty-result"><div class="empty-symbol" aria-hidden="true">∅</div><h3>현재 조건에 맞는 인물이 없습니다.</h3><p>선택한 조건을 바꾸어 다시 찾아보세요.</p>'+(s.topic ? '<button type="button" class="text-button" data-action="clear-topic">업무 조건만 해제 →</button>' : '<button type="button" class="text-button" data-action="clear-all">조건 모두 해제 →</button>')+'</div>';
    if(visible.length===1) {
      const p=visible[0],ex=p.experience;
      const label=s.view==="organization" ? teamText(p) : (ex ? ex.topic : "명부에 등록된 사람");
      return '<div class="single-result"><p class="single-top">'+esc(label)+' · 현재 조건에서 1명</p>'+buttonPerson(p,s)+(ex ? line(ex.role,p.id)+'<div class="single-evidence" data-evidence-person="'+esc(p.id)+'">'+esc(ex.evidence.id)+' '+esc(ex.evidence.version)+'<small>이 역할을 설명하는 '+esc(ex.evidence.kind)+' · 상세에서 읽기</small></div>' : '<p class="map-explanation">기록 유무는 역량에 대한 판단이 아닙니다.</p>')+'</div>';
    }
    return '<div class="map-grid">'+visible.map(p=>{
      const ex=p.experience,org=s.view==="organization";
      const label=org ? (p.team || "소속 미기재") : (ex ? ex.topic : "연결 기록 없음");
      const relationship=org ? (p.id==="PF-DEMO-02" ? "현재 소속 · 2026~" : (p.team ? "사례상 소속 · 기준일 미기재" : "조직 관계 미기재")) : (ex ? ex.role : "명부 등록");
      return '<section class="map-group '+tone(p)+'" aria-label="'+esc(label)+'"><div class="group-label"><span>'+esc(label)+'</span><small>1명</small></div>'+line(relationship,p.id)+buttonPerson(p,s)+'</section>';
    }).join("")+'</div>';
  }
  function renderQuestion(s,p) {
    const checked=hasEvidence(s,p), ex=p.experience;
    let body='<div class="section-label"><span>03 · 대화 준비</span><span>첫 15분</span></div><h3>무엇부터 물어볼까요?</h3>';
    if(!checked) return '<section class="detail-section"><div class="question-form">'+body+'<p class="gated">위의 근거를 읽고 포함할 항목을 직접 선택해 주세요. 선택한 업무를 바탕으로 질문 초안을 수정할 수 있습니다.</p></div></section>';
    body+='<p class="micro">질문 대상: '+esc(p.name)+' · 포함 근거 1개</p><label class="form-label" for="problem">지금 확인하고 싶은 문제</label><textarea id="problem" data-field="problem" maxlength="2000" placeholder="내 상황과 비교할 조건을 적어보세요.">'+esc(s.problem)+'</textarea><label class="form-label" for="draft">질문 초안 · 직접 수정할 수 있어요</label><textarea id="draft" class="draft-area" data-field="draft" maxlength="4000">'+esc(s.draft)+'</textarea>';
    body+='<details class="ai-options"'+(s.includeAi?' open':'')+'><summary>AI 자료도 참고하기 · 선택 사항</summary><p class="ai-explainer">AI 자료 없이도 질문을 준비할 수 있습니다. 원답과 내가 확인할 가정을 구분해서 적어주세요.</p><label class="evidence-check"><input type="checkbox" id="include-ai"'+(s.includeAi?' checked':'')+'>내가 가진 AI 자료를 함께 검토</label>';
    if(s.includeAi) {
      body+='<label class="form-label" for="ai-text">AI 원답 · 내가 가져오는 선택 자료</label><textarea id="ai-text" data-field="aiText" maxlength="6000" placeholder="AI 원답과 출처·버전을 직접 적어주세요.">'+esc(s.aiText)+'</textarea>';
      if(p.ai) body+='<p class="ai-explainer"><strong>이 가상 사례에서 확인할 가정</strong><br>'+esc(p.ai.assumption)+'<br>사례 식별자 '+esc(p.ai.id)+' · 원답 전문은 이 시안에 없습니다. 자동 요약이나 판단을 만들지 않습니다.</p>';
    }
    body+='</details><p class="draft-foot">이 페이지에서만 편집하는 초안입니다. 새로 열면 초기화되며, 상대에게 전달되지 않습니다.</p>';
    return '<section class="detail-section"><div class="question-form">'+body+'</div></section>';
  }
  function renderDetail(s) {
    const p=selectedPerson(s);
    if(!p) return '<div class="detail-empty"><span class="eyebrow small">02 · PERSON & EVIDENCE</span><div class="empty-mark" aria-hidden="true">↗</div><h2>이름 너머의 경험을<br>차근히 살펴보세요.</h2><p>동료를 선택하면 그 사람이 어떤 일을 맡았고, 어떤 기록이 이를 설명하는지 볼 수 있습니다.</p><div class="journey"><ul><li><span>01</span>이름이나 업무 조건으로 찾기</li><li><span>02</span>역할과 그 근거 읽기</li><li><span>03</span>짧은 질문으로 대화 준비하기</li></ul></div></div>';
    let html='<div class="detail-topline"><span class="eyebrow small">02 · PERSON & EVIDENCE</span><button class="close-detail" type="button" data-action="close">목록으로 ↩</button></div><div class="detail-head" data-detail-person="'+esc(p.id)+'"><div class="detail-name">'+avatar(p)+'<h2 id="detail-title" tabindex="-1">'+esc(p.name)+'<span class="fiction-tag">가상 인물</span></h2></div><p class="detail-team">'+esc(teamText(p))+'</p><p class="detail-meta">'+esc(p.teamNote || "소속 기준일 미기재")+'</p><p class="detail-meta">현재 역할: '+esc((p.currentRole || "미기재").replace(/^현재 역할\s*/, ""))+'</p></div>';
    if(!p.experience) return html+'<section class="detail-section zero-record"><div class="section-label">등록 정보</div><h3>등록 프로필 · 연결된 기록 없음</h3><p>이 가상 명부에는 이름만 등록되어 있습니다. 논문·경력·프로젝트·업무와 기타 연결 기록은 없습니다.</p><p>아직 기록되지 않은 경험이나 역량이 없다는 뜻은 아닙니다.</p></section>';
    const ex=p.experience,e=ex.evidence;
    html+='<section class="detail-section"><div class="section-label"><span>맡았던 일</span><span>'+esc(ex.topic)+'</span></div><h3>'+esc(ex.title)+'</h3><p class="role-line">'+esc(ex.role)+'</p><dl class="facts"><dt>참여 기간</dt><dd>'+esc(ex.period)+'</dd><dt>당시 소속</dt><dd>'+esc(ex.thenTeam || "미기재")+'</dd></dl><div class="evidence-card"><p class="doc-meta">'+esc(e.kind)+' · '+esc(e.id)+' '+esc(e.version)+'</p><p>'+esc(e.summary)+'</p><p class="evidence-limits">'+esc(e.limit)+'</p><details><summary>근거의 범위와 출처</summary><p>가상 사례에 명시된 근거 요약입니다. 원문 인용이나 실제 직원의 수행 인증이 아닙니다.</p><p>원문 위치: '+esc(e.location || "미기재")+'<br>자료 작성일: '+esc(e.date || "미기재")+'</p></details></div><label class="evidence-check"><input type="checkbox" id="include-evidence" data-evidence="'+esc(e.id)+'"'+(hasEvidence(s,p)?' checked':'')+'>이 근거를 질문 준비에 포함</label></section>';
    return html+renderQuestion(s,p);
  }
  function mount(doc) {
    let state=C.initialState();
    const $=id=>doc.getElementById(id);
    function render() {
      const v=C.visiblePeople(state);
      $("people-list").innerHTML=renderRoster(state);
      $("people-map").innerHTML=renderMap(state);
      $("person-detail").innerHTML=renderDetail(state);
      $("results-summary").innerHTML='<strong>'+v.length+'</strong>명'+(state.topic ? ' · '+esc(state.topic) : ' · 현재 조건의 가상 명부')+(state.query ? ' · 이름 “'+esc(state.query)+'”' : '');
      $("map-title").textContent=state.view==="organization" ? "소속에서 만나는 동료" : "경험으로 만나는 동료";
      $("map-explanation").textContent=state.view==="organization" ? "사례에 명시된 소속으로 묶었습니다. 기준일이 없는 소속은 현재 여부를 확정하지 않습니다." : "업무 → 기록에 명시된 역할 → 사람. 관계의 이유를 읽고 동료를 선택하세요.";
      doc.querySelectorAll("[data-topic]").forEach(el=>el.setAttribute("aria-pressed",String(el.dataset.topic===state.topic)));
      doc.querySelectorAll("[data-view]").forEach(el=>el.setAttribute("aria-pressed",String(el.dataset.view===state.view)));
      if($("name-search").value!==state.query) $("name-search").value=state.query;
    }
    function dispatch(action) {state=C.reduce(state,action);render();}
    doc.addEventListener("input",event=>{
      const t=event.target;
      if(t.id==="name-search") {dispatch({type:"QUERY",value:t.value});return;}
      const types={problem:"PROBLEM",draft:"DRAFT",aiText:"AI_TEXT"};
      if(t.dataset.field && types[t.dataset.field]) state=C.reduce(state,{type:types[t.dataset.field],value:t.value});
    });
    doc.addEventListener("change",event=>{
      const t=event.target;
      if(t.dataset.evidence) {dispatch({type:"EVIDENCE",id:t.dataset.evidence,checked:t.checked});$("include-evidence")?.focus();}
      if(t.id==="include-ai") {dispatch({type:"INCLUDE_AI",value:t.checked});$("include-ai")?.focus();}
    });
    doc.addEventListener("click",event=>{
      const b=event.target.closest("button");
      if(!b) return;
      if(b.dataset.person) {
        dispatch({type:"SELECT",id:b.dataset.person});
        $("detail-title")?.focus({preventScroll:true});
        if(typeof matchMedia==="function" && matchMedia("(max-width:1180px)").matches) $("person-detail").scrollIntoView({block:"start",behavior:"auto"});
      } else if(b.hasAttribute("data-topic")) dispatch({type:"TOPIC",value:b.dataset.topic});
      else if(b.dataset.view) dispatch({type:"VIEW",value:b.dataset.view});
      else if(b.id==="clear-filters" || b.dataset.action==="clear-all") {dispatch({type:"CLEAR_FILTERS"});$("name-search").focus();}
      else if(b.dataset.action==="clear-topic") {dispatch({type:"CLEAR_TOPIC"});$("name-search").focus();}
      else if(b.dataset.action==="close") {const previous=state.selectedId;dispatch({type:"CLOSE_DETAIL"});$("row-"+previous)?.focus({preventScroll:false});}
    });
    render();
    return {getState:()=>({...state,evidenceIds:[...state.evidenceIds]})};
  }
  return {renderRoster,renderMap,renderDetail,selectedPerson,mount,esc};
});
