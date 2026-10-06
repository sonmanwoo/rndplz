'use strict';
// Live research-map layout and graph filter on the real scoped corpus; no browser/network/model calls.
const assert = require('node:assert/strict');
const path = require('node:path');
const {execFileSync} = require('node:child_process');
const Live = require('../rndplz/web/people-map-live.js');
globalThis.RndPeopleMapLayout = require('../rndplz/web/people-map-layout.js');
const createGraph = require('../rndplz/web/people-map-graph.js');
const create = require('../rndplz/web/people-map-model.js');

// Filter syntax: words, quotes, fields, AND / OR / NOT / -, parentheses.
const nodes = [
  {kind: 'person', label: '손만우', org: 'GS칼텍스', text: '증류 흡착 공정 모델링'},
  {kind: 'person', label: 'Gerhard Ertl', org: 'Fritz Haber Institute', text: '표면 화학 촉매'},
  {kind: 'capability', label: '촉매 설계·반응 평가', org: '', text: '촉매를 설계하고'},
  {kind: 'topic', label: '표면 반응·촉매', org: '', text: ''},
  {kind: 'project', label: 'GS그룹 해커톤 2026', org: '', text: ''}
];
const pick = query => nodes.filter(Live.compileFilter(query)).map(n => n.label);
assert.deepEqual(pick(''), nodes.map(n => n.label));
assert.deepEqual(pick('촉매'), ['Gerhard Ertl', '촉매 설계·반응 평가', '표면 반응·촉매']);
assert.deepEqual(pick('공정모델링'), ['손만우'], 'spacing inside a word is ignored, as in the map search');
assert.deepEqual(pick('type:사람 촉매'), ['Gerhard Ertl']);
assert.deepEqual(pick('type:person -org:gs'), ['Gerhard Ertl']);
assert.deepEqual(pick('종류:역량 OR 종류:프로젝트'), ['촉매 설계·반응 평가', 'GS그룹 해커톤 2026']);
assert.deepEqual(pick('NOT type:사람 AND (촉매 OR 해커톤)'), ['촉매 설계·반응 평가', '표면 반응·촉매', 'GS그룹 해커톤 2026']);
assert.deepEqual(pick('name:"gerhard ertl"'), ['Gerhard Ertl']);
assert.deepEqual(pick('소속:칼텍스'), ['손만우']);
for (const bad of ['type:로봇', 'where:x', '"열린 따옴표', '(촉매', '촉매)', 'org:', 'OR 촉매']) {
  assert.throws(() => Live.compileFilter(bad), Error, bad);
}

// Local graph depth over undirected links.
const links = [{from: 'a', to: 'b'}, {from: 'b', to: 'c'}, {from: 'c', to: 'd'}, {from: 'x', to: 'y'}];
assert.deepEqual([...Live.reach('b', 1, links)].sort(), ['a', 'b', 'c']);
assert.deepEqual([...Live.reach('a', 2, links)].sort(), ['a', 'b', 'c']);
assert.deepEqual([...Live.reach('a', 3, links)].sort(), ['a', 'b', 'c', 'd']);

// The real map: start from the fixed layout, settle without overlapping cards, follow a dragged card.
const payload = JSON.parse(execFileSync('python', ['-X', 'utf8', '-c', `
import json
from rndplz.data import Corpus
from rndplz.demo_pool import project_corpus
from rndplz.engine import Engine
from rndplz.people_map import build_people_map
from rndplz.public_profiles import APPROVED_PERSON_IDS, restrict_personal_publication
c=Corpus(); restrict_personal_publication(c,APPROVED_PERSON_IDS)
print(json.dumps(build_people_map(Engine(project_corpus(c,allow_personal_omission=True)))))
`], {cwd: path.resolve(__dirname, '..'), encoding: 'utf8'}));
const C = create(payload), G = createGraph(C);
const positions = new Map(), sim = new Live.Simulation(Live.DEFAULTS);
sim.aspect = 1.7;
function layout(state) {
  const graph = G.graph(state), placed = new Set();
  const cards = graph.nodes.map(n => {
    const card = positions.get(n.key) || {key: n.key, x: n.x, y: n.y};
    if (positions.has(n.key)) placed.add(n.key);
    card.w = n.width; card.h = n.height; positions.set(n.key, card);
    return card;
  });
  sim.setGraph(cards, graph.edges);
  let ticks = 0;
  while (sim.active && ticks < 1000) { sim.tick(); ticks++; }
  assert(ticks < 1000, 'the layout comes to rest');
  for (let i = 0; i < cards.length; i++) for (let j = i + 1; j < cards.length; j++) {
    const p = cards[i], q = cards[j];
    assert(!(Math.abs(p.x - q.x) < (p.w + q.w) / 2 && Math.abs(p.y - q.y) < (p.h + q.h) / 2), `${p.key} overlaps ${q.key}`);
  }
  const width = Math.max(...cards.map(c => c.x)) - Math.min(...cards.map(c => c.x));
  assert(width < Math.max(1200, graph.layout.bounds.width * 1.6), 'the live layout stays near the fixed layout size');
  return {graph, cards, ticks};
}
const all = C.initialState();
const first = layout(all);
const catalyst = layout(C.reduce(all, {type: 'CAPABILITY', value: 'catalyst'}));
assert(catalyst.cards.length < first.cards.length);
layout(all);
const card = first.cards.find(c => c.key === 'person:LOCAL-MANWOO');
sim.pin(card.key, card.x + 300, card.y - 200);
for (let i = 0; i < 30; i++) sim.tick();
assert.equal(card.x, card.fx); assert.equal(card.y, card.fy);
assert(sim.active, 'a held card keeps the layout running');
sim.release(card.key);
assert.equal(card.fx, undefined);
for (let i = 0; i < 1000 && sim.active; i++) sim.tick();
assert(!sim.active, 'released cards settle again');
console.log(JSON.stringify({pass: true, cards: first.cards.length, links: first.graph.edges.length, ticks: first.ticks, catalystCards: catalyst.cards.length}));
