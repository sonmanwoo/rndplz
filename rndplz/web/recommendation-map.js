/* Presentation only: recommendation membership/evidence belong to the chat result.
 * The existing people-map renderer supplies every node, portrait and relation. */
const instances = new WeakMap();
let instanceNumber = 0;

export function deriveRecommendationFocus(graph, rows) {
  if (!graph || !Array.isArray(graph.nodes) || !Array.isArray(graph.edges)) {
    throw new TypeError('기존 연구맵 자료가 필요합니다.');
  }
  if (!Array.isArray(rows) || !rows.length) throw new TypeError('연결 후보가 필요합니다.');
  const byPerson = new Map(graph.nodes.filter(n => n.type === 'person').map(n => [n.id, n]));
  const byKey = new Map(graph.nodes.map(n => [n.key, n]));
  const seen = new Set();
  const candidates = rows.map(row => {
    if (!row || typeof row.id !== 'string' || !row.id || seen.has(row.id)) {
      throw new TypeError('후보의 등록 ID를 확인할 수 없습니다.');
    }
    seen.add(row.id);
    const node = byPerson.get(row.id);
    if (!node) throw new Error('추천 후보가 기존 연구맵에 없습니다: ' + row.id);
    // Only the evidence projected into this result is authoritative. No tags,
    // names, profile similarity or broader map evidence may extend the result.
    const evidenceIds = new Set((Array.isArray(row.evidence) ? row.evidence : [])
      .map(item => item?.id).filter(id => typeof id === 'string' && id));
    const edges = graph.edges.filter(edge => edge.personId === row.id &&
      Array.isArray(edge.recordIds) && edge.recordIds.some(id => evidenceIds.has(id)) &&
      (edge.from === node.key || edge.to === node.key));
    return { id: row.id, node, evidenceIds: [...evidenceIds], edges };
  });
  const edgeKeys = new Set(candidates.flatMap(c => c.edges.map(edge => edge.key)));
  const matchingEdges = graph.edges.filter(edge => edgeKeys.has(edge.key));
  const fieldKeys = new Set();
  matchingEdges.forEach(edge => [edge.from, edge.to].forEach(key => {
    if (byKey.get(key)?.type !== 'person' && byKey.has(key)) fieldKeys.add(key);
  }));
  return {
    candidateIds: candidates.map(c => c.id),
    candidateNodes: candidates.map(c => c.node),
    fieldNodes: graph.nodes.filter(node => fieldKeys.has(node.key)),
    matchingEdges,
    unmappedCandidateIds: candidates.filter(c => !c.edges.length).map(c => c.id),
  };
}

// Fail closed before listeners/camera when the mounted layout contract is absent.
// This is containment, not a diagnosis of why a stylesheet did not take effect.
function requireRecommendationMapLayout(win, root, stage, nodeElements) {
  const fail = part => {
    const error = new Error('연구맵 배치 스타일을 확인하지 못했습니다.');
    error.code = 'recommendation_map_layout_not_ready'; error.layoutPart = part;
    throw error;
  };
  const close = (value, expected) => Number.isFinite(Number.parseFloat(value)) && Math.abs(Number.parseFloat(value) - expected) <= .5;
  const positive = value => Number.isFinite(value) && value > 0;
  const origin = (style, x, y) => {
    const parts = style.transformOrigin.split(/\s+/);
    return close(parts[0], x) && close(parts[1], y);
  };
  const clipped = style => ['hidden', 'clip'].includes(style.overflowX) && ['hidden', 'clip'].includes(style.overflowY);
  if (!root.isConnected || !stage.isConnected) fail('mount');
  const stageStyle = win.getComputedStyle(stage), box = stage.getBoundingClientRect();
  if (stageStyle.position !== 'relative' || !clipped(stageStyle) ||
      !positive(stage.clientWidth) || !positive(stage.clientHeight) || !positive(box.width) || !positive(box.height)) fail('stage');
  const nodes = stage.querySelector('.mp-spatial-nodes'), edges = stage.querySelector('.mp-spatial-edges');
  for (const layer of [nodes, edges]) {
    if (!layer || layer.parentElement !== stage) fail('layer-structure');
    const style = win.getComputedStyle(layer);
    if (style.position !== 'absolute' || !origin(style, 0, 0) || !close(style.left, 0) || !close(style.top, 0)) fail('layer-style');
  }
  for (const node of nodeElements) {
    const style = win.getComputedStyle(node), width = Number.parseFloat(style.width), height = Number.parseFloat(style.height);
    if (node.parentElement !== nodes || style.position !== 'absolute' || !positive(width) || !positive(height) || !origin(style, width / 2, height / 2)) fail('node');
    if (!node.classList.contains('mp-spatial-person')) continue;
    if (!close(style.width, 128) || !close(style.height, 124)) fail('person-size');
    const shell = node.querySelector('.mp-face-shell'), face = shell?.querySelector('.mp-node-face');
    if (!shell || !face) fail('face-structure');
    const shellStyle = win.getComputedStyle(shell), faceStyle = win.getComputedStyle(face);
    if (shellStyle.position !== 'relative' || !close(shellStyle.width, 48) || !close(shellStyle.height, 48) ||
        !close(faceStyle.width, 48) || !close(faceStyle.height, 48) || !clipped(faceStyle)) fail('face-style');
    for (const image of face.querySelectorAll('img')) {
      const imageStyle = win.getComputedStyle(image);
      if (!close(imageStyle.width, 48) || !close(imageStyle.height, 48) || imageStyle.objectFit !== 'cover') fail('face-image');
    }
  }
}

export function initRecommendationMap(host, {
  mapData, rows, records, onDetail, quiet = false, animateOnShow = true,
  bottomBoundary = null, onBoundaryFit, onJourneyEnd,
} = {}) {
  const doc = host?.ownerDocument, win = doc?.defaultView;
  if (!host || !doc || !win) throw new TypeError('지도를 표시할 영역이 필요합니다.');
  if (![win.createPeopleMapModel, win.createPeopleMapGraph, win.createPeopleMapView]
    .every(factory => typeof factory === 'function') || !win.RndPeopleMapLayout) {
    throw new Error('기존 연구맵 구성 요소를 불러오지 못했습니다.');
  }
  // The existing model freezes its input. Keep that implementation detail away
  // from the caller's API response and, especially, from saved chat candidates.
  const C = win.createPeopleMapModel(JSON.parse(JSON.stringify(mapData)));
  const state = { ...C.initialState(), scope: 'all', view: 'experience', query: '', topic: '', capability: '' };
  const graph = win.createPeopleMapGraph(C).graph(state);
  const focus = deriveRecommendationFocus(graph, rows);
  const nodeByKey = new Map(graph.nodes.map(node => [node.key, node]));
  const candidateIds = new Set(focus.candidateIds);
  const candidateById = new Map(focus.candidateNodes.map(node => [node.id, node]));
  const rowById = new Map(rows.map(row => [row.id, row]));
  const rowIndexById = new Map(rows.map((row, index) => [row.id, index]));
  const adjacentLabel = '인접 분야 후보 · 직접 근거 부족';
  const matchedFields = new Set(focus.fieldNodes.map(node => node.key));
  const matchedPairs = new Set(focus.matchingEdges.map(edge => edge.from + '\0' + edge.to));

  function readyRecords(items) {
    if (!Array.isArray(items) || items.length !== focus.candidateIds.length ||
      items.some((item, i) => !item || item.id !== focus.candidateIds[i] ||
        typeof item.name !== 'string' || !item.name.trim())) {
      throw new TypeError('표시할 인물은 현재 추천 후보와 같아야 합니다.');
    }
    return items.map(item => ({ ...item }));
  }
  let displayRecords = records === undefined ? null : readyRecords(records);
  const staging = doc.createElement('div');
  staging.innerHTML = win.createPeopleMapView(C).renderMap(state);
  const stage = staging.querySelector('.mp-graph-stage');
  if (!stage || stage.querySelectorAll('[data-map-node]').length !== graph.nodes.length ||
    stage.querySelectorAll('.mp-spatial-edge').length !== graph.edges.length) {
    throw new Error('기존 연구맵을 그대로 표시할 수 없습니다.');
  }
  const uid = 'recommendation-map-' + (++instanceNumber);
  const root = doc.createElement('section');
  root.id = 'peopleMapHost';
  root.className = 'recommendation-map';
  root.setAttribute('aria-label', '현재 추천 후보의 연구맵');
  root.dataset.phase = 'overview';
  const map = doc.createElement('div');
  map.className = 'mp-map';
  const shell = doc.createElement('div');
  shell.className = 'mp-graph-shell mobile-show-map';
  const toolbar = doc.createElement('div');
  toolbar.className = 'rm-toolbar';
  const status = doc.createElement('p');
  status.className = 'rm-status';
  status.id = uid + '-status';
  status.setAttribute('role', 'status');
  status.setAttribute('aria-live', 'polite');
  const actions = doc.createElement('div');
  actions.className = 'rm-actions';
  function button(label, action, parent = actions) {
    const element = doc.createElement('button');
    element.type = 'button'; element.textContent = label;
    element.dataset.rmAction = action; parent.append(element);
    return element;
  }
  button('전체 지도', 'overview');
  const together = button('후보 함께 보기', 'together');
  button('다시 보기', 'replay');
  const skip = button('바로 보기', 'skip');
  toolbar.append(status, actions);
  stage.id = uid + '-stage';
  stage.setAttribute('aria-describedby', uid + '-help ' + status.id);
  const controls = doc.createElement('div');
  controls.className = 'rm-camera-controls';
  button('−', 'out', controls).setAttribute('aria-label', '지도 축소');
  const zoomLevel = doc.createElement('output');
  zoomLevel.setAttribute('aria-label', '확대 비율');
  controls.append(zoomLevel);
  button('+', 'in', controls).setAttribute('aria-label', '지도 확대');
  button('화면 맞춤', 'fit', controls);
  const help = doc.createElement('p');
  help.id = uid + '-help'; help.className = 'rm-help';
  help.textContent = '이 지도에서는 이번 추천 후보만 선택할 수 있어요. 지도 아래 카드나 지도의 후보를 누르면 근거가 열립니다. 지도: 방향키 이동 · + / − 확대 · Home 화면 맞춤.';
  const exploreLink = doc.createElement('a');
  exploreLink.href = '/explore#map'; exploreLink.target = '_blank'; exploreLink.rel = 'noopener';
  exploreLink.textContent = '전체 연구 맵 탐색 ↗';
  help.append(' 다른 등록 인물은 ', exploreLink, '에서 확인해 주세요.');
  const note = doc.createElement('p'); note.className = 'rm-note';
  note.textContent = focus.unmappedCandidateIds.length
    ? '일부 후보의 추천 근거는 이 지도의 연결선에 아직 연결되어 있지 않습니다. 후보를 선택해 추천 근거를 확인해 주세요.'
    : '강조한 연결선은 이번 추천 근거와 일치하는 기존 연구 기록입니다.';
  const list = doc.createElement('div');
  list.className = 'rm-candidates';
  list.setAttribute('role', 'group'); list.setAttribute('aria-label', '현재 요청의 추천 후보');
  // Candidates sit right under the map as a hand of cards; no need to find them on the map.
  shell.append(toolbar, stage, controls, list, help, note);
  map.append(shell); root.append(map);

  const nodeElements = [...stage.querySelectorAll('[data-map-node]')];
  const edgeElements = [...stage.querySelectorAll('.mp-spatial-edge')];
  nodeElements.forEach(element => {
    const node = nodeByKey.get(element.dataset.mapNode);
    if (!node) throw new Error('연구맵 노드를 확인할 수 없습니다.');
    element.removeAttribute('aria-controls');
    if (node.type === 'person') {
      const candidate = candidateIds.has(node.id);
      element.tabIndex = candidate ? 0 : -1;
      element.setAttribute('aria-disabled', String(!candidate));
      if (!candidate) element.removeAttribute('aria-pressed');
      if (candidate && rowById.get(node.id)?.purpose_relation === 'adjacent') {
        const marker = doc.createElement('span');
        marker.className = 'rm-adjacent-marker';
        marker.textContent = '인접';
        marker.setAttribute('aria-hidden', 'true');
        element.append(marker);
        const description = uid + '-context-' + rowIndexById.get(node.id);
        element.setAttribute('aria-describedby',
          [element.getAttribute('aria-describedby'), description].filter(Boolean).join(' '));
      }
    } else {
      // Field controls only move this camera; they never filter candidates.
      element.tabIndex = -1;
      element.removeAttribute('aria-pressed');
    }
  });
  let disposed = false, currentKey, hasShown = false, quietSource = quiet;
  let phase = 0, selectedId = null, running = false, cameraMode = 'overview';
  // Set by show() for a fresh result; cleared once the journey ends or the user picks someone.
  let revealPending = false;
  let camera = { x: 0, y: 0, scale: 1 }, frame = 0, runToken = 0;
  let boundaryInFlow = false, customNodes = null, pointer = null;
  let measuredWidth = 0, measuredHeight = 0;
  let suppressClickUntil = 0;
  const timers = new Set(), removers = [];
  const motion = win.matchMedia?.('(prefers-reduced-motion: reduce)');
  const phaseNames = ['overview', 'fields', 'candidates', 'person'];
  function listen(target, type, handler, options) {
    target.addEventListener(type, handler, options);
    removers.push(() => target.removeEventListener(type, handler, options));
  }
  function isQuiet() {
    try { return !!(motion?.matches || (typeof quietSource === 'function' ? quietSource() : quietSource)); }
    catch { return true; }
  }
  function stop() {
    runToken += 1;
    if (frame) win.cancelAnimationFrame(frame);
    frame = 0;
    timers.forEach(timer => win.clearTimeout(timer)); timers.clear();
    running = false; skip.hidden = true;
    root.setAttribute('aria-busy', 'false');
  }
  function schedule(delay, fn, token = runToken) {
    const timer = win.setTimeout(() => {
      timers.delete(timer);
      if (!disposed && token === runToken) fn();
    }, delay);
    timers.add(timer);
  }
  function dimensions() { return { width: stage.clientWidth || 1, height: stage.clientHeight || 1 }; }
  function cameraFor(nodes, maxScale = 1.35) {
    const { width, height } = dimensions();
    const padding = 40;
    const left = Math.min(...nodes.map(n => n.x - n.width / 2));
    const right = Math.max(...nodes.map(n => n.x + n.width / 2));
    const top = Math.min(...nodes.map(n => n.y - n.height / 2));
    const bottom = Math.max(...nodes.map(n => n.y + n.height / 2));
    const scale = Math.max(.001, Math.min(maxScale,
      Math.max(1, width - padding) / Math.max(1, right - left),
      Math.max(1, height - padding) / Math.max(1, bottom - top)));
    return { x: width / 2 - (left + right) / 2 * scale,
      y: height / 2 - (top + bottom) / 2 * scale, scale };
  }
  function targetCamera() {
    if (cameraMode === 'custom' && customNodes?.length) return cameraFor(customNodes);
    if (phase === 3 && selectedId) return cameraFor([candidateById.get(selectedId)], 1.8);
    if (phase === 2) return cameraFor(focus.candidateNodes, 1.5);
    if (phase === 1) return cameraFor([...focus.fieldNodes, ...focus.candidateNodes], 1.2);
    return cameraFor(graph.nodes, 1.1);
  }
  function applyCamera() {
    if (disposed) return;
    for (const element of nodeElements) {
      const node = nodeByKey.get(element.dataset.mapNode);
      element.style.width = node.width + 'px'; element.style.height = node.height + 'px';
      element.style.transform = 'translate(' + (camera.x + node.x * camera.scale) + 'px,' +
        (camera.y + node.y * camera.scale) + 'px) translate(-50%,-50%) scale(' + camera.scale + ')';
    }
    for (const element of edgeElements) {
      const a = nodeByKey.get(element.dataset.from), b = nodeByKey.get(element.dataset.to);
      if (a && b) element.setAttribute('d', 'M' + (camera.x + a.x * camera.scale) + ',' +
        (camera.y + a.y * camera.scale) + ' L' + (camera.x + b.x * camera.scale) + ',' +
        (camera.y + b.y * camera.scale));
    }
    zoomLevel.textContent = Math.round(camera.scale * 100) + '%';
  }
  function travel(target, duration, done) {
    if (disposed) return;
    if (frame) win.cancelAnimationFrame(frame);
    frame = 0;
    if (isQuiet() || doc.hidden || !duration || !stage.clientWidth) {
      camera = target; applyCamera(); done?.(); return;
    }
    const from = { ...camera }, started = win.performance.now(), token = runToken;
    const tick = now => {
      frame = 0;
      if (disposed || token !== runToken) return;
      const t = Math.min(1, Math.max(0, (now - started) / duration));
      const eased = t * t * (3 - 2 * t);
      camera = { x: from.x + (target.x - from.x) * eased,
        y: from.y + (target.y - from.y) * eased,
        scale: from.scale + (target.scale - from.scale) * eased };
      applyCamera();
      if (t < 1) frame = win.requestAnimationFrame(tick); else done?.();
    };
    frame = win.requestAnimationFrame(tick);
  }
  function paint() {
    root.dataset.phase = phaseNames[phase];
    for (const element of nodeElements) {
      const node = nodeByKey.get(element.dataset.mapNode);
      const isCandidate = node.type === 'person' && candidateIds.has(node.id);
      element.classList.toggle('rm-candidate', phase >= 2 && isCandidate);
      element.classList.toggle('rm-noncandidate', phase >= 2 && node.type === 'person' && !isCandidate);
      element.classList.toggle('rm-selected', phase === 3 && node.id === selectedId && isCandidate);
      element.classList.toggle('rm-related-field', phase >= 1 && matchedFields.has(node.key));
      if (isCandidate) element.setAttribute('aria-pressed', String(phase === 3 && node.id === selectedId));
    }
    edgeElements.forEach(element => element.classList.toggle('rm-related-edge', phase >= 1 &&
      matchedPairs.has(element.dataset.from + '\0' + element.dataset.to)));
    for (const element of list.querySelectorAll('[data-rm-person]')) {
      element.setAttribute('aria-pressed', String(element.dataset.rmPerson === selectedId));
    }
    status.textContent = phase === 0 ? '전체 연구맵' : phase === 1
      ? (focus.fieldNodes.length ? '추천 근거와 연결된 분야' : '추천 후보의 위치를 확인합니다')
      : phase === 3 ? candidateById.get(selectedId).label + ' · 선택한 후보'
      : '이번 요청의 후보 ' + focus.candidateIds.length + '명 · 인물을 선택해 근거를 확인하세요';
    together.textContent = focus.candidateIds.length === 1 ? '후보 보기' : '후보 함께 보기';
  }
  function moveTo(next, animate = true, after) {
    phase = next; cameraMode = phaseNames[next]; customNodes = null;
    paint(); travel(targetCamera(), animate ? 650 : 0, after);
  }
  function journeyEnded() {
    if (!revealPending) return;
    revealPending = false; onJourneyEnd?.();
  }
  function finish() {
    if (disposed || !hasShown) return;
    const skipped = running;
    stop(); selectedId = null; moveTo(2, false);
    if (skipped) journeyEnded();
  }
  function replay() {
    if (disposed || !hasShown) return;
    stop(); selectedId = null;
    if (isQuiet() || doc.hidden) { moveTo(2, false); journeyEnded(); return; }
    running = true; skip.hidden = false; root.setAttribute('aria-busy', 'true');
    moveTo(0, false);
    schedule(420, () => moveTo(1, true, () => schedule(480, () => moveTo(2, true, () => {
      running = false; skip.hidden = true; root.setAttribute('aria-busy', 'false');
      journeyEnded();
    }))));
  }
  // Camera close-up on a candidate without reopening its details (the inspect view drives it).
  function select(id) {
    if (disposed || !hasShown || !candidateIds.has(id)) return;
    revealPending = false; stop(); selectedId = id; moveTo(3);
  }
  function choose(id) {
    if (disposed || !hasShown || !candidateIds.has(id)) return;
    revealPending = false; stop(); selectedId = id; moveTo(3);
    // This callback is the existing person-detail flow, never a new search.
    onDetail?.({ id });
  }
  function fillList() {
    list.replaceChildren();
    displayRecords.forEach(record => {
      const item = doc.createElement('button');
      item.type = 'button'; item.dataset.rmPerson = record.id; item.className = 'rm-hand-card';
      item.setAttribute('aria-pressed', 'false');
      const row = rowById.get(record.id);
      const relation = row?.purpose_relation === 'adjacent' ? 'adjacent' : row?.purpose_relation === 'direct' ? 'direct' : '';
      if (relation) item.dataset.relation = relation;
      const face = doc.createElement('span'); face.className = 'rm-hand-face'; face.setAttribute('aria-hidden', 'true');
      const thumb = typeof record.portrait === 'string' && /^\/portraits\/[A-Za-z0-9_.-]+-detail\.webp$/.test(record.portrait)
        ? record.portrait.replace(/-detail\.webp$/, '-thumb.webp') : '';
      if (thumb) {
        const image = doc.createElement('img');
        image.src = thumb; image.alt = ''; image.decoding = 'async'; image.loading = 'lazy';
        face.append(image);
      } else face.textContent = Array.from(record.name.trim())[0] || '?';
      const name = doc.createElement('strong'); name.textContent = record.name;
      const badge = doc.createElement('span'); badge.className = 'rm-hand-badge';
      badge.textContent = relation === 'adjacent' ? '인접 분야' : relation === 'direct' ? '직접 관련' : '후보';
      const caption = doc.createElement('span'); caption.className = 'rm-hand-caption';
      caption.textContent = record.capability || '이력과 근거 보기';
      item.append(face, name, badge, caption);
      if (row?.purpose_relation === 'adjacent') {
        const context = doc.createElement('span');
        context.className = 'rm-candidate-context';
        context.id = uid + '-context-' + rowIndexById.get(record.id);
        const label = doc.createElement('span');
        label.className = 'rm-purpose-label';
        label.textContent = adjacentLabel;
        context.append(label);
        if (typeof row.purpose_missing === 'string' && row.purpose_missing.trim()) {
          const missing = doc.createElement('span');
          missing.className = 'rm-purpose-missing';
          missing.textContent = '추가 확인 사항 · ' + row.purpose_missing;
          context.append(missing);
        }
        item.append(context);
      }
      list.append(item);
    });
  }
  function refreshBoundary() {
    if (disposed || !hasShown) return;
    // A map and all candidate controls can exceed the viewport on small screens.
    // Keep the existing composer in document flow instead of masking map controls.
    if (bottomBoundary && !boundaryInFlow) {
      boundaryInFlow = true; onBoundaryFit?.(false);
    }
  }
  function show(items, key) {
    if (disposed) return;
    if (hasShown && Object.is(currentKey, key)) return;
    const ready = readyRecords(items);
    stop(); currentKey = key; hasShown = true; selectedId = null;
    displayRecords = ready; root.hidden = false; fillList(); refreshBoundary();
    revealPending = animateOnShow;
    // History restoration is static, but its explicit replay remains available.
    if (animateOnShow) replay(); else finish();
  }
  function cancel({ clear = true } = {}) {
    if (disposed) return;
    stop(); hasShown = false; selectedId = null; pointer = null;
    if (clear) { list.replaceChildren(); root.hidden = true; }
    if (boundaryInFlow) { boundaryInFlow = false; onBoundaryFit?.(true); }
  }
  function setQuiet(value) {
    if (arguments.length) quietSource = value;
    const valueNow = isQuiet();
    if (valueNow && (running || frame)) {
      if (running) finish(); else { stop(); camera = targetCamera(); applyCamera(); }
    }
    return valueNow;
  }
  function zoom(factor) {
    stop(); cameraMode = 'manual';
    const { width, height } = dimensions(), previous = camera.scale;
    const scale = Math.max(.03, Math.min(3, previous * factor));
    camera = { x: width / 2 - (width / 2 - camera.x) * scale / previous,
      y: height / 2 - (height / 2 - camera.y) * scale / previous, scale };
    applyCamera();
  }
  function fitCurrent() {
    stop(); cameraMode = phaseNames[phase]; customNodes = null;
    travel(targetCamera(), 350);
  }
  function click(event) {
    if (disposed || !hasShown || win.performance.now() < suppressClickUntil) return;
    const element = event.target.closest('button');
    if (!element || !root.contains(element)) return;
    if (element.dataset.rmPerson) { choose(element.dataset.rmPerson); return; }
    if (element.dataset.person) { choose(element.dataset.person); return; }
    if (element.dataset.mapNode) {
      const node = nodeByKey.get(element.dataset.mapNode);
      if (node && node.type !== 'person') {
        stop(); cameraMode = 'custom'; customNodes = [node];
        travel(targetCamera(), 450);
      }
      return;
    }
    switch (element.dataset.rmAction) {
      case 'overview': stop(); selectedId = null; moveTo(0); break;
      case 'together': stop(); selectedId = null; moveTo(2); break;
      case 'replay': replay(); break;
      case 'skip': finish(); break;
      case 'in': zoom(1.25); break;
      case 'out': zoom(.8); break;
      case 'fit': fitCurrent(); break;
    }
  }
  function keydown(event) {
    if (!hasShown || event.altKey || event.ctrlKey || event.metaKey) return;
    if (event.key === 'Escape') {
      event.preventDefault(); stop(); selectedId = null; moveTo(2); return;
    }
    // Leave native Enter/Space activation on candidate buttons unchanged.
    if (event.target !== stage) return;
    const pan = { ArrowLeft: [45, 0], ArrowRight: [-45, 0], ArrowUp: [0, 45], ArrowDown: [0, -45] }[event.key];
    if (pan) {
      event.preventDefault(); stop(); cameraMode = 'manual';
      camera.x += pan[0]; camera.y += pan[1]; applyCamera();
    } else if (['+', '=', '-', 'Home'].includes(event.key)) {
      event.preventDefault();
      if (event.key === 'Home') fitCurrent(); else zoom(event.key === '-' ? .8 : 1.25);
    }
  }
  function resize() {
    if (disposed || !hasShown) return;
    const width = stage.clientWidth, height = stage.clientHeight;
    if (width === measuredWidth && height === measuredHeight) { refreshBoundary(); return; }
    measuredWidth = width; measuredHeight = height;
    // Resizing settles to the relevant fit; it cannot restart the journey.
    if (running) finish(); else { stop(); camera = targetCamera(); applyCamera(); }
    refreshBoundary();
  }
  function visibility() {
    if (!doc.hidden || disposed) return;
    if (running) finish(); else { stop(); camera = targetCamera(); applyCamera(); }
    pointer = null;
  }
  function pointerDown(event) {
    // Touch remains native vertical scrolling. Zoom buttons work on every device.
    if (!hasShown || event.pointerType === 'touch' || event.button !== 0) return;
    stop(); pointer = { id: event.pointerId, x: event.clientX, y: event.clientY, moved: false };
  }
  function pointerMove(event) {
    if (!pointer || pointer.id !== event.pointerId) return;
    const x = event.clientX - pointer.x, y = event.clientY - pointer.y;
    if (!pointer.moved && Math.abs(x) + Math.abs(y) < 4) return;
    if (!pointer.moved) stage.setPointerCapture?.(event.pointerId);
    pointer.moved = true; pointer.x = event.clientX; pointer.y = event.clientY;
    cameraMode = 'manual'; camera.x += x; camera.y += y; applyCamera();
  }
  function pointerEnd(event) {
    if (!pointer || pointer.id !== event.pointerId) return;
    if (pointer.moved) suppressClickUntil = win.performance.now() + 150;
    pointer = null;
    if (stage.hasPointerCapture?.(event.pointerId)) stage.releasePointerCapture(event.pointerId);
  }
  const observer = win.ResizeObserver ? new win.ResizeObserver(resize) : null;
  function dispose() {
    if (disposed) return;
    stop(); disposed = true; pointer = null;
    observer?.disconnect(); removers.forEach(remove => remove());
    root.remove();
    if (instances.get(host) === controller) instances.delete(host);
    if (boundaryInFlow) { boundaryInFlow = false; onBoundaryFit?.(true); }
  }
  const controller = { show, cancel, finish, dispose, refreshBoundary, setQuiet, select };
  // Data is checked above; mounted CSS must be ready before listeners/camera.
  instances.get(host)?.dispose();
  host.replaceChildren(root);
  try { requireRecommendationMapLayout(win, root, stage, nodeElements); }
  catch (error) { observer?.disconnect(); root.remove(); throw error; }
  instances.set(host, controller);
  measuredWidth = stage.clientWidth; measuredHeight = stage.clientHeight;
  listen(root, 'click', click);
  listen(stage, 'keydown', keydown);
  listen(stage, 'pointerdown', pointerDown);
  listen(stage, 'pointermove', pointerMove);
  listen(stage, 'pointerup', pointerEnd);
  listen(stage, 'pointercancel', pointerEnd);
  listen(doc, 'visibilitychange', visibility);
  listen(win, 'resize', resize);
  if (motion?.addEventListener) listen(motion, 'change', () => setQuiet());
  listen(stage, 'error', event => {
    const image = event.target;
    if (image?.tagName === 'IMG' && image.closest('.mp-node-face')) {
      image.parentElement.textContent = '그림 없음';
    }
  }, true);
  observer?.observe(stage);
  paint(); camera = targetCamera(); applyCamera();
  return controller;
}
