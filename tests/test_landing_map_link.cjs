'use strict';
// DOM-contract tests only: no browser, server, network or screen tools.
const assert = require('node:assert/strict');
const {capabilityFromLocation, mount} = require('../rndplz/web/landing-map-link.js');

const route = (search = '', hash = '#map', pathname = '/explore') => ({pathname, search, hash});
assert.equal(capabilityFromLocation(route('?capability=control')), 'control');
assert.equal(capabilityFromLocation(route('?capability=project%3Ademo')), 'project:demo');
assert.equal(capabilityFromLocation(route('?capability=%EC%97%B0%EA%B5%AC')), '연구');
assert.equal(capabilityFromLocation(route()), '');
assert.equal(capabilityFromLocation(route('?capability=')), '');
assert.equal(capabilityFromLocation(route('?capability=control', '#inbox')), '');
assert.equal(capabilityFromLocation(route('?capability=control', '', '/')), '');

function harness(location = route('?capability=control')) {
  let buttons = [], callback = null, timer = null, disconnected = 0, observed = 0, clicks = 0;
  const events = new Map();
  const controls = {querySelectorAll(selector) { assert.equal(selector, '[data-capability]'); return buttons; }};
  const host = {isConnected: true, querySelector(selector) {
    assert.equal(selector, '#capability-controls'); return controls;
  }};
  const win = {
    location,
    document: {getElementById(id) { assert.equal(id, 'peopleMapHost'); return host; }},
    MutationObserver: class {
      constructor(fn) { callback = fn; }
      observe(node, options) {
        assert.equal(node, host);
        assert.deepEqual(options, {childList: true, subtree: true}); observed++;
      }
      disconnect() { disconnected++; }
    },
    setTimeout(fn, ms) { assert.equal(ms, 30000); timer = fn; return 1; },
    clearTimeout(id) { assert.equal(id, 1); timer = null; },
    addEventListener(type, fn) { events.set(type, fn); },
    removeEventListener(type) { events.delete(type); }
  };
  return {
    win, host,
    button(id, pressed = false) {
      const item = {dataset: {capability: id}, getAttribute(name) {
        assert.equal(name, 'aria-pressed'); return pressed ? 'true' : 'false';
      }, click() { pressed = !pressed; clicks++; }};
      buttons.push(item); return item;
    },
    mutate() { if (callback) callback(); },
    expire() { if (timer) timer(); },
    pagehide() { if (events.get('pagehide')) events.get('pagehide')(); },
    stats() { return {clicks, observed, disconnected, timer: Boolean(timer), listeners: events.size}; }
  };
}

// The ordinary map route never waits for or touches map controls.
const ordinary = harness(route());
mount(ordinary.win);
assert.deepEqual(ordinary.stats(), {clicks: 0, observed: 0, disconnected: 0, timer: false, listeners: 0});

// A slow map applies the exact capability once after the existing controls mount.
const delayed = harness();
mount(delayed.win);
delayed.mutate();
assert.equal(delayed.stats().clicks, 0);
delayed.button('catalyst'); delayed.button('control');
delayed.mutate(); delayed.mutate();
assert.deepEqual(delayed.stats(), {clicks: 1, observed: 1, disconnected: 1, timer: false, listeners: 0});

// Already-selected controls must not be toggled off; stale links keep all people.
for (const [id, selected] of [['control', true], ['catalyst', false]]) {
  const ready = harness(); ready.button(id, selected); mount(ready.win);
  assert.deepEqual(ready.stats(), {clicks: 0, observed: 0, disconnected: 0, timer: false, listeners: 0});
}

// Encoded punctuation is compared literally, without selector interpolation.
const project = harness(route('?capability=project%3Ademo'));
project.button('project:demo'); mount(project.win);
assert.equal(project.stats().clicks, 1);
const selector = harness(route('?capability=%22%5D%2C%5Bdata-person%5D'));
selector.button('control'); mount(selector.win);
assert.equal(selector.stats().clicks, 0);

// A failed/detached/navigated-away map must not retain observers or late actions.
for (const exit of ['expire', 'pagehide', 'detach']) {
  const waiting = harness(); mount(waiting.win);
  if (exit === 'detach') { waiting.host.isConnected = false; waiting.mutate(); }
  else waiting[exit]();
  waiting.button('control'); waiting.mutate();
  assert.deepEqual(waiting.stats(), {clicks: 0, observed: 1, disconnected: 1, timer: false, listeners: 0});
}

console.log('landing map capability link: passed');
