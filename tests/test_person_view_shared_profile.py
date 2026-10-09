"""공용 인물 내용과 프로필 편집 연결의 합성 회귀 시험(브라우저 검증과 별개)."""
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PRELUDE = r"""
const assert = require('node:assert/strict'), fs = require('node:fs'), vm = require('node:vm');
const read = name => fs.readFileSync('rndplz/web/' + name + '.js', 'utf8');
function take(name, file='profile') {
  const source=read(file), indent=file==='profile'?'  ':'';
  const start=source.search(new RegExp('^'+indent+'(?:async )?function '+name+'\\(', 'm'));
  assert(start>=0, name);
  const tail=source.slice(start), end=tail.slice(1).search(new RegExp('^'+indent+'(?:async )?function ', 'm'));
  return end<0?tail:tail.slice(0,end+1);
}
function install(names,file='profile') { for(const name of names) vm.runInThisContext(take(name,file)); }
function element(tag='div') {
  const el={tagName:tag.toUpperCase(),childNodes:[],dataset:{},listeners:new Map(),className:'',textContent:'',
    classList:{values:new Set(),add(value){this.values.add(value);},toggle(){},remove(){}},
    append(...nodes){this.childNodes.push(...nodes);},prepend(...nodes){this.childNodes.unshift(...nodes);},
    replaceChildren(...nodes){this.childNodes=nodes;},setAttribute(){},focus(){},
    querySelector(){return null;},querySelectorAll(){return [];},contains(){return true;},
    addEventListener(type,handler){this.listeners.set(type,handler);}};
  Object.defineProperty(el,'children',{get(){return this.childNodes;}});
  Object.defineProperty(el,'innerHTML',{set(value){this.markup=value;this.childNodes=value?[{textContent:value.replace(/<[^>]*>/g,'')}]:[];},get(){return this.markup||'';}});
  return el;
}
global.window=global;
global.document={createElement:element};
global.RndPersonView=require('./rndplz/web/person-view.js');
const profileSource=read('profile');
vm.runInThisContext(profileSource.slice(profileSource.indexOf('  const CARD_BLOCKS='),profileSource.indexOf('  function renderCardMode(')));
install(['node','button','empty']);
global.clone=value=>JSON.parse(JSON.stringify(value));
global.cardEditing=null;global.cardBefore=null;global.cardError='';
global.cardMode=()=>true;global.blockChanged=()=>false;
"""


def run_js(script):
    result = subprocess.run(['node', '-'], input=PRELUDE + script, text=True,
                            encoding='utf-8', cwd=ROOT, capture_output=True)
    assert result.returncode == 0, result.stderr


def test_profile_edit_sections_survive_heading_and_class_changes_and_empty_values():
    run_js(r"""
install(['renderCard','cardBlock']);
const host=element();global.$=id=>id==='cardView'?host:{disabled:false};
global.cardPerson={id:'P',name:'Synthetic',profile:{display_name:'합성 인물',curated:true,
  timeline:[{record_id:'C',date:'2026',text:'연결 경력'}],projects:[{record_id:'R',title:'합성 과제',text:'과제 설명'}]},
  evidence:[{id:'C',kind:'career_record',date:'2026',title:'경력 기록'},{id:'R',kind:'project_record',title:'과제 기록'}]};
const sections=RndPersonView.sections;
const ids=sections(cardPerson,{editable:true}).map(s=>s.id);
RndPersonView.sections=(person,options)=>sections(person,options).map(s=>({...s,html:s.html
  .replace(/<h3>[^<]*<\/h3>/g,'<h3>임의로 바뀐 표시 제목</h3>')
  .replaceAll('researcher-timeline','another-timeline')}));
let opened=null;global.openBlock=key=>{opened=key;};
renderCard();
assert.deepEqual(host.children.map(el=>el.dataset.personSection),ids);
for(const id of ['identity','bio','skills','careers','interests']){
  const block=host.children.find(el=>el.dataset.personSection===id);
  assert(block.classList.values.has('is-editable'),id);
  assert.equal(block.dataset.block,id);
  block.children.find(el=>el.className==='card-edit').listeners.get('click')();
  assert.equal(opened,id);
}
assert(host.children.find(el=>el.dataset.personSection==='projects').classList.values.has('is-locked'));
assert(!host.children.find(el=>el.dataset.personSection==='evidence').dataset.block);
assert(!profileSource.includes('CARD_HEADINGS'));assert(!profileSource.includes('function blockKey('));
""")


def test_editor_close_and_escape_cancel_but_apply_keeps_draft_without_saving():
    run_js(r"""
install(['blockValues','cancelBlock','closeBlock','blockEditor']);
global.labels={bio:'약력'};global.fieldOrigin=()=>'';global.editableField=()=>element('input');
global.view={limits:{fields:{bio:2000}}};global.draft={fields:{bio:'편집 전',skills:''},careers:[{id:'C',title:'이전 경력'}]};
let renders=0,controls=0,previews=0,applied=false;
global.renderCard=()=>{renders++;};global.updateControls=()=>{controls++;};
global.refreshCard=()=>{previews++;};
global.$=()=>({querySelector:()=>({closest:()=>({classList:{add:value=>{applied=value==='is-applying';}}})})});
const reset=()=>{cardEditing='bio';draft.fields.bio='편집 전';cardBefore=blockValues(CARD_BLOCKS.bio);draft.fields.bio='수정 중';};
reset();let box=blockEditor(CARD_BLOCKS.bio);
box.children[0].children[1].listeners.get('click')();
assert.equal(draft.fields.bio,'편집 전');assert.equal(cardEditing,null);assert.equal(cardBefore,null);
reset();box=blockEditor(CARD_BLOCKS.bio);let prevented=false;
box.listeners.get('keydown')({key:'Escape',preventDefault(){prevented=true;}});
assert(prevented);assert.equal(draft.fields.bio,'편집 전');assert.equal(cardEditing,null);
cardEditing='careers';cardBefore=blockValues(CARD_BLOCKS.careers);draft.careers[0].title='수정 중 경력';
cancelBlock();assert.equal(draft.careers[0].title,'이전 경력');
reset();box=blockEditor(CARD_BLOCKS.bio);
box.children.find(el=>el.className==='button-row').children[0].listeners.get('click')();
assert.equal(draft.fields.bio,'수정 중');assert.equal(cardEditing,null);assert.equal(cardBefore,null);
assert.equal(previews,1);assert(applied);assert.equal(renders,3);assert.equal(controls,3);
""")


def test_map_sheet_uses_single_shared_sections_with_found_context_and_record_links():
    run_js(r"""
install(['personEvidenceStats','sheetHtml'],'app');
global.esc=s=>String(s??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;');
global.RndCraft={isLaureate:()=>false};global.canPropose=c=>c.proposal_allowed!==false;
global.detailRequestAction=()=>'<p>의뢰 불가 이유</p>';
const person={id:'P',name:'Synthetic',org:'합성 조직',reason:'조건에 연결된 이유',profile:{display_name:'합성 인물',curated:true,
  biography:'소개 문장',skills:['기술1','기술2','기술3','기술4','기술5'],
  timeline:[{record_id:'C',date:'2026',text:'연결된 실제 경력 설명'}]},
  evidence:[{id:'C',kind:'career_record',date:'2026',title:'경력 기록'},{id:'X',title:'설명 없는 기록',in_current_pool:false}]};
const found={hasCondition:true,recordIds:['C']},labels=new Map([['C','조건으로 찾은 기록']]);
const markup=sheetHtml(person,found,labels,person.evidence,{id:'P',evidence:[person.evidence[0]],proposal_allowed:false});
assert.equal((markup.match(/class="sheet-id"/g)||[]).length,1);
assert.equal((markup.match(/data-person-section="evidence"/g)||[]).length,1);
assert.equal((markup.match(/연결된 실제 경력 설명/g)||[]).length,1);
assert.equal((markup.match(/class="scope-note person-notice"/g)||[]).length,1);
assert.equal((markup.match(/조건에 연결된 이유/g)||[]).length,1);
for(const value of ['전체 등록 이력 2건 · 이번 조건에 연결된 근거 1건','조건으로 찾은 기록','data-action="record" data-id="C"','data-chips-more','의뢰 불가 이유'])assert(markup.includes(value),value);
assert(markup.includes('data-action="record" data-id="X" disabled'));
assert(!markup.includes('class="sheet-more"'));assert(!markup.includes('data-action="letter"'));
assert(!markup.includes('data-person-section="identity"'));assert(!markup.includes('data-person-section="skills"'));
""")


def test_candidate_sheet_keeps_partial_and_saved_response_scope():
    run_js(r"""
install(['personEvidenceStats','sheetHtml','showPerson'],'app');
global.esc=s=>String(s??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;');
global.RndCraft={isLaureate:()=>false};global.canPropose=()=>false;global.detailRequestAction=()=>'';
const host=element(),dialog=element();global.$=id=>id==='detailContent'?host:dialog;
global.foundLabels=()=>new Map();global.markFound=()=>{};global.showDialog=()=>{};global.setSheetMode=()=>{};
const person={id:'P',name:'합성 인물',profile:{curated:true},evidence:[{id:'R',title:'저장된 선택 근거'}]};
for(const historical of [false,true]){
 global.session={result:{candidates:[person],historical_result:historical,scope_note:'저장 당시 공개 범위'}};
 global.displayResult=s=>s?.result;
 showPerson(person,true,null,true,'full');
 assert(host.innerHTML.includes('이번 조건에 연결된 근거 1건'));
 assert(!/전체 등록 이력 \d+건/.test(host.innerHTML));
 assert.equal(host.innerHTML.includes('현재 전체 등록 이력이 아닙니다'),historical);
 assert.equal(host.innerHTML.includes('저장 당시 공개 범위'),historical);
}
// Historical researchers are still current directory records, separate from saved responses.
const deceased={...person,profile:{display_type:'historical_researcher'}};
const markup=sheetHtml(deceased,null,new Map(),deceased.evidence,null);
assert(markup.includes('역사적 연구 자료'));assert(markup.includes('전체 등록 이력 1건'));
assert(!markup.includes('현재 전체 등록 이력이 아닙니다'));
""")
