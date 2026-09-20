/* Deterministic geometry extracted from the fixed research-map preview.
 * No people, records, filters, network or application state are owned here.
 * Source model.js SHA256: d84675b4f7f76d7b5a9fb34070362a23fbe3387dc03bed45baf14d936de19119
 */
(function (root, factory) {
  'use strict';
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.RndPeopleMapLayout = factory();
}(typeof window !== 'undefined' ? window : globalThis, function () {
  'use strict';
  const unique = values => [...new Set(values)];
  const SIZE = Object.freeze({person: Object.freeze({width: 128, height: 124}), capability: Object.freeze({width: 140, height: 60})});
  const GAP = 12;
  const round = value => Math.round(value * 1000) / 1000;

  function boundsFor(nodes) {
    if (!nodes.length) return {minX: 0, minY: 0, maxX: 0, maxY: 0, width: 0, height: 0};
    const minX = Math.min(...nodes.map(n => n.x - n.width / 2));
    const maxX = Math.max(...nodes.map(n => n.x + n.width / 2));
    const minY = Math.min(...nodes.map(n => n.y - n.height / 2));
    const maxY = Math.max(...nodes.map(n => n.y + n.height / 2));
    return {minX: round(minX), minY: round(minY), maxX: round(maxX), maxY: round(maxY), width: round(maxX - minX), height: round(maxY - minY)};
  }
  function center(nodes) {
    const b = boundsFor(nodes), dx = (b.minX + b.maxX) / 2, dy = (b.minY + b.maxY) / 2;
    for (const node of nodes) { node.x = round(node.x - dx); node.y = round(node.y - dy); }
  }

  function compactLayout(nodes, personNodes, fieldNodes) {
    if (personNodes.length === 1) {
      const person = personNodes[0]; person.x = fieldNodes.length ? 108 : 0; person.y = 0;
      fieldNodes.forEach((node, index) => { node.x = -96; node.y = (index - (fieldNodes.length - 1) / 2) * 74; });
    } else {
      // Two cards stay adjacent; their evidence-backed hubs form compact rows.
      personNodes.forEach((node, index) => { node.x = (index - .5) * 144; node.y = 64; });
      const columns = Math.min(3, Math.max(1, fieldNodes.length));
      const rows = Math.ceil(fieldNodes.length / columns);
      fieldNodes.forEach((node, index) => {
        const row = Math.floor(index / columns), rowCount = Math.min(columns, fieldNodes.length - row * columns);
        node.x = (index % columns - (rowCount - 1) / 2) * 158;
        node.y = -42 - (rows - 1 - row) * 74;
      });
    }
    center(nodes);
  }

  // Deterministic offline layout only. Distance, degree and position never
  // indicate a person's skill, rank, collaboration history or availability.
  function connectedComponents(nodes, edges) {
    const byKey = new Map(nodes.map(node => [node.key, node]));
    const neighbours = new Map(nodes.map(node => [node.key, []]));
    for (const edge of edges) { neighbours.get(edge.from).push(edge.to); neighbours.get(edge.to).push(edge.from); }
    const visited = new Set(), components = [];
    for (const node of nodes) {
      if (visited.has(node.key)) continue;
      const queue = [node.key]; visited.add(node.key);
      for (let index = 0; index < queue.length; index += 1) for (const key of neighbours.get(queue[index])) {
        if (!visited.has(key)) { visited.add(key); queue.push(key); }
      }
      const keys = new Set(queue);
      components.push({nodes: queue.map(key => byKey.get(key)), edges: edges.filter(edge => keys.has(edge.from)), neighbours});
    }
    return components.sort((a, b) => b.nodes.length - a.nodes.length || a.nodes[0].key.localeCompare(b.nodes[0].key));
  }
  function layoutComponent(component) {
    const {nodes, edges, neighbours} = component;
    const persons = nodes.filter(node => node.type === 'person'), fields = nodes.filter(node => node.type === 'capability');
    if (persons.length <= 2) { compactLayout(nodes, persons, fields); return; }
    const byKey = new Map(nodes.map(node => [node.key, node]));
    // Initialize from actual graph adjacency, not arbitrary field array order.
    // This unweighted graph centre is a layout device, never a person ranking.
    function distances(start) {
      const values = new Map([[start, 0]]), queue = [start];
      for (let i = 0; i < queue.length; i += 1) for (const key of neighbours.get(queue[i])) if (!values.has(key)) {
        values.set(key, values.get(queue[i]) + 1); queue.push(key);
      }
      return values;
    }
    const rootKey = nodes.map(node => ({key: node.key, distance: [...distances(node.key).values()].reduce((sum, value) => sum + value, 0)})).sort((a, b) => a.distance - b.distance || a.key.localeCompare(b.key))[0].key;
    const children = new Map(nodes.map(node => [node.key, []])), seen = new Set([rootKey]), order = [rootKey];
    for (let i = 0; i < order.length; i += 1) for (const key of neighbours.get(order[i])) if (!seen.has(key)) {
      seen.add(key); children.get(order[i]).push(key); order.push(key);
    }
    const weights = new Map();
    for (const key of [...order].reverse()) weights.set(key, Math.max(1, children.get(key).reduce((sum, child) => sum + weights.get(child), 0)));
    byKey.get(rootKey).x = 0; byKey.get(rootKey).y = 0;
    function branch(key, start, end) {
      let cursor = start;
      const parent = byKey.get(key), descendants = children.get(key), total = descendants.reduce((sum, child) => sum + weights.get(child), 0);
      for (const child of descendants) {
        const span = (end - start) * weights.get(child) / total, angle = cursor + span / 2, node = byKey.get(child);
        node.x = parent.x + Math.cos(angle) * 162; node.y = parent.y + Math.sin(angle) * 142;
        branch(child, cursor, cursor + span); cursor += span;
      }
    }
    branch(rootKey, -Math.PI, Math.PI);
    const anchors = nodes.map(node => ({x: node.x, y: node.y}));
    const nodeIndex = new Map(nodes.map((node, index) => [node.key, index]));
    for (let pass = 0; pass < 440; pass += 1) {
      const force = nodes.map((node, index) => ({x: (anchors[index].x - node.x) * .0004 - node.x * .009, y: (anchors[index].y - node.y) * .0004 - node.y * .024}));
      for (let i = 0; i < nodes.length; i += 1) for (let j = i + 1; j < nodes.length; j += 1) {
        const a = nodes[i], b = nodes[j];
        let dx = b.x - a.x, dy = b.y - a.y;
        if (Math.abs(dx) + Math.abs(dy) < .001) { dx = i % 2 ? .01 : -.01; dy = j % 2 ? .02 : -.02; }
        const distance = Math.max(18, Math.hypot(dx, dy)), strength = 850 / (distance * distance);
        const fx = dx / distance * strength, fy = dy / distance * strength;
        force[i].x -= fx; force[i].y -= fy; force[j].x += fx; force[j].y += fy;
        const ox = (a.width + b.width) / 2 + GAP - Math.abs(dx), oy = (a.height + b.height) / 2 + GAP - Math.abs(dy);
        if (ox > 0 && oy > 0) {
          if (ox < oy) { const push = Math.sign(dx || 1) * (ox + .1) * .34; force[i].x -= push; force[j].x += push; }
          else { const push = Math.sign(dy || 1) * (oy + .1) * .34; force[i].y -= push; force[j].y += push; }
        }
      }
      for (const edge of edges) {
        const i = nodeIndex.get(edge.from), j = nodeIndex.get(edge.to), a = nodes[i], b = nodes[j];
        const dx = b.x - a.x, dy = b.y - a.y, distance = Math.max(1, Math.hypot(dx, dy));
        const pull = (distance - 142) * .055;
        force[i].x += dx / distance * pull; force[i].y += dy / distance * pull;
        force[j].x -= dx / distance * pull; force[j].y -= dy / distance * pull;
      }
      nodes.forEach((node, index) => { node.x += Math.max(-16, Math.min(16, force[index].x)); node.y += Math.max(-16, Math.min(16, force[index].y)); });
    }
    // Preserve actual card/pill dimensions. Expand positions, never shrink nodes.
    for (let pass = 0; pass < 240; pass += 1) {
      let overlaps = 0;
      for (let i = 0; i < nodes.length; i += 1) for (let j = i + 1; j < nodes.length; j += 1) {
        const a = nodes[i], b = nodes[j], dx = b.x - a.x, dy = b.y - a.y;
        const ox = (a.width + b.width) / 2 + GAP - Math.abs(dx), oy = (a.height + b.height) / 2 + GAP - Math.abs(dy);
        if (ox <= 0 || oy <= 0) continue;
        overlaps += 1;
        if (ox < oy) { const delta = Math.sign(dx || (i % 2 ? 1 : -1)) * (ox / 2 + .03); a.x -= delta; b.x += delta; }
        else { const delta = Math.sign(dy || (j % 2 ? 1 : -1)) * (oy / 2 + .03); a.y -= delta; b.y += delta; }
      }
      if (!overlaps) break;
    }
    center(nodes);
  }
  function spatialLayout(nodes, edges) {
    const components = connectedComponents(nodes, edges);
    for (const component of components) { layoutComponent(component); component.bounds = boundsFor(component.nodes); }
    // Separate disconnected groups instead of mixing unrelated cards among links.
    const gap = 32, largest = Math.max(...components.map(component => component.bounds.width));
    const widths = unique([largest, Math.max(largest, 1100), Math.max(largest, 1300), largest + 320, largest + 500]);
    let best = null;
    for (const limit of widths) {
      const placed = [];
      for (const component of components) {
        const width = component.bounds.width, height = component.bounds.height;
        const xs = unique([0, ...placed.map(rect => rect.x + rect.width + gap)]), ys = unique([0, ...placed.map(rect => rect.y + rect.height + gap)]);
        const candidates = [];
        for (const y of ys) for (const x of xs) {
          if (x + width > limit + .01) continue;
          if (placed.some(rect => x < rect.x + rect.width + gap && x + width + gap > rect.x && y < rect.y + rect.height + gap && y + height + gap > rect.y)) continue;
          candidates.push({x, y, width, height, component});
        }
        candidates.sort((a, b) => (a.y + a.height) - (b.y + b.height) || a.x - b.x);
        placed.push(candidates[0]);
      }
      const width = Math.max(...placed.map(rect => rect.x + rect.width)), height = Math.max(...placed.map(rect => rect.y + rect.height));
      const score = Math.max(width / 1300, height / 740) + width * height / (1300 * 740) * .03;
      if (!best || score < best.score) best = {score, placed};
    }
    for (const rect of best.placed) {
      const dx = rect.x - rect.component.bounds.minX, dy = rect.y - rect.component.bounds.minY;
      for (const node of rect.component.nodes) { node.x += dx; node.y += dy; }
    }
    center(nodes);
    return components.map(component => ({key: component.nodes.map(node => node.key).sort()[0], nodeKeys: component.nodes.map(node => node.key), nodeCount: component.nodes.length, edgeCount: component.edges.length, bounds: boundsFor(component.nodes)}));
  }

  function arrange(inputNodes, inputEdges) {
    const nodes = inputNodes.map(node => ({...node, filter: node.filter ? {...node.filter} : null, x: 0, y: 0}));
    const edges = inputEdges.map(edge => ({...edge, recordIds: [...edge.recordIds]}));
    const keys = new Set(nodes.map(node => node.key));
    if (keys.size !== nodes.length || nodes.some(node => !node.key || !['person', 'capability'].includes(node.type) || !Number.isFinite(node.width) || !Number.isFinite(node.height) || node.width <= 0 || node.height <= 0)) {
      throw new TypeError('Unique, sized people-map nodes are required.');
    }
    if (edges.some(edge => !keys.has(edge.from) || !keys.has(edge.to) || edge.from === edge.to)) {
      throw new TypeError('Every people-map edge must connect existing distinct nodes.');
    }
    const persons = nodes.filter(node => node.type === 'person');
    const fields = nodes.filter(node => node.type === 'capability');
    if (!persons.length && nodes.length) throw new TypeError('A field hub requires a visible person.');
    let components = [];
    if (persons.length && persons.length <= 2) compactLayout(nodes, persons, fields);
    else if (persons.length) components = spatialLayout(nodes, edges);
    const bounds = boundsFor(nodes), pad = 24;
    return {nodes, edges, layout: {
      kind: persons.length <= 2 ? 'compact' : 'component-spring', bounds, components,
      width: round(bounds.width + (nodes.length ? pad * 2 : 0)),
      height: round(bounds.height + (nodes.length ? pad * 2 : 0)),
      minViewportAt078: {width: nodes.length ? Math.ceil(bounds.width * .78 + pad * 2) : 0, height: nodes.length ? Math.ceil(bounds.height * .78 + pad * 2) : 0},
      target: {width: 1300, height: 740}, gap: GAP,
      personSize: {...SIZE.person}, capabilitySize: {...SIZE.capability}
    }};
  }
  return Object.freeze({arrange, boundsFor, SIZE, GAP});
}));
