"""2차 팩: 실제 조각 HTML의 순서·밀도·접힘 계약. 브라우저/픽셀 검증과 별개."""
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRELUDE = r"""
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
global.window=global;
global.RndPersonView=require('./rndplz/web/person-view.js');
const P=RndPersonView;
const read=name=>fs.readFileSync('rndplz/web/'+name+'.js','utf8');
function take(file,name){
 const source=read(file),start=source.search(new RegExp('^(?:async )?function '+name+'\\(','m'));
 assert(start>=0,name);
 const tail=source.slice(start),end=tail.slice(1).search(/^(?:async )?function /m);
 return end<0?tail:tail.slice(0,end+1);
}
function install(file,names){for(const name of names)vm.runInThisContext(take(file,name));}
global.esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
global.safeUrl=s=>{try{return ['http:','https:'].includes(new URL(s).protocol);}catch{return false;}};
function ordered(markup,parts){let at=-1;for(const part of parts){const next=markup.indexOf(part,at+1);assert(next>at,part);at=next;}}
function element(){
 const listeners=new Map();return {dataset:{},innerHTML:'',scrollTop:0,style:{},
 classList:{toggle(){},add(){},remove(){}},setAttribute(){},contains(){return true;},querySelectorAll(){return [];},
 addEventListener(type,fn){if(!listeners.has(type))listeners.set(type,[]);listeners.get(type).push(fn);},
 emit(type,event={}){for(const fn of listeners.get(type)||[])fn(event);},clearListeners(){listeners.clear();}};
}
"""


def run_js(script):
    result=subprocess.run(['node','-'],input=PRELUDE+script,text=True,encoding='utf-8',cwd=ROOT,capture_output=True)
    assert result.returncode == 0, result.stderr


def test_inspect_evidence_keeps_original_closed_row_and_kind_label():
    run_js(r"""
install('chat',['evidenceDescription','inspectEvidenceHtml']);
const evidence={id:'N',title:'공개 연구 제목',scope:'공개 연구 사례',evidence_label:'종류 미확인',date:'2008',url:'https://example.org/source'};
const markup=inspectEvidenceHtml(evidence,{});
assert.equal(markup,'<details><summary><strong>공개 연구 제목</strong><span>공개 연구 사례 · 2008</span></summary><a href="https://example.org/source" target="_blank" rel="noopener noreferrer">원문 출처 ↗</a></details>');
assert(!/<details[^>]*\bopen\b/.test(markup));
assert(!markup.includes('종류 미확인'));
const described=inspectEvidenceHtml({...evidence,kind:'career_record',id:'C'},
 {timeline:[{record_id:'C',date:'2008',text:'정확한 기록의 설명'}]});
assert(described.includes('<p>정확한 기록의 설명</p>'));
assert(!/<details[^>]*\bopen\b/.test(described));
assert(!inspectEvidenceHtml({...evidence,url:'javascript:alert(1)'},{}).includes('<details'));
""")


def test_home_summary_restores_name_org_capability_closed_evidence_and_short_footer():
    run_js(r"""
install('chat',['plainScience','evidenceDescription','inspectEvidenceHtml','inspectFullHtml','renderInspect']);
const dialog=element(),host=element(),sheet=element(),card=element(),full=element(),body=element();
host.querySelector=()=>sheet;
sheet.querySelector=s=>({'.pi-card':card,'.pi-full':full,'.pi-body':body}[s]);
global.$=id=>({personCardDialog:dialog,personCardHost:host}[id]);
global.inspectTicket=0;global.registeredEpoch=0;global.session=null;global.drawController=null;
global.RndCraft={quiet:()=>true};global.cardPortrait=()=>'';global.cardCapability=p=>P.capability(p);
global.candidatePurposeRelation=()=>'';global.candidatePurposeLabel=()=>'';
global.pickAvailable=()=>false;global.historicalProfile=()=>false;global.currentDetailCandidate=()=>null;global.canPropose=()=>false;
const person={id:'N',name:'Recorded Name',org:'간단한 소속',profile:{display_name:'표시 이름',curated:true,
 tagline:'표면 반응·촉매',current_role:'요약에 나오면 안 되는 긴 소속 원문',biography:'요약에 나오면 안 되는 소개',
 profile_note:'요약에 나오면 안 되는 긴 고지'},evidence:[{id:'E',title:'연구 기록',scope:'공개 연구 사례',date:'2008',url:'https://example.org/source'}]};
global.inspectPerson=async()=>person;
(async()=>{
 await renderInspect('N');
 const markup=host.innerHTML;
 ordered(markup,['class="pi-hero"','class="pi-facts"','표시 이름','간단한 소속','표면 반응·촉매','class="pi-body"','전체 등록 이력 1건','눌러서 펼치기','<details>','class="pi-actions"','등록 이력은 본인 제공·공개 기록이에요.','전체 약력 보기']);
 for(const extra of ['Recorded Name',person.profile.current_role,person.profile.biography,person.profile.profile_note,'person-section','researcher-korean','laureate-role'])assert(!markup.includes(extra),extra);
 assert(!/<details[^>]*\bopen\b/.test(markup));
 assert.equal((markup.match(/등록 이력은 본인 제공·공개 기록이에요\./g)||[]).length,1);
})().catch(e=>{console.error(e);process.exitCode=1;});
""")


def test_full_inspect_keeps_original_section_order_and_dense_markup():
    run_js(r"""
install('chat',['plainScience','evidenceDescription','inspectEvidenceHtml','inspectFullHtml']);
const person={profile:{biography:'소개 설명',links:[{label:'소개 링크',url:'https://example.org/about'}],
 skills:['기술 A','기술 B'],timeline:[{record_id:'C',date:'2024',text:'경력 설명'}],
 projects:[{record_id:'R',date:'2025',title:'프로젝트 제목',text:'프로젝트 설명'}]},evidence:[
 {id:'C',kind:'career_record',title:'경력 제목',date:'2024',scope:'본인 제공 경력'},
 {id:'R',kind:'project_record',title:'프로젝트 제목',date:'2025',scope:'사용자 제공 프로젝트 이력'}]};
const markup=inspectFullHtml(person,person.profile);
assert.deepEqual([...markup.matchAll(/<h3>([^<]+)/g)].map(m=>m[1].trim()),['소개','기술','경력','프로젝트','전체 등록 이력 2건']);
ordered(markup,['class="pi-links"','class="pi-skills"','class="pi-row"','경력 설명','프로젝트 설명','전체 등록 이력 2건']);
assert(!markup.includes('person-section'));assert(!markup.includes('researcher-timeline'));assert(!markup.includes('portrait-art'));
assert(!/<details[^>]*\bopen\b/.test(markup));
""")


def test_side_record_details_restore_tags_dates_sources_and_participant_links():
    run_js(r"""
install('app',['evidenceHtml']);
const evidence={id:'R',title:'프로젝트 기록',kind:'project_record',evidence_label:'제공 프로젝트 이력',
 scope:'사용자 제공 프로젝트 이력',role:'기록상 담당',date:'2026-09',checked_at:'2026-09-23',
 access:'사용자 제공 참여 정보',classification_basis:['사용자 제공 참여 정보'],boundary:'독립 검증을 하지 않은 기록입니다.',
 url:'https://example.org/record',project_participants:[{id:'SELF',display_name:'현재 인물'},{id:'P1',display_name:'함께한 인물 하나'},{id:'P2',display_name:'함께한 인물 둘'}]};
const markup=evidenceHtml(evidence,'SELF','찾은 조건');
ordered(markup,['class="detail-block found-record"','class="found-label"','class="record-link"','class="tags"','제공 프로젝트 이력','사용자 제공 프로젝트 이력','기록상 담당','<dl>','기록 날짜·기간','자료 확인일','확인한 자료','기록 종류 근거','class="detail-note"','원본 출처 열기','class="project-participants"','함께한 사람 · 사용자 제공 참여 정보','현재 인물 · 현재 인물','data-action="person" data-id="P1"','data-action="person" data-id="P2"']);
assert(!markup.includes('person-evidence'));assert(!markup.includes('기록 보기 ›'));assert(!markup.includes('<details'));
assert(!evidenceHtml({...evidence,in_current_pool:false},'SELF').includes('data-action="person"'));
""")


def test_participant_links_escape_ids_preserve_current_person_and_hide_unavailable_records():
    run_js(r"""
const evidence={id:'R',kind:'project_record',title:'프로젝트 기록',project_participants:[
 {id:'SELF',display_name:'현재 인물'},{id:'P/&?\"><',display_name:'동료 <script>'},
 {id:'P/&?\"><',display_name:'중복 참여자'},{id:' ',display_name:'빈 식별자'},null]};
const markup=P.detailEvidence(evidence,{personId:'SELF',personLinks:true,recordAction:false});
assert(markup.includes('<span>현재 인물 · 현재 인물</span>'));
assert(markup.includes('href="/explore?person=P%2F%26%3F%22%3E%3C" target="_blank" rel="noopener noreferrer"'));
assert(markup.includes('동료 &lt;script&gt;'));
assert(!markup.includes('<script>'));assert(!markup.includes('data-action="person"'));
assert(!markup.includes('중복 참여자'));assert(!markup.includes('빈 식별자'));
assert.equal((markup.match(/href="\/explore\?person=/g)||[]).length,1);
assert(!P.detailEvidence({...evidence,in_current_pool:false},{personId:'SELF',personLinks:true}).includes('project-participants'));
assert(!P.detailEvidence({...evidence,kind:'career_record'},{personId:'SELF',personLinks:true}).includes('project-participants'));
""")


def test_desktop_side_card_keeps_original_profile_context_and_record_order():
    run_js(r"""
install('app',['evidenceHtml','showPerson']);
const person={id:'P',name:'합성 인물',org:'합성 조직',profile:{curated:true,biography:'소개 문장',portrait_note:'사진 안내',
 skills:['기술1','기술2','기술3','기술4','기술5'],links:[{label:'소개 링크',url:'https://example.org/about'}],
 timeline:[{record_id:'C',date:'2024',text:'경력 설명'}],projects:[{record_id:'R',title:'과제 제목',date:'2025',text:'과제 설명'}],
 education:[{title:'교육 제목',date:'2023',text:'교육 설명'}],skill_groups:[{name:'기술 묶음',items:['묶음 항목']}],interests:['관심 항목'],
 sources:[{title:'프로필 출처',url:'https://example.org/profile'}],profile_note:'프로필 범위 고지'},evidence:[
 {id:'C',title:'경력 기록 제목',kind:'career_record',date:'2024',evidence_label:'제공된 직무 경력',scope:'본인 제공 경력',role:'기록상 담당'},
 {id:'R',title:'과제 기록 제목',kind:'project_record',date:'2025',evidence_label:'제공 프로젝트 이력',scope:'사용자 제공 프로젝트 이력',role:'기록상 담당',project_participants:[{id:'OTHER',display_name:'동료 인물'}]}]};
const ids=P.sections(person).map(section=>section.id);
assert.deepEqual(ids,['identity','portrait','bio','links','skills','portraitNote','careers','projects','education','skillGroups','interests','sources','notice']);
const profile=P.render(person);assert(!profile.includes('person-section'));assert(!profile.includes('data-chips-more'));
assert.equal(P.render({...person,profile:{}}),'');
const host=element(),dialog=element();global.$=id=>id==='detailContent'?host:dialog;
global.session=null;global.displayResult=()=>null;global.foundLabels=()=>new Map();global.markFound=()=>{};global.showDialog=()=>{};
global.detailRequestAction=()=>'';global.RndCraft={profileDetails:p=>P.render(p)};
showPerson(person,false,null,true,null);
const markup=host.innerHTML;assert(markup.startsWith(profile));
ordered(markup,['class="researcher-name"','class="researcher-detail-hero','class="researcher-bio"','class="researcher-intro-links"','class="researcher-skills"','사진 안내','이력의 발자취','프로젝트 이력','교육 이력','다룰 수 있는 일','관심 분야','class="researcher-sources"','프로필 범위 고지','class="selected-holo" hidden','이 기록과 연결되어 있어요.','전체 등록 이력 2건','경력 기록 제목','과제 기록 제목','함께한 사람','data-action="person" data-id="OTHER"']);
assert.equal((markup.match(/<dl>/g)||[]).length,2);assert(!markup.includes('person-evidence'));assert(!markup.includes('기록 보기 ›'));
""")


def test_shared_chip_binding_handles_button_edge_descendants_once_after_replacement():
    run_js(r"""
const root=element(),rest={hidden:true},button={hidden:false,attributes:{},parentElement:{querySelector:()=>rest},
 setAttribute(name,value){this.attributes[name]=value;},remove(){this.removed=true;}};
let selector='';const edge={closest(value){selector=value;return button;}};
P.bind(root);P.bind(root);root.emit('click',{target:edge});
assert.equal(selector,'[data-chips-more]');assert.equal(rest.hidden,false);assert.equal(button.removed,true);assert.equal(button.attributes['aria-expanded'],'true');
// The event target may belong to a newly rendered chip button, without rebinding the container.
const replacedRest={hidden:true},replacedButton={...button,removed:false,attributes:{},parentElement:{querySelector:()=>replacedRest}};
root.emit('click',{target:{closest:()=>replacedButton}});assert.equal(replacedRest.hidden,false);assert.equal(replacedButton.removed,true);
root.contains=()=>false;rest.hidden=true;root.emit('click',{target:edge});assert.equal(rest.hidden,true);
""")


def test_chip_hit_ring_and_active_transform_preserve_edge_click_contract():
    css=(ROOT/'rndplz/web/person-view.css').read_text(encoding='utf-8')
    # The invisible ring, not the painted chip, is what the R10 edge-click addresses.
    ring=re.search(r'[^{}]*\.sheet-chip-more::after\s*\{([^}]+)\}',css)
    assert ring and 'position:absolute' in re.sub(r'\s+','',ring.group(1))
    assert re.search(r'inset\s*:\s*-8px\s+-4px',ring.group(1))
    active=re.search(r'[^{}]*\.sheet-chip-more:active[^{}]*\{([^}]+)\}',css)
    assert active and re.search(r'transform\s*:\s*none',active.group(1))

