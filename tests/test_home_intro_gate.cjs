'use strict';
// The home opening is decided in <head> before the first paint (2026-10-12): a visitor every visit, a signed-in browser
// once a day; an opened conversation, motion off and rndplz.intro = "off" skip it.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '..', 'rndplz', 'web', 'home-intro-gate.js'), 'utf8');
const today = new Date().toLocaleDateString('sv-SE');
function decide({ url = 'https://example.test/', local = {}, session = {}, reduced = false } = {}) {
  const store = values => ({ getItem: key => (key in values ? values[key] : null) });
  const dataset = {};
  vm.runInNewContext(source, {
    location: { href: url }, URL, Date,
    matchMedia: () => ({ matches: reduced }),
    localStorage: store(local), sessionStorage: store(session),
    document: { documentElement: { dataset } },
  });
  return dataset.homeIntro || null;
}

assert.equal(decide(), 'play', 'a visitor sees it');
assert.equal(decide({ local: { 'rndplz.intro.day': today } }), 'play', 'a visitor sees it on every visit');
assert.equal(decide({ local: { 'rndplz.account.look': 'account' } }), 'play', 'signed in, first visit of the day');
assert.equal(decide({ local: { 'rndplz.account.look': 'account', 'rndplz.intro.day': today } }), null, 'signed in, already today');
assert.equal(decide({ local: { 'rndplz.account.look': 'account', 'rndplz.intro.day': '2000-01-01' } }), 'play', 'signed in, a new day');
assert.equal(decide({ url: 'https://example.test/?chat=abc' }), null, 'an opened conversation');
assert.equal(decide({ url: 'https://example.test/explore' }), null, 'only the home');
assert.equal(decide({ reduced: true }), null, 'reduced motion');
assert.equal(decide({ session: { 'rndplz-motion': 'off' } }), null, 'motion switched off');
assert.equal(decide({ local: { 'rndplz.intro': 'off' } }), null, 'switched off for automation');
assert.equal(decide({ url: 'https://example.test/?landing=off' }), 'play', 'the bare home too');
console.log('home intro gate: passed');
