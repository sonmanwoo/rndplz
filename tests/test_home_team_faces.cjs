'use strict';
// The home's rotating phrases lead with a teammate's face (2026-10-14), sparingly: only in a capability the person
// has, one teammate per phrase beside a field expert, each teammate in one phrase only.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const code = fs.readFileSync(path.join(__dirname, '..', 'rndplz', 'web', 'home-cosmos.js'), 'utf8').replace(/\r\n/g, '\n');
const team = code.match(/const TEAM = \[[^\]]*\];/)[0];
const start = code.indexOf('  function pickFaces(scenes) {');
const end = code.indexOf('\n  }\n', start) + 4;
assert.ok(start > 0, 'pickFaces is in home-cosmos.js');
const { TEAM, pickFaces } = new Function(team + '\n' + code.slice(start, end) + '\nreturn { TEAM, pickFaces };')();
const [JINHO, MANWOO, DASOL, HONG] = ['LOCAL-JINHO', 'LOCAL-MANWOO', 'LOCAL-DASOL', 'LOCAL-HONG'];
assert.deepEqual([...TEAM].sort(), [JINHO, MANWOO, DASOL, HONG].sort());

const p = id => ({ id });
const scene = (id, ...people) => ({ id, phrase: id, people: people.map(p) });
const picked = pickFaces([
  scene('catalyst', 'E1', 'E2', JINHO, HONG),
  scene('process', 'E3', MANWOO, 'E4'),
  scene('separation', 'E5', MANWOO, 'E6'),
  scene('saf', JINHO, 'E7'),
  scene('control', 'E8', 'E9'),
]);
const faces = Object.fromEntries(picked.map(s => [s.id, s.thumbs.map(t => t.id)]));

// The teammate with the fewest phrases is placed first; each goes where they rank highest.
assert.deepEqual(faces.catalyst, [HONG, 'E1'], 'HONG has only catalyst, so JINHO takes saf');
assert.deepEqual(faces.saf, [JINHO, 'E7']);
assert.deepEqual(faces.process, [MANWOO, 'E3'], 'MANWOO ranks higher in process than in separation');
// Phrases without a lead keep two field experts, even when a teammate belongs there.
assert.deepEqual(faces.separation, ['E5', 'E6']);
assert.deepEqual(faces.control, ['E8', 'E9']);
const counts = {};
for (const s of picked) for (const id of s.thumbs.map(t => t.id)) if (TEAM.includes(id)) counts[id] = (counts[id] || 0) + 1;
assert.ok(Object.values(counts).every(n => n === 1), 'each teammate leads one phrase at most');
assert.ok(!(DASOL in counts), 'a teammate without one of these capabilities is not added');
// The fewest-choices order lets everyone in: JINHO ranks first in 'a', but HONG has nowhere else.
const spread = Object.fromEntries(pickFaces([scene('a', JINHO, HONG, 'E1'), scene('b', 'E2', JINHO, 'E3')]).map(s => [s.id, s.thumbs[0].id]));
assert.deepEqual(spread, { a: HONG, b: JINHO });
// A phrase with only teammates still shows two faces.
assert.deepEqual(pickFaces([scene('x', JINHO, MANWOO)])[0].thumbs.map(t => t.id), [JINHO, MANWOO]);
console.log('home team faces: ok');
