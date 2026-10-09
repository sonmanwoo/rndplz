"""인물 보기 B: 실제 JS 함수의 합성 상태 회귀 검사(브라우저 배치 검증과 별개)."""
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PRELUDE = r"""
const assert = require('node:assert/strict'), fs = require('node:fs'), vm = require('node:vm');
function read(name) { return fs.readFileSync('rndplz/web/' + name + '.js', 'utf8'); }
function take(file, name) {
  const source = read(file), start = source.search(new RegExp('^(?:async )?function ' + name + '\\(', 'm'));
  assert(start >= 0, name);
  return source.slice(start, source.indexOf('\n}', start) + 2);
}
function install(file, names) { for (const name of names) vm.runInThisContext(take(file, name)); }
global.esc = s => String(s ?? '').replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('"', '&quot;');
global.safeUrl = () => false;
function element() {
  const listeners = new Map();
  return {style:{}, dataset:{}, innerHTML:'', scrollTop:0, open:true, isConnected:true,
    classList:{toggle(){},add(){},remove(){}}, setAttribute(){}, focus(){}, clearListeners(){listeners.clear();},
    addEventListener(type, fn){if(!listeners.has(type))listeners.set(type,new Set());listeners.get(type).add(fn);},
    removeEventListener(type, fn){listeners.get(type)?.delete(fn);},
    emit(type, event={}){for(const fn of [...(listeners.get(type)||[])])fn(event);},
    close(){this.open=false;this.emit('close');}, getBoundingClientRect(){return {height:600};},
    setPointerCapture(id){this.capture=id;}, hasPointerCapture(id){return this.capture===id;},
    releasePointerCapture(){this.capture=null;}, querySelectorAll(){return [];}
  };
}
"""


def run_js(script):
    result = subprocess.run(['node', '-'], input=PRELUDE + script, text=True,
                            encoding='utf-8', cwd=ROOT, capture_output=True)
    assert result.returncode == 0, result.stderr


def test_career_description_uses_id_and_refuses_ambiguous_legacy_dates():
    run_js(r"""
install('chat', ['evidenceDescription']);
const evidence = {id:'B', kind:'career_record', date:'2026'};
assert.equal(evidenceDescription(evidence,{timeline:[
  {record_id:'A',date:'2026',text:'첫 경력'}, {record_id:'B',date:'2025',text:'둘째 경력'}
]}),'둘째 경력');
assert.equal(evidenceDescription(evidence,{timeline:[{date:'2026',text:'하나'}]}),'하나');
assert.equal(evidenceDescription(evidence,{timeline:[{date:'2026',text:'하나'},{date:'2026',text:'둘'}]}),'');
assert.equal(evidenceDescription(evidence,{timeline:[{record_id:'A',date:'2026',text:'다른 기록'}]}),'');
assert.equal(evidenceDescription({...evidence, date:''},{timeline:[{date:'',text:'미상'}]}),'');
assert.equal(evidenceDescription({...evidence,excerpt:'직접 설명'},{timeline:[]}),'직접 설명');
""")


def test_map_counts_distinguish_total_and_intersected_condition():
    run_js(r"""
install('app', ['personEvidenceStats']);
const person={evidence:[{id:'a'},{id:'b'},{id:'c'}],record_count:99,works_count:999};
assert.equal(personEvidenceStats(person,{hasCondition:false,recordIds:['a','b','c']}),'전체 등록 이력 3건');
assert.equal(personEvidenceStats(person,{hasCondition:true,recordIds:['b','b','missing']}),
  '전체 등록 이력 3건 · 이번 조건에 연결된 근거 1건');
assert.equal(personEvidenceStats(person,{hasCondition:true,recordIds:[]}),
  '전체 등록 이력 3건 · 이번 조건에 연결된 근거 0건');
assert.equal(personEvidenceStats(person,null,{evidence:[{id:'b'}]}),
  '전체 등록 이력 3건 · 이번 조건에 연결된 근거 1건');
""")


def test_inspect_registered_context_counts_full_view_and_frozen_history():
    run_js(r"""
install('chat', ['plainScience','evidenceDescription','inspectEvidenceHtml','inspectFullHtml',
  'registeredContextHtml','registeredRequestAction','renderInspect']);
const dialog=element(), host=element(), sheet=element(), card=element(), full=element(), body=element();
host.querySelector=()=>sheet;
let markup="";Object.defineProperty(host,"innerHTML",{get(){return markup;},set(value){markup=value;full.clearListeners();}});
sheet.querySelector=s=>({'.pi-card':card,'.pi-full':full,'.pi-body':body}[s]);
global.$=id=>({personCardDialog:dialog,personCardHost:host}[id]);
global.inspectTicket=0; global.registeredEpoch=1; global.drawController=null;
global.RndCraft={quiet:()=>true}; global.cardPortrait=()=>''; global.cardCapability=()=>'';
global.candidatePurposeRelation=()=>''; global.candidatePurposeLabel=()=>'';
global.pickAvailable=()=>false; global.historicalProfile=()=>false;
global.currentDetailCandidate=()=>null; global.canPropose=()=>false;
global.extraRecordSources=()=>'';
let person={id:'P',name:'합성 인물',profile:{},evidence:Array.from({length:7},(_,i)=>({id:String(i),title:'이력 '+i}))};
let candidate={id:'P',name:'합성 인물',reason:'연결 이유',purpose_missing:'목적 확인',
  unverified_conditions:['미확인 조건'],evidence:person.evidence.slice(0,2),can_review_draft:true};
global.session={id:'S',result:{candidates:[candidate]}};
global.registeredBinding=()=> 'v1'; global.currentRegisteredCandidate=()=>candidate;
global.inspectPerson=async(id,historical)=>historical?null:person;
(async()=>{
  dialog.dataset.registeredReview='true';dialog.inspectIds=['P'];
  assert.equal(await renderInspect('P'),true);
  for(const text of ['전체 등록 이력 7건','이번 조건에 연결된 근거 2건','연결 이유','목적 확인','미확인 조건','registered-letter'])assert(host.innerHTML.includes(text),text);
  full.emit('click');assert(body.innerHTML.includes('전체 등록 이력 7건'));assert.equal(full.textContent,'요약으로');
  candidate.can_review_draft=false;candidate.proposal_unavailable_reason='검토 불가 이유';
  await renderInspect('P');assert(!host.innerHTML.includes('data-action="registered-letter"'));assert(host.innerHTML.includes('검토 불가 이유'));
  dialog.dataset.registeredReview='false';global.session=null;
  await renderInspect('P');assert(host.innerHTML.includes('전체 등록 이력 7건'));assert(host.innerHTML.includes('앞 4건'));assert(!host.innerHTML.includes('이번 조건에 연결된 근거'));
  global.session={id:'S',result:{historical_result:true,candidates:[candidate]}};
  await renderInspect('P');assert(host.innerHTML.includes('이번 조건에 연결된 근거 2건'));assert(!host.innerHTML.includes('전체 등록 이력 7건'));
  full.emit('click');assert(body.innerHTML.includes('이번 조건에 연결된 근거 2건'));assert(body.innerHTML.includes('현재 전체 등록 이력이 아닙니다'));
})().catch(e=>{console.error(e);process.exitCode=1;});
""")


def test_map_graph_filter_counts_only_visible_record_links():
    run_js(r"""
const source=read('people-map'),start=source.indexOf('  function found(id){');
vm.runInThisContext(source.slice(start,source.indexOf('\n  }',start)+4));
global.state={query:'',capability:'',topic:''};global.appliedGraphFilter='';
const person={id:'P',records:[],sourcePerson:{}};
global.C={visiblePeople:()=>[person],capabilityLink:()=>null,searchTerms:()=>[],
  visibleEvidence:()=>[{id:'a'},{id:'b'},{id:'c'}]};
global.currentCapability=()=>null;global.shown={links:[
  {from:'capability:x',to:'person:P',recordIds:['b','b','missing']},
  {from:'capability:x',to:'person:OTHER',recordIds:['c']}
]};
assert.equal(found('P').hasCondition,false);assert.deepEqual(found('P').recordIds,['a','b','c']);
appliedGraphFilter='촉매';assert.equal(found('P').hasCondition,true);assert.deepEqual(found('P').recordIds,['b']);
shown.links=[];assert.deepEqual(found('P').recordIds,[]);
""")


def test_registered_card_cannot_finish_after_request_revision_changes():
    run_js(r"""
install('chat',['renderInspect']);
const dialog=element();dialog.dataset.registeredReview='true';
global.$=()=>dialog;global.inspectTicket=0;global.registeredEpoch=1;
global.session={result:{}};let revision='v1',resolve;
global.registeredBinding=()=>revision;global.currentRegisteredCandidate=()=>({id:'P'});
global.inspectPerson=()=>new Promise(r=>resolve=r);
(async()=>{const pending=renderInspect('P');revision='v2';resolve({id:'P'});assert.equal(await pending,false);})()
 .catch(e=>{console.error(e);process.exitCode=1;});
""")


def test_map_record_return_restores_context_scroll_and_width():
    run_js(r"""
install('app',['openDetailRecord','restoreDetailPerson']);
const dialog=element(),content=element(),button=element();button.dataset.id='R';
button.scrollIntoView=()=>{button.scrolled=true;};content.contains=()=>true;content.querySelectorAll=()=>[button];
Object.defineProperty(content,'childNodes',{get(){return [content.innerHTML];}});
content.replaceChildren=(...nodes)=>{content.innerHTML=nodes.join('');};
global.$=id=>id==='detailDialog'?dialog:content;
global.api=async()=>({id:'R',title:'합성 기록',text:'기록 본문'});global.evidenceHtml=()=>'';global.showDialog=()=>{};
global.SHEET_MEDIA={matches:false};global.sheetMode=()=>null;global.setSheetMode=()=>{};
let restored;
global.showPerson=(p,candidate,found,docked,sheet)=>{restored={p,candidate,found,docked,sheet};content.innerHTML='새 레이아웃';global.detailRecordReturn=null;};
(async()=>{
 for(const mobile of [false,true]){
  global.SHEET_MEDIA.matches=mobile;
  global.detailPersonView={p:{id:'P'},candidate:false,found:{recordIds:['R']},docked:true,sheet:mobile?'full':null};
  global.detailRecordReturn=null;content.innerHTML='<details open>펼친 기록 목록</details>';dialog.scrollTop=320;
  await openDetailRecord('R',button);assert(content.innerHTML.startsWith('<button'));assert(content.innerHTML.includes('‹ 인물로 돌아가기'));assert.equal(dialog.scrollTop,0);
  restoreDetailPerson();assert.equal(restored.p.id,'P');assert.equal(restored.sheet,mobile?'full':null);assert.equal(dialog.scrollTop,320);assert(content.innerHTML.includes('<details open>'));
 }
 global.detailRecordReturn=null;global.detailPersonView.sheet='full';
 await openDetailRecord('R',button);global.SHEET_MEDIA.matches=false;restoreDetailPerson();assert.equal(restored.sheet,null);assert(button.scrolled);
})().catch(e=>{console.error(e);process.exitCode=1;});
""")


def test_handle_tap_drag_cancel_desktop_and_reduced_motion():
    run_js(r"""
install('chat',['bindInspectHandle']);
global.window=element();let mobile=true,quiet=false;
global.matchMedia=query=>({get matches(){return query.includes('700px')?mobile:quiet;}});
global.setTimeout=()=>1;global.clearTimeout=()=>{};
const dialog=element(),handle=element();bindInspectHandle(dialog);
function fire(type,y){dialog.emit(type,{pointerId:1,button:0,clientY:y,target:{closest:()=>handle},preventDefault(){}});}
function finish(){dialog.emit('transitionend',{target:dialog,propertyName:'height'});}
fire('pointerdown',100);fire('pointerup',100);assert(dialog.open);assert.equal(dialog.style.height,'');
fire('pointerdown',100);fire('pointermove',140);fire('pointerup',140);finish();assert(dialog.open);
fire('pointerdown',100);fire('pointermove',141);assert.equal(dialog.style.height,'559px');fire('pointerup',141);
assert(dialog.open);assert.equal(dialog.style.transition,'height .26s cubic-bezier(.22,.75,.18,1)');finish();assert(!dialog.open);
dialog.open=true;quiet=true;fire('pointerdown',100);fire('pointerup',141);assert(!dialog.open);assert.equal(dialog.style.height,'');
dialog.open=true;fire('pointerdown',100);fire('pointermove',200);fire('pointercancel',200);assert(dialog.open);assert.equal(dialog.style.height,'');
mobile=false;fire('pointerdown',100);fire('pointerup',300);assert(dialog.open);assert.equal(dialog.style.height,'');
""")
