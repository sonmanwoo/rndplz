/* Optional presentation only. Call decorate after rendering the existing cards.
 * Keeps the original nodes, their order, names, evidence links, and handlers.
 * The current demo has no person-confirmation evidence. Neither hands_on nor
 * proposal acceptance can promote its record-only appearance.
 */
(() => {
  'use strict';
  const selector = '.candidate-card[data-person-id]';
  const roots = new Map();
  const cards = new WeakMap();
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)');
  const fine = window.matchMedia('(hover: hover) and (pointer: fine)');
  const topics = Object.freeze({
    T01:'유체 물성·점도', T02:'소재 호환성', T03:'열화·신뢰성',
    T04:'열전달·유동', T05:'AI 분자 탐색', T06:'전기 절연',
    T07:'사이클로펜타논·산화', T08:'결정화·속도론',
    T_catalyst_handling:'촉매 취급', T_procurement:'자원·이관'
  });
  let enabled = false;
  let active = null;
  let frame = 0;
  let position = null;
  let bounds = null;

  const node = (tag, className, text) => {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (text !== undefined) element.textContent = String(text);
    return element;
  };
  const count = value => Number.isSafeInteger(value) && value >= 0 ? value : null;
  const formatted = value => value === null ? '미확인' : value.toLocaleString('ko-KR');
  const motionEnabled = () => enabled && fine.matches && !reduced.matches && !document.hidden;

  function reset() {
    if (frame) window.cancelAnimationFrame(frame);
    frame = 0;
    if (active) {
      active.classList.remove('is-holo-active');
      for (const key of ['--holo-rx','--holo-ry','--holo-x','--holo-y']) active.style.removeProperty(key);
    }
    active = null; position = null; bounds = null;
  }
  function paint() {
    frame = 0;
    if (!active?.isConnected || !motionEnabled() || !position || !bounds?.width || !bounds?.height) {reset();return;}
    const x = Math.max(0, Math.min(1, (position.x-bounds.left)/bounds.width));
    const y = Math.max(0, Math.min(1, (position.y-bounds.top)/bounds.height));
    active.style.setProperty('--holo-rx', ((0.5-y)*6).toFixed(2)+'deg');
    active.style.setProperty('--holo-ry', ((x-0.5)*6).toFixed(2)+'deg');
    active.style.setProperty('--holo-x', (x*100).toFixed(1)+'%');
    active.style.setProperty('--holo-y', (y*100).toFixed(1)+'%');
    // No self-scheduling loop: only a new pointer event can request a frame.
  }
  function targetCard(target, entry) {
    const card = typeof target?.closest === 'function' ? target.closest(selector) : null;
    return card && entry.root.contains(card) && entry.cards.has(card) ? card : null;
  }
  function move(event, entry) {
    if (event.pointerType === 'touch' || !motionEnabled()) {reset();return;}
    const card = targetCard(event.target, entry);
    if (!card) {reset();return;}
    if (active !== card) {
      reset(); active = card;
      // One layout read when entering a card; scroll/resize invalidate it.
      bounds = card.getBoundingClientRect();
      card.classList.add('is-holo-active');
    }
    position = {x:event.clientX, y:event.clientY};
    if (!frame) frame = window.requestAnimationFrame(paint);
  }
  function attach(root) {
    let entry = roots.get(root);
    if (entry) return entry;
    entry = {root, people:new Map(), cards:new Set()};
    entry.move = event => move(event, entry);
    entry.out = event => {if (active && entry.cards.has(active) && !active.contains(event.relatedTarget)) reset();};
    entry.leave = () => {if (active && entry.cards.has(active)) reset();};
    root.addEventListener('pointermove', entry.move, {passive:true});
    root.addEventListener('pointerout', entry.out, {passive:true});
    root.addEventListener('pointerleave', entry.leave, {passive:true});
    roots.set(root, entry);
    return entry;
  }

  function field(person) {
    const ids = person.topics || [];
    if (person.virtual) return {id:'site', name:'가상 현장', icon:'⌁'};
    if (ids.includes('T08')) return {id:'crystal', name:'결정화', icon:'◇'};
    if (ids.includes('T07')) return {id:'catalysis', name:'촉매·산화', icon:'◈'};
    if (ids.some(id => /^T0[1-6]$/.test(id))) return {id:'cooling', name:'액침냉각', icon:'≋'};
    return {id:'research', name:'연구 기록', icon:'◌'};
  }
  function metric(label, amount, suffix) {
    const box = node('div','rd-holo-metric');
    box.append(node('dt','',label), node('dd','',formatted(amount)+(amount === null ? '' : suffix)));
    return box;
  }
  function decoration(person) {
    const type = field(person);
    const section = node('section','rd-holo-details');
    section.setAttribute('aria-label','기록 카드의 부가 정보');
    section.dataset.holoDecoration = 'true';
    const heading = node('div','rd-holo-heading');
    const typeLabel = node('span','rd-holo-type');
    const icon = node('span','rd-holo-type-icon',type.icon); icon.setAttribute('aria-hidden','true');
    typeLabel.append(icon, node('span','',type.name));
    const hp = node('span','rd-holo-hp');
    hp.append(node('b','','HP '+(person.virtual ? '—' : formatted(count(person.works_count)))));
    hp.append(node('small','',person.virtual ? '전체 논문 수 · 해당 없음' : '전체 논문 수 · 능력 점수 아님'));
    heading.append(typeLabel,hp);

    const art = node('div','rd-holo-art');
    art.dataset.field = type.id;
    art.setAttribute('role','img');
    art.setAttribute('aria-label',type.name+' 분야의 추상 패턴입니다. 인물 사진이 아닙니다.');
    const pattern = node('div','rd-holo-pattern'); pattern.setAttribute('aria-hidden','true');
    pattern.append(node('i','rd-holo-orbit orbit-one'),node('i','rd-holo-orbit orbit-two'),node('i','rd-holo-orbit orbit-three'),node('i','rd-holo-axis'));
    const topicNames = [...new Set((person.topics || []).map(id => topics[id]).filter(Boolean))];
    art.append(pattern, node('span','rd-holo-art-label','사진 없음 · 주제 추상화'),node('span','rd-holo-art-topic',topicNames.slice(0,2).join(' / ') || '기록에 남은 연결'));
    if (person.virtual) art.append(node('span','rd-holo-virtual','가상 현장 기록'));

    const related = count(person.relevant_records);
    const evidenceCount = related ?? (Array.isArray(person.evidence) ? new Set(person.evidence.map(item => item.id).filter(Boolean)).size : null);
    const topicCount = Array.isArray(person.topics) ? new Set(person.topics).size : null;
    const metrics = node('dl','rd-holo-metrics');
    metrics.append(metric('연결 주제',topicCount,'개'),metric('관련 근거 기록',evidenceCount,'건'));
    const level = node('p','rd-holo-level','기록만 · 본인 미확인');
    level.title = '공개 메타데이터와 가상 기록의 확인 상태입니다. 개인 수행 추정이나 시연 수락은 본인 확인 근거가 아닙니다.';
    const limit = node('p','rd-holo-limit','수치는 기록의 범위이며 사람의 역량·가용성을 평가하지 않습니다.');
    const identifier = String(person.id || '기록 ID 미확인');
    const openalex = identifier.match(/^https?:\/\/openalex\.org\/(A\d+)\/?$/);
    const setId = node('p','rd-holo-set',openalex ? 'OpenAlex · '+openalex[1] : (person.virtual ? '가상 인물 · ' : '기록 ID · ')+identifier);
    section.append(heading,art,metrics,level,limit,setId);
    section.hidden = !enabled;
    return section;
  }

  function undecorate(card) {
    if (active === card) reset();
    cards.get(card)?.section.remove();
    cards.delete(card);
    card.classList.remove('rd-holo-card','is-holo-active');
    for (const key of ['holoEnabled','holoLevel','holoVirtual']) delete card.dataset[key];
  }
  function metadata(entry) {
    return {cards:entry?.cards.size || 0, enabled, level:'records', motionEnabled:motionEnabled()};
  }
  function decorate(root, people = []) {
    if (!root || typeof root.querySelectorAll !== 'function') throw new TypeError('후보 카드를 담은 DOM을 지정해 주세요.');
    const entry = attach(root);
    entry.people = new Map((Array.isArray(people) ? people : []).filter(person => person && person.id).map(person => [String(person.id),person]));
    const current = new Set(root.querySelectorAll(selector));
    if (typeof root.matches === 'function' && root.matches(selector)) current.add(root);
    for (const card of entry.cards) {
      if (!current.has(card) || !entry.people.has(card.dataset.personId)) {undecorate(card);entry.cards.delete(card);}
    }
    for (const card of current) {
      const person = entry.people.get(card.dataset.personId);
      if (!person) continue;
      cards.get(card)?.section.remove();
      const section = decoration(person);
      // Add one independent block without recreating the original actionable DOM.
      const anchor = card.querySelector('.person-org') || card.querySelector('.person-name');
      if (anchor?.parentNode === card) anchor.after(section); else card.append(section);
      card.classList.add('rd-holo-card');
      card.dataset.holoEnabled = String(enabled);
      card.dataset.holoLevel = 'records';
      card.dataset.holoVirtual = String(!!person.virtual);
      cards.set(card,{section}); entry.cards.add(card);
    }
    reset();
    return metadata(entry);
  }
  function setEnabled(value) {
    enabled = value === true;
    reset();
    let total = 0;
    for (const entry of roots.values()) for (const card of entry.cards) {
      if (!card.isConnected) continue;
      card.dataset.holoEnabled = String(enabled);
      const section = cards.get(card)?.section;
      if (section) section.hidden = !enabled;
      total++;
    }
    return {cards:total,enabled,level:'records',motionEnabled:motionEnabled()};
  }
  function refresh(root) {
    const entry = roots.get(root);
    return entry ? decorate(root,[...entry.people.values()]) : metadata(null);
  }
  function destroy(root) {
    const entry = roots.get(root);
    if (!entry) return;
    for (const card of entry.cards) undecorate(card);
    root.removeEventListener('pointermove',entry.move);
    root.removeEventListener('pointerout',entry.out);
    root.removeEventListener('pointerleave',entry.leave);
    roots.delete(root);
  }
  reduced.addEventListener('change',reset);
  fine.addEventListener('change',reset);
  window.addEventListener('blur',reset);
  window.addEventListener('resize',reset,{passive:true});
  window.addEventListener('scroll',reset,{capture:true,passive:true});
  document.addEventListener('visibilitychange',reset);
  window.RndplzHolo = Object.freeze({decorate,setEnabled,refresh,destroy});
})();
