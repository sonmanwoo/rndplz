'use strict';
// Contract tests in a small DOM double: no browser, server or external request.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const landing = require('../rndplz/web/landing.js');
const boot = fs.readFileSync(path.join(__dirname, '../rndplz/web/landing-boot.js'), 'utf8');
const settle = () => new Promise(resolve => setImmediate(resolve));

class Element {
  constructor(tag = 'div', doc) {
    this.tagName = tag.toUpperCase(); this.doc = doc; this.children = []; this.dataset = {};
    this.attributes = {}; this.events = new Map(); this.className = ''; this.hidden = false;
    this.scrollLeft = 0; this.scrollWidth = 900; this.clientWidth = 400;
    this.classList = {
      contains: name => this.className.split(/\s+/).includes(name),
      toggle: (name, on) => {
        const names = new Set(this.className.split(/\s+/).filter(Boolean));
        if (on == null) on = !names.has(name);
        if (on) names.add(name); else names.delete(name);
        this.className = [...names].join(' '); return on;
      },
    };
  }
  set innerHTML(_) { throw new Error('Untrusted presentation must use textContent, not HTML.'); }
  append(...children) { for (const child of children) { child.parent = this; this.children.push(child); } }
  replaceChildren(...children) { this.children.forEach(child => { child.parent = null; }); this.children = []; this.append(...children); }
  remove() { if (this.parent) this.parent.children = this.parent.children.filter(child => child !== this); this.parent = null; }
  get firstElementChild() { return this.children[0]; }
  getBoundingClientRect() { return {width: 260}; }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  removeAttribute(name) { delete this.attributes[name]; }
  addEventListener(type, fn) { if (!this.events.has(type)) this.events.set(type, []); this.events.get(type).push(fn); }
  emit(type, event = {}) {
    const action = {target: this, preventDefault() { this.defaultPrevented = true; },
      stopPropagation() { this.propagationStopped = true; }, ...event};
    this.dispatch(type, action); return action;
  }
  dispatch(type, action) {
    for (const fn of this.events.get(type) || []) fn(action);
    if (type === 'click' && !action.propagationStopped && this.parent) this.parent.dispatch(type, action);
  }
  click() { this.clicks = (this.clicks || 0) + 1; return this.emit('click'); }
  focus(options) { this.doc.activeElement = this; this.focusOptions = options; }
  contains(target) { return this === target || this.children.some(child => child.contains(target)); }
  scrollIntoView(options) { this.scrolledInto = options; }
  scrollBy(options) { this.scrolledBy = options; }
  scrollTo(options) { this.scrolledTo = options; }
  matches(selector) {
    if (selector.startsWith('.')) return this.classList.contains(selector.slice(1));
    const attribute = selector.match(/^(\w+)?\[data-([a-z-]+)\]$/);
    if (attribute) {
      const key = attribute[2].replace(/-([a-z])/g, (_, char) => char.toUpperCase());
      return (!attribute[1] || this.tagName === attribute[1].toUpperCase()) && key in this.dataset;
    }
    return this.tagName === selector.toUpperCase();
  }
  querySelectorAll(selector) { return this.children.flatMap(child => [...(child.matches(selector) ? [child] : []), ...child.querySelectorAll(selector)]); }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
}

const fixture = {
  schema_version: 'people-map-home-v1',
  people: [
    {id: 'PUB-Z', name: 'Fallback', profile: {display_name: '<b>첫 연구자</b>', portrait: {path: '/portraits/first.png'}}, field_label: '기록 분야', private_value: 'omit'},
    {id: 'LOCAL-1', name: '개인 자료', profile: {portrait: {path: '/portraits/local.png'}}},
    {id: 'PUB-A', name: '둘째 연구자', profile: {portrait: {path: '/portraits/second-detail.webp'}}, evidence: [{secret: 'omit'}]},
    {id: 'PUB-BAD', name: '제외', profile: {portrait: {path: 'https://example.invalid/face.png'}}},
  ],
  capabilities: [
    {id: '분리 / 정제', label: '분리·정제', people: [{id: 'PUB-A'}, {id: 'LOCAL-1'}, {id: 'PUB-Z'}], evidence: 'omit'},
    {id: 'empty', label: '다른 분야', people: [{id: 'LOCAL-1'}]},
  ],
};

function harness(mode = 'people', quiet = false) {
  const doc = new Element('document'); doc.doc = doc; doc.hidden = false;
  doc.body = new Element('body', doc); doc.head = new Element('head', doc); doc.append(doc.head, doc.body);
  doc.body.className = 'home-welcome'; if (mode != null) doc.body.dataset.landing = mode;
  const ids = {};
  const element = (id, parent = doc.body, tag = 'div') => { const node = new Element(tag, doc); if (id) ids[id] = node; parent.append(node); return node; };
  doc.getElementById = id => ids[id] || null;
  doc.createElement = tag => new Element(tag, doc);
  for (const id of ['landingIntro', 'landingDown', 'landingFeatures', 'landingFields', 'landingPeople', 'landingMap', 'landingMapCanvas', 'landingPersonError', 'message', 'accountMenu', 'accountToggle', 'googleLogin', 'feedbackDialog', 'chatForm']) element(id);
  element('', ids.landingFeatures, 'h2');
  element('landingFeatureRail', ids.landingFeatures, 'ul').className = 'landing-rail';
  element('', ids.landingFeatureRail, 'li');
  const featureImage = element('', ids.landingFeatures, 'img'); featureImage.dataset.src = '/landing-assets/chat.webp';
  element('landingPeopleRail', ids.landingPeople, 'ul').className = 'landing-rail';
  element('landingFieldList', ids.landingFields, 'ul');
  for (const host of [ids.landingFields, ids.landingPeople]) element('', host, 'p').dataset.landingDataStatus = '';
  const retry = element('', ids.landingFields, 'button'); retry.dataset.landingRetry = '';
  const ask = element('', doc.body, 'button'); ask.dataset.landingAsk = '';
  const login = element('', doc.body, 'button'); login.dataset.landingLogin = '';
  const feedback = element('', doc.body, 'button'); feedback.dataset.landingFeedback = '';
  const existingFeedback = element('', doc.body, 'button'); existingFeedback.dataset.feedbackOpen = '';
  const next = element('', ids.landingFeatures, 'button'); next.dataset.landingNext = 'landingFeatureRail';
  ids.accountMenu.hidden = true; ids.landingMap.hidden = true;
  ids.accountToggle.addEventListener('click', () => { ids.accountMenu.hidden = false; });
  doc.addEventListener('click', event => {
    if (event.target !== ids.accountToggle && !ids.accountMenu.contains(event.target)) ids.accountMenu.hidden = true;
  });
  existingFeedback.addEventListener('click', () => { ids.feedbackDialog.open = true; });
  const observers = [], mediaEvents = [], intervals = new Map(), fetches = [], scripts = [], cards = [], mapMounts = [];
  let timer = 0;
  const media = {matches: quiet, addEventListener(type, fn) { mediaEvents.push(fn); }};
  const win = new Element('window', doc); win.document = doc;
  Object.assign(win, {
    matchMedia: () => media,
    IntersectionObserver: class {
      constructor(callback, options = {}) { this.callback = callback; this.options = options; this.targets = []; observers.push(this); }
      observe(target) { this.targets.push(target); }
      disconnect() { this.targets = []; }
    },
    MutationObserver: class { constructor(callback) { this.callback = callback; } observe() {} },
    setInterval(fn, delay) { assert.equal(delay, 2000); intervals.set(++timer, fn); return timer; },
    clearInterval(id) { intervals.delete(id); },
    fetch(url, options) { fetches.push({url, options}); return Promise.resolve({ok: true, json: async () => fixture}); },
    openPersonCard(...args) { cards.push(args); return Promise.resolve(); },
    LandingMapPreview: {mount(host) { mapMounts.push(host); return Promise.resolve(); }},
  });
  win.Landing = {
    quiet: () => media.matches || doc.body.classList.contains('no-motion'),
    loadScript: async url => { scripts.push(url); },
    openPersonCard: (...args) => win.openPersonCard(...args),
  };
  const intersect = (target, isIntersecting, intersectionRatio = isIntersecting ? 1 : 0) => {
    for (const observer of [...observers]) if (observer.targets.includes(target)) observer.callback([{target, isIntersecting, intersectionRatio}]);
  };
  return {doc, win, ids, featureImage, retry, ask, login, feedback, existingFeedback, next, observers, media, mediaEvents, intervals, fetches, scripts, cards, mapMounts, intersect};
}

function runBoot(h) {
  delete h.win.Landing;
  vm.runInNewContext(boot, {window: h.win, document: h.doc, matchMedia: h.win.matchMedia,
    IntersectionObserver: h.win.IntersectionObserver}, {filename: 'landing-boot.js', importModuleDynamically: vm.constants.USE_MAIN_CONTEXT_DEFAULT_LOADER});
}

(async () => {
  // No opt-in document means no added listeners, observers, data or assets.
  for (const mode of [null, '', 'invalid']) {
    const ordinary = harness(mode); landing.init(ordinary.win); runBoot(ordinary);
    assert.equal(ordinary.observers.length, 0); assert.equal(ordinary.doc.head.children.length, 0);
    assert.equal(ordinary.fetches.length, 0); assert.equal(ordinary.win.Landing, undefined);
  }

  // Public projection drops unrelated source fields and preserves API ordering.
  const source = JSON.stringify(fixture), projected = landing.project(fixture);
  assert.equal(JSON.stringify(fixture), source);
  assert.deepEqual(projected.people, [
    {id: 'PUB-Z', name: '<b>첫 연구자</b>', portrait: '/portraits/first-thumb.webp', field: '기록 분야'},
    {id: 'PUB-A', name: '둘째 연구자', portrait: '/portraits/second-detail.webp', field: '분리·정제'},
  ]);
  assert.deepEqual(projected.fields.map(item => [item.id, item.label, item.people.map(person => person.id)]), [
    ['분리 / 정제', '분리·정제', ['PUB-A', 'PUB-Z']], ['empty', '다른 분야', []],
  ]);
  assert.deepEqual(projected.fields.map(item => Object.keys(item).sort()), [['id', 'label', 'people'], ['id', 'label', 'people']]);
  assert.deepEqual(landing.project(null), {people: [], fields: []});
  for (const value of ['https://example.invalid/a.webp', '/portraits/../a.png', '/portraits/a.svg', '/portraits/a.png?x=1', 'javascript:alert(1)', null]) assert.equal(landing.safePortrait(value), '');
  assert.equal(landing.safePortrait('/portraits/a.JPEG'), '/portraits/a-thumb.webp');
  assert.equal(landing.capabilityURL('분리 / 정제'), '/explore?capability=%EB%B6%84%EB%A6%AC%20%2F%20%EC%A0%95%EC%A0%9C#map');

  const people = harness(); landing.init(people.win);
  assert.equal(people.fetches.length, 0); assert.equal(people.scripts.length, 0); assert.equal(people.featureImage.src, undefined);
  people.intersect(people.ids.landingFields, false); people.intersect(people.featureImage, false);
  assert.equal(people.fetches.length, 0); assert.equal(people.featureImage.src, undefined);
  people.intersect(people.ids.landingFields, true, 0); people.intersect(people.ids.landingPeople, true, 0); people.intersect(people.featureImage, true, 0);
  assert.equal(people.fetches.length, 0); assert.equal(people.featureImage.src, undefined); assert.equal(people.intervals.size, 0);
  assert(people.observers.every(observer => observer.options.threshold > 0), 'visibility must cross a positive-area threshold');
  people.intersect(people.featureImage, true); assert.equal(people.featureImage.src, '/landing-assets/chat.webp');
  people.intersect(people.ids.landingFields, true); people.intersect(people.ids.landingPeople, true); await settle();
  assert.equal(people.fetches.length, 1); assert.match(people.fetches[0].url, /^\/api\/people-map\?view=home(?:&landing=1)?$/);
  assert.equal(people.fetches[0].options.credentials, 'same-origin');
  assert.equal(people.ids.landingPeopleRail.children.length, 2);
  const firstPerson = people.ids.landingPeopleRail.children[0];
  assert.equal(firstPerson.querySelector('h3').textContent, '<b>첫 연구자</b>');
  assert.equal(firstPerson.querySelector('b'), null, 'display name must remain plain text');
  const portraits = people.ids.landingPeopleRail.querySelectorAll('img');
  assert(portraits.length > 0); assert(portraits.every(image => image.src === undefined && image.loading === 'lazy'));
  people.intersect(portraits[0], true); assert.match(portraits[0].src, /^\/portraits\/.+\.webp$/);
  firstPerson.querySelector('button').click(); await settle();
  assert.equal(people.cards[0][0], 'PUB-Z'); assert.equal(people.cards[0][1], firstPerson.querySelector('button'));
  assert.equal(people.intervals.size, 1); [...people.intervals.values()][0]();
  const links = people.ids.landingFieldList.querySelectorAll('a');
  assert.equal(links[1].classList.contains('is-current'), true);
  people.intersect(people.ids.landingFields, true, 0); assert.equal(people.intervals.size, 0, 'edge contact does not count as a visible rotating list');
  people.intersect(people.ids.landingFields, true); assert.equal(people.intervals.size, 1);
  people.media.matches = true; people.mediaEvents.forEach(fn => fn()); assert.equal(people.intervals.size, 0);
  const rail = people.ids.landingFeatureRail;
  assert.equal(rail.emit('keydown', {key: 'ArrowRight'}).defaultPrevented, true); assert.equal(rail.scrolledBy.behavior, 'instant');
  rail.emit('keydown', {key: 'End'}); assert.equal(rail.scrolledTo.left, rail.scrollWidth);
  assert.equal(rail.emit('keydown', {key: 'ArrowLeft', ctrlKey: true}).defaultPrevented, undefined);
  people.ask.click(); assert.equal(people.doc.activeElement, people.ids.message); assert.equal(people.win.scrolledTo.top, 0); assert.equal(people.win.scrolledTo.behavior, 'instant');
  people.login.click(); assert.equal(people.ids.accountToggle.clicks, 1); assert.equal(people.doc.activeElement, people.ids.googleLogin);
  assert.equal(people.ids.accountMenu.hidden, false, 'footer login must survive the account menu outside-click listener');
  people.feedback.click(); assert.equal(people.existingFeedback.clicks, 1); people.ids.feedbackDialog.emit('close'); assert.equal(people.doc.activeElement, people.feedback);

  const map = harness('map'); landing.init(map.win);
  map.intersect(map.ids.landingMap, false); await settle(); assert.deepEqual(map.scripts, []); assert.equal(map.fetches.length, 0);
  map.intersect(map.ids.landingMap, true, 0); await settle(); assert.deepEqual(map.scripts, []); assert.deepEqual(map.mapMounts, []);
  map.intersect(map.ids.landingMap, true); await settle();
  assert.deepEqual(map.scripts, ['/landing-map-preview.js']); assert.deepEqual(map.mapMounts, [map.ids.landingMapCanvas]);

  // The small entry waits for a positive intersection and reuses original card actions.
  for (const quiet of [false, true]) {
    const h = harness('map', quiet); h.doc.body.dataset.landingAssets = JSON.stringify({'/landing.js': '/landing.js?v=abc'});
    runBoot(h); assert.equal(h.doc.head.children.length, 0); assert.equal(h.ids.landingPeople.hidden, true); assert.equal(h.ids.landingMap.hidden, false);
    await h.win.Landing.openPersonCard('PUB-Z', h.ask); assert.equal(h.cards.length, 1); assert.equal(h.doc.head.children.length, 0);
    h.ids.landingDown.click(); assert.equal(h.doc.activeElement, h.ids.landingFeatures); assert.equal(h.ids.landingFeatures.scrolledInto.behavior, quiet ? 'instant' : 'smooth');
    h.intersect(h.ids.landingFeatures, false); assert.equal(h.doc.head.children.length, 0);
    h.intersect(h.ids.landingFeatures, true, 0); assert.equal(h.doc.head.children.length, 0, 'touching the viewport edge must not load below-fold code');
    assert(h.observers.every(observer => observer.options.threshold > 0));
    h.intersect(h.ids.landingFeatures, true); assert.equal(h.doc.head.children.length, 1); assert.equal(h.doc.head.children[0].src, '/landing.js?v=abc');
    h.doc.head.children[0].onload(); await settle(); h.intersect(h.ids.landingFeatures, true); assert.equal(h.doc.head.children.length, 1);
  }

  // Dependency ordering is observable through actual loader promises; import is an offline data module.
  const dependencies = harness(); dependencies.doc.body.dataset.landingAssets = JSON.stringify({'/recommendation-map.js': 'data:text/javascript,export const ready=true'});
  runBoot(dependencies);
  const recommendation = dependencies.win.Landing.loadRecommendation();
  const expected = ['/people-map-model.js', '/people-map-layout.js', '/people-map-graph.js', '/people-map.js'];
  for (let index = 0; index < expected.length; index++) {
    assert.equal(dependencies.doc.head.children.length, index + 1);
    const script = dependencies.doc.head.children[index]; assert.equal(script.src, expected[index]);
    script.onload(); await settle();
  }
  assert.equal((await recommendation).ready, true);
  await dependencies.win.Landing.loadRecommendation(); assert.equal(dependencies.doc.head.children.length, 4);
  console.log('landing UI contracts passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
