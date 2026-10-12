'use strict';
// Same-meaning words in the research map's model (2026-10-12): people found through them join the results, marked,
// only for the query they were asked for, and each word can be taken out.
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
`], {cwd: path.resolve(__dirname, '..'), encoding: 'utf8'}));
const model = create(structuredClone(payload));
const ids = state => model.visiblePeople(state).map(p => p.id);

// A word nobody's text holds finds no one, until a same-meaning word for that very query arrives.
let state = model.reduce(model.initialState(), {type: 'QUERY', value: 'zymurgy'});
assert.deepEqual(ids(state), []);
state = model.reduce(state, {type: 'SYNONYMS', query: 'zymurgy', terms: ['발효', 7, '']});
assert(ids(state).includes('PUB-PRATHER'));
const prather = model.visiblePeople(state).find(p => p.id === 'PUB-PRATHER');
assert.equal(model.foundBySynonym(state, prather), true);
assert.deepEqual(model.synonymTerms(state, prather), ['발효']);
assert.deepEqual(state.synonyms.terms, ['발효'], 'only words are kept');

// People the typed word already finds are not marked as found by a same-meaning word.
let typed = model.reduce(model.initialState(), {type: 'QUERY', value: '발효'});
typed = model.reduce(typed, {type: 'SYNONYMS', query: '발효', terms: ['fermentation']});
const direct = model.visiblePeople(typed).find(p => p.id === 'PUB-PRATHER');
assert.equal(model.foundBySynonym(typed, direct), false);

// Words for an earlier query never count; typing on drops them; a word can be taken out; clearing drops them.
assert.equal(model.reduce(state, {type: 'SYNONYMS', query: 'zymurg', terms: ['촉매']}).synonyms.terms[0], '발효');
assert.equal(model.reduce(state, {type: 'QUERY', value: 'zymurgy '}).synonyms, null);
assert.deepEqual(ids(model.reduce(state, {type: 'REMOVE_SYNONYM', term: '발효'})), []);
assert.equal(model.reduce(state, {type: 'CLEAR_FILTERS'}).synonyms, null);
// A saved state whose words belong to another query loses them.
assert.equal(model.reduce({...state, query: 'other'}, {type: 'PAGE', value: 0}).synonyms, null);
console.log('people map synonyms: passed');
