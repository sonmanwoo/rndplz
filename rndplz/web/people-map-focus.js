/* Research map focus (people-map.js calls RndPeopleMapFocus.attach after mounting):
 * one press on a person focuses them — their circle stays, the rest fades — with a preview card and a step
 * wheel (1 their fields · 2 people in the same fields · 3 one more hop · all); two presses open the person card
 * (app.js, as a [data-map-open="person"] button does); the cube button floats the same cards in 3D.
 * Position and distance never rank a person. No network, storage or model calls.
 */
(function (root) {
  'use strict';
  const attached = new WeakSet();
  function attach(host, controller, core) {
    if (attached.has(host)) return;
    attached.add(host);
    const portraits = new Map(core.people.map(person => {
      const path = person.portrait?.path;
      return [person.id, typeof path === 'string' && /^\/portraits\/[a-z0-9-]+\.(png|jpe?g)$/i.test(path)
        ? path.replace(/\.(png|jpe?g)$/i, '-thumb.webp') : null];
    }));
    // The page's own handler (app.js) opens the person card for a [data-map-open="person"] button in the host.
    let cardShown = null;
    document.getElementById('detailDialog')?.addEventListener('close', () => { cardShown = null; });
    function openCard(id) {
      cardShown = id;
      const button = document.createElement('button');
      button.type = 'button'; button.hidden = true; button.dataset.mapOpen = 'person'; button.dataset.id = id;
      host.append(button); button.click(); button.remove();
    }
    const focusMap = createFocusMap();
    const live3d = createLive3D();
    new MutationObserver(() => { live3d.install(); focusMap.refresh(); }).observe(host, { childList:true, subtree:true });
    live3d.install(); focusMap.refresh();

  function createFocusMap() {
    const debug = window.__focus = { center:null, step:2, visiblePeople:0, faded:0 };
    const people = new Map(core.people.map(p => [p.id, p]));
    const steps = [1, 2, 3, 'all'], depths = [1, 2, 4, Infinity];
    const labels = ['이 사람의 분야', '같은 분야의 사람', '한 다리 더 건넌 사람', '전체'];
    const controls = '.mp-focus-ui,.mp-live-gear,.mp-live-bar,.mp-live-panel,button,input,select,textarea';
    const block = e => { e.preventDefault(); e.stopImmediatePropagation(); };
    let stage, card, wheel, hint, nodes = [], edges = [], ranges = [], counts = [], disabled = [], fields = 0, preferred = 2;
    let history = [], signature = '', lastClick = null, moved = false, revision = 0, fitTimer = 0;
    const pointers = new Map();
    const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    const face = (id, size) => portraits.get(id)
      ? `<img src="${esc(portraits.get(id))}" alt="" width="${size}" height="${size}">`
      : `<span aria-hidden="true">${esc(Array.from(people.get(id)?.name || '')[0] || '')}</span>`;

    function install() {
      const next = host.querySelector('#mp-graph-stage');
      if (next === stage) return;
      stage = next; signature = '';
      if (!stage) return;
      card = document.createElement('section');
      card.className = 'mp-focus-ui mp-focus-card'; card.hidden = true;
      card.setAttribute('aria-label', '미리보기 카드');
      wheel = document.createElement('div');
      wheel.className = 'mp-focus-ui mp-focus-wheel'; wheel.hidden = true;
      wheel.tabIndex = 0; wheel.setAttribute('role', 'slider');
      wheel.setAttribute('aria-label', '연결 단계');
      wheel.setAttribute('aria-valuemin', '1'); wheel.setAttribute('aria-valuemax', '4');
      wheel.innerHTML = steps.map((step, i) => `<button type="button" tabindex="-1" data-focus-step="${step}" aria-label="${labels[i]}">${['1','2','3','∞'][i]}</button>`).join('');
      hint = document.createElement('span'); hint.className = 'mp-focus-hint';
      wheel.append(hint); stage.append(wheel); placeCard();
    }

    // Phones: the preview card is a sheet over the lower screen; fit() keeps the circle above it.
    function placeCard() {
      if (!stage || !card) return;
      const narrow = innerWidth < 760;
      if (narrow && card.previousElementSibling !== stage) stage.after(card);
      else if (!narrow && card.parentElement !== stage) stage.append(card);
      card.classList.toggle('mp-focus-card-below', narrow);
    }

    function refresh(force = false) {
      install();
      if (!stage || !host.isConnected) return;
      nodes = [...stage.querySelectorAll('[data-map-node]')].filter(n => n.style.display !== 'none');
      const keys = new Set(nodes.map(n => n.dataset.mapNode));
      edges = [...stage.querySelectorAll('.mp-spatial-edge')].filter(e => keys.has(e.dataset.from) && keys.has(e.dataset.to) && e.style.display !== 'none');
      const next = JSON.stringify([nodes.map(n => n.dataset.mapNode), edges.map(e => [e.dataset.from,e.dataset.to]), controller?.getState().topic]);
      if (!force && signature === next) return;
      signature = next;
      history = history.filter(id => keys.has('person:' + id));
      if (debug.center && !keys.has('person:' + debug.center)) { clear(); return; }
      if (debug.center) { calculate(); renderCard(); paint(); fit(); }
      else { debug.visiblePeople = nodes.filter(n => n.dataset.person).length; debug.faded = 0; }
    }

    function calculate() {
      const adjacent = new Map(nodes.map(n => [n.dataset.mapNode, []]));
      for (const e of edges) { adjacent.get(e.dataset.from).push(e.dataset.to); adjacent.get(e.dataset.to).push(e.dataset.from); }
      const distance = new Map([['person:' + debug.center, 0]]), queue = [...distance.keys()];
      for (let i = 0; i < queue.length; i++) for (const key of adjacent.get(queue[i]) || []) {
        if (!distance.has(key)) { distance.set(key, distance.get(queue[i]) + 1); queue.push(key); }
      }
      ranges = depths.map(depth => new Set(nodes.filter(n => depth === Infinity || distance.get(n.dataset.mapNode) <= depth).map(n => n.dataset.mapNode)));
      counts = ranges.map(range => nodes.filter(n => n.dataset.person && range.has(n.dataset.mapNode)).length);
      // The first step is always available: it shows fields, even with no peers.
      disabled = counts.map((count, i) => i > 0 && count <= counts[i - 1]);
      fields = [...ranges[0]].filter(key => !key.startsWith('person:')).length;
    }

    // Step 1 shows this person's fields; steps 2-3 count the other people now in view.
    function amount(i) { return i === 0 ? `${fields}개` : `${i === 3 ? counts[i] : Math.max(0, counts[i] - 1)}명`; }
    function describe(i) { return disabled[i] ? '더 이어진 사람이 없어요' : `${labels[i]} · ${amount(i)}`; }
    function showHint(i) {
      const button = wheel.querySelectorAll('button')[i];
      if (!button) return;
      hint.textContent = describe(i);
      hint.style.setProperty('--hint-x', `${button.offsetLeft + button.offsetWidth / 2}px`);
      hint.style.setProperty('--hint-y', `${button.offsetTop + button.offsetHeight / 2}px`);
    }
    function paint() {
      // A step that adds nobody for this person falls back to the nearest open step below it.
      let i = steps.indexOf(preferred);
      while (i > 0 && disabled[i]) i--;
      debug.step = steps[i];
      const range = ranges[i];
      for (const node of nodes) node.classList.toggle('mp-focus-faded', !range.has(node.dataset.mapNode));
      for (const edge of edges) edge.classList.toggle('mp-focus-faded', !range.has(edge.dataset.from) || !range.has(edge.dataset.to));
      debug.visiblePeople = counts[i]; debug.faded = nodes.length - range.size;
      card.hidden = wheel.hidden = false;
      wheel.setAttribute('aria-valuenow', String(i + 1));
      wheel.setAttribute('aria-valuetext', describe(i));
      wheel.setAttribute('aria-orientation', innerWidth < 760 ? 'horizontal' : 'vertical');
      [...wheel.querySelectorAll('button')].forEach((button, n) => {
        button.setAttribute('aria-pressed', String(n === i));
        button.setAttribute('aria-disabled', String(disabled[n]));
        button.setAttribute('aria-label', `${labels[n]} · ${disabled[n] ? '더 이어진 사람이 없어요' : amount(n)}`);
      });
      showHint(i);
    }

    function renderCard() {
      const p = people.get(debug.center), state = controller.getState();
      if (!p) return;
      const capabilities = core.capabilities.filter(c => c.kind !== 'project' && core.capabilityLink({...state, capability:c.id}, p)).slice(0,3);
      const records = core.visibleEvidence(state, p).length;
      card.innerHTML = `<div class="mp-focus-top">`
        + (history.length ? `<div class="mp-focus-history" role="group" aria-label="앞서 본 사람">${history.map(id => `<button type="button" data-focus-history="${esc(id)}" aria-label="${esc(people.get(id)?.name)} 다시 보기" title="${esc(people.get(id)?.name)}">${face(id,24)}</button>`).join('')}</div>` : '<span></span>')
        + `<button type="button" class="mp-focus-close" data-focus-close aria-label="주변 보기 닫기">×</button></div>`
        + `<div class="mp-focus-person"><div class="mp-focus-face">${face(p.id,56)}</div><div><strong>${esc(p.name)}</strong><p>${esc(p.organization || '')}</p></div></div>`
        + (capabilities.length ? `<p class="mp-focus-label">다룰 수 있는 일</p><div class="mp-focus-skills">${capabilities.map(c => `<span>${esc(c.label)}</span>`).join('')}</div>` : '')
        + `<p class="mp-focus-evidence">연결된 근거 ${records}건</p>`
        + '<button type="button" class="mp-focus-open" data-focus-open>전체 카드 보기</button>';
    }

    function fit() {
      clearTimeout(fitTimer);
      if (!debug.center || live3d.isActive() || !host.isConnected) return;
      // Phones never shrink below 40%: a wider circle is panned to, centred on the person.
      const covered = () => { const s = stage.getBoundingClientRect(), c = card && !card.hidden && card.getClientRects().length ? card.getBoundingClientRect() : null; return c ? Math.max(0, s.bottom - c.top) : 0; };
      controller?.fitNodes([...ranges[steps.indexOf(debug.step)]], innerWidth < 760
        ? { top:wheel.offsetHeight + 24, bottom:covered() + 24, minScale:.4, anchor:'person:' + debug.center }
        : { right:380 });
    }
    function center(id) {
      refresh();
      if (!nodes.some(n => n.dataset.person === id)) return;
      if (debug.center && debug.center !== id) history = [debug.center, ...history.filter(p => p !== debug.center && p !== id)].slice(0,3);
      debug.center = id;
      controller.select(id); calculate(); renderCard(); paint();
      // A person card already open beside or under the map follows the newly focused person.
      if (cardShown && cardShown !== id && document.getElementById('detailDialog')?.open) openCard(id);
      // Only camera motion waits for the double-click window; preview/selection
      // is immediate and no delayed navigation is scheduled.
      clearTimeout(fitTimer); fitTimer = setTimeout(fit, 350);
    }
    function clear(refit = true) {
      revision++; lastClick = null;
      clearTimeout(fitTimer);
      const hadCenter = !!debug.center;
      debug.center = null; preferred = debug.step = 2; history = [];
      for (const el of host.querySelectorAll('.mp-focus-faded')) el.classList.remove('mp-focus-faded');
      if (card) card.hidden = true;
      if (wheel) wheel.hidden = true;
      debug.faded = 0; debug.visiblePeople = nodes.filter(n => n.dataset.person).length;
      if (hadCenter) host.querySelector('[data-map-action="clear-selection"]')?.click();
      if (refit && hadCenter) controller?.fitNodes(null);
    }
    function change(index) {
      if (!debug.center || index < 0 || index > 3 || disabled[index]) return;
      preferred = debug.step = steps[index]; paint(); fit();
    }
    function advance(delta) {
      let i = steps.indexOf(debug.step) + delta;
      while (i >= 0 && i < 4 && disabled[i]) i += delta;
      change(i);
    }
    function activate(id, event) {
      const now = performance.now();
      const double = event.detail !== 0 && lastClick?.id === id && now - lastClick.at <= 350;
      lastClick = { id, at:now };
      const token = ++revision;
      if (double) {
        lastClick = null; clearTimeout(fitTimer); controller?.fitNodes([]); live3d.reset(); openCard(id);
      } else live3d.leave(() => { if (token === revision && !!host.isConnected) center(id); });
    }

    // Track press movement only, so a drag (card move or pan, handled by people-map.js) is never a click.
    host.addEventListener('pointerdown', e => {
      if (e.target.closest('.mp-focus-ui')) { e.stopImmediatePropagation(); return; }
      if (!e.target.closest('#mp-graph-stage') || e.button > 0) return;
      clearTimeout(fitTimer); controller?.fitNodes([]);
      if (!pointers.size) moved = false;
      pointers.set(e.pointerId, { x:e.clientX, y:e.clientY });
      if (pointers.size > 1) { moved = true; lastClick = null; }
    }, true);
    host.addEventListener('pointermove', e => {
      const press = pointers.get(e.pointerId); if (!press) return;
      if (Math.hypot(e.clientX-press.x,e.clientY-press.y) > 4) { moved = true; lastClick = null; revision++; }
    }, true);
    for (const type of ['pointerup','pointercancel']) host.addEventListener(type, e => {
      pointers.delete(e.pointerId);
      if (type === 'pointercancel') { moved = true; lastClick = null; }
    }, true);
    window.addEventListener('blur', () => { pointers.clear(); moved = true; lastClick = null; });
    for (const type of ['pointerup','pointercancel']) window.addEventListener(type, e => {
      if (pointers.has(e.pointerId)) { pointers.delete(e.pointerId); moved = true; lastClick = null; }
    });
    host.addEventListener('click', e => {
      if (e.target.closest('.mp-focus-ui')) {
        block(e);
        if (e.target.closest('[data-focus-open]')) { revision++; live3d.reset(); openCard(debug.center); }
        else if (e.target.closest('[data-focus-close]')) live3d.leave(() => clear());
        else if (e.target.closest('[data-focus-history]')) {
          const id = e.target.closest('[data-focus-history]').dataset.focusHistory;
          live3d.leave(() => center(id));
        } else if (e.target.closest('[data-focus-step]')) {
          const i = steps.findIndex(s => String(s) === e.target.closest('[data-focus-step]').dataset.focusStep);
          live3d.leave(() => change(i));
        }
        return;
      }
      const person = e.target.closest('[data-map-node][data-person]');
      if (person) { block(e); if (!moved || e.detail === 0) activate(person.dataset.person,e); return; }
      if (e.target.closest('#mp-graph-stage') && !e.target.closest(controls)) {
        if (!moved) { block(e); live3d.leave(() => clear()); }
      } else if (e.target.closest('[data-map-action="clear-selection"]') && debug.center) { block(e); clear(); }
      else if (e.target.closest('[data-map-camera="fit"]') && debug.center && !live3d.isActive()) { block(e); fit(); }
    }, true);
    host.addEventListener('dblclick', e => { if (e.target.closest('[data-map-node][data-person]')) block(e); }, true);
    host.addEventListener('wheel', e => {
      if (e.target.closest('.mp-focus-wheel')) { block(e); if (e.deltaY) live3d.leave(() => advance(e.deltaY < 0 ? -1 : 1)); }
      else if (e.target.closest('.mp-focus-card')) e.stopImmediatePropagation();
      else if (e.target.closest('#mp-graph-stage')) { clearTimeout(fitTimer); controller?.fitNodes([]); }
    }, {capture:true, passive:false});
    host.addEventListener('keydown', e => {
      if (e.target.closest('.mp-focus-wheel') && ['ArrowUp','ArrowDown','ArrowLeft','ArrowRight'].includes(e.key)) {
        block(e); live3d.leave(() => advance(['ArrowUp','ArrowLeft'].includes(e.key) ? -1 : 1));
      } else if (e.target.closest('.mp-focus-ui') && e.key !== 'Escape') e.stopPropagation();
      else if (e.target === stage && e.key === 'Home' && debug.center && !live3d.isActive()) { block(e); fit(); }
      else if (e.target === stage) controller?.fitNodes([]);
    }, true);
    document.addEventListener('keydown', e => {
      if (e.key === 'Escape' && !!host.isConnected && (debug.center || live3d.isActive())) { block(e); revision++; live3d.leave(() => clear()); }
    }, true);
    host.addEventListener('pointerover', e => {
      const b = e.target.closest('[data-focus-step]');
      if (b) showHint(steps.findIndex(s => String(s) === b.dataset.focusStep));
    });
    host.addEventListener('pointerout', e => { if (e.target.closest('[data-focus-step]') && debug.center) showHint(steps.indexOf(debug.step)); });
    for (const type of ['input','change','click']) host.addEventListener(type, e => {
      const settings = !!e.target.closest('.mp-live-panel');
      queueMicrotask(() => refresh(settings));
    });
    window.addEventListener('resize', () => queueMicrotask(() => { placeCard(); if (debug.center) { renderCard(); paint(); fit(); } }));
    return { refresh, clear, suspend() { revision++; lastClick = null; pointers.clear(); clearTimeout(fitTimer); controller?.fitNodes([]); } };
  }

  // Plan A: the native simulation has no public pause API. Wait for its own
  // settled status AND a quiet transform stream, then only read its coordinates.
  // CSS variables override presentation; native inline transforms are untouched.
  function createLive3D() {
    const DEG = Math.PI / 180;
    const reduced = matchMedia('(prefers-reduced-motion: reduce)');
    const clamp = (n, a, b) => Math.max(a, Math.min(b, n));
    const debug = window.__live3d = { on:false, theta:0, phi:0, fps:0, cards:0 };
    const touches = new Map();
    let stage = null, button = null, canvas = null, ctx = null;
    let cards = [], edges = [], order = [], center = { x:0, y:0, z:0 };
    let phase = 'off', transition = null, afterExit = null;
    let theta = 0, phi = 0, lift = 0, zoom = 1;
    let width = 0, height = 0, dpr = 1, local = false;
    let raf = 0, last = 0, frames = 0, fpsStart = 0, resumeAt = 0;
    let hover = false, gesture = null, suppressClick = false;
    let waitTimer = 0, waitObserver = null;
    const controlSelector = '.mp-focus-ui,.mp-live-bar,.mp-live-gear,.mp-live-panel,[data-map-camera],[data-map-action]';
    const active = () => phase !== 'off' && phase !== 'waiting';

    function install() {
      const next = host.querySelector('#mp-graph-stage');
      if (next === stage && button?.isConnected) return;
      reset();
      stage = next;
      button = null;
      if (!stage) return;
      button = document.createElement('button');
      button.type = 'button';
      button.className = 'mp-live-gear mp-live-3d';
      button.setAttribute('aria-label', '입체로 보기');
      button.setAttribute('aria-pressed', 'false');
      button.innerHTML = '<svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M10 2 17 6v8l-7 4-7-4V6l7-4Zm0 8 7-4M10 10 3 6m7 4v8"/></svg>';
      stage.append(button);
    }

    function stopWaiting() {
      clearTimeout(waitTimer);
      waitObserver?.disconnect();
      waitObserver = null;
    }

    function enter() {
      if (!stage || !host.isConnected) return;
      controller?.fitNodes([]);
      phase = 'waiting';
      button.setAttribute('aria-pressed', 'true');
      const check = () => {
        if (phase !== 'waiting') return;
        if (!host.querySelector('.mp-live-status')?.textContent.includes('배치 안정') || document.hidden) {
          waitTimer = setTimeout(check, 150);
          return;
        }
        stopWaiting();
        capture();
      };
      // The native camera can continue easing after the status says settled.
      // Only style/geometry changes postpone capture; no layout polling in rAF.
      const defer = () => { clearTimeout(waitTimer); waitTimer = setTimeout(check, 150); };
      waitObserver = new MutationObserver(defer);
      waitObserver.observe(stage.querySelector('.mp-spatial-nodes'), {
        subtree:true, attributes:true, attributeFilter:['style'], childList:true
      });
      defer();
    }

    function random(key) {
      let hash = 2166136261;
      for (const char of key) hash = Math.imul(hash ^ char.charCodeAt(0), 16777619);
      return (hash >>> 0) / 4294967295;
    }

    function depths() {
      const pills = cards.filter(n => !n.person);
      const neighbors = new Map(cards.map(n => [n, new Set()]));
      for (const e of edges) {
        neighbors.get(e.a).add(e.b);
        neighbors.get(e.b).add(e.a);
      }
      const springs = [];
      for (let i = 0; i < pills.length; i++) for (let j = i + 1; j < pills.length; j++) {
        const a = pills[i], b = pills[j];
        const shared = [...neighbors.get(a)].filter(n => n.person && neighbors.get(b).has(n)).length;
        if (shared) springs.push({ a, b, weight:shared });
      }
      for (const n of pills) { n.seed = n.z = (random(n.key) * 2 - 1) * 180; n.velocity = 0; }
      for (let i = 0; i < 100; i++) {
        for (const n of pills) n.force = (n.seed - n.z) * .025;
        for (const s of springs) {
          const f = (s.b.z - s.a.z) * Math.min(s.weight, 12) * .012;
          s.a.force += f; s.b.force -= f;
        }
        for (const n of pills) {
          n.velocity = (n.velocity + n.force) * .65;
          n.z = clamp(n.z + n.velocity, -180, 180);
        }
      }
      for (const n of cards.filter(n => n.person)) {
        const linked = [...neighbors.get(n)].filter(other => !other.person);
        n.z = linked.reduce((sum, other) => sum + other.z, 0) / (linked.length || 1)
          + (random(n.key) * 2 - 1) * 120;
      }
      center = cards.reduce((sum, n) => ({ x:sum.x+n.x, y:sum.y+n.y, z:sum.z+n.z }), { x:0, y:0, z:0 });
      for (const axis of ['x','y','z']) center[axis] /= cards.length;
    }

    function capture() {
      // All geometry and computed styles are read once, before the animation.
      const area = stage.getBoundingClientRect();
      width = stage.clientWidth; height = stage.clientHeight;
      if (!width || !height) { reset(); return; }
      cards = [...stage.querySelectorAll('[data-map-node]')].filter(el => el.style.display !== 'none').map(el => {
        const box = el.getBoundingClientRect(), style = getComputedStyle(el);
        const matrix = new DOMMatrixReadOnly(style.transform);
        return { el, key:el.dataset.mapNode, person:el.hasAttribute('data-person'),
          x:box.left + box.width/2 - area.left - stage.clientLeft,
          y:box.top + box.height/2 - area.top - stage.clientTop,
          scale:Math.hypot(matrix.a, matrix.b), z:0,
          opacity:Number(style.opacity), px:0, py:0, pz:0, alpha:1 };
      });
      if (!cards.length) { reset(); return; }
      const byKey = new Map(cards.map(n => [n.key, n]));
      edges = [...stage.querySelectorAll('.mp-spatial-edge')].flatMap(el => {
        const a = byKey.get(el.dataset.from), b = byKey.get(el.dataset.to);
        return a && b && el.style.display !== 'none' ? [{ el, a, b }] : [];
      });
      cacheEdges();
      depths();
      order = [...cards];
      local = !!window.__focus?.center;
      hover = cards.some(n => n.el.matches(':hover'));
      canvas = document.createElement('canvas');
      canvas.className = 'mp-live-3d-lines';
      canvas.setAttribute('aria-hidden', 'true');
      dpr = Math.min(devicePixelRatio || 1, 2);
      canvas.width = Math.ceil(width * dpr); canvas.height = Math.ceil(height * dpr);
      ctx = canvas.getContext('2d');
      if (!ctx) { reset(); return; }
      stage.prepend(canvas);
      theta = phi = lift = 0; zoom = 1;
      paint();
      stage.classList.add('mp-live-3d-on');
      debug.on = true; debug.cards = cards.length;
      phase = 'enter';
      transition = { start:performance.now(), theta:0, phi:0, lift:0, zoom:1 };
      last = fpsStart = performance.now(); frames = 0;
      start();
    }

    function cacheEdges() {
      const hidden = stage.classList.contains('mp-edges-off');
      for (const edge of edges) {
        const style = getComputedStyle(edge.el);
        edge.color = style.stroke;
        edge.width = parseFloat(style.strokeWidth) || 1.2;
        edge.opacity = hidden ? 0 : Number(style.opacity);
      }
    }

    function start() { if (!raf && active() && !document.hidden) raf = requestAnimationFrame(frame); }

    function paint() {
      const cy = Math.cos(theta), sy = Math.sin(theta), cx = Math.cos(phi), sx = Math.sin(phi);
      let minZ = Infinity, maxZ = -Infinity;
      for (const n of cards) {
        const x = n.x - center.x, y = n.y - center.y, z = (n.z - center.z) * lift;
        const rx = x*cy + z*sy, rz = -x*sy + z*cy;
        const ry = y*cx - rz*sx;
        n.pz = y*sx + rz*cx;
        const perspective = 1200 / Math.max(120, 1200 - n.pz);
        n.px = center.x + rx * perspective * zoom;
        n.py = center.y + ry * perspective * zoom;
        n.projectedScale = n.scale * perspective * zoom;
        minZ = Math.min(minZ, n.pz); maxZ = Math.max(maxZ, n.pz);
      }
      order.sort((a, b) => a.pz - b.pz);
      const span = maxZ - minZ;
      for (let i = 0; i < order.length; i++) {
        const n = order[i];
        n.alpha = 1 - lift + lift * (.35 + .65 * (span > .001 ? (n.pz - minZ)/span : 1));
        // Only writes to cached elements. No DOM queries, rects, styles or reparenting.
        n.el.style.setProperty('--live3d-transform', `translate3d(${n.px}px,${n.py}px,0) translate(-50%,-50%) scale(${n.projectedScale})`);
        n.el.style.setProperty('--live3d-opacity', String(n.opacity * n.alpha));
        n.el.style.setProperty('--live3d-order', String(i + 1));
      }
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, width, height);
      for (const e of edges) {
        if (!e.opacity) continue;
        ctx.strokeStyle = e.color; ctx.lineWidth = e.width;
        ctx.globalAlpha = e.opacity * (e.a.alpha + e.b.alpha) / 2;
        ctx.beginPath(); ctx.moveTo(e.a.px, e.a.py); ctx.lineTo(e.b.px, e.b.py); ctx.stroke();
      }
      debug.theta = theta; debug.phi = phi;
    }

    function frame(now) {
      raf = 0;
      if (!active() || document.hidden) return;
      const dt = Math.min((now - last) / 1000, .1); last = now;
      frames++;
      if (now - fpsStart >= 1000) { debug.fps = frames * 1000 / (now - fpsStart); frames = 0; fpsStart = now; }
      if (transition) {
        const t = clamp((now - transition.start) / 600, 0, 1), eased = 1 - (1-t)**3;
        const entering = phase === 'enter';
        theta = transition.theta * (1-eased);
        phi = transition.phi + ((entering ? -14*DEG : 0) - transition.phi) * eased;
        lift = transition.lift + ((entering ? 1 : 0) - transition.lift) * eased;
        zoom = transition.zoom + ((entering ? .9 : 1) - transition.zoom) * eased;
        if (t === 1) {
          transition = null;
          if (phase === 'exit') {
            const action = afterExit;
            reset();
            action?.();
            return;
          }
          phase = 'on';
        }
      } else if (!reduced.matches && !local && !hover && !touches.size && now >= resumeAt) {
        theta = (theta + 6*DEG*dt) % (Math.PI*2);
      }
      paint();
      start();
    }

    function leave(action) {
      if (phase === 'off') { action?.(); return; }
      if (phase === 'waiting') { reset(); action?.(); return; }
      if (phase === 'exit') { if (action) afterExit = action; return; }
      clearGesture();
      // Return by the nearest full turn, ending exactly at the native projection.
      theta = Math.atan2(Math.sin(theta), Math.cos(theta));
      phase = 'exit'; afterExit = action || null;
      transition = { start:performance.now(), theta, phi, lift, zoom };
      start();
    }

    function clearGesture() {
      for (const id of touches.keys()) if (stage?.hasPointerCapture(id)) stage.releasePointerCapture(id);
      touches.clear(); gesture = null;
      stage?.classList.remove('mp-live-3d-dragging');
      resumeAt = performance.now() + 1500;
    }

    function reset() {
      stopWaiting(); cancelAnimationFrame(raf); raf = 0;
      phase = 'off'; transition = afterExit = null;
      clearGesture(); suppressClick = false;
      stage?.classList.remove('mp-live-3d-on');
      for (const n of cards) for (const property of ['--live3d-transform','--live3d-opacity','--live3d-order']) n.el.style.removeProperty(property);
      canvas?.remove(); canvas = ctx = null;
      cards = []; edges = []; order = [];
      theta = phi = lift = 0; zoom = 1;
      button?.setAttribute('aria-pressed', 'false');
      Object.assign(debug, { on:false, theta:0, phi:0, fps:0, cards:0 });
    }

    const block = event => { event.preventDefault(); event.stopImmediatePropagation(); };
    const inStage = target => stage?.contains(target) && !target.closest(controlSelector);
    host.addEventListener('click', event => {
      if (event.target.closest('.mp-live-3d') === button && button) {
        block(event);
        if (phase === 'off') enter(); else leave();
        return;
      }
      if (phase === 'off') return;
      const target = event.target.closest('button');
      if (!target) return;
      // Capture before native target listeners, then replay the original button
      // only after restoration. Existing SELECT/filter/Cosmos routing is retained.
      block(event);
      if (suppressClick && event.detail !== 0) { suppressClick = false; return; }
      leave(() => { if (target.isConnected) target.click(); });
    }, true);

    host.addEventListener('pointerdown', event => {
      if (!active() || !inStage(event.target) || event.button > 0) return;
      event.stopImmediatePropagation();
      // Keep native focus/click defaults on cards. Capture only after movement.
      const point = { x:event.clientX, y:event.clientY };
      touches.set(event.pointerId, point);
      suppressClick = false;
      if (touches.size === 1) gesture = { ...point, startX:point.x, startY:point.y, moved:false, pinch:0 };
      else if (touches.size === 2) {
        const [a,b] = [...touches.values()];
        gesture.pinch = Math.hypot(a.x-b.x, a.y-b.y); gesture.moved = true;
      }
    }, true);

    host.addEventListener('pointermove', event => {
      if (!active() || !touches.has(event.pointerId) || !gesture) return;
      block(event);
      touches.set(event.pointerId, { x:event.clientX, y:event.clientY });
      if (phase !== 'on') return;
      if (touches.size === 2) {
        const [a,b] = [...touches.values()], distance = Math.hypot(a.x-b.x, a.y-b.y);
        if (gesture.pinch > 0) zoom = clamp(zoom * distance / gesture.pinch, .25, 3);
        gesture.pinch = distance;
      } else {
        if (Math.hypot(event.clientX-gesture.startX, event.clientY-gesture.startY) > 4) gesture.moved = true;
        if (gesture.moved) {
          theta += (event.clientX - gesture.x) * .3 * DEG;
          phi = clamp(phi + (event.clientY - gesture.y) * .2 * DEG, -45*DEG, 10*DEG);
        }
        gesture.x = event.clientX; gesture.y = event.clientY;
      }
      if (gesture.moved) {
        stage.setPointerCapture(event.pointerId);
        stage.classList.add('mp-live-3d-dragging');
      }
    }, true);

    function endPointer(event) {
      if (!touches.has(event.pointerId)) return;
      event.stopImmediatePropagation();
      suppressClick = !!gesture?.moved || event.type === 'pointercancel';
      touches.delete(event.pointerId);
      if (stage.hasPointerCapture(event.pointerId)) stage.releasePointerCapture(event.pointerId);
      if (touches.size === 1) {
        const point = [...touches.values()][0];
        gesture = { ...point, startX:point.x, startY:point.y, moved:true, pinch:0 };
      } else if (!touches.size) clearGesture();
    }
    host.addEventListener('pointerup', endPointer, true);
    host.addEventListener('pointercancel', endPointer, true);

    host.addEventListener('wheel', event => {
      if (!active() || !inStage(event.target)) return;
      block(event);
      if (phase === 'on') zoom = clamp(zoom * (event.deltaY < 0 ? 1.08 : 1/1.08), .25, 3);
    }, { capture:true, passive:false });

    document.addEventListener('keydown', event => {
      if (phase !== 'off' && event.key === 'Escape') { block(event); leave(); }
    }, true);
    host.addEventListener('keydown', event => {
      if (!active() || event.target !== stage) return;
      const directions = { ArrowLeft:-.06, ArrowRight:.06, ArrowUp:-.04, ArrowDown:.04 };
      if (event.key in directions) {
        block(event);
        if (phase === 'on') {
          if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') theta += directions[event.key];
          else phi = clamp(phi + directions[event.key], -45*DEG, 10*DEG);
          resumeAt = performance.now() + 1500;
        }
      } else if (['+','=','-','Home'].includes(event.key)) {
        block(event);
        if (event.key === 'Home') leave(() => host.querySelector('[data-map-camera="fit"]')?.click());
        else if (phase === 'on') zoom = clamp(zoom * (event.key === '-' ? 1/1.2 : 1.2), .25, 3);
      }
    }, true);

    // Selects/inputs in an already open native settings panel must also restore
    // before their target-level native handlers can replace/rearrange the graph.
    for (const type of ['input','change']) host.addEventListener(type, () => {
      if (phase !== 'off') reset();
    }, true);
    for (const type of ['pointerover','pointerout','focusin','focusout']) host.addEventListener(type, event => {
      if (!active()) return;
      const node = event.target.closest('[data-map-node]');
      if (!node || node.contains(event.relatedTarget)) return;
      if (type === 'pointerover') hover = true;
      if (type === 'pointerout') hover = !!event.relatedTarget?.closest?.('[data-map-node]');
      // Native emphasis runs on this same host. Cache its final line appearance
      // after event delivery, never during the animation frame.
      queueMicrotask(() => { if (active()) cacheEdges(); });
    });
    window.addEventListener('resize', () => { if (phase !== 'off') reset(); });
    window.addEventListener('blur', clearGesture);
    document.addEventListener('visibilitychange', () => {
      if (document.hidden) { cancelAnimationFrame(raf); raf = 0; clearGesture(); }
      else { last = fpsStart = performance.now(); frames = 0; start(); }
    });
    return { install, reset, leave, isActive:() => phase !== 'off', isProjecting:active };
  }
  }
  root.RndPeopleMapFocus = Object.freeze({ attach });
})(typeof window !== 'undefined' ? window : globalThis);
