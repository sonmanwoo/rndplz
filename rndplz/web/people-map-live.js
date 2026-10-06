/* Live research-map layout and display filter (after the Codex vault-graph prototype).
 * Cards keep moving toward balance; a dragged card stays under the pointer and the rest settle
 * again when it is let go. No DOM, network or application state, so Node tests can run it.
 * Position, distance and degree never rank a person or assert their skill or availability.
 */
(function (root, factory) {
  'use strict';
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.RndPeopleMapLive = factory();
}(typeof window !== 'undefined' ? window : globalThis, function () {
  'use strict';
  const DEFAULTS = Object.freeze({
    filter: '', capabilities: true, topics: true, projects: true, orphans: true,
    labels: true, edges: true, textZoom: 0, nodeSize: 1, lineWidth: 1,
    center: 1, repel: 2, link: 1, distance: 130, groups: Object.freeze([])
  });
  const KINDS = {'사람': 'person', '인물': 'person', person: 'person', people: 'person',
    '역량': 'capability', capability: 'capability', '주제': 'topic', topic: 'topic',
    '프로젝트': 'project', project: 'project'};
  const FIELDS = {type: 'type', '종류': 'type', name: 'name', '이름': 'name', org: 'org', '소속': 'org'};
  // Same comparison as the map search: width-normalised, case-folded, spacing ignored.
  const key = value => String(value == null ? '' : value).normalize('NFKC').replace(/\s+/g, '').toLocaleLowerCase('ko');

  // Words, "quoted phrases", field:value, AND / OR / NOT, a leading - and parentheses.
  // Nodes are {kind, label, org, text}; plain words search label, org and text.
  function compileFilter(query) {
    const tokens = [];
    let i = 0;
    query = String(query == null ? '' : query);
    while (i < query.length) {
      if (/\s/.test(query[i])) { i++; continue; }
      if ('()-'.includes(query[i])) { tokens.push(query[i++]); continue; }
      let value = '', quoted = false;
      while (i < query.length && (quoted || !/[\s()]/.test(query[i]))) {
        const c = query[i++];
        if (c === '"') { quoted = !quoted; continue; }
        value += c;
      }
      if (quoted) throw new Error('닫는 따옴표가 필요해요.');
      if (value) tokens.push({value});
    }
    let cursor = 0;
    const isOp = (token, op) => token && token.value === op;
    function atom() {
      const token = tokens[cursor++];
      if (!token) throw new Error('조건이 비어 있어요.');
      if (token === '-' || isOp(token, 'NOT')) { const child = atom(); return n => !child(n); }
      if (token === '(') {
        const inner = or();
        if (tokens[cursor++] !== ')') throw new Error('닫는 괄호가 필요해요.');
        return inner;
      }
      if (typeof token === 'string' || isOp(token, 'OR') || isOp(token, 'AND')) throw new Error('조건 사이의 연산자를 확인해 주세요.');
      const colon = token.value.indexOf(':'), name = colon < 0 ? '' : token.value.slice(0, colon).toLowerCase();
      const field = colon < 0 ? 'text' : FIELDS[name];
      if (!field) throw new Error('쓸 수 있는 조건: type: · name: · org: (종류: · 이름: · 소속:)');
      const value = key(colon < 0 ? token.value : token.value.slice(colon + 1));
      if (!value) throw new Error(name + ': 뒤에 찾을 말이 필요해요.');
      if (field === 'type') {
        const kind = KINDS[value];
        if (!kind) throw new Error('type: 뒤에는 사람 · 역량 · 주제 · 프로젝트 중 하나를 써 주세요.');
        return n => n.kind === kind;
      }
      if (field === 'name') return n => key(n.label).includes(value);
      if (field === 'org') return n => key(n.org).includes(value);
      return n => key([n.label, n.org, n.text].join(' ')).includes(value);
    }
    function and() {
      let result = atom();
      while (cursor < tokens.length && tokens[cursor] !== ')' && !isOp(tokens[cursor], 'OR')) {
        if (isOp(tokens[cursor], 'AND')) cursor++;
        const a = result, b = atom();
        result = n => a(n) && b(n);
      }
      return result;
    }
    function or() {
      let result = and();
      while (isOp(tokens[cursor], 'OR')) { cursor++; const a = result, b = and(); result = n => a(n) || b(n); }
      return result;
    }
    if (!tokens.length) return () => true;
    const result = or();
    if (cursor !== tokens.length) throw new Error('괄호나 연산자를 확인해 주세요.');
    return result;
  }

  // Nodes within `depth` links of `root` over the given links ({from, to}).
  function reach(root, depth, links) {
    const next = new Map();
    for (const link of links) {
      if (!next.has(link.from)) next.set(link.from, []);
      if (!next.has(link.to)) next.set(link.to, []);
      next.get(link.from).push(link.to); next.get(link.to).push(link.from);
    }
    const seen = new Set([root]);
    let front = [root];
    for (let step = 0; step < depth; step++) {
      const ahead = [];
      for (const id of front) for (const other of next.get(id) || []) if (!seen.has(other)) { seen.add(other); ahead.push(other); }
      front = ahead;
    }
    return seen;
  }

  const GAP = 12;
  // Nodes are {key, x, y, w, h} objects owned by the caller; positions are updated in place.
  class Simulation {
    constructor(settings) { this.settings = {...DEFAULTS, ...settings}; this.aspect = 1; this.alpha = 0; this.setGraph([], []); }
    setGraph(nodes, links) {
      this.nodes = nodes;
      const byKey = new Map(nodes.map(node => [node.key, node]));
      this.links = links.map(link => ({a: byKey.get(link.from), b: byKey.get(link.to)})).filter(link => link.a && link.b);
      nodes.forEach((node, index) => {
        if (!Number.isFinite(node.x) || !Number.isFinite(node.y)) {
          const angle = index * 2.399963, radius = 60 * Math.sqrt(index + 1);
          node.x = Math.cos(angle) * radius; node.y = Math.sin(angle) * radius;
        }
        if (!Number.isFinite(node.vx)) node.vx = 0;
        if (!Number.isFinite(node.vy)) node.vy = 0;
      });
      this.reheat();
    }
    configure(settings) { Object.assign(this.settings, settings); this.reheat(.6); }
    reheat(value = 1) { this.alpha = Math.max(this.alpha, value); }
    get active() { return this.alpha > .003 || this.nodes.some(node => node.fx != null); }
    pin(key, x, y) {
      const node = this.nodes.find(item => item.key === key);
      if (node) { node.fx = node.x = x; node.fy = node.y = y; node.vx = node.vy = 0; this.reheat(.5); }
    }
    release(key) {
      const node = this.nodes.find(item => item.key === key);
      if (node) { delete node.fx; delete node.fy; this.reheat(.7); }
    }
    tick() {
      const s = this.settings, nodes = this.nodes, a = Math.max(.05, this.alpha);
      // A wide stage gets a wide layout: vertical pull grows with the stage's aspect ratio.
      const gx = s.center * .01 * a, gy = gx * Math.max(1, Math.min(2.4, this.aspect));
      for (const node of nodes) { node.vx -= node.x * gx; node.vy -= node.y * gy; }
      for (let i = 0; i < nodes.length; i++) for (let j = i + 1; j < nodes.length; j++) {
        const p = nodes[i], q = nodes[j];
        let dx = p.x - q.x, dy = p.y - q.y, d2 = dx * dx + dy * dy;
        if (d2 < .01) { dx = i % 2 ? .1 : -.1; dy = .1; d2 = .02; }
        const force = s.repel * 40 / Math.max(d2, 900) * a;
        p.vx += dx * force; p.vy += dy * force; q.vx -= dx * force; q.vy -= dy * force;
      }
      for (const {a: p, b: q} of this.links) {
        const dx = q.x - p.x, dy = q.y - p.y, d = Math.max(.1, Math.hypot(dx, dy));
        const f = (d - s.distance) / d * s.link * .04 * a;
        p.vx += dx * f; p.vy += dy * f; q.vx -= dx * f; q.vy -= dy * f;
      }
      let speed = 0;
      for (const node of nodes) {
        if (node.fx != null) { node.x = node.fx; node.y = node.fy; node.vx = node.vy = 0; continue; }
        node.vx *= .7; node.vy *= .7;
        const v = Math.hypot(node.vx, node.vy);
        if (v > 20) { node.vx *= 20 / v; node.vy *= 20 / v; }
        node.x += node.vx; node.y += node.vy; speed += v;
      }
      // Cards keep their size: overlapping boxes are pushed apart along the shorter overlap.
      for (let i = 0; i < nodes.length; i++) for (let j = i + 1; j < nodes.length; j++) {
        const p = nodes[i], q = nodes[j], dx = q.x - p.x, dy = q.y - p.y;
        const ox = (p.w + q.w) / 2 + GAP - Math.abs(dx), oy = (p.h + q.h) / 2 + GAP - Math.abs(dy);
        if (ox <= 0 || oy <= 0) continue;
        const pFixed = p.fx != null, qFixed = q.fx != null;
        if (pFixed && qFixed) continue;
        const share = pFixed ? 0 : qFixed ? 1 : .5;
        if (ox < oy) { const push = Math.sign(dx || (i % 2 ? 1 : -1)) * ox * .5; p.x -= push * share; q.x += push * (1 - share); }
        else { const push = Math.sign(dy || (j % 2 ? 1 : -1)) * oy * .5; p.y -= push * share; q.y += push * (1 - share); }
      }
      this.alpha *= .97;
      this.speed = speed / Math.max(1, nodes.length);
      return this.active;
    }
  }

  return Object.freeze({DEFAULTS, compileFilter, reach, Simulation, key});
}));
