'use strict';
// 제품 함수를 그대로 실행한다. 브라우저·서버·AI 네트워크 호출은 없다.
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const crypto=require('node:crypto');
const source=fs.readFileSync(path.join(__dirname,'../rndplz/web/profile-chat.js'),'utf8');
const between=(start,end)=>{const i=source.indexOf(start),j=source.indexOf(end,i);assert(i>=0&&j>i);return source.slice(i,j);};
const helpers=['CAREER','uid','cleanCareer','listItems','listJoin'].map(name=>source.split(/\r?\n/).find(line=>line.trimStart().startsWith('const '+name+' ='))).join('\n');
const functions=[between('    function newRequest(','    async function perform('),between('    async function saveDraft()','    function selectedValue('),between('    async function digestDocument(','    async function compareLatest('),between('    async function resolveConflict()','    function provenanceLabel(')].join('\n');
const clone=value=>JSON.parse(JSON.stringify(value));
function fixture(){
  const view={profile:{version:2,fields:{name:'기존 이름',organization:'기존 소속',aliases:['Old Alias'],bio:'이전 소개',skills:'기존 기술',interests:''},careers:[{id:'existing',title:'기존 경력'}],provenance:{bio:{source_ids:['active-old','inactive-old']}}},sources:[{id:'active-old',status:'active'},{id:'inactive-old',status:'unlinked'}]};
  const digest={source_id:'new-source',name:'입력 자료.txt',base_version:2,proposal:{name:'새 이름',organization:'새 소속',department:'새 부서',role:'새 직위',aliases:['New Alias'],tagline:'한 줄 소개',bio_addition:'추가 소개',skills:['새 기술'],interests:['관심'],careers:[{title:'새 경력',description:'확인 필요 회 실험'}],warnings:[{message:'원문에서 확인되지 않은 숫자를 확인 필요로 표시했습니다.'}]}};
  const context={crypto,Date,Set,Map,Promise,setInterval:()=>1,clearInterval:()=>{},setTimeout,
    view,digest,captured:null,generation:1,opened:true,busy:false,activeMutation:false,error:null,errorRequest:null,
    readingProgress:'',draft:null,reply:'',conflict:null,uncertain:null,editor:null,editorRevision:0,selectionRevision:0,
    selected:new Map(),getSessionId:()=>null,paint:()=>{},paintError:()=>{},controls:()=>{},showError:e=>{context.lastError=e;},
    copy:clone,same:(a,b)=>JSON.stringify(a)===JSON.stringify(b),targetValue:(v,key)=>v.profile.fields[key]||'',
    api:async()=>digest,perform:async request=>{context.captured=request;return request;}};
  vm.createContext(context);vm.runInContext(helpers+'\n'+functions,context);return context;
}
(async()=>{
  const c=fixture();await vm.runInContext('digestDocument(digest.source_id)',c);
  assert.equal(c.draft.fields.department,'새 부서');assert.deepEqual([...c.draft.fields.aliases],['Old Alias','New Alias']);
  assert(c.draft.warnings[0].message.includes('확인 필요'));
  c.draft.skip.add('name');c.draft.fields.role='고친 직위';c.draft.edited.add('role');c.draft.careers[0].edited=true;
  c.draft.editing='role';await vm.runInContext('saveDraft()',c);assert(!c.captured);assert(c.lastError.message.includes('고치기'));
  c.draft.editing=null;await vm.runInContext('saveDraft()',c);
  const payload=c.captured.body.payload;
  assert(!('name' in payload.fields));assert(!payload.field_sources.name);
  assert.equal(payload.field_sources.role.edited,true);
  assert.deepEqual([...payload.field_sources.bio.source_ids],['active-old','new-source']);
  assert.deepEqual([...payload.careers[1].source_ids],['new-source']);assert.equal(payload.careers[1].edited,true);
  assert.equal(payload.careers[0].id,'existing');assert(!payload.careers[0].source_ids);

  // 저장 충돌 뒤 현재값/제안을 비교하여 계속해도 출처와 새 경력은 보존한다.
  for(const choice of ['latest','mine']){
    const x=fixture();await vm.runInContext('digestDocument(digest.source_id)',x);
    const base=clone(x.view),latest=clone(x.view);latest.profile.version=3;latest.profile.fields.organization='다른 창의 소속';
    latest.profile.careers.push({id:'concurrent',title:'다른 창의 경력'});
    x.conflict={base,latest,request:{body:{action:'save'}},choices:new Map(),rows:[]};x.view=latest;
    vm.runInContext('buildConflict()',x);
    assert.equal(x.conflict.rows.length,1);assert.equal(x.conflict.rows[0].kind,'draft');
    x.conflict.choices.set('draft:organization',choice);
    await vm.runInContext('resolveConflict()',x);assert.equal(x.draft.base_version,3);
    await vm.runInContext('saveDraft()',x);
    assert.equal(x.captured.body.payload.base_version,3);
    assert.equal('organization' in x.captured.body.payload.fields,choice==='mine');
    assert.deepEqual([...x.captured.body.payload.careers].map(row=>row.id||'new'),['existing','concurrent','new']);
    assert.deepEqual([...x.captured.body.payload.careers[2].source_ids],['new-source']);
  }
  const empty=fixture();empty.digest.proposal={warnings:[{message:'소속은 원문에서 확인되지 않아 제안에서 제외했습니다.'}]};
  await vm.runInContext('digestDocument(digest.source_id)',empty);assert(empty.reply.includes('제외했습니다.'));

  const personView=require('../rndplz/web/person-view.js');
  const lineage={source_ids:['private-source'],sources:[{id:'private-source',title:'입력 자료.txt',url:'',status:'active'}],source_review:'자료 기반 + 사용자 수정'};
  const person={id:'P',name:'표시 이름',aliases:['Explicit Alias'],org:'저장 소속',profile:{curated:true,department:'저장 부서',current_role:'저장 직위',tagline:'20자를 넘어서도 머리에 유지되는 저장된 한 줄 소개',skills:['다른 기술'],timeline:[{date:'2026',text:'저장 경력',...lineage}],provenance:{organization:lineage}},evidence:[{id:'R',title:'등록 경력',kind:'career_record',date:'2026',summary:'경력 설명',...lineage}]};
  for(const options of [{},{compact:true}]){
    const head=personView.nameBlock(person,'strong','sheet-id',options);
    for(const value of ['Explicit Alias','저장 소속','저장 부서','저장 직위',person.profile.tagline])assert(head.includes(value));
  }
  const card=personView.render(person,{includeEvidence:true});
  assert(card.includes('입력 자료.txt'));assert(card.includes('자료 기반 + 사용자 수정'));assert(!card.includes('private-source'));assert(!card.includes('href=""'));
  const createModel=require('../rndplz/web/people-map-model.js');
  const model=createModel({schema_version:'people-map-existing-v1',people:[person],topics:[],featured_ids:[],capabilities:[]});
  const state={...model.initialState(),query:'Explicit Alias',selectedId:'P'};
  assert.equal(model.visiblePeople(state).length,1,'기존 이름 검색 경로에서 aliases를 찾는다');
  // 소속·부서·직위·한 줄 소개가 전용 칸으로 옮겨 가도 연구 맵 검색에서 찾힌다(P0 회귀 방지).
  for(const query of ['저장 소속','저장 부서','저장 직위','저장된 한 줄 소개'])assert.equal(model.visiblePeople({...state,query}).length,1,query);
  const createView=require('../rndplz/web/people-map.js');
  const map=createView(model,()=>({})).renderDetail(state);
  for(const value of ['Explicit Alias','저장 소속','저장 부서','저장 직위','입력 자료.txt','자료 기반 + 사용자 수정'])assert(map.includes(value),value);
  console.log(JSON.stringify({통과:true,검사:'대화 채택·출처·제외·수정·충돌·경고·카드/맵 출처·별칭 검색'}));
})().catch(error=>{console.error(error);process.exitCode=1;});
