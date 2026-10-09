/* A quiet, read-only view of the canonical research-map graph and layout, turning slowly in 3D. */
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
  // The research map's "입체로 보기" pose and pace (people-map-focus.js createLive3D).
  const DEG = Math.PI / 180, TILT = -14 * DEG, ZOOM = .9, SPEED = 6 * DEG;
  const EXTENT = {person: {left: 56, right: 56, top: 36, bottom: 40}, field: {left: 68, right: 68, top: 27, bottom: 27}};

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

  function random(key) {
    let hash = 2166136261;
    for (const char of String(key)) hash = Math.imul(hash ^ char.charCodeAt(0), 16777619);
    return (hash >>> 0) / 4294967295;
  }

  // Depth as in the research map's 3D view: fields that share people sit near each other in depth,
  // and each person floats near their own fields. Scaled to the layout so the turn reads as volume.
  function scene(graph) {
    const nodes = graph.nodes.map(node => ({key: node.key, person: node.type === 'person', x: node.x, y: node.y, z: 0}));
    const index = new Map(nodes.map((node, i) => [node.key, i]));
    const neighbors = nodes.map(() => new Set());
    for (const edge of graph.edges) {
      const a = index.get(edge.from), b = index.get(edge.to);
      if (a === undefined || b === undefined) continue;
      neighbors[a].add(b); neighbors[b].add(a);
    }
    const fields = nodes.map((node, i) => i).filter(i => !nodes[i].person), springs = [];
    for (let i = 0; i < fields.length; i++) for (let j = i + 1; j < fields.length; j++) {
      const a = fields[i], b = fields[j];
      const shared = [...neighbors[a]].filter(k => nodes[k].person && neighbors[b].has(k)).length;
      if (shared) springs.push({a, b, weight: Math.min(shared, 12)});
    }
    const seed = new Map(fields.map(i => [i, (random(nodes[i].key) * 2 - 1) * 180])), velocity = new Map();
    for (const i of fields) { nodes[i].z = seed.get(i); velocity.set(i, 0); }
    for (let step = 0; step < 100; step++) {
      const force = new Map(fields.map(i => [i, (seed.get(i) - nodes[i].z) * .025]));
      for (const s of springs) {
        const f = (nodes[s.b].z - nodes[s.a].z) * s.weight * .012;
        force.set(s.a, force.get(s.a) + f); force.set(s.b, force.get(s.b) - f);
      }
      for (const i of fields) {
        velocity.set(i, (velocity.get(i) + force.get(i)) * .65);
        nodes[i].z = Math.max(-180, Math.min(180, nodes[i].z + velocity.get(i)));
      }
    }
    nodes.forEach((node, i) => {
      if (!node.person) return;
      const linked = [...neighbors[i]].filter(k => !nodes[k].person);
      node.z = linked.reduce((sum, k) => sum + nodes[k].z, 0) / (linked.length || 1) + (random(node.key) * 2 - 1) * 120;
    });
    const bounds = graph.layout.bounds, unit = Math.max(bounds.width, bounds.height, 1) / 1000;
    for (const node of nodes) node.z *= unit * 1.3;
    const center = {x: 0, y: 0, z: 0};
    for (const node of nodes) { center.x += node.x / nodes.length; center.y += node.y / nodes.length; center.z += node.z / nodes.length; }
    return {nodes, index, center, distance: 1200 * unit * 1.3};
  }

  function project(world, theta) {
    const cy = Math.cos(theta), sy = Math.sin(theta), cx = Math.cos(TILT), sx = Math.sin(TILT), c = world.center;
    const pose = world.nodes.map(node => {
      const x = node.x - c.x, y = node.y - c.y, z = node.z - c.z;
      const rx = x * cy + z * sy, rz = -x * sy + z * cy;
      const ry = y * cx - rz * sx, pz = y * sx + rz * cx;
      const scale = world.distance / Math.max(world.distance * .1, world.distance - pz) * ZOOM;
      return {x: c.x + rx * scale, y: c.y + ry * scale, z: pz, scale, alpha: 1};
    });
    const depths = pose.map(point => point.z), near = Math.max(...depths), far = Math.min(...depths), span = near - far;
    for (const point of pose) point.alpha = .4 + .6 * (span > .001 ? (point.z - far) / span : 1);
    return pose;
  }

  // One box for every angle, so the turn never crops or rescales the drawing.
  function frame(world) {
    const box = {minX: Infinity, minY: Infinity, maxX: -Infinity, maxY: -Infinity}, padding = 16;
    for (let step = 0; step < 36; step++) project(world, step * 10 * DEG).forEach((point, i) => {
      const extent = world.nodes[i].person ? EXTENT.person : EXTENT.field;
      box.minX = Math.min(box.minX, point.x - extent.left * point.scale);
      box.maxX = Math.max(box.maxX, point.x + extent.right * point.scale);
      box.minY = Math.min(box.minY, point.y - extent.top * point.scale);
      box.maxY = Math.max(box.maxY, point.y + extent.bottom * point.scale);
    });
    if (!Number.isFinite(box.minX)) return '0 0 1 1';
    return [box.minX - padding, box.minY - padding, Math.max(1, box.maxX - box.minX + padding * 2),
      Math.max(1, box.maxY - box.minY + padding * 2)].map(number).join(' ');
  }

  const place = point => 'translate(' + number(point.x) + ' ' + number(point.y) + ') scale(' + number(point.scale) + ')';

  function render(graph, world) {
    world = world || scene(graph);
    const pose = project(world, 0);
    const people = new Map(graph.visible.map(person => [person.id, person]));
    const lines = graph.edges.map(edge => {
      const a = world.index.get(edge.from), b = world.index.get(edge.to);
      if (a === undefined || b === undefined) return '';
      return '<line data-from="' + a + '" data-to="' + b + '" x1="' + number(pose[a].x) + '" y1="' + number(pose[a].y) +
        '" x2="' + number(pose[b].x) + '" y2="' + number(pose[b].y) + '" stroke="' + color(edge.kind) +
        '" stroke-opacity=".24" stroke-width="1.4" opacity="' + number((pose[a].alpha + pose[b].alpha) / 2) +
        '" vector-effect="non-scaling-stroke"/>';
    }).join('');
    const order = graph.nodes.map((node, index) => index).sort((a, b) => pose[a].z - pose[b].z);
    const shapes = order.map(index => {
      const node = graph.nodes[index], open = '<g data-k="' + index + '" transform="' + place(pose[index]) +
        '" opacity="' + number(pose[index].alpha) + '">';
      if (node.type === 'person') {
        const person = people.get(node.id);
        if (!person) return '';
        const image = portrait(person.portrait && person.portrait.path), name = person.name || node.label;
        const clip = 'landing-map-face-' + index;
        return open + '<title>' + esc(name) + '</title>' +
          '<circle cy="-8" r="27" fill="var(--paper,#F7F5F3)" stroke="var(--line,#D8D5D1)" stroke-width="1"/>' +
          '<text y="-2" text-anchor="middle" font-size="19" fill="var(--ink,#0D0D0D)">' + esc(Array.from(name)[0] || '') + '</text>' +
          (image ? '<clipPath id="' + clip + '"><circle cy="-8" r="24"/></clipPath><image href="' +
            esc(image) + '" x="-24" y="-32" width="48" height="48" preserveAspectRatio="xMidYMid slice" clip-path="url(#' + clip + ')"/>' : '') +
          '<text y="34" text-anchor="middle" font-size="12" fill="var(--ink,#0D0D0D)">' + esc(name) + '</text></g>';
      }
      const chunks = Array.from(String(node.label || '')).reduce((rows, character, index) => {
        const row = Math.floor(index / 12); rows[row] = (rows[row] || '') + character; return rows;
      }, []);
      return open + '<rect x="-68" y="-27" width="136" height="54" rx="14" ' +
        'fill="var(--paper,#F7F5F3)" stroke="' + color(node.kind) + '" stroke-opacity=".65"/>' +
        '<text text-anchor="middle" font-size="12" fill="' + color(node.kind) + '">' +
        chunks.map((row, index) => '<tspan x="0" y="' + number((index - (chunks.length - 1) / 2) * 15 + 4) + '">' + esc(row) + '</tspan>').join('') +
        '</text></g>';
    }).join('');
    return '<svg xmlns="http://www.w3.org/2000/svg" class="landing-map-graph" width="100%" height="100%" viewBox="' + frame(world) +
      '" preserveAspectRatio="xMidYMid meet" role="img" aria-label="' + esc(graph.visible.length + '명의 사람과 연구 분야를 잇는 연구 맵 미리보기') + '">' +
      '<desc>현재 연구 맵의 사람과 근거가 있는 분야 연결을 입체로 천천히 돌려 보여 줍니다. 자세한 탐색은 전체 연구 맵에서 할 수 있습니다.</desc>' +
      '<g aria-hidden="true"><g>' + lines + '</g><g data-layer="nodes">' + shapes + '</g></g></svg>';
  }

  // Turns only while on screen and the tab is visible; reduced motion keeps the first 3D pose.
  function spin(host, world) {
    const svg = host.querySelector('svg.landing-map-graph'), layer = svg && svg.querySelector('[data-layer="nodes"]');
    if (!layer) return;
    const groups = new Map(Array.from(layer.querySelectorAll('[data-k]'), el => [Number(el.dataset.k), el]));
    const lines = Array.from(svg.querySelectorAll('line[data-from]'), el => ({el, a: Number(el.dataset.from), b: Number(el.dataset.to)}));
    const doc = root.document;
    const quiet = () => (root.Landing && root.Landing.quiet) ? root.Landing.quiet()
      : root.matchMedia('(prefers-reduced-motion: reduce)').matches;
    let theta = 0, last = 0, painted = 0, raf = 0, visible = false, order = '';
    function paint() {
      const pose = project(world, theta);
      for (const [index, el] of groups) {
        el.setAttribute('transform', place(pose[index]));
        el.setAttribute('opacity', String(number(pose[index].alpha)));
      }
      for (const line of lines) {
        const a = pose[line.a], b = pose[line.b];
        line.el.setAttribute('x1', number(a.x)); line.el.setAttribute('y1', number(a.y));
        line.el.setAttribute('x2', number(b.x)); line.el.setAttribute('y2', number(b.y));
        line.el.setAttribute('opacity', String(number((a.alpha + b.alpha) / 2)));
      }
      const sorted = [...groups.keys()].sort((a, b) => pose[a].z - pose[b].z), next = sorted.join(',');
      if (next !== order) { order = next; for (const index of sorted) layer.append(groups.get(index)); }
    }
    function tick(now) {
      raf = 0;
      if (!host.isConnected || !visible || doc.hidden || quiet()) { last = 0; return; }
      if (last) theta = (theta + SPEED * Math.min((now - last) / 1000, .1)) % (Math.PI * 2);
      last = now;
      if (now - painted >= 32) { painted = now; paint(); }
      raf = root.requestAnimationFrame(tick);
    }
    const resume = () => { if (!raf && visible && !doc.hidden) raf = root.requestAnimationFrame(tick); };
    new root.IntersectionObserver(entries => { visible = entries.some(entry => entry.isIntersecting); resume(); }).observe(host);
    doc.addEventListener('visibilitychange', resume);
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
        const world = scene(graph);
        host.innerHTML = render(graph, world);
        host.dataset.mapState = 'ready';
        if (typeof host.querySelector === 'function' && root.requestAnimationFrame && root.IntersectionObserver) spin(host, world);
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

  return {mount, render, portrait, complete, scene, project};
}));
