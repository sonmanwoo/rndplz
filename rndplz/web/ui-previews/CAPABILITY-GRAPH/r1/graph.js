(function () {
  'use strict';
  const $ = id => document.getElementById(id);
  const svgNS = 'http://www.w3.org/2000/svg';
  const el = (tag, className, text) => { const node = document.createElement(tag); if (className) node.className = className; if (text !== undefined) node.textContent = text; return node; };
  const svgEl = (tag, attributes = {}) => { const node = document.createElementNS(svgNS, tag); for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, String(value)); return node; };
  const safeURL = value => { try { const url = new URL(value); return ['https:', 'http:'].includes(url.protocol) ? url.href : null; } catch { return null; } };
  const textOf = value => typeof value === 'string' ? value : Array.isArray(value) ? value.map(textOf).filter(Boolean).join(' · ') : '';
  const sourceLabels = {self_reported: '본인 제공 경력', provided_resume: '제공된 경력 자료', public_research_case: '공개 연구 자료', curated_public: '공개 연구 자료', public_research: '공개 연구 자료'};
  const sourceLabel = value => sourceLabels[value] || '등록 자료';
  const roleLabels = {unknown: '세부 역할 미확인', first: '첫 번째 저자로 기재', middle: '공동저자로 기재', last: '마지막 저자로 기재', sole: '단독 저자로 기재', recorded_role: '제공 경력에 역할 기재'};
  const contributionLabels = {'listed author': '저자로 기재됨', 'listed author; corresponding author on publisher record': '출판사 기록에 저자·교신저자로 기재됨'};
  const coverageLabels = {selected_roster_author_only: '선정 인물의 저자 기재만 연결 · 전체 저자 목록 미수집', selected_manifest_profile_only: '선정 인물의 저자 기재만 연결 · 전체 저자 목록으로 간주하지 않음', provided_career_subject: '제공 경력의 당사자', full_list_from_publisher_deposited_metadata: '출판사가 제공한 서지의 전체 저자 목록', full_list_from_official_institution_and_publisher_metadata: '공식 기관·출판사 서지의 전체 저자 목록', selected_author_only_full_list_not_collected: '선정 저자만 연결 · 전체 저자 목록 미수집', full_list_from_original_paper_root_spotcheck: '원문 저자 목록 대조', full_list_from_publisher_metadata: '출판사 서지의 전체 저자 목록', full_list_from_official_paper_or_author_institution_metadata: '공식 논문·저자 기관 자료의 전체 저자 목록'};
  let model;
  try { model = window.CapabilityGraphModel.createModel(window.CAPABILITY_GRAPH_DATA); }
  catch (error) { $('data-error').hidden = false; $('data-error').textContent = '자료를 표시할 수 없습니다. ' + error.message; $('workspace').hidden = true; return; }
  const data = model.data;
  const {personDisplayName, personSupportingName} = window.CapabilityGraphModel;
  const state = {query: '', capabilityId: null, personId: null};
  let graph, nodeMap = new Map(), renderKey = '', searchTimer = 0;
  const camera = {scale: 1, x: 0, y: 0};
  const pointers = new Map();
  let gesture = null, suppressClick = false, resizeFrame = 0;
  $('person-total').textContent = String(data.people.length);
  $('record-total').textContent = String(data.records.length);
  if (window.matchMedia('(max-width:720px)').matches) document.querySelector('.people-details').open = false;

  function button(text, className, action, label) {
    const node = el('button', className, text); node.type = 'button'; if (label) node.setAttribute('aria-label', label); node.addEventListener('click', action); return node;
  }
  function appendLink(host, label, value) {
    const href = safeURL(value); if (!href) return;
    const node = el('a', '', label); node.href = href; node.target = '_blank'; node.rel = 'noopener noreferrer'; host.append(node);
  }
  function announce(message) { $('live-status').textContent = message; }
  function preserveFocus() {
    const active = document.activeElement;
    return active?.dataset?.focusKey || null;
  }
  function restoreFocus(key) {
    if (!key) return;
    const replacement = [...document.querySelectorAll('[data-focus-key]')].find(node => node.dataset.focusKey === key);
    (replacement || $('graph')).focus({preventScroll: true});
  }
  function selectCapability(id) {
    if (!model.capabilities.has(id)) return;
    state.capabilityId = id; state.personId = null;
    render();
    announce(model.capabilities.get(id).label + ', 연결된 인물 ' + model.visiblePeople(state).length + '명. 그래프와 인물 목록에서 고를 수 있습니다.');
  }
  function selectPerson(id) {
    if (!model.visiblePeople(state).some(person => person.id === id)) return;
    state.personId = id;
    render();
    announce(personDisplayName(model.people.get(id)) + ' 선택. 이 인물의 전체 근거 ' + model.personRecords(id).length + '개가 열렸습니다.');
  }
  function overview() {
    state.capabilityId = null; state.personId = null;
    render(); announce(state.query ? '분야 필터를 해제했습니다. 검색어는 유지합니다.' : '전체 분야를 보여 줍니다.');
  }
  function renderCapabilities() {
    const host = $('capabilities'); host.replaceChildren();
    model.visibleCapabilities(state).forEach((cap, index) => {
      if (index === 0 || index === 8) host.append(el('p', 'cap-group-label', index === 0 ? '역량별 연결 · 8개 시작점' : '등록 자료의 주제'));
      const node = button('', 'cap-button' + (cap.basisType === 'registered_record_topic' ? ' is-topic' : ''), () => selectCapability(cap.id));
      node.setAttribute('aria-pressed', String(state.capabilityId === cap.id));
      node.setAttribute('aria-label', cap.label + ', 검색 조건에 맞는 인물 ' + cap.visibleCount + '명');
      node.dataset.focusKey = 'cap:' + cap.id;
      node.append(el('span', 'cap-dot'), el('span', 'cap-label', cap.label), el('span', 'count', String(cap.visibleCount)));
      host.append(node);
    });
  }
  function renderPeople() {
    const people = model.visiblePeople(state), host = $('people-list'); host.replaceChildren();
    $('list-count').textContent = String(people.length);
    $('list-context').textContent = state.capabilityId || state.query ? '현재 분야·검색에 해당하는 사람 · 공개 모음 순서' : '전체 ' + data.people.length + '명 · 공개 모음 순서';
    for (const person of people) {
      const node = button(personDisplayName(person), 'person-button', () => selectPerson(person.id));
      const supportingName = personSupportingName(person);
      if (supportingName) node.append(el('br'), el('small', 'original-name', supportingName));
      node.dataset.focusKey = 'person:' + person.id;
      node.setAttribute('aria-pressed', String(state.personId === person.id));
      node.title = person.capabilityLine;
      host.append(node);
    }
    if (!people.length) {
      host.append(el('p', 'list-empty', '이 조건에 연결된 자료가 없습니다. 분야나 검색어를 바꿔 보세요. 역량의 부재를 뜻하지 않습니다.'));
      host.append(button('필터와 검색 지우기', 'text-button', () => { state.query = ''; $('search').value = ''; overview(); $('search').focus(); }));
    }
  }
  function renderBreadcrumbs() {
    const host = $('breadcrumbs'); host.replaceChildren();
    const all = button('전체 분야', '', overview); all.dataset.focusKey = 'crumb:all'; host.append(all);
    const cap = model.capabilities.get(state.capabilityId);
    if (cap) { host.append(el('span', '', ' / ')); const current = button(cap.label, '', () => selectCapability(cap.id)); current.dataset.focusKey = 'crumb:' + cap.id; host.append(current); }
    else if (state.query) host.append(el('span', '', ' / “' + state.query + '” 검색'));
    if (state.personId) host.append(el('span', '', ' / ' + personDisplayName(model.people.get(state.personId))));
  }
  function addDefinition(dl, title, value) { const text = textOf(value); if (!text) return; dl.append(el('dt', '', title), el('dd', '', text)); }
  function recordDetails(record, person) {
    const details = el('details', 'record'); details.id = 'record-' + encodeURIComponent(record.id);
    const summary = el('summary', '', record.title); summary.dataset.focusKey = 'record:' + record.id;
    details.append(summary);
    const role = model.recordRole(record, person.id);
    const kind = record.kind === 'career_record' ? '경력 자료' : record.kind === 'paper' ? '연구 문헌' : '등록 기록';
    details.append(el('p', 'record-meta', [kind, textOf(record.date), sourceLabel(record.sourceType)].filter(Boolean).join(' · ')));
    const cap = model.capabilities.get(state.capabilityId);
    if (cap) {
      const capRecordIds = cap.people.find(link => link.id === person.id)?.recordIds || [];
      details.append(el('p', 'record-meta', capRecordIds.includes(record.id) ? '현재 분야의 연결 근거' : '이 인물의 다른 등록 근거 · 현재 분야의 직접 연결 근거는 아님'));
    }
    if (record.summary) details.append(el('p', '', textOf(record.summary)));
    const dl = el('dl');
    addDefinition(dl, '기록에 기재된 역할', roleLabels[role?.role] || role?.role);
    addDefinition(dl, '기재된 참여 범위', role?.scope);
    addDefinition(dl, '분류된 자료 주제', (record.topics || []).map(topic => typeof topic === 'string' ? topic : topic.label));
    addDefinition(dl, '기여·저자 정보의 범위', contributionLabels[record.contributionNote] || record.contributionNote);
    addDefinition(dl, '저자 정보의 수집 범위', record.authorCoverageNote || coverageLabels[record.authorCoverage]);
    addDefinition(dl, '역할 확인 범위', record.roleVerificationLevel);
    if (record.kind === 'career_record') addDefinition(dl, '기재 기간 원문', record.date);
    details.append(dl);
    if (!role?.role && !role?.scope) details.append(el('p', 'record-meta', '이 자료에는 개인의 구체적인 수행 역할이 별도 기재되지 않았습니다.'));
    const limitation = textOf(record.limit);
    if (limitation) details.append(el('p', 'limit', limitation));
    if (record.sourceAccessNote) details.append(el('p', 'record-meta', textOf(record.sourceAccessNote)));
    if (safeURL(record.url)) appendLink(details, '원문 출처 열기 ↗', record.url);
    else details.append(el('p', 'record-meta', '이 시안에는 별도의 공개 원문 링크가 없습니다. 위 등록 내용만 표시합니다.'));
    return details;
  }
  function assetSources(person) {
    const details = el('details', 'asset-source'); details.append(el('summary', '', '일러스트 출처와 표시 기준'));
    const meta = person.portraitMeta || {}, ref = meta.reference || {};
    details.append(el('p', '', person.portraitLabel || '등록 초상'));
    const credits = [...new Set([person.portraitCredit, meta.generated_credit, meta.credit, ref.credit].filter(value => typeof value === 'string' && value))];
    for (const credit of credits) details.append(el('p', '', credit));
    const notes = [...new Set([meta.reference_note, meta.change_note, meta.generated_change_note].filter(value => typeof value === 'string' && value))];
    for (const note of notes) details.append(el('p', '', note));
    if (meta.generated_license) {
      details.append(el('p', '', '일러스트 라이선스 · ' + meta.generated_license));
      appendLink(details, '일러스트 라이선스 확인 ↗', meta.generated_license_url);
    }
    if (ref.author) details.append(el('p', '', '참고 사진 저작자 · ' + ref.author));
    if (ref.license) details.append(el('p', '', '참고 사진 라이선스 · ' + ref.license));
    appendLink(details, '참고 사진의 라이선스 확인 ↗', ref.license_url);
    appendLink(details, '원래 사진·공식 출처 확인 ↗', ref.url || meta.reference_url);
    if (meta.license && !meta.generated_license) { details.append(el('p', '', '등록 라이선스 표기 · ' + meta.license)); appendLink(details, '등록 라이선스 확인 ↗', meta.license_url); }
    details.append(el('p', '', 'AI 일러스트는 외형을 표현한 그림입니다. 인물의 서명·추천·연락 동의를 뜻하지 않습니다. 원사진을 새로 복제하거나 표시하지 않습니다.'));
    return details;
  }
  function renderInspector() {
    const host = $('inspector'), person = model.people.get(state.personId);
    host.classList.toggle('has-person', Boolean(person));
    if (!person) {
      host.replaceChildren();
      const empty = el('div', 'inspector-empty');
      empty.append(el('div', 'empty-symbol', '↗'), el('p', 'eyebrow', '한 사람, 그 뒤의 근거'), el('h2', '', '사람을 고르면 자료가 이어집니다.'), el('p', '', '이름과 역량을 먼저 보고, 역할·원문·자료의 한계를 확인하세요.'));
      const steps = el('ol'); for (const copy of ['분야를 펼칩니다.', '관심 인물을 고릅니다.', '연결된 근거를 읽습니다.']) steps.append(el('li', '', copy)); empty.append(steps); host.append(empty); return;
    }
    host.replaceChildren();
    const overview = el('div', 'person-overview'), header = el('header', 'person-head');
    header.append(el('p', 'eyebrow', '선택한 인물'), el('h2', '', personDisplayName(person)));
    const supportingName = personSupportingName(person);
    if (supportingName) header.append(el('p', 'original-name', supportingName));
    overview.append(header);
    const portrait = el('figure', 'portrait');
    if (/^(\.\/)?assets\/[a-zA-Z0-9._-]+\.(png|jpe?g|webp)$/i.test(person.portrait || '')) {
      const image = el('img'); image.alt = personDisplayName(person) + ' · ' + (person.portraitLabel || '등록 초상'); image.loading = 'lazy'; image.decoding = 'async'; image.width = 600; image.height = 800; image.src = person.portrait;
      image.addEventListener('error', () => { portrait.replaceChildren(el('div', 'portrait-placeholder', '일러스트를 불러오지 못했습니다.')); }, {once: true}); portrait.append(image);
    } else portrait.append(el('div', 'portrait-placeholder', '등록된 초상이 없습니다.'));
    overview.append(portrait, el('p', 'portrait-note', person.portraitLabel || '등록 초상'), el('p', 'capability-line', person.capabilityLine));
    if (person.org) overview.append(el('p', 'person-org', person.org));
    overview.append(el('span', 'source-pill', sourceLabel(person.sourceType)));
    const profile = person.profile || {};
    if (profile.org_basis || profile.org_as_of) overview.append(el('p', 'person-org', [profile.org_basis, profile.org_as_of].filter(Boolean).join(' · ')));
    host.append(overview);
    const section = el('section', 'detail-section'); section.append(el('h3', '', '연결된 자료 주제'));
    const fields = el('div', 'field-pills');
    for (const cap of model.personCaps(person.id)) { const node = button(cap.label, '', () => { state.capabilityId = cap.id; render(); announce('분야 맥락을 ' + cap.label + '로 바꿨습니다. 선택 인물은 유지합니다.'); }); node.dataset.focusKey = 'context-cap:' + cap.id; fields.append(node); }
    section.append(fields, el('p', '', '자료로 확인된 연결을 보여 줍니다. 실제 수행 범위와 현재 협업 가능성은 별도 확인이 필요합니다.'));
    host.append(section);
    const evidence = el('section', 'detail-section'); evidence.append(el('h3', '', '이 인물의 전체 근거 · ' + model.personRecords(person.id).length + '개'));
    evidence.append(el('p', '', '제목을 펼치면 역할·출처·한계를 볼 수 있습니다. 문헌 날짜는 개인의 참여 기간과 다를 수 있습니다.'));
    for (const record of model.personRecords(person.id)) evidence.append(recordDetails(record, person));
    host.append(evidence, assetSources(person));
  }
  function openRecord(id) {
    const details = $('record-' + encodeURIComponent(id)); if (!details) return;
    details.open = true; details.querySelector('summary').focus({preventScroll: true}); details.scrollIntoView({block: 'nearest', behavior: 'auto'});
    announce('근거를 펼쳤습니다. 제목 다음에 역할과 자료의 한계가 있습니다.');
  }
  function activateNode(node) {
    if (node.type === 'capability') selectCapability(node.id);
    else if (node.type === 'person') selectPerson(node.id);
    else openRecord(node.id);
  }
  function splitLabel(text, limit) {
    const words = String(text).split(/\s+/), lines = []; let line = '';
    for (const word of words) {
      if (line && (line + ' ' + word).length > limit) { lines.push(line); line = word; } else line += (line ? ' ' : '') + word;
    }
    if (line) lines.push(line);
    const chunks = [];
    for (const part of lines) for (let i = 0; i < part.length; i += limit) chunks.push(part.slice(i, i + limit));
    return chunks.slice(0, 3).map((part, i) => i === 2 && chunks.length > 3 ? part.slice(0, limit - 1) + '…' : part);
  }
  function renderGraph() {
    graph = model.graph(state); nodeMap = new Map(graph.nodes.map(node => [node.key, node]));
    const edges = $('graph-edges'), nodes = $('graph-nodes'); edges.replaceChildren(); nodes.replaceChildren();
    $('graph-title').textContent = graph.title;
    $('graph-context').textContent = graph.subtitle;
    $('graph-step').textContent = graph.mode === 'overview' ? '01 · 분야를 고르세요' : graph.mode === 'people' ? '02 · 사람을 고르세요' : '03 · 근거를 확인하세요';
    $('back').hidden = !state.personId;
    $('back').textContent = state.capabilityId ? '← 분야의 사람들' : '← 검색·전체 분야';
    $('go-detail').hidden = !state.personId;
    $('graph-empty').hidden = graph.visible.length > 0;
    $('graph-empty').textContent = '이 조건과 연결된 자료가 없습니다. 분야나 검색어를 바꿔 보세요.';
    $('graph-stage').classList.toggle('is-empty', graph.visible.length === 0);
    for (const edge of graph.edges) {
      const from = nodeMap.get(edge.from), to = nodeMap.get(edge.to);
      const path = svgEl('path', {d: 'M' + from.x + ',' + from.y + ' L' + to.x + ',' + to.y, class: 'graph-edge type-' + edge.type});
      path.dataset.from = edge.from; path.dataset.to = edge.to; edges.append(path);
    }
    for (const node of graph.nodes) {
      const group = svgEl('g', {transform: 'translate(' + node.x + ',' + node.y + ')', class: 'graph-node type-' + node.type + (node.selected ? ' is-selected' : '') + (node.group === 'topic' ? ' is-topic' : '') + (node.evidenceScope === 'other' ? ' is-other-evidence' : ''), role: 'button', tabindex: '0', 'aria-label': node.label + (node.supportingLabel ? ' · ' + node.supportingLabel : '') + (node.count !== undefined ? ' · 연결된 사람 ' + node.count + '명' : node.type === 'record' ? ' · 근거 펼치기' : ' · 인물 선택')});
      group.dataset.focusKey = 'node:' + node.key;
      group.dataset.nodeKey = node.key;
      const radius = node.type === 'capability' ? 11 : node.type === 'person' ? 8 : 5;
      group.append(svgEl('circle', {class: 'hit-target', r: 24}), svgEl('circle', {class: 'node-ring', r: radius + 6}));
      group.append(node.type === 'record' ? svgEl('rect', {class: 'node-dot', x: -5, y: -5, width: 10, height: 10, rx: 2}) : svgEl('circle', {class: 'node-dot', r: radius}));
      const title = svgEl('title'); title.textContent = node.label + (node.supportingLabel ? ' · ' + node.supportingLabel : ''); group.append(title);
      const lines = splitLabel(node.label, node.type === 'record' ? 30 : 21);
      const label = svgEl('text', {'text-anchor': 'middle', y: 30});
      lines.forEach((line, index) => { const span = svgEl('tspan', {x: 0, dy: index ? 18 : 0}); span.textContent = line; label.append(span); }); group.append(label);
      if (node.count !== undefined || node.evidenceScope || node.supportingLabel) { const count = svgEl('text', {class: 'node-count', x: 0, y: 37 + lines.length * 18, 'text-anchor': 'middle'}); count.textContent = node.count !== undefined ? node.count + '명' : node.evidenceScope ? (node.evidenceScope === 'other' ? '다른 등록 기록' : '선택 분야의 근거') : node.supportingLabel; group.append(count); }
      group.addEventListener('click', event => { if (suppressClick) return; event.stopPropagation(); activateNode(node); });
      group.addEventListener('keydown', event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); event.stopPropagation(); activateNode(node); } });
      const highlight = enabled => { for (const path of edges.children) path.classList.toggle('is-highlight', enabled && (path.dataset.from === node.key || path.dataset.to === node.key)); };
      group.addEventListener('pointerenter', () => highlight(true)); group.addEventListener('pointerleave', () => highlight(false)); group.addEventListener('focus', () => highlight(true)); group.addEventListener('blur', () => highlight(false));
      nodes.append(group);
    }
    const nextKey = [state.query, state.capabilityId, state.personId].join('|');
    if (nextKey !== renderKey || !renderKey) { renderKey = nextKey; fit(); } else applyCamera();
  }
  function stageSize() { const rect = $('graph-stage').getBoundingClientRect(); return {width: Math.max(rect.width, 240), height: Math.max(rect.height, 240)}; }
  function applyCamera() {
    $('graph-camera').setAttribute('transform', 'translate(' + camera.x + ',' + camera.y + ') scale(' + camera.scale + ')');
    $('zoom-level').textContent = Math.round(camera.scale * 100) + '%';
  }
  function fit() {
    if (!graph) return;
    const {width, height} = stageSize(); $('graph').setAttribute('viewBox', '0 0 ' + width + ' ' + height);
    const items = graph.nodes;
    if (!items.length) { camera.scale = 1; camera.x = width / 2; camera.y = height / 2; applyCamera(); return; }
    const minX = Math.min(...items.map(node => node.x)) - 120, maxX = Math.max(...items.map(node => node.x)) + 120;
    const minY = Math.min(...items.map(node => node.y)) - 30, maxY = Math.max(...items.map(node => node.y)) + 103;
    camera.scale = Math.max(.2, Math.min(1.25, (width - 36) / (maxX - minX), (height - 85) / (maxY - minY)));
    camera.x = width / 2 - (minX + maxX) / 2 * camera.scale;
    camera.y = (height - 48) / 2 - (minY + maxY) / 2 * camera.scale;
    applyCamera();
  }
  function zoom(factor, position) {
    const {width, height} = stageSize(); const p = position || {x: width / 2, y: height / 2};
    const previous = camera.scale; camera.scale = Math.max(.2, Math.min(3, previous * factor));
    camera.x = p.x - (p.x - camera.x) * camera.scale / previous;
    camera.y = p.y - (p.y - camera.y) * camera.scale / previous;
    applyCamera();
  }
  function localPoint(event) { const rect = $('graph').getBoundingClientRect(); return {x: event.clientX - rect.left, y: event.clientY - rect.top}; }
  function render() {
    const focusKey = preserveFocus();
    const visible = model.visiblePeople(state);
    if (state.personId && !visible.some(person => person.id === state.personId)) state.personId = null;
    $('clear-search').hidden = !state.query;
    renderCapabilities(); renderPeople(); renderBreadcrumbs(); renderInspector(); renderGraph(); restoreFocus(focusKey);
  }
  $('search').addEventListener('input', () => { window.clearTimeout(searchTimer); searchTimer = window.setTimeout(() => { state.query = $('search').value.trim(); render(); announce('현재 조건에 맞는 인물 ' + model.visiblePeople(state).length + '명.'); }, 120); });
  $('clear-search').addEventListener('click', () => { window.clearTimeout(searchTimer); $('search').value = ''; state.query = ''; render(); $('search').focus(); announce('검색어를 지웠습니다. 분야 선택은 유지합니다.'); });
  $('overview').addEventListener('click', overview);
  $('back').addEventListener('click', () => { state.personId = null; render(); $('graph').focus({preventScroll: true}); announce('인물 선택을 해제했습니다. 분야·검색 조건은 유지합니다.'); });
  $('go-detail').addEventListener('click', () => { $('inspector').focus({preventScroll: true}); $('inspector').scrollIntoView({block: 'start', behavior: 'auto'}); });
  $('zoom-in').addEventListener('click', () => zoom(1.25)); $('zoom-out').addEventListener('click', () => zoom(.8)); $('fit').addEventListener('click', fit);
  $('graph').addEventListener('wheel', event => { event.preventDefault(); zoom(Math.exp(-Math.sign(event.deltaY) * .13), localPoint(event)); }, {passive: false});
  $('graph').addEventListener('keydown', event => {
    const movement = event.shiftKey ? 80 : 35;
    if (event.key === '+' || event.key === '=') zoom(1.2);
    else if (event.key === '-') zoom(1 / 1.2);
    else if (event.key === 'Home') fit();
    else if (event.key === 'ArrowLeft') { camera.x += movement; applyCamera(); }
    else if (event.key === 'ArrowRight') { camera.x -= movement; applyCamera(); }
    else if (event.key === 'ArrowUp') { camera.y += movement; applyCamera(); }
    else if (event.key === 'ArrowDown') { camera.y -= movement; applyCamera(); }
    else return; event.preventDefault();
  });
  $('graph').addEventListener('pointerdown', event => {
    if (event.button !== 0) return;
    pointers.set(event.pointerId, localPoint(event));
    if (pointers.size === 1) { const p = localPoint(event); gesture = {x: p.x, y: p.y, startX: p.x, startY: p.y, moved: false, onNode: Boolean(event.target.closest('.graph-node'))}; suppressClick = false; }
    else if (pointers.size === 2) { const [a, b] = [...pointers.values()]; gesture = {distance: Math.hypot(a.x - b.x, a.y - b.y), moved: true}; suppressClick = true; }
    if (!gesture.onNode || pointers.size > 1) $('graph').setPointerCapture(event.pointerId);
  });
  $('graph').addEventListener('pointermove', event => {
    if (!pointers.has(event.pointerId) || !gesture) return;
    const point = localPoint(event); pointers.set(event.pointerId, point);
    if (pointers.size === 2) {
      const [a, b] = [...pointers.values()], distance = Math.hypot(a.x - b.x, a.y - b.y);
      if (gesture.distance > 0) zoom(distance / gesture.distance, {x: (a.x + b.x) / 2, y: (a.y + b.y) / 2}); gesture.distance = distance; suppressClick = true;
    } else if (!gesture.onNode) {
      if (Math.hypot(point.x - gesture.startX, point.y - gesture.startY) > 4) { gesture.moved = true; suppressClick = true; }
      if (gesture.moved) { camera.x += point.x - gesture.x; camera.y += point.y - gesture.y; applyCamera(); $('graph').classList.add('is-dragging'); }
      gesture.x = point.x; gesture.y = point.y;
    }
  });
  const endPointer = event => { if (!pointers.has(event.pointerId)) return; pointers.delete(event.pointerId); if (!pointers.size) { gesture = null; $('graph').classList.remove('is-dragging'); window.setTimeout(() => { suppressClick = false; }, 0); } else { const p = [...pointers.values()][0]; gesture = {x: p.x, y: p.y, startX: p.x, startY: p.y, moved: true, onNode: false}; } };
  window.addEventListener('pointerup', endPointer); window.addEventListener('pointercancel', endPointer);
  window.addEventListener('blur', () => { pointers.clear(); gesture = null; suppressClick = false; $('graph').classList.remove('is-dragging'); });
  const observer = new ResizeObserver(() => { cancelAnimationFrame(resizeFrame); resizeFrame = requestAnimationFrame(fit); }); observer.observe($('graph-stage'));
  render();
  announce('공개 자료 ' + data.people.length + '명과 ' + data.records.length + '개 기록을 준비했습니다. 분야를 고르거나 이름을 검색하세요.');
})();
