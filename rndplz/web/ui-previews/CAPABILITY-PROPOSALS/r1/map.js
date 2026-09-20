const mountedMaps = new WeakMap();
let mapSequence = 0;

/** Render the supplied, source-linked projection; no requests or persisted state. */
export function initMap(container, data = {}) {
  if (!(container instanceof HTMLElement)) throw new TypeError('A map container is required.');
  mountedMaps.get(container)?.();
  const prefix = `mp-${++mapSequence}`;
  const abort = new AbortController();
  const people = unique(data.people);
  const records = unique(data.records);
  const capabilities = unique(data.capabilities);
  const peopleById = new Map(people.map(person => [person.id, person]));
  const recordsById = new Map(records.map(record => [record.id, record]));
  let activeCapability = capabilities.find(item => item.id === 'process') || capabilities[0] || null;
  let activePersonId = null;
  let frame = 0;
  let destroyed = false;

  function element(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text != null) node.textContent = String(text);
    return node;
  }

  function unique(items) {
    const seen = new Set();
    return (Array.isArray(items) ? items : []).filter(item => {
      if (!item || typeof item.id !== 'string' || seen.has(item.id)) return false;
      seen.add(item.id);
      return true;
    });
  }

  function label(person) {
    return person.name || person.displayName || '이름 미기재';
  }

  function linksFor(capability) {
    const grouped = new Map();
    for (const link of capability?.people || []) {
      if (!peopleById.has(link.id)) continue;
      if (!grouped.has(link.id)) grouped.set(link.id, { id: link.id, scopes: [], recordIds: [] });
      const item = grouped.get(link.id);
      if (link.scope && !item.scopes.includes(link.scope)) item.scopes.push(link.scope);
      for (const id of Array.isArray(link.recordIds) ? link.recordIds : []) {
        if (recordsById.has(id) && !item.recordIds.includes(id)) item.recordIds.push(id);
      }
    }
    return [...grouped.values()];
  }

  function publicUrl(value, image = false) {
    if (typeof value !== 'string' || !value.trim()) return null;
    try {
      const url = new URL(value, document.baseURI);
      if (!['https:', 'http:'].includes(url.protocol)) return null;
      // Portraits are supplied with the static package, never fetched from another host.
      if (image && url.origin !== location.origin) return null;
      return url.href;
    } catch { return null; }
  }

  const root = element('section', 'mp-map');
  root.setAttribute('aria-label', '역량별 인물과 연결 근거');
  const layout = element('div', 'mp-layout');
  const navigation = element('nav', 'mp-navigation');
  const navigationTitle = element('h3', 'mp-section-label', '찾고 있는 역량');
  navigationTitle.id = `${prefix}-navigation-title`;
  navigation.setAttribute('aria-labelledby', navigationTitle.id);
  const capabilityList = element('div', 'mp-capability-list');
  navigation.append(navigationTitle, capabilityList);

  const stage = element('section', 'mp-stage');
  stage.id = `${prefix}-stage`;
  const stageHeader = element('header', 'mp-stage-header');
  const stageKicker = element('p', 'mp-section-label', '자료로 연결된 사람');
  const stageTitle = element('h3', 'mp-stage-title');
  stageTitle.id = `${prefix}-stage-title`;
  stage.setAttribute('aria-labelledby', stageTitle.id);
  const stageDescription = element('p', 'mp-stage-description');
  const stageCount = element('p', 'mp-stage-count');
  stageHeader.append(stageKicker, stageTitle, stageDescription, stageCount);
  const graph = element('div', 'mp-graph');
  const lines = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  lines.classList.add('mp-lines');
  lines.setAttribute('aria-hidden', 'true');
  lines.setAttribute('focusable', 'false');
  const capabilityNode = element('div', 'mp-capability-node');
  const peopleList = element('div', 'mp-people');
  peopleList.setAttribute('role', 'group');
  peopleList.setAttribute('aria-label', '근거를 볼 인물');
  graph.append(lines, capabilityNode, peopleList);
  stage.append(stageHeader, graph, element('p', 'mp-connection-note', '연결선은 이 역량과 관련된 자료가 있음을 나타냅니다.'));

  const evidence = element('section', 'mp-evidence');
  evidence.id = `${prefix}-evidence`;
  const evidenceTitle = element('h3', 'mp-evidence-title');
  evidenceTitle.id = `${prefix}-evidence-title`;
  evidence.setAttribute('aria-labelledby', evidenceTitle.id);
  const evidenceScope = element('p', 'mp-evidence-scope');
  const evidenceList = element('div', 'mp-evidence-list');
  evidence.append(element('p', 'mp-section-label', '선택한 사람의 연결 근거'), evidenceTitle, evidenceScope, evidenceList);
  layout.append(navigation, stage, evidence);

  const footer = element('footer', 'mp-footer');
  footer.append(element('p', '', '자료에 나타난 주제를 연결했습니다. 숙련도·직접 수행 범위·현재 협업 가능성을 평가한 결과는 아닙니다.'));
  const status = element('p', 'mp-sr-only');
  status.setAttribute('role', 'status');
  status.setAttribute('aria-live', 'polite');
  status.setAttribute('aria-atomic', 'true');
  root.append(layout, footer, status);
  container.replaceChildren(root);

  capabilities.forEach((capability, index) => {
    const button = element('button', 'mp-capability');
    button.type = 'button';
    button.dataset.mpCapability = capability.id;
    button.setAttribute('aria-controls', `${prefix}-stage ${evidence.id}`);
    button.setAttribute('aria-pressed', 'false');
    const count = linksFor(capability).length;
    button.append(
      element('span', 'mp-capability-index', String(index + 1).padStart(2, '0')),
      element('span', 'mp-capability-label', capability.label || '분류 미기재'),
      element('span', 'mp-capability-count', `${count}명`)
    );
    capabilityList.append(button);
  });

  function renderPeople() {
    const links = linksFor(activeCapability);
    if (!links.some(link => link.id === activePersonId)) activePersonId = links[0]?.id || null;
    stageTitle.textContent = activeCapability?.label || '연결된 역량이 없습니다';
    stageDescription.textContent = activeCapability?.description || '';
    const recordCount = new Set(links.flatMap(link => link.recordIds)).size;
    stageCount.textContent = `${links.length}명 · 연결 기록 ${recordCount}개`;
    capabilityNode.replaceChildren(
      element('span', 'mp-node-mark', '↗'),
      element('span', 'mp-node-eyebrow', '선택한 역량'),
      element('strong', 'mp-node-title', activeCapability?.label || '자료 준비 중'),
      element('span', 'mp-node-count', `${links.length}명의 연결 기록`)
    );
    root.dataset.mpCount = String(links.length);
    peopleList.replaceChildren();
    if (!links.length) peopleList.append(element('p', 'mp-empty', '이 분류에 연결된 인물 자료가 없습니다.'));
    for (const link of links) {
      const person = peopleById.get(link.id);
      const button = element('button', 'mp-person');
      button.type = 'button';
      button.dataset.mpPerson = person.id;
      button.setAttribute('aria-controls', evidence.id);
      button.setAttribute('aria-pressed', String(person.id === activePersonId));
      const portrait = element('span', 'mp-portrait');
      const fallback = element('span', 'mp-initial', label(person).slice(0, 1));
      fallback.setAttribute('aria-hidden', 'true');
      portrait.append(fallback);
      const text = element('span', 'mp-person-text');
      text.append(element('strong', 'mp-person-name', label(person)));
      if (person.displayName && person.displayName !== label(person)) text.append(element('span', 'mp-person-original-name', person.displayName));
      if (person.field) text.append(element('span', 'mp-person-field', person.field));
      text.append(element('span', 'mp-person-records', `근거 ${link.recordIds.length}개 보기`));
      const arrow = element('span', 'mp-person-arrow', '↗');
      arrow.setAttribute('aria-hidden', 'true');
      button.append(portrait, text, arrow);
      peopleList.append(button);
    }
    capabilityList.querySelectorAll('[data-mp-capability]').forEach(button => {
      button.setAttribute('aria-pressed', String(button.dataset.mpCapability === activeCapability?.id));
    });
    renderEvidence();
    scheduleLines();
  }

  function renderEvidence() {
    const person = peopleById.get(activePersonId);
    const link = linksFor(activeCapability).find(item => item.id === activePersonId);
    evidenceTitle.textContent = person ? label(person) : '인물을 선택하면 근거를 볼 수 있어요';
    evidenceScope.textContent = link?.scopes.join(' · ') || '';
    evidenceList.replaceChildren();
    peopleList.querySelectorAll('[data-mp-person]').forEach(button => {
      const selected = button.dataset.mpPerson === activePersonId;
      button.setAttribute('aria-pressed', String(selected));
      const portrait = button.querySelector('.mp-portrait');
      const existingImage = portrait.querySelector('img');
      if (!selected) {
        existingImage?.remove();
        return;
      }
      if (existingImage) return;
      const selectedPerson = peopleById.get(activePersonId);
      const portraitUrl = publicUrl(typeof selectedPerson.portrait === 'string' ? selectedPerson.portrait : selectedPerson.portrait?.path, true);
      if (!portraitUrl) return;
      const image = element('img');
      image.alt = '';
      image.width = 108;
      image.height = 144;
      image.loading = 'lazy';
      image.decoding = 'async';
      image.addEventListener('error', () => image.remove(), { once: true, signal: abort.signal });
      image.src = portraitUrl;
      portrait.append(image);
    });
    for (const [index, recordId] of (link?.recordIds || []).entries()) {
      const record = recordsById.get(recordId);
      const detail = element('details', 'mp-record');
      detail.open = index === 0;
      const summary = element('summary', 'mp-record-summary');
      summary.append(
        element('span', 'mp-record-meta', [record.kind || '자료', record.year || '연도 미기재'].join(' · ')),
        element('strong', 'mp-record-title', record.title || '제목 미기재'),
        element('span', 'mp-record-toggle', '근거 읽기')
      );
      const body = element('div', 'mp-record-body');
      if (record.summary) body.append(element('p', 'mp-record-description', record.summary));
      body.append(element('p', 'mp-record-limit', record.limit || '이 기록만으로 개인의 직접 수행 범위나 현재 협업 가능성을 확인할 수 없습니다.'));
      const url = publicUrl(record.sourceUrl);
      if (url) {
        const source = element('a', 'mp-source', '원문 출처 열기 ↗');
        source.href = url;
        source.target = '_blank';
        source.rel = 'noopener noreferrer';
        source.setAttribute('aria-label', `${record.title || '자료'} 원문 출처, 새 탭`);
        body.append(source);
      } else body.append(element('span', 'mp-source-missing', '연결된 원문 주소 없음'));
      detail.append(summary, body);
      evidenceList.append(detail);
    }
    if (person && !link?.recordIds.length) evidenceList.append(element('p', 'mp-empty', '이 역량에 연결된 근거 자료가 아직 없습니다.'));
    scheduleLines();
  }

  function scheduleLines() {
    if (frame || destroyed) return;
    frame = requestAnimationFrame(() => { frame = 0; drawLines(); });
  }

  function drawLines() {
    if (destroyed || !graph.isConnected) return;
    const bounds = graph.getBoundingClientRect();
    const from = capabilityNode.getBoundingClientRect();
    if (!bounds.width || !bounds.height) return;
    lines.setAttribute('viewBox', `0 0 ${bounds.width} ${bounds.height}`);
    lines.replaceChildren();
    for (const button of peopleList.querySelectorAll('[data-mp-person]')) {
      const to = button.getBoundingClientRect();
      const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
      const horizontal = from.right <= to.left;
      const y = to.top + to.height / 2 - bounds.top;
      const x = to.left - bounds.left;
      if (horizontal) {
        const sx = from.right - bounds.left;
        const sy = from.top + from.height / 2 - bounds.top;
        const mid = sx + (x - sx) / 2;
        path.setAttribute('d', `M ${sx} ${sy} C ${mid} ${sy}, ${mid} ${y}, ${x} ${y}`);
      } else {
        const sx = from.left + 12 - bounds.left;
        const sy = from.bottom - bounds.top;
        path.setAttribute('d', `M ${sx} ${sy} V ${y} H ${x}`);
      }
      path.classList.add(button.dataset.mpPerson === activePersonId ? 'mp-line-active' : 'mp-line');
      lines.append(path);
    }
  }

  container.addEventListener('click', event => {
    const target = event.target instanceof Element ? event.target : event.target?.parentElement;
    const capabilityButton = target?.closest('[data-mp-capability]');
    if (capabilityButton && root.contains(capabilityButton)) {
      const next = capabilities.find(item => item.id === capabilityButton.dataset.mpCapability);
      if (!next || next.id === activeCapability?.id) return;
      activeCapability = next;
      activePersonId = null;
      renderPeople();
      status.textContent = `${next.label}. 연결된 인물 ${linksFor(next).length}명. ${peopleById.has(activePersonId) ? `${label(peopleById.get(activePersonId))}의 근거를 표시합니다.` : ''}`;
      return;
    }
    const personButton = target?.closest('[data-mp-person]');
    if (personButton && root.contains(personButton) && linksFor(activeCapability).some(link => link.id === personButton.dataset.mpPerson)) {
      activePersonId = personButton.dataset.mpPerson;
      renderEvidence();
      status.textContent = `${label(peopleById.get(activePersonId))}의 연결 근거를 표시합니다.`;
    }
  }, { signal: abort.signal });

  const observer = typeof ResizeObserver === 'function' ? new ResizeObserver(scheduleLines) : null;
  observer?.observe(graph);
  observer?.observe(peopleList);
  window.addEventListener('resize', scheduleLines, { signal: abort.signal });
  renderPeople();

  function destroy() {
    if (destroyed) return;
    destroyed = true;
    abort.abort();
    observer?.disconnect();
    if (frame) cancelAnimationFrame(frame);
    if (mountedMaps.get(container) === destroy) mountedMaps.delete(container);
  }
  mountedMaps.set(container, destroy);
  return destroy;
}
