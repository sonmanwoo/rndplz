'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const preview = require('../rndplz/web/landing-map-preview.js');
const createModel = require('../rndplz/web/people-map-model.js');
const createGraph = require('../rndplz/web/people-map-graph.js');
const layout = require('../rndplz/web/people-map-layout.js');

const data = {
  schema_version: 'people-map-existing-v1', complete: true,
  counts: {people: 2, featured_people: 2}, featured_ids: ['P1', 'P2'], topics: [],
  people: [
    {id: 'P1', name: 'First', display_name: '첫 연구자', org: '', profile: {portrait: {path: '/portraits/public-person.png'}},
      topic_ids: [], record_count: 1, evidence: [{id: 'R1', kind: 'paper', title: '첫 근거', tags: []}]},
    {id: 'P2', name: 'Second', display_name: '<script>unsafe</script>', org: '', profile: {portrait: {path: 'https://outside.example/image.png'}},
      topic_ids: [], record_count: 1, evidence: [{id: 'R2', kind: 'paper', title: '둘째 근거', tags: []}]}
  ],
  capabilities: [{id: 'test', label: '실제 연결 & <분야>', description: '근거로만 연결',
    people: [{id: 'P1', scope: '첫 기록', recordIds: ['R1']}, {id: 'P2', scope: '둘째 기록', recordIds: ['R2']}]}]
};
const model = createModel(data), graph = createGraph(model).graph(model.initialState());
assert.equal(preview.complete(data), true);
assert.equal(preview.complete({...data, complete: false}), false);
assert.equal(preview.complete({...data, counts: {people: 3, featured_people: 2}}), false);
assert.equal(preview.complete({...data, people: data.people.map(person => ({...person, evidence: []}))}), false);
assert.equal(preview.complete({...data, featured_ids: ['P1', 'missing']}), false);
assert.equal(preview.portrait('/portraits/public-person.jpeg'), '/portraits/public-person-thumb.webp');
assert.equal(preview.portrait('//remote.example/photo.png'), '');
assert.equal(preview.portrait('/portraits/../secret.png'), '');

const html = preview.render(graph);
assert.equal((html.match(/<line /g) || []).length, graph.edges.length, 'every rendered line has canonical graph evidence');
assert.equal((html.match(/<title>/g) || []).length, graph.visible.length, 'every canonical person remains in the preview');
assert(html.includes('첫 연구자'));
assert(html.includes('&lt;script&gt;unsafe&lt;/script&gt;'));
assert(!html.includes('<script>'));
assert(!html.includes('https://outside'));
assert(html.includes('/portraits/public-person-thumb.webp'));
assert(html.includes('role="img"'));
assert(!html.includes('<button'), 'a scaled graph has no undersized interactive targets');

async function testLazyMount() {
  const loaded = [], requests = [];
  const attributes = new Map();
  const host = {dataset: {}, isConnected: true, innerHTML: '', textContent: '',
    setAttribute(key, value) { attributes.set(key, value); }, removeAttribute(key) { attributes.delete(key); }};
  const win = {
    Landing: {async loadScript(url) {
      loaded.push(url);
      if (url === '/people-map-model.js') win.createPeopleMapModel = createModel;
      if (url === '/people-map-layout.js') win.RndPeopleMapLayout = layout;
      if (url === '/people-map-graph.js') win.createPeopleMapGraph = createGraph;
    }},
    async fetch(url, options) { requests.push({url, options}); return {ok: true, async json() { return data; }}; }
  };
  win.window = win;
  vm.runInNewContext(fs.readFileSync(path.resolve(__dirname, '../rndplz/web/landing-map-preview.js'), 'utf8'), win);
  assert.equal(loaded.length, 0, 'loading the adapter does not load graph code or data');
  assert.equal(requests.length, 0);
  await Promise.all([win.LandingMapPreview.mount(host), win.LandingMapPreview.mount(host)]);
  assert.deepEqual(loaded, ['/people-map-model.js', '/people-map-layout.js', '/people-map-graph.js']);
  assert.equal(requests.length, 1);
  assert.equal(requests[0].url, '/api/people-map');
  assert.equal(requests[0].options.credentials, 'same-origin');
  assert.equal(host.dataset.mapState, 'ready');
  assert(!attributes.has('aria-busy'));
  assert(host.innerHTML.includes('연구 맵 미리보기'));
  await win.LandingMapPreview.mount(host);
  assert.equal(requests.length, 1, 'remounts reuse the graph');

  const failed = {...host, dataset: {}, innerHTML: '', textContent: ''};
  win.fetch = async () => ({ok: true, async json() { return {...data, complete: false}; }});
  assert.equal(await win.LandingMapPreview.mount(failed), null);
  assert.equal(failed.dataset.mapState, 'error');
  assert(failed.textContent.includes('전체 연구 맵'));
  assert.equal(failed.innerHTML, '');
  win.fetch = async () => ({ok: true, async json() { return data; }});
  assert(await win.LandingMapPreview.mount(failed), 'an explicit retry may recover after an incomplete response');
  assert.equal(failed.dataset.mapState, 'ready');
}

testLazyMount().then(() => console.log('landing map preview: passed')).catch(error => {
  console.error(error); process.exitCode = 1;
});
