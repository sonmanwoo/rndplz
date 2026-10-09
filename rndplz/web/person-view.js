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
    const org=typeof person?.org==='string'?person.org:p.org||'';
    const orgTag=sheet?'span':'p',orgClass=sheet?'':options.orgClass||(className==='pi-facts'?'pi-org':'candidate-org');
    return '<div class="'+html(className)+'"><'+tag+headingAttrs+'>'+html(name)+'</'+tag+'>'+
      (original&&original!==name?'<span class="researcher-korean">'+html(original)+'</span>':'')+
      (org?'<'+orgTag+(orgClass?' class="'+html(orgClass)+'"':'')+'>'+html(org)+'</'+orgTag+'>':'')+
      (p.current_role?'<p class="laureate-role">'+html(p.current_role)+(p.affiliation_as_of?' · 공개 프로필 확인 '+html(p.affiliation_as_of):'')+'</p>':'')+
      (sheet?'<em>'+html(capability(person))+'</em>':'')+
      (sheet&&strings(options.tags).length?'<span class="sheet-tags">'+strings(options.tags).map(t=>'<b>'+html(t)+'</b>').join('')+'</span>':'')+'</div>';
  }
  function portrait(profile,name,options={}){
    if(!options.variant||options.variant==='detail')return detailPortrait(profile||{},name||'이름 미확인');
    let path=displayPath(profile?.portrait?.path);
    if(options.variant==='thumb')path=path.replace(/-detail\.webp$/i,'-thumb.webp');
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
    const values=skillValues(person),limit=options.limit===null?values.length:Math.max(0,Number.isInteger(options.limit)?options.limit:4);
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
  function evidenceRow(e,profile,options={}){
    const title=html(e.title||e.id||'연결 근거'),meta=[e.scope_label||e.evidence_label||e.scope,e.date].filter(Boolean).map(html).join(' · ');
    const fullText=evidenceDescription(e,profile),text=options.described?.get(e.id)?.has(compact(fullText))?'':fullText;
    const label=options.label?'<span class="found-label">'+html(options.label)+'</span>':'';
    const heading=label+'<strong>'+title+'</strong>'+(meta?'<span>'+meta+'</span>':'');
    const source=(safeUrl(e.url)?sourceLink(e.url,'원문 출처'):'')+rows(e.metadata_sources).filter(s=>safeUrl(s.url)).map(s=>'<p>'+sourceLink(s.url,s.title||s.label||(/correction/i.test(s.basis||s.type||'')?'정정 출처':'추가 확인 출처'))+'</p>').join('');
    const boundary=options.showBoundary!==false&&e.boundary&&e.boundary!==profile?.profile_note?'<p class="detail-note">'+html(e.boundary)+'</p>':'';
    const action=recordLink(e,options),cls='person-evidence'+(options.label?' found-record':'');
    return text?'<details class="'+cls+'"><summary>'+heading+'</summary><p>'+html(plainScience(text))+'</p>'+boundary+source+action+'</details>':
      '<div class="pi-evidence-plain '+cls+'">'+heading+source+action+'</div>';
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
  function notice(person,options={}){
    const p=person?.profile||{};
    if(options.historical)return '<p class="scope-note person-notice">이전 응답 당시 선택 근거이며 현재 전체 등록 이력이 아닙니다.</p>'+(options.scopeNote?'<p class="scope-note">'+html(options.scopeNote)+'</p>':'');
    return '<p class="scope-note person-notice">'+html(person?.virtual?'시연용 가상 인물과 기록입니다. 실제 인물·사업장·승인 절차가 아닙니다.':p.profile_note||'등록 이력은 본인 제공·공개 기록이에요. 지금의 역량이나 협업 가능 여부를 확인한 것은 아니에요.')+'</p>';
  }
  function introLinks(profile){
    const links=rows(profile?.links).filter(l=>typeof l.url==='string'&&/^https:\/\//i.test(l.url)&&safeUrl(l.url));
    return links.length?'<p class="researcher-intro-links"><span>본인이 소개하는 자료</span> '+links.map(l=>'<a class="researcher-intro-link" href="'+html(l.url)+'" target="_blank" rel="noopener noreferrer">'+html(l.label||'소개 페이지')+' ↗</a>').join(' · ')+'</p>':'';
  }
  function careerRecord(row,evidence,timeline){
    if(row.record_id)return evidence.find(e=>e.id===row.record_id)||null;
    const dated=timeline.filter(t=>row.date&&t.date===row.date),records=evidence.filter(e=>e.kind==='career_record'&&row.date&&e.date===row.date);
    return dated.length===1&&records.length===1?records[0]:null;
  }
  function sections(person,options={}){
    const p=person?.profile||{},result=[],editable=options.editable===true,nobel=isLaureate(p),personal=isPersonalIllustration(p);
    const evidence=rows(options.evidence??person?.evidence),timeline=rows(p.timeline),described=new Map();
    const add=(id,content,empty=false)=>{if(content||empty)result.push({id,html:content});};
    const remember=(id,text)=>{if(id&&compact(text)){if(!described.has(id))described.set(id,new Set());described.get(id).add(compact(text));}};
    if(options.includeIdentity!==false)add('identity',nameBlock(person,options.heading||'h2',options.nameClass||(nobel?'laureate-name':personal?'personal-name':'researcher-name'),options)+'<p class="researcher-capability">'+html(capability(person))+'</p>');
    if(options.includePortrait!==false||options.portraitMetadata)add('portrait',(options.includePortrait!==false?'<div class="researcher-detail-hero holo-card'+(nobel?' laureate-card':'')+'" data-tilt'+laureateAttributes(p)+'>'+portrait(p,displayName(person))+'</div>':'')+awardSummary(p)+(personal?personalPortraitNote(p,true):portraitSources(p)+(p.portrait_note?'<p class="scope-note">'+html(p.portrait_note)+'</p>':'')));
    add('bio',p.biography?'<p class="researcher-bio">'+html(p.biography)+'</p>':editable?'<p class="researcher-bio card-empty">아직 적은 소개가 없어요.</p>':'');
    add('links',introLinks(p)||(editable?'<p class="researcher-intro-links card-empty">아직 연결한 소개 자료가 없어요.</p>':''));
    if(options.includeSkills!==false)add('skills',skills(person,{limit:options.skillsLimit===undefined?4:options.skillsLimit,className:'researcher-skills'})||(editable?'<div class="researcher-skills"><p class="card-empty">아직 적은 기술이 없어요.</p></div>':''));
    add('careers',timeline.length?'<h3>이력의 발자취</h3><ol class="researcher-timeline">'+timeline.map(t=>{
      const e=careerRecord(t,evidence,timeline),text=t.text||(e?evidenceDescription(e,p):'');remember(e?.id,text);
      return '<li><span>'+html(t.date)+'</span><div>'+html(text)+' '+sourceLink(t.url,'출처')+recordLink(e,options)+'</div></li>';
    }).join('')+'</ol>':editable?'<h3>이력의 발자취</h3><p class="card-empty">＋ 이력 추가</p>':'');
    for(const [key,title] of [['projects','프로젝트 이력'],['education','교육 이력']]){
      const entries=rows(p[key]);add(key,entries.length?'<h3>'+title+'</h3><ol class="researcher-timeline">'+entries.map(x=>{
        const id=x.record_id||x.id,e=key==='projects'&&id?evidence.find(r=>r.id===id)||null:null,text=x.text||(e?evidenceDescription(e,p):'');remember(e?.id,text);
        return '<li><span>'+html(x.date)+'</span><div><strong>'+html(x.title)+'</strong><p>'+html(text)+'</p>'+sourceLink(x.url,'출처')+recordLink(e,options)+'</div></li>';
      }).join('')+'</ol>':'');
    }
    const groups=rows(p.skill_groups).filter(g=>strings(g.items).length);
    add('skillGroups',groups.length?'<h3>다룰 수 있는 일</h3>'+groups.map(g=>'<h4>'+html(g.name)+'</h4><p>'+strings(g.items).map(html).join(' · ')+'</p>').join(''):'');
    add('interests',strings(p.interests).length?'<h3>관심 분야</h3><ul>'+strings(p.interests).map(x=>'<li>'+html(x)+'</li>').join('')+'</ul>':editable?'<h3>관심 분야</h3><p class="card-empty">＋ 관심 분야 추가</p>':'');
    const sources=rows(p.sources);add('sources',sources.length?'<div class="researcher-sources">'+sources.map(x=>sourceLink(x.url,x.title)).join(' · ')+'</div>':'');
    if(options.includeNotice!==false)add('notice',notice(person,options));
    if(options.includeEvidence!==false)add('evidence',evidenceSection(evidence,p,{...options,limit:options.evidenceLimit,described}));
    return result;
  }
  function render(person,options={}){return sections(person,options).map(s=>'<section class="person-section" data-person-section="'+s.id+'">'+s.html+'</section>').join('');}
  // One delegated binding survives full-card replacement and the editor's rerender.
  const bound=new WeakSet();
  function bind(rootNode){
    if(!rootNode?.addEventListener||bound.has(rootNode))return;
    bound.add(rootNode);rootNode.addEventListener('click',event=>{
      const button=event.target?.closest?.('[data-chips-more]');if(!button||!rootNode.contains(button))return;
      const rest=button.parentElement?.querySelector('.sheet-chips-rest');if(!rest)return;
      rest.hidden=false;button.setAttribute('aria-expanded','true');button.hidden=true;
    });
  }
  const api={displayName,nameBlock,portrait,capability,skillValues,skills,evidenceDescription,evidenceRow,evidenceSection,evidenceStats,countLabel,notice,sections,render,bind,
    isLaureate,isPersonalIllustration,personalPortraitNote,awardSummary,effectControls,laureateAttributes};
  root.RndPersonView=api;
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(typeof window!=='undefined'?window:globalThis);
