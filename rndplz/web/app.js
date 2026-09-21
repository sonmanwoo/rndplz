"use strict";
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const nfmt = n => Number(n||0).toLocaleString("ko-KR");
const stateNames={draft:"초안",sent:"보냄 · 시연",accepted:"수락 · 시연",declined:"거절 · 시연",closed:"종료 · 시연",cancelled:"취소"};
const modes={advice:"자문",verify:"AI 답 검증",member:"프로젝트 멤버",site_request:"현장 의뢰",resource_request:"자원 요청"};
const labels=["AI 답 검증","PCB·고무 씰","열전달·유동","전기 절연","AI 분자 탐색","전기차에서 힌트","낯선 분야","CPN·N₂O","결정화 속도","현장 거품","촉매 5kg"];
let boot, session=null, token="", admin=null, letter=null, toastTimer, busy=false, exported=null;
let view="chat", received=null, detailReturn=null, detailTrigger=null, detailPersonId=null;
const slots=()=>Object.fromEntries(["goal","target","conditions","resources","deadline"].map(k=>[k,$(k).value]));
async function api(path,body){
 const res=await fetch(path,body===undefined?{}:{method:"POST",headers:{"Content-Type":"application/json","X-RnDplz-Token":token},body:JSON.stringify(body)});
 let data;try{data=await res.json();}catch{throw new Error("서버 응답을 읽지 못했습니다. 입력을 유지하고 다시 시도해 주세요.");}
 if(!res.ok)throw new Error(data.error||"요청을 완료하지 못했습니다.");
 return data;
}
function toast(message,error=false){
 clearTimeout(toastTimer);$("toast").hidden=false;$("toast").className="toast"+(error?" error":"");$("toast").textContent=message;
 toastTimer=setTimeout(()=>$("toast").hidden=true,error?9000:5500);
}
async function task(fn,button){
 if(busy)return;busy=true;if(button){button.disabled=true;button.setAttribute("aria-busy","true");}
 try{await fn();}catch(e){toast(e.message,true);if($("letterDialog").open)$("letterError").textContent=e.message;}
 finally{busy=false;if(button){button.disabled=false;button.removeAttribute("aria-busy");}}
}
function showDialog(id){
 const prior=document.querySelector("dialog[open]");
 if(id==="detailDialog"){if(prior?.id!=="detailDialog")detailReturn=prior?.id||null;}
 else if(prior?.id==="detailDialog"){detailReturn=null;detailTrigger=null;detailPersonId=null;}
 for(const d of document.querySelectorAll("dialog[open]"))d.close();
 $(id).showModal();
}
function rememberDetailTrigger(trigger,personId=null){
 if(!$("detailDialog").open){detailTrigger=trigger;detailPersonId=personId||(trigger?.dataset.action==="person"?trigger.dataset.id:null);}
}
function detailFocusAvailable(element){
 return Boolean(element?.isConnected&&!element.disabled&&!element.closest('[hidden], [inert]')&&element.getClientRects().length);
}
function closeDetail(){
 const back=detailReturn, trigger=detailTrigger, personId=detailPersonId;
 detailReturn=null;detailTrigger=null;detailPersonId=null;
 $("detailDialog").close();
 if(back)showDialog(back);
 const replacement=personId?Array.from(document.querySelectorAll('[data-action="person"]')).find(b=>b.dataset.id===personId&&detailFocusAvailable(b)):null;
 const target=detailFocusAvailable(trigger)?trigger:replacement||[ $("people-list"),$("name-search") ].find(detailFocusAvailable);
 target?.focus();
}
function renderExamples(){
 const groups=[["연구",boot.questions.filter(q=>!["Q00","Q09","Q10"].includes(q.id))],["검증",boot.questions.filter(q=>q.id==="Q00")],["현장·자원",boot.questions.filter(q=>["Q09","Q10"].includes(q.id))]];
 $("exampleGroups").innerHTML=groups.map(([name,qs])=>'<div class="example-row"><span class="example-category">'+name+'</span><div class="chips">'+qs.map(q=>'<button class="chip" data-action="example" data-id="'+q.id+'" title="'+esc(q.question)+'">'+labels[Number(q.id.slice(1))]+'</button>').join("")+'</div></div>').join("");
}
function displaySlots(s){
 const fields=s?.slots||{},spec=s?.request_spec;
 return Object.fromEntries(["goal","target","conditions","resources","deadline"].map(k=>[k,typeof fields[k]==="string"?fields[k]:k==="goal"?spec?.summary||"":k==="conditions"?(spec?.conditions||[]).map(c=>(c.kind==="required"?"필수 · ":"선호 · ")+c.text).join("\n"):""]));
}
function displayResult(s){
 if(!s?.ready||!s.result)return null;
 if(s.scout&&(!s.scout.disclosed||s.pending||!s.scout.revision||s.scout.revision!==s.discovery?.revision||s.scout.revision!==s.prepared_discovery_revision))return null;
 const r=s.result,array=value=>Array.isArray(value)?value:[],candidates=array(r.candidates).map(c=>({...c,evidence:array(c.evidence),relevant_records:Number.isFinite(c.relevant_records)?c.relevant_records:array(c.evidence).length}));
 // Only already-disclosed display data is used. Omitted author/raw retrieval
 // fields stay empty; a visible-record count is not the full search count.
 return {...r,candidates,mode_label:r.mode_label||modes[r.mode]||"등록 기록",
  record_count:Number.isFinite(r.record_count)?r.record_count:new Set(candidates.flatMap(c=>array(c.evidence).map(e=>e.id).filter(Boolean))).size,
  claims:array(r.claims),closest_topics:array(r.closest_topics),author_strip:array(r.author_strip),author_strip_record:r.author_strip_record||{}};
}
function renderSession(){
 $("messages").innerHTML=session?(session.messages||[]).map(m=>'<div class="message '+m.role+'"><small>'+(m.role==="user"?"내가 풀고 싶은 일":"수소문")+'</small>'+esc(m.text)+'</div>').join(""):"";
 $("messages").scrollTop=$("messages").scrollHeight;
 $("applySlots").disabled=!session||session.kind==="chat";$("followupActions").hidden=!session?.followup;
 $("askButton").innerHTML=(session?.followup?"조건 전달하기":session?.ready?"새 질문으로 찾기":"사람 찾기")+' <span>↗</span>';
 $("questionHint").textContent=session?.followup?"아는 조건만 한 가지 더 알려주세요.":session?.ready?"여기에 쓰면 새 질문을 시작해요. 지금 질문의 조건은 메모에서 수정해 주세요.":"막힌 현상, 목표, 조건 중 아는 것부터.";
 $("question").placeholder=session?.followup?"예: FKM 씰부터, 60°C 조건으로 검토하고 싶어요.":"예: 액침 냉각유에 오래 잠긴 PCB와 고무 씰의 신뢰성을 검토하려고 해요.";
 const fields=displaySlots(session);$("mode").disabled=session?.kind==="chat";
 if(session)$("mode").value=session.mode||"";
 for(const k of ["goal","target","conditions","resources","deadline"]){$(k).value=fields[k];$(k).readOnly=session?.kind==="chat";}
 renderResults();
}

const canPropose=c=>Boolean(c)&&c.proposal_allowed!==false&&!c.lookup_only;
function checkProposalSelection(ids){
 if(!Array.isArray(ids)||!ids.length)throw new Error("현재 근거로 제안할 인물을 선택해 주세요.");
 for(const id of ids){const c=displayResult(session)?.candidates.find(x=>x.id===id);if(!canPropose(c))throw new Error(c?.proposal_unavailable_reason||"현재 시연 범위의 인물과 근거로 다시 찾아 주세요.");}
}
function extraRecordSources(e){
 return (Array.isArray(e.metadata_sources)?e.metadata_sources:[]).filter(x=>safeUrl(x.url)).map(x=>'<p><a href="'+esc(x.url)+'" target="_blank" rel="noopener noreferrer">'+esc(x.title||x.label||(/correction/i.test(x.basis||x.type||'')?'정정 출처':'추가 확인 출처'))+' ↗</a></p>').join('');
}

function renderResults(){
 if(!session){$("results").innerHTML="";return;}
 const r=displayResult(session);
 if(!r){$("results").innerHTML=session.kind==="chat"?'<div class="pending-note">대화에서 조건을 확인하고 수소문을 누르면 결과를 볼 수 있어요. <a href="/?chat='+encodeURIComponent(session.id)+'">대화로 돌아가기</a></div>':'<div class="pending-note">조건을 한 번 더 확인하고 있어요. 답을 적거나, 위의 ‘추가 조건 없이 후보 보기’를 눌러주세요.</div>';return;}
 let html='<div class="results-heading"><div><div class="section-label">03 / 이 경험에서 시작해볼까요?</div><h2>'+(r.candidates.length?'연결해볼 사람 '+r.candidates.length+'명':'아직, 근거가 부족해요.')+'</h2><p>참여 기록은 연결의 출발점입니다. 개인의 수행 역할과 현재 연락 의향은 확인이 필요해요.</p></div><span class="results-label">'+esc(r.mode_label)+' · 관련 기록 '+r.record_count+'건</span></div>';
 if(r.scope_note)html+='<p class="scope-note">'+esc(r.scope_note)+'</p>';
 if(r.mode==="verify")html+='<div class="claims"><h3>먼저, 이 주장을 확인하려고 해요.</h3><p>검증 대상 · AI 답변의 내용을 사실로 확인한 것이 아닙니다.</p><ul>'+r.claims.map(x=>'<li>'+esc(x)+'</li>').join("")+'</ul></div>';
 if(!r.candidates.length)html+='<div class="empty-state"><span class="symbol">◌</span><h3>이 자료에서 적임자를 찾지 못했습니다.</h3><p>분야의 전문가가 없다는 뜻은 아닙니다.<br>대상을 바꾸거나, 새로운 근거 자료가 필요해요.</p><div class="topic-hints">현재 다루는 주제: '+r.closest_topics.map(esc).join(" · ")+'</div></div>';
 if(r.mode==="resource_request"&&r.candidates.some(canPropose)&&r.candidates.every(c=>Number.isFinite(c.route_order)))html+='<div class="route-bar">'+r.candidates.map(c=>'<span>'+c.route_order+'. '+esc(c.route_role)+'</span>').join('<span aria-hidden="true">→</span>')+'<button class="primary" data-action="route-letter">경로 전체에 제안하기 ↗</button></div>';
 html+='<div class="cards">'+r.candidates.map((c,i)=>'<article class="candidate-card"><div class="card-topline"><span class="number">'+String(i+1).padStart(2,"0")+' / CONNECTION</span><span class="sticker" title="기록으로 확인할 수 있는 프로필 범위">'+(c.virtual?'시연용 가상 인물':c.org_type==="company"?'문헌 당시 산업체 소속':'저자 참여 기록')+'</span></div><h3>'+esc(c.name)+'</h3><p class="org">'+esc(c.org)+'</p><p class="role">'+esc(c.route_role||c.role)+'</p><p class="reason">'+esc(c.reason)+'</p><div class="evidence-title"><small>연결의 근거 · '+esc(c.evidence[0]?.date)+'</small><button class="record-link" data-action="record" data-id="'+esc(c.evidence[0]?.id)+'" title="이 후보를 연결한 근거 기록 열기"'+(!c.evidence.length||c.evidence[0]?.in_current_pool===false?' disabled':'')+'>'+esc(c.evidence[0]?.title||"연결된 기록 없음")+'</button></div><div class="tags"><span class="tag">'+esc(c.evidence[0]?.scope)+'</span><span class="tag">'+esc(c.evidence[0]?.evidence_label)+'</span><span class="tag">관련 기록 '+c.relevant_records+'건</span></div><p class="card-limit">'+(c.virtual?"가상 작업 기록으로 만든 시연 후보입니다.":"개인 수행 · 본인 확인 · 연락 의향 미확인")+'</p>'+candidateContext(c)+(c.proposal_unavailable_reason?'<p class="context-note">'+esc(c.proposal_unavailable_reason)+'</p>':'')+'<div class="card-actions"><button class="text-button" data-action="candidate" data-id="'+esc(c.id)+'">근거 살펴보기</button><button class="primary" data-action="letter" data-id="'+esc(c.id)+'"'+(canPropose(c)?'':' disabled')+'>제안하기 ↗</button></div></article>').join("")+'</div>';
 if(r.author_strip.length)html+='<details class="author-strip"><summary>함께 참여한 저자들 · '+r.author_strip.length+'명</summary><p>'+esc(r.author_strip_record.title)+'</p><div class="authors">'+r.author_strip.map(a=>'<'+(a.id&&a.profile_available!==false?'button data-action="person" data-id="'+esc(a.id)+'"':'span')+' class="author">'+esc(a.name)+'<small>'+esc(a.role)+(a.corresponding?" · 교신저자":"")+' · '+esc(a.profile_status)+'</small></'+(a.id&&a.profile_available!==false?"button":"span")+'>').join("")+'</div><p class="scope-note">저자 순서로 개인의 실험 수행 여부를 판정하지 않습니다. 교신 표시는 원본 플래그가 있는 경우에만 표시합니다.</p></details>';
 $("results").innerHTML=html;
}

function candidateContext(c){
 const e=c.evidence?.[0]||{};
 let html=String(e.scope_key||"").startsWith("adjacent")?'<p class="context-note">'+esc(e.boundary)+'</p>':"";
 if(c.virtual){
  const lessons=(c.details?.experiences||[]).filter(x=>/실패|오판/.test(x.outcome||""));
  if(lessons.length)html+='<details class="experience-note"><summary>관련 시행착오 기록 · 가상</summary>'+lessons.map(x=>'<p><small>'+esc(x.date)+'</small><br>'+esc(x.what)+'<br>'+esc(x.outcome)+'</p>').join("")+'</details>';
 }
 if(c.route_order)html+='<p class="context-note">다음: '+esc(c.next||"경로의 마지막 단계")+'</p>';
 return html;
}

async function ask(skip=false){
 const follow=Boolean(session?.followup);
 const text=$("question").value.trim();
 if(!text&&!skip){$("question").focus();return;}
 session=await api("/api/converse",{text,session_id:follow?session.id:undefined,mode:session?.ready?undefined:$("mode").value||undefined,slots:session?.ready?{}:slots(),skip});
 $("question").value="";admin=null;renderSession();
 if(session.ready)$("results").scrollIntoView({block:"start",behavior:window.matchMedia("(prefers-reduced-motion: reduce)").matches?"instant":"smooth"});
 else $("question").focus();
}
function newQuestion(){
 session=null;$("question").value="";$("mode").value="";
 for(const k of ["goal","target","conditions","resources","deadline"])$(k).value="";
 renderSession();$("question").focus();
}
function projectParticipantsHtml(e,currentPersonId=null){
 if(e?.kind!=="project_record"||e.in_current_pool===false||!Array.isArray(e.project_participants))return "";
 const seen=new Set(),items=[];
 for(const participant of e.project_participants){
  if(!participant||typeof participant.id!=="string"||!participant.id||participant.id.trim()!==participant.id||typeof participant.display_name!=="string"||!participant.display_name.trim()||seen.has(participant.id))continue;
  seen.add(participant.id);
  items.push(participant.id===currentPersonId?'<span>'+esc(participant.display_name)+' · 현재 인물</span>':'<button type="button" class="text-button" data-action="person" data-id="'+esc(participant.id)+'" aria-label="'+esc(participant.display_name+' 인물 상세 보기')+'">'+esc(participant.display_name)+' ↗</button>');
 }
 return items.length?'<div class="project-participants"><p class="detail-note">함께한 사람 · 사용자 제공 참여 정보</p>'+items.join(' · ')+'</div>':"";
}
function evidenceDatesHtml(e){
 if(e.kind!=='patent_record')return '<dt>기록 날짜·기간</dt><dd>'+esc(e.date)+'</dd>';
 const label=({application_publication_date:'출원공개일',registration_publication_date:'등록공고일'})[e.date_kind]||'공보일(유형 미기재)';
 return '<dt>출원일</dt><dd>'+esc(e.filing_date||'미기재')+'</dd><dt>'+esc(label)+'</dt><dd>'+esc(e.publication_date||e.date||'미기재')+'</dd><dt>공보번호</dt><dd>'+esc(e.publication_id||'미기재')+'</dd>';
}
function evidenceHtml(e,currentPersonId=null){
 return '<section class="detail-block"><button class="record-link" data-action="record" title="근거 기록의 내용과 출처 보기" data-id="'+esc(e.id)+'"'+(e.in_current_pool===false?' disabled':'')+'>'+esc(e.title)+'</button><div class="tags"><span class="tag">'+esc(e.evidence_label)+'</span><span class="tag">'+esc(e.scope)+'</span><span class="tag">'+esc(e.role)+(e.corresponding?" · 교신":"")+'</span></div><dl>'+evidenceDatesHtml(e)+'<dt>자료 확인일</dt><dd>'+esc(e.checked_at)+'</dd><dt>확인한 자료</dt><dd>'+esc(e.access)+'</dd><dt>기록 종류 근거</dt><dd>'+esc((e.classification_basis||[]).join(" · ")||"분류할 정보가 부족함")+'</dd></dl><p class="detail-note">'+esc(e.boundary)+'</p>'+(safeUrl(e.url)?'<a href="'+esc(e.url)+'" target="_blank" rel="noopener noreferrer">원본 출처 열기 ↗</a>':"")+extraRecordSources(e)+projectParticipantsHtml(e,currentPersonId)+'</section>';
}
function safeUrl(u){try{return ["http:","https:"].includes(new URL(u).protocol);}catch{return false;}}
function showPerson(p,candidate=false){
 if(!p)throw new Error("현재 공개된 인물과 근거를 다시 확인해 주세요.");
 $("detailContent").innerHTML=RndCraft.profileDetails(p)+'<div class="selected-holo"'+(p.profile?.curated?' hidden':'')+'><span class="tag">'+(p.virtual?"시연용 가상 인물":"공개 연구자 프로필")+'</span><h2 class="detail-name">'+esc(p.name)+'</h2><p class="muted">'+esc(p.org)+'</p><div class="checks"><span>참여 기록 확인</span><span>개인 수행 미확인</span><span>본인 확인 미완료</span></div></div><div class="detail-block"><h3>이 기록과 연결되어 있어요.</h3><p>'+esc(p.reason||"출처가 연결된 연구·직무 경력입니다.")+'</p><p class="muted">'+(p.works_in_corpus!=null||p.record_count!=null?'코퍼스 안 기록 '+(p.works_in_corpus??p.record_count):'표시된 근거 '+(p.evidence||[]).length)+'건'+(p.works_count!=null?" · OpenAlex 전체 저작 "+nfmt(p.works_count)+"건":"")+'</p>'+(p.profile_topics?.length?'<p>프로필 주제: '+p.profile_topics.map(esc).join(" / ")+'</p>':"")+'<p class="scope-note">기록 수는 개인의 역량 점수가 아닙니다. 소속은 기록 시점에 따라 다를 수 있습니다.</p></div>'+(p.evidence||[]).map(e=>evidenceHtml(e,p.id)).join("")+(candidate&&canPropose(p)?'<button class="primary full" data-action="letter" data-id="'+esc(p.id)+'">이 사람에게 제안하기 ↗</button>':"");
 showDialog("detailDialog");
}
async function openLetter(ids){
 checkProposalSelection(ids);
 const drafts=await Promise.all(ids.map(id=>api("/api/draft",{session_id:session.id,candidate_id:id})));
 letter={ids,sessionId:session.id,key:crypto.randomUUID(),drafts,index:0,bodies:Object.fromEntries(drafts.map(d=>[d.candidate.id,d.body]))};
 renderLetter();showDialog("letterDialog");
}
function renderLetter(){
 const draft=letter.drafts[letter.index];
 $("letterHeader").innerHTML='<h2>'+esc(draft.candidate.name)+'님에게</h2><p class="muted">'+esc(modes[draft.request_kind])+' 제안 · '+(draft.candidate.virtual?"시연용 가상 현장 기록":"연구·경력 기록을 통해 찾은 연결")+'</p>'+(letter.ids.length>1?'<label>경로별 편지<select id="letterRecipient">'+letter.drafts.map((d,i)=>'<option value="'+i+'"'+(i===letter.index?' selected':"")+'>'+esc(d.candidate.route_order+". "+d.candidate.name+" · "+d.candidate.route_role)+'</option>').join("")+'</select></label>':"");
 $("letterBody").value=letter.bodies[draft.candidate.id];$("letterError").textContent="";
 $("aiDraftButton").hidden=!boot.model.enabled;
}
function keepLetter(){
 if(!letter)return;const id=letter.ids[letter.index], value=$("letterBody").value;
 if(letter.bodies[id]!==value){letter.bodies[id]=value;letter.key=crypto.randomUUID();}
}
async function saveLetter(status){
 keepLetter();
 if(letter.lastStatus&&letter.lastStatus!==status)letter.key=crypto.randomUUID();
 letter.lastStatus=status;
 const saved=await api("/api/proposals",{session_id:letter.sessionId,candidate_ids:letter.ids,bodies:letter.bodies,state:status,idempotency_key:letter.key});
 $("letterDialog").close();admin=null;
 $("inboxCount").textContent=Number($("inboxCount").textContent)+saved.length;
 letter=null;
 if(status==="sent"&&!sessionStorage.getItem("rndplz-envelope")&&!matchMedia("(prefers-reduced-motion: reduce)").matches){sessionStorage.setItem("rndplz-envelope","seen");$("sentScene").showModal();$("sentScene").querySelector("button").focus();}
 else toast(saved.length+"건이 제안함에 저장됐어요. "+(status==="sent"?"시연 기록입니다.":"초안입니다."));
}
async function openInbox(){
 const proposals=await api("/api/proposals");$("inboxCount").textContent=proposals.length;
 const actions={draft:[["sent","보내기 · 시연"],["cancelled","취소"]],sent:[["accepted","수락 · 시연"],["declined","거절 · 시연"],["closed","종료"],["cancelled","취소"]],accepted:[["closed","종료"]],declined:[["closed","종료"]],closed:[],cancelled:[]};
 $("inboxContent").innerHTML=proposals.length?proposals.slice().reverse().map(p=>'<article class="inbox-item"><header><h3>'+esc(p.recipient_name)+'</h3><span class="tag">'+stateNames[p.state]+'</span></header><small>'+esc(modes[p.request_kind])+' · '+esc(p.direction)+' · '+new Date(p.created).toLocaleString("ko-KR")+(p.route_order?' · 경로 '+p.route_order+'/'+p.route_total:"")+'</small><details><summary>보관된 편지와 근거 보기</summary><pre>'+esc(p.body)+'</pre><p>근거 '+p.evidence.length+'건 · 제안자 사본 보관</p><p>시연 이력: '+p.history.map(h=>stateNames[h.state]).join(" → ")+'</p></details><div class="inbox-actions"><button class="outline" data-action="recipient" data-id="'+p.id+'">받는 사람 화면 · 시연</button>'+actions[p.state].map(([s,label])=>'<button class="outline" data-action="transition" data-id="'+p.id+'" data-value="'+s+'">'+label+'</button>').join("")+'</div></article>').join(""):'<div class="empty-state"><span class="symbol">✉</span><h3>첫 연결을 기다리고 있어요.</h3><p>후보 카드에서 제안문을 작성해보세요.</p></div>';
 showDialog("inboxDialog");
}

function renderRecipient(opened=false){
 const p=received;
 if(!opened){
  $("recipientContent").innerHTML='<button class="received-envelope" data-action="open-received" aria-label="'+esc(p.recipient_name)+'님에게 온 시연 편지 펼치기"><span>TO.</span><strong>'+esc(p.recipient_name)+'</strong><b class="service-name">수소문</b><small>편지 펼치기 ↗</small></button>';
  return;
 }
 const actions=p.state==="sent"?[["accepted","수락 · 시연"],["declined","거절 · 시연"],["closed","종료 · 시연"]]:["accepted","declined"].includes(p.state)?[["closed","종료 · 시연"]]:[];
 $("recipientContent").innerHTML='<article class="received-letter"><span class="tag">'+stateNames[p.state]+'</span><h2>'+esc(p.recipient_name)+'님에게</h2><pre>'+esc(p.body)+'</pre><section class="detail-block"><h3>왜 저에게 왔나요?</h3><p>아래 기록과 질문이 연결되어 제안을 받았습니다. 개인 수행 능력이 확인됐다는 뜻은 아닙니다.</p>'+p.evidence.map(e=>'<p><button class="record-link" data-action="record" data-id="'+esc(e.id)+'">'+esc(e.title)+'</button><br><small>'+esc(e.scope)+' · '+esc(e.role)+'</small></p>').join("")+'</section><div class="inbox-actions">'+actions.map(([value,label])=>'<button class="outline" data-action="recipient-transition" data-value="'+value+'">'+label+'</button>').join("")+'</div></article>';
}

async function showTab(tab){
 view=tab;$("chatView").hidden=tab!=="chat";$("mapView").hidden=tab!=="map";
 for(const x of ["chat","map"]){$(x+"Tab").classList.toggle("active",x===tab);if(x===tab)$(x+"Tab").setAttribute("aria-current","page");else $(x+"Tab").removeAttribute("aria-current");}
 if(tab==="map")await renderMap();
}
async function renderMap(){
 await RndPeopleMap.ensure($("peopleMapHost"),api);
}
function renderSettings(){
 $("settingsContent").innerHTML='<h3>AI 사용</h3><div class="setting-value">'+(boot.model.enabled?esc(boot.model.provider+" · "+boot.model.model):"외부 API 미설정 · 기본 추천 사용")+'</div><p>AI는 질문을 정리하고 제안 문장을 다듬는 데 사용합니다. 후보와 근거는 기록에서 확인합니다. 대화 모델은 첫 화면의 모델 연결 설정에서 선택합니다.</p>'+(boot.model.enabled?'<label class="model-toggle"><input type="checkbox" id="modelConsent" '+(sessionStorage.getItem("rndplz-model-consent")==="yes"?"checked":"")+'>이 시연에서 외부 AI 문장 도우미 사용</label><p class="scope-note">사용 시 질문·조건·선택 후보의 공개 근거·편지 초안이 '+esc(boot.model.provider)+'로 전송됩니다. 현재 시연에 실제 사내 자료를 입력하지 마세요.</p>':'<p class="scope-note">외부 API 연결은 실행 환경에서 설정합니다. 연결 전에도 질문·추천·제안함·맵을 사용할 수 있습니다.</p>')+'<details><summary>AI 실행 현황</summary><p>이 서버 실행에서 '+boot.model.calls+' / '+boot.model.limit+'회 호출</p><p class="scope-note">호출 시간·적용 여부만 로컬에 기록합니다. 질문·편지·API 키는 관측 기록에 남기지 않습니다.</p></details><h3>독립 서비스</h3><p>브라우저에서 직접 접속합니다. 대화와 제안은 이 기기의 저장소에 보관됩니다. Teams·AiU 없이도 사용할 수 있습니다.</p><h3>Obsidian으로 이어보기</h3><p>논문·사람·주제·제안이 연결된 볼트를 만듭니다. 폴더와 그래프에 같은 종류 색을 적용합니다.</p><button class="outline" data-action="export">현재 기록 내보내기 ↗</button>'+(exported?'<div class="export-result"><p>노트 '+exported.note_count+'개 · 연결 오류 '+exported.unresolved.length+'개 · 수동 수정 충돌 '+exported.conflicts.length+'개</p><p>'+esc(exported.path)+'</p><a href="'+esc(exported.uri)+'">Obsidian에서 시작 노트 열기 ↗</a><p>처음에는 Obsidian에서 위 경로를 볼트로 열어주세요.</p></div>':"");
}
async function exportVault(){
 toast("현재 기록을 Obsidian 볼트로 만들고 있어요.");
 exported=await api("/api/export",{});
 renderSettings();showDialog("settingsDialog");
 toast(exported.conflicts.length?"사용자가 수정한 노트 "+exported.conflicts.length+"개를 보존했어요. 설정에서 결과를 확인하세요.":exported.note_count+"개의 노트를 내보냈어요.");
}
// Do not change map selection for a person request the existing busy guard cannot accept.
document.addEventListener("click",event=>{
 const person=event.target.closest('button[data-person][data-map-open="person"]');
 if(busy&&person?.closest("#peopleMapHost")){event.preventDefault();event.stopPropagation();}
},true);
document.addEventListener("click",event=>{
 const mapHost=event.target.closest("#peopleMapHost"),mapButton=mapHost&&event.target.closest("button[data-map-open]");
 if(mapHost&&!mapButton)return;
 const button=mapButton||event.target.closest("button[data-action]");if(!button)return;
 const action=mapButton?button.dataset.mapOpen:button.dataset.action,id=button.dataset.id,value=button.dataset.value;
 if(action==="close"){
  const dialog=button.closest("dialog");
  if(dialog.id==="detailDialog")closeDetail();else dialog.close();
  return;
 }
 if(action==="scene-close"){$("sentScene").close();$("askButton").focus();return;}
 task(async()=>{
  if(["person","candidate","record"].includes(action))rememberDetailTrigger(button);
  if(action==="tab"){if(value==="chat")location.href="/";else await showTab(value);}
  else if(action==="new")newQuestion();
  else if(action==="example"){const q=boot.questions.find(q=>q.id===id);newQuestion();$("question").value=q.question+(q.ai_answer?"\n\n[검증 대상 · 가상의 AI 답]\n"+q.ai_answer:"");$("mode").value=q.mode||"";$("question").focus();}
  else if(action==="skip")await ask(true);
  else if(action==="candidate")showPerson(displayResult(session)?.candidates.find(c=>c.id===id),true);
  else if(action==="person")showPerson(await api("/api/person?id="+encodeURIComponent(id)));
  else if(action==="record"){const r=await api("/api/record?id="+encodeURIComponent(id));$("detailContent").innerHTML='<h2>'+esc(r.title)+'</h2>'+evidenceHtml(r)+'<h3>기록에 담긴 내용</h3><div class="record-text">'+esc(r.text||"초록이 없습니다. 제목과 메타데이터를 근거로 연결했습니다.")+'</div>';showDialog("detailDialog");}
  else if(action==="letter")await openLetter([id]);
  else if(action==="route-letter")await openLetter((displayResult(session)?.candidates||[]).filter(canPropose).map(c=>c.id));
  else if(action==="draft-save")await saveLetter("draft");
  else if(action==="send")await saveLetter("sent");
  else if(action==="inbox")await openInbox();
  else if(action==="recipient"){received=(await api("/api/proposals")).find(p=>p.id===id);renderRecipient();showDialog("recipientDialog");}
  else if(action==="open-received"){$("recipientContent").querySelector(".received-envelope")?.classList.add("opening");await RndCraft.pause(560);renderRecipient(true);$("recipientContent").querySelector("h2").setAttribute("tabindex","-1");$("recipientContent").querySelector("h2").focus();}
  else if(action==="recipient-transition"){received=await api("/api/transition",{id:received.id,state:value});admin=null;renderRecipient(true);toast("제안자 사본에도 시연 상태를 반영했어요.");}
  else if(action==="transition"){await api("/api/transition",{id,state:value});admin=null;await openInbox();toast("시연 상태를 변경했어요.");}
  else if(action==="settings"){boot.model=(await api("/api/bootstrap")).model;renderSettings();showDialog("settingsDialog");}
  else if(action==="export")await exportVault();
  else if(action==="ai-structure"){
   if(sessionStorage.getItem("rndplz-model-consent")!=="yes"){toast("설정에서 외부 AI 도우미 사용과 전송 범위를 확인해 주세요.",true);return;}
   const query=$("question").value.trim()||session?.original;
   if(!query){toast("정리할 질문을 먼저 적어주세요.",true);return;}
   const result=await api("/api/ai/structure",{text:query,consent:true});
   if(result.applied){for(const k of ["goal","target","conditions","resources","deadline"])if(result.slots[k])$(k).value=result.slots[k];$("mode").value=result.mode;toast("질문에서 찾은 조건을 메모에 넣었어요. 확인한 뒤 사람 찾기 또는 조건 반영하기를 눌러주세요.");}
   else toast(result.message,true);
  }
  else if(action==="ai-draft"){
   if(sessionStorage.getItem("rndplz-model-consent")!=="yes"){toast("설정에서 외부 AI 도우미 사용과 전송 범위를 확인해 주세요.",true);return;}
   keepLetter();toast("AI가 근거와 요청 범위를 유지하며 문장을 다듬고 있어요.");
   const result=await api("/api/ai/draft",{session_id:letter.sessionId,candidate_id:letter.ids[letter.index],body:$("letterBody").value,consent:true});
   if(result.applied){$("letterBody").value=result.body;keepLetter();toast("원문 아래에 AI가 제안한 문장을 덧붙였어요. 검토한 뒤 편집해 주세요.");}
   else toast(result.message||"AI 응답을 적용하지 못해 기존 초안을 유지했어요.",true);
  }
 },button);
});
$("questionForm").addEventListener("submit",e=>{e.preventDefault();task(()=>ask(),$("askButton"));});
$("slotsForm").addEventListener("submit",e=>{e.preventDefault();if(!session||session.kind==="chat"){toast("채팅에서 시작한 요청은 대화창에서 조건을 바꿔 주세요.",true);return;}task(async()=>{session=await api("/api/slots",{session_id:session.id,slots:slots(),mode:$("mode").value});admin=null;renderSession();toast("조건을 반영했어요.");},$("applySlots"));});
$("letterBody").addEventListener("input",keepLetter);
document.addEventListener("change",e=>{
 if(e.target.id==="letterRecipient"){keepLetter();letter.index=Number(e.target.value);renderLetter();}
 if(e.target.id==="modelConsent")sessionStorage.setItem("rndplz-model-consent",e.target.checked?"yes":"no");
});
(async()=>{
 try{boot=await api("/api/bootstrap");token=boot.token;session=boot.session;if(boot.public)document.querySelectorAll('[data-action="export"]').forEach(b=>b.hidden=true);$("aiQuestionButton").hidden=!boot.model.enabled;$("inboxCount").textContent=boot.proposal_count;$("modelStatus").textContent=boot.model.enabled?"AI 문장 도우미 사용 가능":"모델 없이도 연결되는 경험";renderExamples();renderSession();await showTab("map");if(location.hash==="#inbox")await openInbox();if(location.hash==="#peopleCards")$("people-map")?.scrollIntoView({block:"start"});}
 catch(e){toast(e.message+" 새로고침해 주세요.",true);$("askButton").disabled=true;}
})();

document.addEventListener("pointermove",event=>{
 const card=event.target.closest(".selected-holo");
 if(!card||matchMedia("(prefers-reduced-motion: reduce)").matches)return;
 const box=card.getBoundingClientRect(),x=(event.clientX-box.left)/box.width,y=(event.clientY-box.top)/box.height;
 card.style.setProperty("--shine-x",(x*100)+"%");
 card.style.setProperty("--shine-y",(y*100)+"%");
 card.style.transform="perspective(900px) rotateX("+((.5-y)*3)+"deg) rotateY("+((x-.5)*3)+"deg)";
});
document.addEventListener("pointerout",event=>{
 const card=event.target.closest(".selected-holo");
 if(card&&!card.contains(event.relatedTarget)){card.style.transform="";card.style.removeProperty("--shine-x");card.style.removeProperty("--shine-y");}
});

$("detailDialog").addEventListener("cancel",e=>{e.preventDefault();closeDetail();});
