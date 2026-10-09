/* Shared person content. Callers own navigation, request permissions and evidence scope. */
(function(root){
  'use strict';
  const html=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const rows=value=>Array.isArray(value)?value.filter(x=>x&&typeof x==='object'):[];
  const strings=value=>Array.isArray(value)?value.filter(x=>typeof x==='string'&&x.trim()).map(x=>x.trim()):[];
  const isLaureate=profile=>profile?.award?.name==='Nobel Prize';
  const isPersonalIllustration=profile=>['LOCAL-MANWOO','LOCAL-JINHO'].includes(profile?.id)&&['self_reported','provided_resume'].includes(profile?.source_type)&&profile?.portrait?.kind==='personal_illustration'&&profile.portrait.generated===true;
  const safeUrl=value=>{try{return typeof value==='string'&&['http:','https:'].includes(new URL(value).protocol);}catch{return false;}};
  const sourceLink=(url,label)=>safeUrl(url)?'<a href="'+html(url)+'" target="_blank" rel="noopener noreferrer">'+html(label)+' ↗</a>':label==='출처'?'':'<span>'+html(label)+'</span>';
  function sourceEvidence(value){
    const sources=rows(value?.sources),review=typeof value?.source_review==='string'?value.source_review:'';
    if(!sources.length&&!review)return '';
    return '<p class="detail-note person-source">'+html(review||'자료 기반')+(sources.length?' · '+sources.map(s=>sourceLink(s.url,s.title||s.name||'첨부 자료')).join(' · '):'')+'</p>';
  }
  const artPath=value=>typeof value==='string'&&/^\/portraits\/[a-zA-Z0-9_.-]+\.(?:png|jpe?g|webp)$/.test(value)?value:'';
  const displayPath=value=>artPath(value).replace(/\.(?:png|jpe?g)$/i,'-detail.webp');
  function effectiveLaureateEffect(){return 'off';}
  function effectControls(profile,name) {return '';}
  function detailPortrait(profile,name) {
    const nobel=isLaureate(profile), personal=isPersonalIllustration(profile), path=displayPath(profile?.portrait?.path);
    if(!path && !nobel && !personal)return '<div class="portrait-art portrait-unavailable"><strong>초상 미제공</strong><p>이력과 연구 기록을 살펴보세요.</p></div>';
    const generated=profile?.portrait?.generated, background=artPath(profile?.portrait?.background);
    if(personal) {
      const art=profile.portrait, width=Number.isSafeInteger(art.width)&&art.width>0?art.width:600, height=Number.isSafeInteger(art.height)&&art.height>0?art.height:800;
      return '<div class="portrait-art is-illustration personal-illustration" data-asset="'+(path?'loading':'missing')+'" aria-busy="'+Boolean(path)+'"><div class="portrait-status" role="status">'+(path?'일러스트를 불러오는 중입니다.':'일러스트 미제공 · 이력과 근거를 확인해 주세요.')+'</div>'+(path?'<img class="portrait-person" data-personal-image src="'+html(path)+'" alt="'+html(name)+'의 AI 생성 초상 일러스트" loading="eager" decoding="async" width="'+width+'" height="'+height+'">':'')+'<span class="foil-sheen" aria-hidden="true"></span><span class="foil-glare" aria-hidden="true"></span><span class="portrait-label">AI ILLUSTRATION</span></div>';
    }
    if(nobel) {
      return '<div class="portrait-art laureate-portrait '+(generated?'is-illustration':'is-photo')+'" data-laureate-effect="'+effectiveLaureateEffect()+'" data-asset="'+(path?'loading':'missing')+'" aria-busy="'+Boolean(path)+'"><div class="portrait-status" role="status">'+(path?'일러스트를 불러오는 중입니다.':'일러스트 미제공 · 이력과 근거를 확인해 주세요.')+'</div>'+(path?'<img class="portrait-person" data-laureate-image src="'+html(path)+'" alt="'+html(name)+(generated?'의 AI 생성 초상 일러스트':'의 프로필 사진')+'" loading="eager" decoding="async" width="600" height="800">':'')+'<span class="foil-sheen" aria-hidden="true"></span><span class="foil-glare" aria-hidden="true"></span>'+(generated?'<span class="portrait-label">AI ILLUSTRATION</span>':'')+'</div>';
    }
    return '<div class="portrait-art '+(generated?'is-illustration':'is-photo')+(background?' has-process-art portrait-'+html(profile.slug):'')+'">'+(background?'<img class="portrait-backdrop" src="'+html(background)+'" alt="" aria-hidden="true" loading="lazy" decoding="async">':'')+'<img class="portrait-person" src="'+html(path)+'" alt="'+html(name)+(generated?'의 AI 생성 초상 일러스트':'의 제공된 프로필 사진')+'" loading="eager" decoding="async" width="600" height="800"><span class="foil-sheen" aria-hidden="true"></span><span class="foil-glare" aria-hidden="true"></span><span class="portrait-label">'+(generated?'AI ILLUSTRATION':background?'PHOTO + AI ART':'PERSONAL PORTRAIT')+'</span></div>';
  }
  function awardSummary(profile){
    if(!isLaureate(profile))return '';
    const award=profile.award;
    return '<section class="laureate-award" aria-label="확인된 수상 이력"><p class="laureate-award-label"><span aria-hidden="true">✦</span> '+html(award.label_ko||'Nobel Prize')+'</p><p class="laureate-award-domain">'+html(award.year)+' · '+html(award.discipline)+'</p><p>'+html(award.summary)+'</p>'+sourceLink(award.facts_url,'공식 수상 기록')+'<small>수상 이력은 개인 수행·현재 협업 가능성 확인과 구분합니다.</small></section>';
  }
  function portraitSources(profile){
    if(!profile.portrait || (!isLaureate(profile) && profile.portrait.generated!==true))return '';
    const p=profile.portrait,r=p.reference||{};
    const referenceUrl=r.url||p.reference_url||p.photo_url;
    const reference=referenceUrl?'<h4>외형 참고 사진</h4><p>'+sourceLink(referenceUrl,r.title||'참고 사진 출처')+'</p>'+(r.author?'<p>촬영·저작: '+html(r.author)+'</p>':'')+(r.credit?'<p>'+html(r.credit)+'</p>':'')+(r.license?'<p>참고 사진 이용 조건: '+sourceLink(r.license_url,r.license)+'</p>':'')+'<p>참고 사진은 외형 자료이며 이 카드의 표시 이미지는 별도 일러스트입니다.</p>':'';
    return '<details class="portrait-provenance"><summary>일러스트 제작·참고 사진 출처</summary><div><h4>카드에 표시한 생성물</h4><p>'+html(p.generated?'AI 생성 초상 일러스트':p.label||'프로필 이미지')+'</p>'+(p.generated_credit?'<p>'+html(p.generated_credit)+'</p>':'')+(p.generated_license?'<p>생성물 이용 조건: '+sourceLink(p.generated_license_url,p.generated_license)+'</p>':'')+(p.change_note?'<p>변경 이력: '+html(p.change_note)+'</p>':'')+reference+(p.reference_note?'<p>참고 자료 설명: '+html(p.reference_note)+'</p>':'')+'</div></details>';
  }
  function laureateAttributes(profile){return isLaureate(profile)?' data-laureate-card data-laureate-effect="'+effectiveLaureateEffect()+'"':'';}
  function personalPortraitNote(profile,detailed=false){
    if(!isPersonalIllustration(profile))return '';
    const p=profile.portrait,r=p.reference||{};
    const note='<p class="personal-portrait-note">'+html(profile.portrait_note||'제공된 사진의 외형을 참고한 AI 생성 일러스트입니다.')+'</p>';
    if(!detailed)return '';
    return note+'<details class="personal-portrait-provenance"><summary>일러스트 제작·참고 자료</summary><div><h4>카드에 표시한 생성물</h4><p>AI 생성 초상 일러스트</p>'+(p.generated_credit?'<p>'+html(p.generated_credit)+'</p>':'')+(p.change_note?'<p>변경 이력: '+html(p.change_note)+'</p>':'')+'<h4>외형 참고 사진</h4><p>'+html(r.title||'제공된 프로필 사진')+'</p>'+(r.usage?'<p>'+html(r.usage)+'</p>':'')+'</div></details>';
  }
  function displayName(person){
    const p=person?.profile||{},names=[p.display_name,person?.display_name,p.name_ko,person?.name_ko,person?.name];
    const valid=names.filter(n=>typeof n==='string'&&n.trim()).map(n=>n.trim());
    return valid.find(n=>/[가-힣]/.test(n))||valid[0]||'이름 미확인';
  }
  function nameBlock(person,heading='h3',className='researcher-name',options={}){
    const p=person?.profile||{},name=displayName(person),sheet=className==='sheet-id';
    const tag=/^(?:h[1-6]|strong|span)$/.test(heading)?heading:'h3';
    const headingClass=options.headingClass||(className==='pi-facts'?'pi-name':'');
    const headingAttrs=(options.headingId?' id="'+html(options.headingId)+'"':'')+(headingClass?' class="'+html(headingClass)+'"':'');
    const original=typeof person?.name==='string'?person.name.trim():'';
    const aliases=[...new Set([...strings(person?.aliases),...strings(p.aliases),...(!options.compact&&original&&original!==name?[original]:[])])].filter(value=>value!==name);
    const baseOrg=typeof person?.org==='string'?person.org:p.org||'',org=[baseOrg,p.department].filter(Boolean).join(' · ');
    const orgTag=sheet?'span':'p',orgClass=sheet?'':options.orgClass||(className==='pi-facts'?'pi-org':'candidate-org');
    if(options.variant==='inspect')return '<'+tag+headingAttrs+'>'+html(name)+'</'+tag+'>'+(baseOrg?'<p class="'+html(orgClass)+'">'+html(baseOrg)+'</p>':'');
    return '<div class="'+html(className)+'"><'+tag+headingAttrs+'>'+html(name)+'</'+tag+'>'+
      (aliases.length?'<span class="researcher-korean">'+aliases.map(html).join(' · ')+'</span>':'')+
      (org?'<'+orgTag+(orgClass?' class="'+html(orgClass)+'"':'')+'>'+html(org)+'</'+orgTag+'>':'')+
      (p.current_role?'<p class="laureate-role">'+html(p.current_role)+(p.affiliation_as_of?' · 공개 프로필 확인 '+html(p.affiliation_as_of):'')+'</p>':'')+
      (!sheet&&p.tagline?'<p class="candidate-org">'+html(p.tagline)+'</p>':'')+
      (sheet&&(p.tagline||(!options.compact&&capability(person)))?'<em>'+html(p.tagline||capability(person))+'</em>':'')+
      (sheet&&strings(options.tags).length?'<span class="sheet-tags">'+strings(options.tags).map(t=>'<b>'+html(t)+'</b>').join('')+'</span>':'')+'</div>';
  }
  function portrait(profile,name,options={}){
    if(!options.variant||options.variant==='detail')return detailPortrait(profile||{},name||'이름 미확인');
    let path=displayPath(profile?.portrait?.path);
    if(options.variant==='thumb')path=path.replace(/-detail\.webp$/i,'-thumb.webp');
    if(!path&&options.fallbackInitial)return html(Array.from(name||'')[0]||'');
    const cls=options.className?' class="'+html(options.className)+'"':'';
    return path?'<img'+cls+' src="'+html(path)+'" alt="'+html(options.decorative?'':(name||'이름 미확인')+(profile?.portrait?.generated?'의 AI 생성 초상 일러스트':'의 제공된 프로필 사진'))+'" loading="'+(options.loading==='lazy'?'lazy':'eager')+'" decoding="async">':
      '<span class="'+html(options.className||'pi-portrait-empty')+(options.className==='simple-portrait'?' portrait-unavailable':'')+'">초상 미제공</span>';
  }
  function skillValues(person){
    const p=person?.profile||{},topics=Array.isArray(person?.profile_topics)?person.profile_topics.map(t=>typeof t==='string'?t:t?.name):[];
    const values=[...strings(p.skills),...rows(p.skill_groups).flatMap(g=>strings(g.items))];
    return [...new Set(values.length?values:strings(topics))];
  }
  function capability(person){
    const p=person?.profile||{},values=[p.tagline,...skillValues(person),...rows(p.topics).map(t=>t.name)];
    return values.filter(v=>typeof v==='string').map(v=>v.replace(/\s+/g,' ').trim()).find(v=>v&&Array.from(v).length<=20)||'등록 이력과 근거 보기';
  }
  function skills(person,options={}){
    if(options.variant==='inspect')return strings(person?.profile?.skills).length?'<p class="pi-skills">'+strings(person.profile.skills).map(s=>'<span>'+html(s)+'</span>').join('')+'</p>':'';
    const values=options.values?strings(options.values):skillValues(person),limit=options.limit===null?values.length:Math.max(0,Number.isInteger(options.limit)?options.limit:4);
    if(!values.length)return '';
    const chips=list=>list.map(s=>'<span>'+html(s)+'</span>').join(''),rest=values.slice(limit);
    return '<div class="'+html(options.className||'sheet-chips')+'">'+chips(values.slice(0,limit))+
      (rest.length?'<span class="sheet-chips-rest" hidden>'+chips(rest)+'</span><button type="button" class="sheet-chip-more" data-chips-more aria-expanded="false" aria-label="나머지 '+rest.length+'개 더 보기">+'+rest.length+'</button>':'')+'</div>';
  }
  // Legacy rows without an ID may join only a single, nonempty date. An explicit other ID never matches.
  function evidenceDescription(e,profile){
    if(typeof e?.excerpt==='string'&&e.excerpt.trim())return e.excerpt;
    if(e?.kind==='project_record')return rows(profile?.projects).find(p=>e.id&&(p.id===e.id||p.record_id===e.id))?.text||'';
    if(e?.kind==='career_record'){
      const timeline=rows(profile?.timeline),linked=timeline.find(t=>e.id&&t.record_id===e.id);
      if(linked)return linked.text||'';
      const dated=timeline.filter(t=>e.date&&t.date===e.date);
      return dated.length===1&&!dated[0].record_id?dated[0].text||'':'';
    }
    return '';
  }
  const plainScience=text=>String(text).replace(/\$\s*(?:\\text|ext)?\s*\{?([A-Za-z0-9]+)\}?(?:_\{?([0-9]+)\}?)?\s*\$/g,(m,base,sub)=>base+(sub?Array.from(sub,d=>'₀₁₂₃₄₅₆₇₈₉'[d]).join(''):''));
  const compact=text=>String(text||'').replace(/\s+/g,' ').trim();
  function recordLink(e,options={}){
    return options.recordAction&&e?.id?'<button type="button" class="text-button person-record-link" data-action="record" data-id="'+html(e.id)+'"'+(e.in_current_pool===false?' disabled':'')+'>기록 보기 ›</button>':'';
  }
  // Keep the server classification: compact cards show scope, detailed records show kind.
  function evidenceKind(e,variant='inspect'){
    return variant==='detail'?e.evidence_label||e.scope_label||e.scope||'':e.scope_label||e.scope||e.evidence_label||'';
  }
  function evidenceRow(e,profile,options={}){
    const title=html(e.title||e.id||'연결 근거'),meta=[evidenceKind(e),e.date].filter(Boolean).map(html).join(' · ');
    if(options.variant==='inspect'){
      const text=evidenceDescription(e,profile),body=(text?'<p>'+html(plainScience(text))+'</p>':'')+(safeUrl(e.url)?sourceLink(e.url,'원문 출처'):'')+sourceEvidence(e);
      const heading='<strong>'+title+'</strong>'+(meta?'<span>'+meta+'</span>':'');
      return body?'<details><summary>'+heading+'</summary>'+body+'</details>':'<div class="pi-evidence-plain">'+heading+'</div>';
    }
    const fullText=evidenceDescription(e,profile),text=options.described?.get(e.id)?.has(compact(fullText))?'':fullText;
    const label=options.label?'<span class="found-label">'+html(options.label)+'</span>':'';
    const heading=label+'<strong>'+title+'</strong>'+(meta?'<span>'+meta+'</span>':'');
    const source=(safeUrl(e.url)?sourceLink(e.url,'원문 출처'):'')+sourceEvidence(e)+rows(e.metadata_sources).filter(s=>safeUrl(s.url)).map(s=>'<p>'+sourceLink(s.url,s.title||s.label||(/correction/i.test(s.basis||s.type||'')?'정정 출처':'추가 확인 출처'))+'</p>').join('');
    const boundary=options.showBoundary!==false&&e.boundary&&e.boundary!==profile?.profile_note?'<p class="detail-note">'+html(e.boundary)+'</p>':'';
    const action=recordLink(e,options),cls='person-evidence'+(options.label?' found-record':'');
    return text?'<details class="'+cls+'"><summary>'+heading+'</summary><p>'+html(plainScience(text))+'</p>'+boundary+source+action+'</details>':
      '<div class="pi-evidence-plain '+cls+'">'+heading+source+action+'</div>';
  }
function extraRecordSources(e){
 return sourceEvidence(e)+(Array.isArray(e.metadata_sources)?e.metadata_sources:[]).filter(x=>safeUrl(x.url)).map(x=>'<p><a href="'+html(x.url)+'" target="_blank" rel="noopener noreferrer">'+html(x.title||x.label||(/correction/i.test(x.basis||x.type||'')?'정정 출처':'추가 확인 출처'))+' ↗</a></p>').join('');
}

function projectParticipantsHtml(e,currentPersonId=null,options={}){
 if(e?.kind!=="project_record"||e.in_current_pool===false||!Array.isArray(e.project_participants))return "";
 const seen=new Set(),items=[];
 for(const participant of e.project_participants){
  if(!participant||typeof participant.id!=="string"||!participant.id||participant.id.trim()!==participant.id||typeof participant.display_name!=="string"||!participant.display_name.trim()||seen.has(participant.id))continue;
  seen.add(participant.id);
  items.push(participant.id===currentPersonId?'<span>'+html(participant.display_name)+' · 현재 인물</span>':options.personLinks?'<a class="text-button" href="/explore?person='+encodeURIComponent(participant.id)+'" target="_blank" rel="noopener noreferrer" aria-label="'+html(participant.display_name+' 인물 상세 보기')+'">'+html(participant.display_name)+' ↗</a>':'<button type="button" class="text-button" data-action="person" data-id="'+html(participant.id)+'" aria-label="'+html(participant.display_name+' 인물 상세 보기')+'">'+html(participant.display_name)+' ↗</button>');
 }
 return items.length?'<div class="project-participants"><p class="detail-note">함께한 사람 · 사용자 제공 참여 정보</p>'+items.join(' · ')+'</div>':"";
}
function evidenceDatesHtml(e){
 if(e.kind!=='patent_record')return '<dt>기록 날짜·기간</dt><dd>'+html(e.date)+'</dd>';
 const label=({application_publication_date:'출원공개일',registration_publication_date:'등록공고일'})[e.date_kind]||'공보일(유형 미기재)';
 return '<dt>출원일</dt><dd>'+html(e.filing_date||'미기재')+'</dd><dt>'+html(label)+'</dt><dd>'+html(e.publication_date||e.date||'미기재')+'</dd><dt>공보번호</dt><dd>'+html(e.publication_id||'미기재')+'</dd>';
}
function detailEvidence(e,options={}){
 const currentPersonId=options.personId||null,foundLabel=options.label||"";
 return '<section class="detail-block'+(foundLabel?' found-record':'')+'">'+(foundLabel?'<p class="found-label">'+html(foundLabel)+'</p>':'')+'<button class="record-link" data-action="record" title="근거 기록의 내용과 출처 보기" data-id="'+html(e.id)+'"'+((e.in_current_pool===false||options.recordAction===false)?' disabled':'')+'>'+html(e.title)+'</button><div class="tags"><span class="tag">'+html(evidenceKind(e,'detail'))+'</span><span class="tag">'+html(e.scope)+'</span><span class="tag">'+html(e.role)+(e.corresponding?" · 교신":"")+'</span></div><dl>'+evidenceDatesHtml(e)+'<dt>자료 확인일</dt><dd>'+html(e.checked_at)+'</dd><dt>확인한 자료</dt><dd>'+html(e.access)+'</dd><dt>기록 종류 근거</dt><dd>'+html((e.classification_basis||[]).join(" · ")||"분류할 정보가 부족함")+'</dd></dl><p class="detail-note">'+html(e.boundary)+'</p>'+(safeUrl(e.url)?'<a href="'+html(e.url)+'" target="_blank" rel="noopener noreferrer">원본 출처 열기 ↗</a>':"")+extraRecordSources(e)+projectParticipantsHtml(e,currentPersonId,options)+'</section>';
}

  function countLabel(count,partial=false){return (partial?'이번 조건에 연결된 근거 ':'전체 등록 이력 ')+Math.max(0,Number(count)||0)+'건';}
  function evidenceSection(evidence,profile,options={}){
    const all=rows(evidence),limit=Number.isInteger(options.limit)&&options.limit>=0?options.limit:all.length,shown=all.slice(0,limit);
    const expandable=shown.some(e=>{const text=evidenceDescription(e,profile);return text&&!options.described?.get(e.id)?.has(compact(text));});
    const hint=[all.length>shown.length?'앞 '+shown.length+'건':'',expandable?'설명이 있는 항목은 눌러서 펼치기':''].filter(Boolean).join(' · ');
    const boundaries=[...new Set(shown.map(e=>e.boundary).filter(b=>typeof b==='string'&&b.trim()&&b!==profile?.profile_note))];
    return '<h3>'+countLabel(all.length,options.partial||options.historical)+(hint?' <small>'+hint+'</small>':'')+'</h3>'+
      shown.map(e=>evidenceRow(e,profile,{...options,showBoundary:false,label:options.labels?.get(e.id)||''})).join('')+
      boundaries.map(b=>'<p class="detail-note person-evidence-boundary">'+html(b)+'</p>').join('');
  }
  function evidenceStats(person,found,candidate){
    const all=rows(person?.evidence),ids=found?.hasCondition?new Set(found.recordIds||[]):null;
    const linked=found?(ids?all.filter(e=>ids.has(e.id)):null):candidate?rows(candidate.evidence):null;
    return countLabel(all.length)+(linked?' · '+countLabel(linked.length,true):'');
  }
  function evidenceContext(person,options={}){
    const evidence=rows(options.evidence??person?.evidence);
    return '<div class="detail-block"><h3>이 기록과 연결되어 있어요.</h3><p>'+html(person.reason||'출처가 연결된 연구·직무 경력입니다.')+'</p><p class="muted">'+html(options.partial||options.historical?countLabel(evidence.length,true):evidenceStats(person,options.found,options.candidate))+'</p>'+(person.profile_topics?.length?'<p>프로필 주제: '+person.profile_topics.map(html).join(' / ')+'</p>':'')+'<p class="scope-note">기록 수는 개인의 역량 점수가 아닙니다. 소속은 기록 시점에 따라 다를 수 있습니다.</p>'+(options.historical?notice(person,options):'')+'</div>';
  }
  function noticeText(person,options={}){
    if(options.historical)return '이전 응답 당시 선택 근거이며 현재 전체 등록 이력이 아닙니다.';
    if(person?.virtual)return '시연용 가상 인물과 기록입니다. 실제 인물·사업장·승인 절차가 아닙니다.';
    const brief='등록 이력은 본인 제공·공개 기록이에요. 지금의 역량이나 협업 가능 여부를 확인한 것은 아니에요.';
    return options.variant==='inspect'?brief:person?.profile?.profile_note||(options.variant==='detail'?'공개 연구 사례입니다. 사내 구성원이나 협업 가능 인원으로 확인된 것은 아닙니다.':brief);
  }
  function notice(person,options={}){
    return '<p class="scope-note'+(options.variant==='detail'?'':' person-notice')+'">'+html(noticeText(person,options))+'</p>'+(options.historical&&options.scopeNote?'<p class="scope-note">'+html(options.scopeNote)+'</p>':'');
  }
  function introLinks(profile){
    const links=rows(profile?.links).filter(l=>typeof l.url==='string'&&/^https:\/\//i.test(l.url)&&safeUrl(l.url));
    return links.length?'<p class="researcher-intro-links"><span>본인이 소개하는 자료</span> '+links.map(l=>'<a class="researcher-intro-link" href="'+html(l.url)+'" target="_blank" rel="noopener noreferrer">'+html(l.label||'소개 페이지')+' ↗</a>').join(' · ')+'</p>':'';
  }
  // A saved project, paper or patent name heads its line; curated lines without a title stay as they were.
  function timelineTitle(t,text){const title=typeof t?.title==='string'?t.title.trim():'';return title&&!String(text).includes(title)?'<b class="timeline-title">'+html(title)+'</b> ':'';}
  function careerRecord(row,evidence,timeline){
    if(row.record_id)return evidence.find(e=>e.id===row.record_id)||null;
    const dated=timeline.filter(t=>row.date&&t.date===row.date),records=evidence.filter(e=>e.kind==='career_record'&&row.date&&e.date===row.date);
    return dated.length===1&&records.length===1?records[0]:null;
  }
  // Keep the original detailed-card order. Fixed IDs identify editor blocks, never visual headings.
  function sections(person,options={}){
    const p=person?.profile||{},result=[],editable=options.editable===true,nobel=isLaureate(p),personal=isPersonalIllustration(p);
    if(!p.curated&&!editable)return [];
    const evidence=rows(options.evidence??person?.evidence),timeline=rows(p.timeline);
    const add=(id,content)=>{if(content)result.push({id,html:content});};
    if(options.includeIdentity!==false)add('identity',nameBlock(person,options.heading||'h2',options.nameClass||(nobel?'laureate-name':personal?'personal-name':'researcher-name'),options));
    if(options.includePortrait!==false||options.portraitMetadata)add('portrait',(options.includePortrait!==false?'<div class="researcher-detail-hero holo-card'+(nobel?' laureate-card':'')+'" data-tilt'+laureateAttributes(p)+'>'+portrait(p,displayName(person))+'</div>':'')+awardSummary(p)+(personal?personalPortraitNote(p,true):portraitSources(p)));
    add('bio','<p class="researcher-bio">'+html(p.biography)+'</p>');
    add('links',introLinks(p));
    if(options.includeSkills!==false)add('skills','<div class="researcher-skills">'+strings(p.skills).map(x=>'<span>'+html(x)+'</span>').join('')+'</div>');
    if(!personal)add('portraitNote','<p class="scope-note">'+html(p.portrait_note||(p.portrait?.generated?'AI 생성 초상 일러스트':p.portrait?.path?'출처에 표시된 프로필 사진':'사진 미제공 · 공개 프로필과 논문 기록을 확인해 주세요.'))+'</p>');
    add('careers',timeline.length?'<h3>이력의 발자취</h3><ol class="researcher-timeline">'+timeline.map(t=>{
      const e=careerRecord(t,evidence,timeline),text=t.text||(e?evidenceDescription(e,p):'');
      return '<li><span>'+html(t.date)+'</span><div>'+timelineTitle(t,text)+html(text)+' '+sourceLink(t.url,'출처')+sourceEvidence(t)+'</div></li>';
    }).join('')+'</ol>':editable?'<h3>이력의 발자취</h3><p class="card-empty">＋ 이력 추가</p>':'');
    for(const [key,title] of [['projects','프로젝트 이력'],['education','교육 이력']]){
      const entries=rows(p[key]);add(key,p[key]?'<h3>'+title+'</h3><ol class="researcher-timeline">'+entries.map(x=>{
        const id=x.record_id||x.id,e=key==='projects'&&id?evidence.find(r=>r.id===id)||null:null,text=x.text||(e?evidenceDescription(e,p):'');
        return '<li><span>'+html(x.date)+'</span><div><strong>'+html(x.title)+'</strong><p>'+html(text)+'</p></div></li>';
      }).join('')+'</ol>':'');
    }
    add('skillGroups',p.skill_groups?'<h3>다룰 수 있는 일</h3>'+rows(p.skill_groups).map(g=>'<h4>'+html(g.name)+'</h4><p>'+strings(g.items).map(html).join(' · ')+'</p>').join(''):'');
    add('interests',p.interests?'<h3>관심 분야</h3><ul>'+strings(p.interests).map(x=>'<li>'+html(x)+'</li>').join('')+'</ul>':editable?'<h3>관심 분야</h3><p class="card-empty">＋ 관심 분야 추가</p>':'');
    const provenanceLabels={name:'표시 이름',organization:'소속',department:'부서',role:'현재 직위·역할',aliases:'영문 이름·별칭',tagline:'한 줄 소개',bio:'약력',skills:'대표 기술',interests:'관심 분야'};
    add('sources','<div class="researcher-sources">'+rows(p.sources).map(x=>sourceLink(x.url,x.title)).join(' · ')+Object.entries(p.provenance||{}).filter(([key])=>provenanceLabels[key]).map(([key,value])=>'<div><span>'+provenanceLabels[key]+'</span>'+sourceEvidence(value)+'</div>').join('')+'</div>');
    if(options.includeNotice!==false)add('notice',notice(person,{...options,variant:'detail'}));
    if(options.includeEvidence===true)add('evidence',evidenceContext(person,options)+evidence.map(e=>detailEvidence(e,{...options,personId:person.id,label:options.labels?.get(e.id)||''})).join(''));
    return result;
  }
  // The map sheet shares fragments, while keeping its compact reading order and folded details.
  function sheetSections(person,options={}){
    const p=person?.profile||{},result=[],editable=options.editable===true,evidence=rows(options.evidence??person?.evidence),labels=options.labels||new Map();
    const groups=rows(p.skill_groups).filter(g=>strings(g.items).length),topics=skillValues(person),timeline=rows(p.timeline).filter(t=>typeof t.text==='string');
    const chips=list=>list.map(s=>'<span>'+html(s)+'</span>').join('');
    const add=(id,content)=>{if(content)result.push({id,html:content});};
    add('bio',p.biography?'<section class="sheet-sec"><h3>소개</h3><p>'+html(p.biography)+'</p></section>':editable?'<section class="sheet-sec"><h3>소개</h3><p class="card-empty">아직 적은 소개가 없어요.</p></section>':'');
    add('skills',groups.length?'<section class="sheet-sec"><h3>기술</h3>'+groups.map(g=>'<p class="sheet-group">'+html(g.name||'')+'</p><div class="sheet-chips">'+chips(strings(g.items))+'</div>').join('')+'</section>':
      topics.length>4?'<section class="sheet-sec"><h3>기술·주제</h3><div class="sheet-chips">'+chips(topics)+'</div></section>':editable?'<section class="sheet-sec"><h3>기술</h3>'+(topics.length?'<div class="sheet-chips">'+chips(topics)+'</div>':'<p class="card-empty">아직 적은 기술이 없어요.</p>')+'</section>':'');
    add('evidence','<section class="sheet-sec"><h3>'+countLabel(evidence.length,options.partial||options.historical)+'</h3>'+evidence.map(e=>'<button type="button" class="sheet-row'+(labels.has(e.id)?' found-record':'')+'" data-action="record" data-id="'+html(e.id)+'"'+(options.recordAction===false||e.in_current_pool===false?' disabled':'')+'>'+(labels.has(e.id)?'<span class="found-label">'+html(labels.get(e.id))+'</span>':'')+'<strong>'+html(e.title)+'</strong><small>'+html([e.date,e.evidence_label||evidenceKind(e)].filter(Boolean).join(' · '))+' ›</small></button>').join('')+'</section>');
    add('careers',timeline.length?'<section class="sheet-sec"><h3>이력</h3>'+timeline.map(t=>{
      const record=careerRecord(t,evidence,timeline),text=t.text||(record?evidenceDescription(record,p):'');
      return '<div class="sheet-row"'+(record?' data-record-id="'+html(record.id)+'"':'')+'><span class="sheet-clamp">'+timelineTitle(t,text)+html(text)+'</span><small>'+html(t.date||'')+'</small>'+sourceEvidence(t)+'</div>';
    }).join('')+'</section>':editable?'<section class="sheet-sec"><h3>이력</h3><p class="card-empty">＋ 이력 추가</p></section>':'');
    // The folded area keeps unique provenance and record metadata, without repeating the profile card.
    const children=sections(person,{...options,evidence,includeIdentity:false,includePortrait:false,portraitMetadata:true,includeSkills:false,includeEvidence:false})
      .filter(section=>!['bio','careers','skillGroups'].includes(section.id));
    if(!children.some(section=>section.id==='notice'))children.push({id:'notice',html:notice(person,{...options,variant:'detail'})});
    children.push({id:'recordDetails',html:evidence.map(e=>detailEvidence(e,{personId:person?.id,label:labels.get(e.id),recordAction:options.recordAction,personLinks:options.personLinks})).join('')});
    const summary='출처와 근거 설명 전체 보기',extra=children.map(section=>'<section class="person-section" data-person-section="'+section.id+'">'+section.html+'</section>').join('');
    result.push({id:'provenance',summary,children,html:'<details class="sheet-more"><summary>'+summary+'</summary>'+extra+'</details>'});
    return result;
  }

  function render(person,options={}){return sections(person,options).map(s=>s.html).join('');}
  // One delegated binding survives full-card replacement and the editor's rerender.
  const bound=new WeakSet();
  function bind(rootNode){
    if(!rootNode?.addEventListener||bound.has(rootNode))return;
    bound.add(rootNode);rootNode.addEventListener('click',event=>{
      const button=event.target?.closest?.('[data-chips-more]');if(!button||!rootNode.contains(button))return;
      const rest=button.parentElement?.querySelector('.sheet-chips-rest');if(!rest)return;
      rest.hidden=false;button.setAttribute('aria-expanded','true');button.remove();
    });
  }
  const api={displayName,nameBlock,portrait,capability,skillValues,skills,evidenceDescription,evidenceKind,evidenceRow,evidenceSection,evidenceStats,evidenceContext,countLabel,noticeText,notice,detailEvidence,projectParticipantsHtml,evidenceDatesHtml,sections,sheetSections,render,bind,
    isLaureate,isPersonalIllustration,personalPortraitNote,awardSummary,effectControls,laureateAttributes};
  root.RndPersonView=api;
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(typeof window!=='undefined'?window:globalThis);
