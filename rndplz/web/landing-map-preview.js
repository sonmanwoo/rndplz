/* A quiet, read-only view of the canonical research-map graph and layout. */
(function (root, factory) {
  'use strict';
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.LandingMapPreview = factory(root);
}(typeof window !== 'undefined' ? window : globalThis, function (root) {
  'use strict';
  const mounted = new WeakMap();
  const esc = value => String(value == null ? '' : value).replace(/[&<>"']/g,
    mark => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[mark]));
  const colors = {capability: '#2F7F86', topic: '#4A5BA8', project: '#7A5AA6'};
  const color = kind => colors[kind] || colors.capability;
  const number = value => Number.isFinite(value) ? Math.round(value * 1000) / 1000 : 0;

  function portrait(path) {
    return typeof path === 'string' && /^\/portraits\/[a-z0-9-]+\.(?:png|jpe?g)$/i.test(path)
      ? path.replace(/\.(?:png|jpe?g)$/i, '-thumb.webp') : '';
  }

  function complete(data) {
    return Boolean(data && data.complete === true && data.schema_version === 'people-map-existing-v1' &&
      Array.isArray(data.people) && Array.isArray(data.topics) && Array.isArray(data.capabilities) &&
      data.counts && data.counts.people === data.people.length && Array.isArray(data.featured_ids) &&
      data.counts.featured_people === data.featured_ids.length &&
      data.featured_ids.every(id => data.people.some(person => person && person.id === id)) &&
      data.people.every(person => person && typeof person.id === 'string' && person.id &&
        Array.isArray(person.evidence) && person.record_count === person.evidence.length &&
        Array.isArray(person.topic_ids) && person.evidence.every(record => record &&
          typeof record.id === 'string' && record.id)));
  }

  function render(graph) {
    const people = new Map(graph.visible.map(person => [person.id, person]));
    const nodes = new Map(graph.nodes.map(node => [node.key, node]));
    const bounds = graph.layout.bounds, padding = 24;
    const viewBox = [bounds.minX - padding, bounds.minY - padding,
      Math.max(1, bounds.width + padding * 2), Math.max(1, bounds.height + padding * 2)].map(number).join(' ');
    const lines = graph.edges.map(edge => {
      const from = nodes.get(edge.from), to = nodes.get(edge.to);
      if (!from || !to) return '';
      return '<line x1="' + number(from.x) + '" y1="' + number(from.y) + '" x2="' + number(to.x) +
        '" y2="' + number(to.y) + '" stroke="' + color(edge.kind) +
        '" stroke-opacity=".24" stroke-width="1.4" vector-effect="non-scaling-stroke"/>';
    }).join('');
    const shapes = graph.nodes.map((node, index) => {
      const x = number(node.x), y = number(node.y);
      if (node.type === 'person') {
        const person = people.get(node.id);
        if (!person) return '';
        const image = portrait(person.portrait && person.portrait.path), name = person.name || node.label;
        const clip = 'landing-map-face-' + index;
        return '<g transform="translate(' + x + ' ' + y + ')"><title>' + esc(name) + '</title>' +
          '<circle cy="-8" r="27" fill="var(--paper,#F7F5F3)" stroke="var(--line,#D8D5D1)" stroke-width="1"/>' +
          '<text y="-2" text-anchor="middle" font-size="19" fill="var(--ink,#0D0D0D)">' + esc(Array.from(name)[0] || '') + '</text>' +
          (image ? '<clipPath id="' + clip + '"><circle cy="-8" r="24"/></clipPath><image href="' +
            esc(image) + '" x="-24" y="-32" width="48" height="48" preserveAspectRatio="xMidYMid slice" clip-path="url(#' + clip + ')"/>' : '') +
          '<text y="34" text-anchor="middle" font-size="12" fill="var(--ink,#0D0D0D)">' + esc(name) + '</text></g>';
      }
      const chunks = Array.from(String(node.label || '')).reduce((rows, character, index) => {
        const row = Math.floor(index / 12); rows[row] = (rows[row] || '') + character; return rows;
      }, []);
      return '<g transform="translate(' + x + ' ' + y + ')"><rect x="-68" y="-27" width="136" height="54" rx="14" ' +
        'fill="var(--paper,#F7F5F3)" stroke="' + color(node.kind) + '" stroke-opacity=".65"/>' +
        '<text text-anchor="middle" font-size="12" fill="' + color(node.kind) + '">' +
        chunks.map((row, index) => '<tspan x="0" y="' + number((index - (chunks.length - 1) / 2) * 15 + 4) + '">' + esc(row) + '</tspan>').join('') +
        '</text></g>';
    }).join('');
    return '<svg xmlns="http://www.w3.org/2000/svg" class="landing-map-graph" width="100%" height="100%" viewBox="' + viewBox +
      '" preserveAspectRatio="xMidYMid meet" role="img" aria-label="' + esc(graph.visible.length + '명의 사람과 연구 분야를 잇는 연구 맵 미리보기') + '">' +
      '<desc>현재 연구 맵의 사람과 근거가 있는 분야 연결입니다. 자세한 탐색은 전체 연구 맵에서 할 수 있습니다.</desc>' +
      '<g aria-hidden="true">' + lines + shapes + '</g></svg>';
  }

  async function mount(host) {
    if (mounted.has(host)) return mounted.get(host);
    const work = (async function () {
      try {
        host.dataset.mapState = 'loading';
        host.setAttribute('aria-busy', 'true');
        host.textContent = '연구 맵을 불러오는 중이에요.';
        for (const [name, path] of [['createPeopleMapModel', '/people-map-model.js'],
          ['RndPeopleMapLayout', '/people-map-layout.js'], ['createPeopleMapGraph', '/people-map-graph.js']]) {
          if (!root[name]) await root.Landing.loadScript(path);
        }
        const response = await root.fetch('/api/people-map', {credentials: 'same-origin', headers: {'Accept': 'application/json'}});
        if (!response.ok) throw new Error('map unavailable');
        const data = await response.json();
        if (!complete(data)) throw new Error('incomplete map data');
        if (!host.isConnected) return null;
        const model = root.createPeopleMapModel(data);
        const graph = root.createPeopleMapGraph(model).graph(model.initialState());
        host.innerHTML = render(graph);
        host.dataset.mapState = 'ready';
        return graph;
      } catch (error) {
        mounted.delete(host);
        if (host.isConnected) {
          host.dataset.mapState = 'error';
          host.textContent = '미리보기를 불러오지 못했어요. 전체 연구 맵에서 살펴보세요.';
        }
        return null;
      } finally {
        host.removeAttribute('aria-busy');
      }
    }());
    mounted.set(host, work);
    return work;
  }

  return {mount, render, portrait, complete};
}));
