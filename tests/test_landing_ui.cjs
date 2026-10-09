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
    this.scrollLeft = 0; this.scrollWidth = 900; this.clientWidth = 400; this.style = {};
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
  getBoundingClientRect() { const top = this.rectTop ?? 0; return {width: 260, top, bottom: top + 40}; }
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
  schema_version: 'people-map-landing-v1',
  counts: {people: 2345, capabilities: 2, records: 6789},
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
  for (const id of ['landingIntro', 'landingDown', 'landingFeatures', 'landingFields', 'landingMap', 'landingMapCanvas', 'landingSources', 'message', 'accountMenu', 'accountToggle', 'googleLogin', 'feedbackDialog', 'chatForm']) element(id);
  element('', ids.landingFeatures, 'h2');
  element('landingFeatureRail', ids.landingFeatures, 'ul').className = 'landing-rail';
  element('', ids.landingFeatureRail, 'li');
  const featureImage = element('', ids.landingFeatures, 'img'); featureImage.dataset.src = '/landing-assets/chat.webp';
  element('landingCounts', ids.landingSources, 'ul').hidden = true;
  element('landingFieldWindow', ids.landingFields, 'div');
  element('landingFieldList', ids.landingFieldWindow, 'ul');
  element('landingFieldsAll', ids.landingFields, 'a');
  for (const host of [ids.landingFields, ids.landingSources]) element('', host, 'p').dataset.landingDataStatus = '';
  const retry = element('', ids.landingFields, 'button'); retry.dataset.landingRetry = '';
  const sourcesRetry = element('', ids.landingSources, 'button'); sourcesRetry.dataset.landingRetry = '';
  const ask = element('', doc.body, 'button'); ask.dataset.landingAsk = '';
  const login = element('', doc.body, 'button'); login.dataset.landingLogin = '';
  const feedback = element('', doc.body, 'button'); feedback.dataset.landingFeedback = '';
  const existingFeedback = element('', doc.body, 'button'); existingFeedback.dataset.feedbackOpen = '';
  const next = element('', ids.landingFeatures, 'button'); next.dataset.landingNext = 'landingFeatureRail';
  ids.accountMenu.hidden = true;
  ids.accountToggle.addEventListener('click', () => { ids.accountMenu.hidden = false; });
  doc.addEventListener('click', event => {
    if (event.target !== ids.accountToggle && !ids.accountMenu.contains(event.target)) ids.accountMenu.hidden = true;
  });
  existingFeedback.addEventListener('click', () => { ids.feedbackDialog.open = true; });
  const observers = [], mediaEvents = [], intervals = new Map(), timeouts = [], fetches = [], scripts = [], mapMounts = [];
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
    innerHeight: 800,
    setInterval(fn, delay) { assert.equal(delay, 1600); intervals.set(++timer, fn); return timer; },
    setTimeout(fn) { timeouts.push(fn); return timeouts.length; },
    clearTimeout() {},
    clearInterval(id) { intervals.delete(id); },
    fetch(url, options) { fetches.push({url, options}); return Promise.resolve({ok: true, json: async () => fixture}); },
    LandingMapPreview: {mount(host) { mapMounts.push(host); return Promise.resolve({}); }},
  });
  win.Landing = {
    quiet: () => media.matches || doc.body.classList.contains('no-motion'),
    loadScript: async url => { scripts.push(url); },
  };
  const intersect = (target, isIntersecting, intersectionRatio = isIntersecting ? 1 : 0) => {
    for (const observer of [...observers]) if (observer.targets.includes(target)) observer.callback([{target, isIntersecting, intersectionRatio}]);
  };
  return {doc, win, ids, featureImage, retry, sourcesRetry, ask, login, feedback, existingFeedback, next, observers, media, mediaEvents, intervals, timeouts, fetches, scripts, mapMounts, intersect};
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

  // The ticker uses only field labels; counts come from the API rather than projected portraits.
  const source = JSON.stringify(fixture), projected = landing.project(fixture);
  assert.equal(JSON.stringify(fixture), source);
  assert.deepEqual(projected.fields, [
    {id: '분리 / 정제', label: '분리·정제'}, {id: 'empty', label: '다른 분야'},
  ]);
  assert.deepEqual(projected.counts, [
    {label: '공개 연구자', value: 2345, unit: '명'},
    {label: '연구 분야', value: 2, unit: '개'},
    {label: '근거 기록', value: 6789, unit: '건'},
  ]);
  assert.equal('people' in projected, false, 'unused person card projections are removed');
  assert.deepEqual(landing.project(null), {fields: [], counts: []});
  assert.deepEqual(landing.project({counts: {people: 0, capabilities: 0}}).counts, [
    {label: '공개 연구자', value: 0, unit: '명'}, {label: '연구 분야', value: 0, unit: '개'},
  ], 'zero is a real count and a missing evidence total is omitted');
  for (const value of [-1, 1.5, '43', Infinity, NaN, null, undefined, Number.MAX_SAFE_INTEGER + 1]) {
    assert.deepEqual(landing.project({counts: {people: value, capabilities: value, records: value}}).counts, []);
  }
  assert.equal(landing.capabilityURL('분리 / 정제'), '/explore?capability=%EB%B6%84%EB%A6%AC%20%2F%20%EC%A0%95%EC%A0%9C#map');

  const page = harness(); landing.init(page.win);
  assert.equal(page.ids.landingCounts.hidden, true, 'counts stay absent until real data arrives');
  assert.equal(page.fetches.length, 0); assert.equal(page.scripts.length, 0); assert.equal(page.featureImage.src, undefined);
  page.intersect(page.ids.landingFields, false); page.intersect(page.featureImage, false);
  assert.equal(page.fetches.length, 0); assert.equal(page.featureImage.src, undefined);
  page.intersect(page.ids.landingFields, true, 0); page.intersect(page.ids.landingSources, true, 0); page.intersect(page.featureImage, true, 0);
  assert.equal(page.fetches.length, 0); assert.equal(page.featureImage.src, undefined); assert.equal(page.intervals.size, 0);
  assert(page.observers.every(observer => observer.options.threshold > 0), 'visibility must cross a positive-area threshold');
  page.intersect(page.featureImage, true); assert.equal(page.featureImage.src, '/landing-assets/chat.webp');
  page.intersect(page.ids.landingFields, true); page.intersect(page.ids.landingSources, true); await settle();
  assert.equal(page.fetches.length, 1); assert.equal(page.fetches[0].url, '/api/people-map?view=home&landing=1');
  assert.equal(page.fetches[0].options.credentials, 'same-origin');
  assert.equal(page.ids.landingCounts.hidden, false);
  const countSentences = h => h.ids.landingCounts.children.map(item => {
    assert.equal(item.tagName, 'LI');
    return item.querySelector('span').textContent.trim() + ' ' + item.querySelector('strong').textContent.replace(/,/g, '');
  });
  assert.deepEqual(countSentences(page), ['공개 연구자 2345명', '연구 분야 2개', '근거 기록 6789건']);
  assert.equal(page.ids.landingSources.querySelector('[data-landing-data-status]').hidden, true);
  assert.equal(page.retry.hidden, true); assert.equal(page.sourcesRetry.hidden, true);
  assert.equal(page.mapMounts.length, 0, 'loading field and count data does not start the research map');
  assert.equal(page.intervals.size, 1); [...page.intervals.values()][0]();
  const links = page.ids.landingFieldList.querySelectorAll('a');
  assert.equal(links[1].classList.contains('is-current'), true);
  assert.equal(page.ids.landingFieldsAll.hidden, false); assert.match(page.ids.landingFieldsAll.textContent, /분야 2개 모두 보기/);
  page.intersect(page.ids.landingFields, true, 0); assert.equal(page.intervals.size, 0, 'edge contact does not count as a visible rotating list');
  page.intersect(page.ids.landingFields, true); assert.equal(page.intervals.size, 1);
  page.media.matches = true; page.mediaEvents.forEach(fn => fn()); assert.equal(page.intervals.size, 0);
  const rail = page.ids.landingFeatureRail;
  assert.equal(rail.emit('keydown', {key: 'ArrowRight'}).defaultPrevented, true); assert.equal(rail.scrolledBy.behavior, 'instant');
  rail.emit('keydown', {key: 'End'}); assert.equal(rail.scrolledTo.left, rail.scrollWidth);
  assert.equal(rail.emit('keydown', {key: 'ArrowLeft', ctrlKey: true}).defaultPrevented, undefined);
  page.ask.click(); assert.equal(page.doc.activeElement, page.ids.message); assert.equal(page.win.scrolledTo.top, 0); assert.equal(page.win.scrolledTo.behavior, 'instant');
  page.login.click(); assert.equal(page.ids.accountToggle.clicks, 1); assert.equal(page.doc.activeElement, page.ids.googleLogin);
  assert.equal(page.ids.accountMenu.hidden, false, 'footer login must survive the account menu outside-click listener');
  page.feedback.click(); assert.equal(page.existingFeedback.clicks, 1); page.ids.feedbackDialog.emit('close'); assert.equal(page.doc.activeElement, page.feedback);

  for (const mode of ['people', 'map']) {
    const map = harness(mode); landing.init(map.win);
    map.intersect(map.ids.landingMap, false); await settle(); assert.deepEqual(map.scripts, []); assert.equal(map.fetches.length, 0);
    map.intersect(map.ids.landingMap, true, 0); await settle(); assert.deepEqual(map.scripts, []); assert.deepEqual(map.mapMounts, []);
    map.intersect(map.ids.landingMap, true); await settle();
    assert.deepEqual(map.scripts, ['/landing-map-preview.js']); assert.deepEqual(map.mapMounts, [map.ids.landingMapCanvas]);
    assert.equal(map.fetches.length, 0, 'the map adapter owns its separate canonical graph request');
    map.intersect(map.ids.landingMap, true); await settle(); assert.equal(map.mapMounts.length, 1);
  }

  // Jumping directly to the data strip loads counts without starting the map or timer.
  const sources = harness(); landing.init(sources.win);
  sources.intersect(sources.ids.landingSources, true, 0); await settle(); assert.equal(sources.fetches.length, 0);
  sources.intersect(sources.ids.landingSources, true); await settle();
  assert.equal(sources.fetches.length, 1); assert.deepEqual(countSentences(sources), countSentences(page));
  assert.equal(sources.mapMounts.length, 0); assert.equal(sources.intervals.size, 0);
  sources.intersect(sources.ids.landingFields, true); await settle(); assert.equal(sources.fetches.length, 1);

  // Failed/invalid counts never become invented zeroes; either visible section can retry.
  for (const retryAtSources of [false, true]) {
    const failed = harness();
    const successfulFetch = failed.win.fetch;
    failed.win.fetch = async () => ({ok: true, json: async () => ({...fixture, counts: {people: -1, capabilities: 2}})});
    landing.init(failed.win); failed.intersect(failed.ids.landingSources, true); await settle();
    assert.equal(failed.ids.landingCounts.children.length, 0); assert.equal(failed.ids.landingCounts.hidden, true);
    assert.equal(failed.retry.hidden, false); assert.equal(failed.sourcesRetry.hidden, false);
    assert.equal(failed.ids.landingSources.querySelector('[data-landing-data-status]').hidden, false);
    failed.win.fetch = successfulFetch;
    (retryAtSources ? failed.sourcesRetry : failed.retry).click(); await settle();
    assert.deepEqual(countSentences(failed), countSentences(page));
    assert.equal(failed.retry.hidden, true); assert.equal(failed.sourcesRetry.hidden, true);
  }

  const withoutRecords = harness();
  withoutRecords.win.fetch = async () => ({ok: true, json: async () => ({...fixture, counts: {people: 0, capabilities: 2}})});
  landing.init(withoutRecords.win); withoutRecords.intersect(withoutRecords.ids.landingSources, true); await settle();
  assert.deepEqual(countSentences(withoutRecords), ['공개 연구자 0명', '연구 분야 2개']);

  // Both opt-in URLs use the same map document; the entry waits for a positive intersection.
  for (const mode of ['people', 'map']) for (const quiet of [false, true]) {
    const h = harness(mode, quiet); h.doc.body.dataset.landingAssets = JSON.stringify({'/landing.js': '/landing.js?v=abc'});
    runBoot(h); assert.equal(h.doc.head.children.length, 0); assert.equal(h.ids.landingMap.hidden, false);
    assert.equal(h.win.Landing.openPersonCard, undefined, 'the removed card strip has no adapter');
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
  // More fields than rows: the highlight stays on the second row and the list slides up one field per step.
  const savedCapabilities = fixture.capabilities;
  fixture.capabilities = Array.from({length: 10}, (_, i) => ({id: 'f' + i, label: '분야 ' + i, people: [{id: 'PUB-A'}]}));
  const ticker = harness(); landing.init(ticker.win);
  ticker.intersect(ticker.ids.landingFields, true); await settle();
  const labels = () => ticker.ids.landingFieldList.querySelectorAll('a').map(link => link.textContent);
  const highlighted = () => ticker.ids.landingFieldList.querySelectorAll('a').findIndex(link => link.classList.contains('is-current'));
  assert.deepEqual(labels(), ['분야 9', '분야 0', '분야 1', '분야 2', '분야 3', '분야 4', '분야 5', '분야 6', '분야 7'], '8 rows plus one waiting below; the first field opens on row 2');
  assert.equal(highlighted(), 1); assert.equal(ticker.ids.landingFieldWindow.style.height, '320px');
  [...ticker.intervals.values()][0]();
  assert.equal(highlighted(), 2, 'the next field takes the highlight as it slides into row 2');
  assert.equal(ticker.ids.landingFieldList.style.transform, 'translateY(-40px)');
  ticker.timeouts.forEach(fn => fn());
  assert.deepEqual(labels().slice(0, 3), ['분야 0', '분야 1', '분야 2']); assert.equal(highlighted(), 1);
  assert.equal(ticker.ids.landingFieldList.style.transform, '');
  fixture.capabilities = savedCapabilities;
  console.log('landing UI contracts passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
