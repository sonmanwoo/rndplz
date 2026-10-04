'use strict';
// Real scoped corpus plus adversarial fixtures; no browser/network/model calls.
const assert = require('node:assert/strict');
const path = require('node:path');
const {execFileSync} = require('node:child_process');
const create = require('../rndplz/web/people-map-model.js');
const payload = JSON.parse(execFileSync('python', ['-X', 'utf8', '-c', `
import json
from rndplz.data import Corpus
from rndplz.demo_pool import project_corpus
from rndplz.engine import Engine
from rndplz.people_map import build_people_map
from rndplz.public_profiles import APPROVED_PERSON_IDS, restrict_personal_publication
c=Corpus(); restrict_personal_publication(c,APPROVED_PERSON_IDS)
print(json.dumps(build_people_map(Engine(project_corpus(c,allow_personal_omission=True)))))
`], {cwd:path.resolve(__dirname,'..'),encoding:'utf8'}));
const queries={
 'PUB-PANAGIOTOPOULOS':['열역학','thermodynamics'],
 'PUB-KISS':['반응증류','reactive distillation'],
 'PUB-LIVINGSTON':['나노여과','nanofiltration'],
 'PUB-DOHERTY':['결정화','polymorph'],
 'PUB-CURTIS':['다상유동','particle flow'],
 'PUB-MCKINLEY':['점탄성','rheology'],
 'PUB-PRATHER':['발효','fermentation'],
 'PUB-SEO-SANGWOO':['세포공장','synthetic biology'],
 'PUB-CHOI-JANGWOOK':['배터리 진단','battery diagnostics'],
 'PUB-SRINIVASAN':['공정안전','process safety'],
 'PUB-ELIMELECH':['담수화','desalination'],
 'PUB-JENSEN':['연속흐름','flow chemistry'],
 'PUB-ELHALWAGI':['기술경제성','process integration'],
 'PUB-GLADDEN':['자기공명','magnetic resonance'],
 'PUB-KIM-JONGHAK':['기체 분리','gas separation'],
 'PUB-HUBER':['폐플라스틱','waste plastics']
};
const model=create(structuredClone(payload));
let searchCount=0, edgeCount=0;
for(const [id,terms] of Object.entries(queries)) for(const value of terms){
 const state=model.reduce(model.initialState(),{type:'QUERY',value});
 assert(model.visiblePeople(state).some(p=>p.id===id),`${value} -> ${id}`); searchCount++;
}
for(const capability of model.capabilities){
 const state=model.reduce(model.initialState(),{type:'CAPABILITY',value:capability.id});
 assert.deepEqual(new Set(model.visiblePeople(state).map(p=>p.id)),new Set(capability.people.map(p=>p.id)));
 for(const person of model.visiblePeople(state)){
  const link=model.capabilityLink(state,person);
  // Project participation shows the person's whole portfolio by existing design.
  const expected=link.kind==='project' ? person.records.map(r=>r.id) : link.recordIds;
  assert.deepEqual(new Set(model.visibleEvidence(state,person).map(r=>r.id)),new Set(expected)); edgeCount++;
 }
}
// A term only in visible evidence text must work, with no added profile keyword.
const summaryOnly=structuredClone(payload);
summaryOnly.people.find(p=>p.id==='PUB-LIVINGSTON').evidence[0].summary+=' summaryonlyprobe';
const m2=create(summaryOnly);
assert.deepEqual(m2.visiblePeople(m2.reduce(m2.initialState(),{type:'QUERY',value:'summaryonlyprobe'})).map(p=>p.id),['PUB-LIVINGSTON']);
// A stale or foreign record ID cannot survive client-side scope intersection.
const stale=structuredClone(payload);
stale.capabilities=[{id:'stale',label:'Fixture',description:'Fixture',people:[{id:'PUB-LIVINGSTON',scope:'Fixture',recordIds:['CHE26-CURTIS','MISSING']}]}];
assert.equal(create(stale).capabilities[0].people.length,0);
// Older saved payloads retain their existing categories and identity links.
const legacy=structuredClone(payload); delete legacy.capabilities;
const legacyModel=create(legacy);
assert(legacyModel.capabilities.some(c=>c.id==='separation'&&c.people.some(p=>p.id==='LOCAL-MANWOO')));
console.log(JSON.stringify({pass:true,searches:searchCount,categoryEdges:edgeCount,people:model.people.length,categories:model.capabilities.length,summaryOnly:true,foreignRecordRejected:true,legacyCompatible:true}));
