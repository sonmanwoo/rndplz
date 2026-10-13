/* Home before the first message (main.welcome without .is-chat): an opening of the team and every researcher's
 * face ends on the 수소문 mark (2026-10-12; a visitor every visit, a signed-in browser once a day), the second
 * heading line turns over every 4 s to another research field, and the composer shows a rotating example.
 * Behind it the portrait spiral drifts again once the opening ends (back 2026-10-13, owner), and clears for typing.
 * Portraits and fields come from /api/people-map?view=home; position on the spiral means nothing about a person.
 */
(() => {
  'use strict';
  const body = document.body, main = document.getElementById('main');
  const canvas = document.getElementById('homeWhirl'), stage = document.getElementById('welcomeHeading');
  if (!main || !canvas || !stage) return;
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');
  const still = () => reduced.matches || body.classList.contains('no-motion');
  // Curated wording; each field must have at least two portraits in the current data to appear.
  const SCENES = [
    { id:'catalyst', phrase:'촉매 설계 연구자', hint:'촉매 비활성화 원인' },
    { id:'process', phrase:'공정 모델링 전문가', hint:'공정 최적화 조건' },
    { id:'polymer-circularity', phrase:'자원 순환 연구자', hint:'폐플라스틱 재활용 공정' },
    { id:'separation', phrase:'분리·정제 연구자', hint:'증류 분리 효율' },
    { id:'control', phrase:'예측 제어 전문가', hint:'제어기 튜닝 방향' },
    { id:'saf', phrase:'SAF 연료 연구자', hint:'항공유 전환 경로' },
    { id:'cooling', phrase:'냉각·열관리 연구자', hint:'액침 냉각 열성능' }
  ];

  // ---- home state -------------------------------------------------------
  const isHome = () => main.classList.contains('welcome') && !main.classList.contains('is-chat');
  const listeners = new Set();
  function syncHome() {
    const home = isHome();
    body.classList.toggle('home-welcome', home);
    listeners.forEach(fn => fn(home));
  }
  new MutationObserver(syncHome).observe(main, { attributes:true, attributeFilter:['class'] });
  const rail = document.getElementById('historyRailList');
  const syncHistory = () => body.classList.toggle('home-has-history', !!rail?.querySelector('.history-item'));
  if (rail) new MutationObserver(syncHistory).observe(rail, { childList:true, subtree:true });
  syncHistory(); syncHome();

  // ---- composer example (overlay on the textarea, home only) -------------
  // index.html already holds the overlay with the first example, so the field looks right before this runs.
  const message = document.getElementById('message'), wrap = message?.closest('.home-input');
  const hintWords = wrap ? [...wrap.querySelectorAll('.home-hint-words')] : [];
  if (message && wrap) {
    const filled = () => wrap.classList.toggle('has-value', !!message.value);
    message.addEventListener('input', filled); filled();
    new MutationObserver(filled).observe(message, { attributes:true });
    setInterval(filled, 1000); // chat.js clears the value after sending without an input event
  }
  function showHint(text, animate) {
    for (const holder of hintWords) {
      const word = document.createElement('span'); word.textContent = text;
      holder.append(word);
      if (animate && !still()) { word.style.opacity = '0'; requestAnimationFrame(() => { word.style.opacity = '1'; }); }
      const old = [...holder.children].slice(0, -1);
      old.forEach(n => { n.style.opacity = '0'; setTimeout(() => n.remove(), 250); });
    }
  }

  // ---- heading: first line fixed, second line turns over ------------------
  const flipBox = stage.querySelector('.home-flip');
  const heading = stage.querySelector('.home-title');
  function spring(mass, stiffness, damping) {
    let x = 0, v = 0, rest = 0, done = false;
    return dt => {
      rest += dt;
      while (rest >= 1/120 && !done) {
        v += (-stiffness * (x - 1) - damping * v) / mass / 120; x += v / 120; rest -= 1/120;
        if (Math.abs(x - 1) < .001 && Math.abs(v) < .001) { x = 1; v = 0; done = true; }
      }
      return { x, done };
    };
  }
  const clamp = q => Math.max(0, Math.min(1, q));
  // While a pointer rests on (or presses) the faces, or the keyboard is on one, the heading holds that scene,
  // so the face being aimed at is still the one clicked.
  let aiming = false;
  flipBox?.addEventListener('pointerenter', () => { aiming = true; });
  flipBox?.addEventListener('pointerleave', () => { aiming = false; });
  flipBox?.addEventListener('click', event => {
    const face = event.target.closest('.home-thumb[data-person-id]');
    if (face && typeof window.openPersonCard === 'function') window.openPersonCard(face.dataset.personId, face).catch?.(() => {});
  });
  function flipNode(scene) {
    const node = document.createElement('span'); node.className = 'home-flip-item';
    const words = document.createElement('span'); words.textContent = scene.phrase;
    const thumbs = document.createElement('span'); thumbs.className = 'home-thumbs';
    // Like Cosmos's item thumbnails: pressing a face opens that researcher's card (chat.js openPersonCard).
    for (const person of scene.thumbs) {
      const frame = document.createElement('button'); frame.type = 'button'; frame.className = 'home-thumb';
      frame.dataset.personId = person.id; frame.setAttribute('aria-label', (person.name || '연구자') + ' 카드 보기'); frame.title = person.name || '';
      const img = new Image(); img.src = person.image; img.alt = ''; img.decoding = 'async';
      frame.append(img); thumbs.append(frame);
    }
    node.append(words, thumbs); return node;
  }
  function setPose(node, q, entering) {
    const c = clamp(q), t = entering ? 1 - q : q, s = entering ? -1 : 1;
    node.style.opacity = entering ? c : 1 - c;
    node.style.transform = `translateY(${s * 50 * t}%) translateZ(${s * 40 * t}px) rotateX(${-s * 80 * t}deg)`;
    node.style.filter = `blur(${10 * (entering ? 1 - c : c)}px)`;
  }

  // ---- spiral of portraits (Canvas 2D) ------------------------------------
  const ctx = canvas.getContext('2d');
  const cameraSize = () => innerWidth > 1920 ? Math.round(innerWidth / 1920 * 2500) : 2500;
  let R = .75 * cameraSize();
  const turns = 8, steps = 16384, samples = 4096;
  let path = [], N = 0, pathLength = 0;
  function buildPath() {
    R = .75 * cameraSize();
    const raw = [], lengths = new Float64Array(steps + 1);
    for (let i = 0; i <= steps; i++) {
      const t = i / steps, r = R * (1 - t), a = t * turns * 2 * Math.PI, x = r * Math.cos(a), y = r * Math.sin(a);
      raw.push({ x, y }); if (i) lengths[i] = lengths[i - 1] + Math.hypot(x - raw[i - 1].x, y - raw[i - 1].y);
    }
    const length = pathLength = lengths[steps]; path = [];
    for (let j = 0, i = 1; j <= samples; j++) {
      const target = j / samples * length;
      while (i < steps && lengths[i] < target) i++;
      const f = (target - lengths[i - 1]) / (lengths[i] - lengths[i - 1] || 1), t = (i - 1 + f) / steps, a = t * turns * 2 * Math.PI, r = R * (1 - t);
      let tx = -R * Math.cos(a) - r * Math.sin(a) * turns * 2 * Math.PI, ty = -R * Math.sin(a) + r * Math.cos(a) * turns * 2 * Math.PI;
      const norm = Math.hypot(tx, ty) || 1;
      path.push({ x:raw[i - 1].x + (raw[i].x - raw[i - 1].x) * f, y:raw[i - 1].y + (raw[i].y - raw[i - 1].y) * f, tx:tx / norm, ty:ty / norm });
    }
  }
  const sizes = [19111, 18700, 9632].map(area => { const h = Math.sqrt(area / .75); return { w:h * .75, h }; });
  const assets = new Map(), orders = new Map();
  let W = 0, H = 0, dpr = 1, scale = 1, spriteScale = 0, current = [], previous = null;
  let transitionAt = 0, start = null, last = null, offset = 0, raf = 0, firstSeen = new Float64Array(0), running = false;
  function bake(asset) {
    asset.sprites = sizes.map(({ w, h }) => {
      const tile = document.createElement('canvas');
      tile.width = Math.ceil(w * spriteScale); tile.height = Math.ceil(h * spriteScale);
      const c = tile.getContext('2d'); c.scale(tile.width / w, tile.height / h);
      c.beginPath(); c.roundRect(0, 0, w, h, 20); c.clip();
      const cover = Math.max(w / asset.img.naturalWidth, h / asset.img.naturalHeight);
      c.drawImage(asset.img, (w - asset.img.naturalWidth * cover) / 2, (h - asset.img.naturalHeight * cover) * .25, asset.img.naturalWidth * cover, asset.img.naturalHeight * cover);
      c.lineWidth = 6; c.strokeStyle = 'rgba(0,0,0,.12)'; c.stroke();
      return tile;
    });
  }
  function resize() {
    dpr = Math.min(devicePixelRatio || 1, 2, 4096 / Math.max(innerWidth, innerHeight));
    W = canvas.width = Math.round(innerWidth * dpr); H = canvas.height = Math.round(innerHeight * dpr);
    scale = Math.max(2000, innerWidth) * dpr / cameraSize();
    if (scale > spriteScale) { spriteScale = scale; assets.forEach(a => { if (a.ready) bake(a); }); }
    if (path.length) fit();
  }
  // Every face on screen is a different person (2026-10-12; before, half the cards repeated the field's few people and a
  // large screen showed one face up to a dozen times). A card coming into view takes the next person not on screen:
  // the field's people first, then everyone else, never the two faces beside the heading. A screen that would show
  // more cards than there are people spaces them out instead. A new field brings its people into a few of the cards
  // on screen (the rest stay), so no face is ever shown twice, not even while one fades into another.
  let crowd = 0, order = [], field = new Set(), inTitle = new Set(), onScreen = new Uint8Array(0), sceneSeed = 0, sceneFresh = false;
  // Typing clears the stage (2026-10-13): the first letter in the composer sends every card outward and away (0.7 s), so
  // the question has the screen to itself; an empty composer that loses the caret brings them back (1.1 s). The caret
  // alone does nothing: a desktop home has it from the start.
  let calm = 0;
  const scatter = i => ((Math.imul(i + 1, 2654435761) >>> 0) / 4294967296) * .3, ease = t => t <= 0 ? 0 : t >= 1 ? 1 : t * t * (3 - 2 * t);
  const mixed = list => list.sort((m, n) => ((Math.imul(m + 1, 2654435761) ^ sceneSeed) >>> 0) - ((Math.imul(n + 1, 2654435761) ^ sceneSeed) >>> 0));
  function spot(p, size) {
    const alpha = p < 8 ? p / 8 : p > 92 ? (100 - p) / 8 : 1;
    if (alpha < .01) return null;
    const u = p / 100 * samples, j = Math.min(Math.floor(u), samples - 1), mix = u - j, a = path[j], b = path[j + 1];
    let x = a.x + (b.x - a.x) * mix, y = a.y + (b.y - a.y) * mix;
    const d = Math.hypot(x, y), k = d ? R * (d / R) ** (1 / .95) / d : 0; x *= k; y *= k;
    const s = Math.min(d / R, 1) ** .35, factor = s * scale, { w, h } = sizes[size], radius = Math.hypot(w, h) * factor / 2;
    const sx = W / 2 + x * scale, sy = H / 2 + y * scale;
    if (sx + radius < 0 || sx - radius > W || sy + radius < 0 || sy - radius > H) return null;
    if (Math.hypot((sx - W / 2) / (.45 * W), (sy - H / 2) / (.45 * H)) + radius / (.45 * Math.min(W, H)) < .505) return null;
    return { alpha, sx, sy, factor, w, h, angle:Math.atan2(a.ty + (b.ty - a.ty) * mix, a.tx + (b.tx - a.tx) * mix) };
  }
  function fit() {
    let seen = 0;
    for (let j = 0; j < samples; j++) if (spot(j / samples * 100, 1)) seen++;
    const most = Math.max(10, Math.ceil(pathLength / 250)), next = Math.max(10, Math.min(most, Math.floor(crowd * .9 / Math.max(seen / samples, 1e-3))));
    if (next === N) return; // a phone's address bar coming and going keeps the cards as they are
    N = next; onScreen = new Uint8Array(N); firstSeen = new Float64Array(N).fill(-1); current = new Array(N).fill(null); previous = null;
  }
  function sceneOrder(scene, everyone) {
    if (orders.has(scene.id)) return orders.get(scene.id);
    let seed = 2166136261;
    for (const ch of scene.id) seed = Math.imul(seed ^ ch.charCodeAt(0), 16777619) >>> 0;
    const random = () => { seed ^= seed << 13; seed ^= seed >>> 17; seed ^= seed << 5; return (seed >>> 0) / 4294967296; };
    const shuffle = arr => { for (let i = arr.length - 1; i > 0; i--) { const j = Math.floor(random() * (i + 1)); [arr[i], arr[j]] = [arr[j], arr[i]]; } return arr; };
    const title = new Set(scene.thumbs.map(p => p.id)), mine = scene.people.map(p => p.id).filter(id => !title.has(id));
    const list = { order:[...shuffle(mine), ...shuffle(everyone.map(p => p.id).filter(id => !title.has(id) && !mine.includes(id)))], field:new Set(mine) };
    orders.set(scene.id, list); return list;
  }
  function setScene(scene, everyone) {
    ({ order, field } = sceneOrder(scene, everyone)); inTitle = new Set(scene.thumbs.map(p => p.id));
    sceneSeed = (sceneSeed + 0x9e3779b9) >>> 0;
    const next = new Array(N).fill(null), before = new Array(N).fill(null), seen = [];
    for (let i = 0; i < N; i++) if (onScreen[i] && current[i]) { next[i] = current[i]; seen.push(i); }
    const shown = new Set(seen.map(i => next[i])), incoming = order.filter(id => field.has(id) && !shown.has(id));
    // The new heading's faces leave the background; the field's people not on screen take cards held by others.
    const leaving = seen.filter(i => inTitle.has(next[i])), open = mixed(seen.filter(i => !inTitle.has(next[i]) && !field.has(next[i])));
    for (const i of [...leaving, ...open]) {
      if (!inTitle.has(next[i]) && !incoming.length) break;
      before[i] = next[i]; next[i] = incoming.shift() || null;
    }
    previous = !still() && before.some(Boolean) ? before : null;
    current = next; sceneFresh = true;
    transitionAt = performance.now();
    if (start === null) { start = transitionAt; canvas.classList.add('ready'); }
  }
  function frame(now) {
    raf = 0;
    if (!running || document.hidden) return;
    const dt = last === null ? 0 : Math.min((now - last) / 1000, .15); last = now;
    const elapsed = now - start, f = Math.min(elapsed / 3200, 1), ramp = Math.min(elapsed / 700, 1) ** 2;
    const burst = still() ? 1 : (1 - ramp) + (1 + 23 * (1 - f) ** 2) * ramp;
    const clear = !!message && (message.value.length > 0 || (calm > 0 && document.activeElement === message));
    calm = still() ? +clear : Math.min(1, Math.max(0, calm + (clear ? dt / .7 : -dt / 1.1)));
    offset = (offset + (still() ? 0 : .32) * burst * (1 - calm) * dt) % 100;
    ctx.setTransform(1, 0, 0, 1, 0, 0); ctx.clearRect(0, 0, W, H);
    const progress = still() ? 1 : Math.min((now - transitionAt) / 850, 1);
    if (progress === 1) previous = null;
    const blend = progress * progress * (3 - 2 * progress), zoom = 1 + .12 * (1 - progress) ** 3;
    const live = [];
    for (let i = 0; i < N; i++) {
      const at = spot((offset + (i / N - .5) * 100 + 100) % 100, i % 3);
      if (at) live.push([i, at]);
    }
    // Cards already on screen keep their person; the rest, in a mixed order so a field's people spread out, take the next free one.
    // While faces fade into new ones, the fading faces count as shown too.
    const taken = new Set(inTitle), fresh = [];
    if (previous) for (const [i] of live) if (previous[i]) taken.add(previous[i]);
    for (const [i] of live) { if ((onScreen[i] || sceneFresh) && current[i] && !taken.has(current[i])) taken.add(current[i]); else fresh.push(i); }
    for (const i of mixed(fresh)) {
      const id = order.find(person => !taken.has(person)) || null;
      current[i] = id; if (id) taken.add(id);
      if (!(sceneFresh && previous?.[i])) { firstSeen[i] = -1; if (previous) previous[i] = null; }
    }
    onScreen.fill(0); sceneFresh = false;
    for (const [i, at] of live) {
      const gone = calm && ease(calm * 1.3 - scatter(i));
      onScreen[i] = 1;
      const asset = assets.get(current[i]); if (!asset?.ready) continue;
      let alpha = at.alpha * (1 - gone);
      if (firstSeen[i] < 0) firstSeen[i] = now;
      if (!still()) alpha *= Math.min((now - firstSeen[i]) / 400, 1);
      if (alpha < .01) continue;
      const { w, h } = at, factor = at.factor * (1 + .15 * gone), cos = Math.cos(at.angle), sin = Math.sin(at.angle), push = 1 + .55 * gone * gone;
      ctx.setTransform(cos * factor, sin * factor, -sin * factor, cos * factor, W / 2 + (at.sx - W / 2) * push, H / 2 + (at.sy - H / 2) * push); ctx.globalAlpha = alpha;
      if (previous?.[i]) {
        const old = assets.get(previous[i]);
        if (old?.ready) ctx.drawImage(old.sprites[i % 3], -w / 2, -h / 2, w, h);
        ctx.save(); ctx.beginPath(); ctx.roundRect(-w / 2, -h / 2, w, h, 20); ctx.clip();
        ctx.globalAlpha = alpha * blend; ctx.drawImage(asset.sprites[i % 3], -w * zoom / 2, -h * zoom / 2, w * zoom, h * zoom); ctx.restore();
      } else ctx.drawImage(asset.sprites[i % 3], -w / 2, -h / 2, w, h);
    }
    raf = requestAnimationFrame(frame);
  }
  function run(on) {
    running = on && start !== null;
    if (running && !raf && !document.hidden) { last = null; raf = requestAnimationFrame(frame); }
    if (!running && raf) { cancelAnimationFrame(raf); raf = 0; }
  }

  // ---- to the research map: the button under the composer, or scrolling / swiping down on the home screen ----
  // Fields, menus, the conversation list and open dialogs keep their own scrolling.
  const toMap = () => {
    if (body.classList.contains('home-leaving')) return;
    body.classList.add('home-leaving');
    setTimeout(() => location.assign('/explore#map'), still() ? 0 : 200);
  };
  const ownScroll = target => !isHome() || document.querySelector('dialog[open]')
    || target?.closest?.('textarea,input,select,.history-rail,.site-menu,.account-menu');
  const atBottom = () => innerHeight + scrollY >= document.documentElement.scrollHeight - 2;
  let wheelSum = 0, wheelTimer = 0, touchY = null;
  addEventListener('wheel', event => {
    if (event.deltaY <= 0 || ownScroll(event.target) || !atBottom()) return;
    wheelSum += event.deltaY; clearTimeout(wheelTimer); wheelTimer = setTimeout(() => { wheelSum = 0; }, 300);
    if (wheelSum > 60) toMap();
  }, { passive:true });
  addEventListener('touchstart', event => { touchY = event.touches.length === 1 && !ownScroll(event.target) ? event.touches[0].clientY : null; }, { passive:true });
  addEventListener('touchend', event => { if (touchY !== null && atBottom() && touchY - event.changedTouches[0].clientY > 70) toMap(); touchY = null; }, { passive:true });
  addEventListener('pageshow', () => body.classList.remove('home-leaving')); // back from the map

  // ---- opening (2026-10-12, owner) ----------------------------------------------------------------------------
  // The team's four cards swing in (오진호 · 손만우 · 정다솔 · 홍윤기) and wipe to slices of one grid of every researcher's
  // face, which closes up to fill the screen and lifts away like blinds over the 수소문 mark and wordmark (the header's
  // own, scaled up); the mark settles into the header and the heading, the composer and the button rise in. After
  // Cadence's Formation Loader — Slices, at 0.72 of its timings (about 6 s). home-intro-gate.js decides before the
  // first paint (a visitor every visit, a signed-in browser once a day); a click, a tap, a key or the wheel goes straight
  // to the composer. It waits at most 4 s for the data and the team's photos, else the home simply appears. On a phone
  // line (2026-10-13) the team's four photos come first and alone; everyone else follows once the opening has begun.
  const root = document.documentElement, introStage = document.getElementById('homeIntro');
  const homeData = window.rndplzHomeData || fetch('/api/people-map?view=home', { credentials:'same-origin' }).then(r => r.ok ? r.json() : null).catch(() => null);
  let introDone = root.dataset.homeIntro !== 'play' || !introStage || !isHome();
  if (introDone) { delete root.dataset.homeIntro; introStage?.remove(); }
  else playIntro();
  async function playIntro() {
    const T = ms => ms * .72, wait = ms => new Promise(resolve => setTimeout(resolve, ms)), PAPER = '#f7f5f3';
    const TEAM = ['LOCAL-JINHO', 'LOCAL-MANWOO', 'LOCAL-DASOL', 'LOCAL-HONG'];
    let skipped = false, layer = null, brand = null, big = '';
    const onKey = event => { if (event.isTrusted) skip(); };
    function end() {
      introDone = true; delete root.dataset.homeIntro; introStage.remove(); layer?.remove();
      removeEventListener('keydown', onKey, true); removeEventListener('wheel', skip);
    }
    // Straight to the composer: the stage clears, the mark flies to the header, the home rises quickly.
    function skip() {
      if (skipped || introDone) return;
      skipped = true;
      introStage.getAnimations({ subtree:true }).forEach(animation => animation.pause());
      introStage.animate([{ opacity:1 }, { opacity:0 }], { duration:320, easing:'ease-out', fill:'forwards' });
      if (brand) {
        body.append(layer); layer.classList.add('home-intro-top'); layer.style.visibility = 'visible';
        const now = getComputedStyle(brand).transform;
        brand.getAnimations().forEach(animation => animation.cancel());
        brand.animate([{ transform:now === 'none' ? big : now }, { transform:'none' }], { duration:520, easing:'cubic-bezier(.65,0,.35,1)', fill:'forwards' });
      }
      root.dataset.homeIntro = 'quick';
      // With a mouse the caret lands in the composer; a phone keeps its keyboard down until the field is tapped.
      setTimeout(() => { end(); if (matchMedia('(pointer: fine)').matches) message?.focus(); }, 560);
    }
    introStage.addEventListener('pointerdown', skip);
    addEventListener('keydown', onKey, true); addEventListener('wheel', skip, { passive:true });

    const path = p => p.profile?.portrait?.path, deadline = wait(4000);
    const data = await Promise.race([homeData, deadline.then(() => null)]);
    if (skipped) return;
    const people = (data?.people || []).filter(p => /^\/portraits\/[a-z0-9-]+\.(png|jpe?g)$/i.test(path(p) || ''));
    const photo = (p, size, priority = 'auto') => {
      const img = new Image(); img.decoding = 'async'; img.fetchPriority = priority; img.alt = '';
      img.src = path(p).replace(/\.(png|jpe?g)$/i, `-${size}.webp`); return img;
    };
    const team = TEAM.map(id => people.find(p => p.id === id)).filter(Boolean).map(p => photo(p, 'detail', 'high'));
    const ready = team.length > 1 && await Promise.race([Promise.all(team.map(img => img.decode())).then(() => true, () => false), deadline.then(() => false)]);
    if (skipped) return;
    if (!ready) { skip(); return; }
    // Only an opening that plays counts as seen: a slow line that ends in the plain home leaves the day's turn unspent.
    try { localStorage.setItem('rndplz.intro.seen', new Date().toLocaleDateString('sv-SE')); } catch {}
    const vw = innerWidth, vh = innerHeight, narrow = vw < 700 || vw / vh < .8, n = team.length;
    // They keep loading while the team swings in; a phone's grid cells are small enough for the thumbnails.
    const others = people.filter(p => !TEAM.includes(p.id)).map(p => photo(p, narrow ? 'thumb' : 'detail'));
    const gap = narrow ? 8 : 12, total = narrow ? .92 * vw : Math.min(.8 * vw, 1180), colH = (narrow ? .56 : .62) * vh;
    const colW = (total - (n - 1) * gap) / n, left0 = (vw - total) / 2, top0 = (vh - colH) / 2;

    // The header's own mark and wordmark, scaled up in the middle, under the slices until they lift.
    const home = document.querySelector('.craft-header .craft-brand');
    layer = document.createElement('div'); layer.className = 'home-intro-brand-layer';
    brand = home.cloneNode(true); brand.classList.add('home-intro-brand'); brand.removeAttribute('href'); brand.setAttribute('aria-hidden', 'true');
    const to = home.getBoundingClientRect(), word = brand.querySelector('.craft-wordmark');
    const wordInHeader = !!home.querySelector('.craft-wordmark')?.getClientRects().length;
    word.style.display = 'block'; // a phone header with past conversations shows the mark alone; the opening always names it
    brand.style.left = to.left + 'px'; brand.style.top = to.top + 'px';
    layer.append(brand); introStage.append(layer);
    const own = brand.getBoundingClientRect(), k = Math.min(vw * (narrow ? .62 : .46) / own.width, vh * .3 / own.height);
    big = `translate(${vw / 2 - to.left - own.width * k / 2}px,${vh / 2 - to.top - own.height * k / 2}px) scale(${k})`;
    brand.style.transform = big; layer.style.visibility = 'hidden';

    const cols = [];
    team.forEach((img, i) => {
      const L = left0 + i * (colW + gap), col = document.createElement('div'); col.className = 'home-intro-col';
      col.style.cssText = `left:${L}px;top:${top0}px;width:${colW}px;height:${colH}px`;
      const wipe = document.createElement('div'); wipe.className = 'home-intro-wipe';
      const inner = document.createElement('div'); inner.className = 'home-intro-wipe-inner';
      wipe.append(inner); col.append(img, wipe); introStage.append(col);
      const slice = document.createElement('div'); slice.className = 'home-intro-slice';
      slice.style.clipPath = `inset(${top0}px ${vw - L - colW}px ${vh - top0 - colH}px ${L}px round 6px)`; introStage.append(slice);
      cols.push({ col, wipe, inner, slice, L, i });
      col.animate([{ transform:'translateX(50%) rotate(-10deg) skewX(15deg) scaleX(1.05)', opacity:0 }, { transform:'none', opacity:1 }],
                  { duration:T(1500), delay:T(i * 160), easing:'cubic-bezier(.25,1,.5,1)', fill:'both' });
    });
    // A slow line holds the team a little longer (2 s at most) for everyone else's photos, so the grid is not mostly paper.
    const othersIn = Promise.all(others.map(img => img.decode().catch(() => {})));
    await Promise.all([wait(T(1940)), Promise.race([othersIn, wait(T(1940) + 2000)])]); if (skipped) return;
    // One grid of every researcher's face, the size of the screen: each person once, in a mixed order; cells left over
    // stay paper. When a slow line still leaves many photos on their way, the cells grow until those at hand fill most of it.
    const shown = [...team, ...others].filter(img => img.complete && img.naturalWidth), rowsFor = per => Math.ceil(vh / (vw / per * 4 / 3));
    let per = narrow ? 4 : 8;
    while (per > 2 && per * rowsFor(per) * .75 > shown.length) per--;
    const cw = vw / per, ch = cw * 4 / 3, rows = rowsFor(per), dpr = Math.min(devicePixelRatio || 1, 2);
    const canvas = document.createElement('canvas'); canvas.width = Math.round(vw * dpr); canvas.height = Math.round(vh * dpr);
    const g = canvas.getContext('2d'); g.scale(dpr, dpr); g.fillStyle = PAPER; g.fillRect(0, 0, vw, vh);
    let seed = 7; const random = () => (seed = Math.imul(seed ^ (seed >>> 15), 2246822519) + 3266489917 >>> 0) / 4294967296;
    for (let i = shown.length - 1; i > 0; i--) { const j = Math.floor(random() * (i + 1)); [shown[i], shown[j]] = [shown[j], shown[i]]; }
    const y0 = (vh - rows * ch) / 2;
    shown.slice(0, rows * per).forEach((img, cell) => {
      const x = cell % per * cw, y = y0 + Math.floor(cell / per) * ch, cover = Math.max(cw / img.naturalWidth, ch / img.naturalHeight);
      g.save(); g.beginPath(); g.rect(x, y, cw, ch); g.clip();
      g.drawImage(img, x + (cw - img.naturalWidth * cover) / 2, y + (ch - img.naturalHeight * cover) * .25, img.naturalWidth * cover, img.naturalHeight * cover);
      g.restore();
    });
    const grid = `url(${canvas.toDataURL('image/jpeg', .9)})`;
    for (const c of cols) {
      c.inner.style.cssText = `background-image:${grid};background-size:${vw}px ${vh}px;background-position:${-c.L}px ${-top0}px`;
      c.slice.style.backgroundImage = grid; c.slice.style.backgroundSize = `${vw}px ${vh}px`;
      c.wipe.animate([{ transform:'translateY(-102%)' }, { transform:'none' }], { duration:T(1100), delay:T(c.i * 120), easing:'cubic-bezier(.45,0,.55,1)', fill:'both' });
      c.inner.animate([{ transform:'translateY(102%)' }, { transform:'none' }], { duration:T(1100), delay:T(c.i * 120), easing:'cubic-bezier(.45,0,.55,1)', fill:'both' });
    }
    await wait(T((n - 1) * 120 + 1100 + 350)); if (skipped) return;
    // The slices close up into the whole grid.
    const mid = (n - 1) / 2;
    for (const c of cols) {
      c.slice.style.display = 'block'; c.col.style.display = 'none';
      const share = vw / n; c.l = c.i * share; c.r = Math.max(0, vw - (c.i + 1) * share - 1);
      c.slice.animate([{ clipPath:c.slice.style.clipPath }, { clipPath:`inset(0px ${c.r}px 0px ${c.l}px round 0px)` }],
        { duration:T(1300), delay:T(Math.abs(c.i - mid) / mid * 100), easing:'cubic-bezier(.76,0,.24,1)', fill:'forwards' });
    }
    await wait(T(1300 + 100 + 525)); if (skipped) return;
    // The grid lifts away like blinds and the mark shows through as it goes.
    layer.style.visibility = 'visible';
    for (const c of cols) c.slice.animate([{ clipPath:`inset(0px ${c.r}px 0px ${c.l}px round 0px)` }, { clipPath:`inset(0px ${c.r}px ${vh}px ${c.l}px round 0px)` }],
      { duration:T(1100), delay:T(c.i * 80), easing:'cubic-bezier(.76,0,.24,1)', fill:'forwards' });
    await wait(T((n - 1) * 80 + 1100) + 350); if (skipped) return;
    // The mark settles into the header; the heading, the composer and the button rise in.
    body.append(layer); layer.classList.add('home-intro-top');
    introStage.animate([{ opacity:1 }, { opacity:0 }], { duration:450, easing:'ease', fill:'forwards' });
    brand.animate([{ transform:big }, { transform:'none' }], { duration:780, easing:'cubic-bezier(.65,0,.35,1)', fill:'forwards' });
    if (!wordInHeader) word.animate([{ opacity:1 }, { opacity:0 }], { duration:500, easing:'ease', fill:'forwards' });
    await wait(380); if (skipped) return;
    root.dataset.homeIntro = 'rise';
    await wait(900); if (skipped) return;
    end();
  }

  // ---- data and loop ------------------------------------------------------
  const thumb = path => typeof path === 'string' && /^\/portraits\/[a-z0-9-]+\.(png|jpe?g)$/i.test(path) ? path.replace(/\.(png|jpe?g)$/i, '-thumb.webp') : null;
  homeData.then(data => {
    if (!data || !Array.isArray(data.people)) return;
    const everyone = data.people.map(p => ({ id:p.id, name:p.profile?.display_name || p.name, image:thumb(p.profile?.portrait?.path) })).filter(p => p.image);
    const byId = new Map(everyone.map(p => [p.id, p]));
    const scenes = SCENES.map(scene => {
      const capability = (data.capabilities || []).find(c => c.id === scene.id);
      const people = capability ? capability.people.map(link => byId.get(link.id)).filter(Boolean) : [];
      return { ...scene, people, thumbs:people.slice(0, 2) };
    }).filter(scene => scene.people.length >= 2);
    if (!scenes.length || !everyone.length) return;
    crowd = Math.max(1, everyone.length - 2); buildPath(); resize();
    for (const person of everyone) {
      const img = new Image(); img.decoding = 'async'; img.src = person.image;
      const asset = { img, ready:false, sprites:[] };
      asset.promise = img.decode().then(() => { asset.ready = true; bake(asset); }, () => {});
      assets.set(person.id, asset);
    }
    let index = 0, shown = flipNode(scenes[0]), transition = null, elapsed = 0, lastTick = null, timer = 0;
    flipBox.replaceChildren(shown); showHint(scenes[0].hint, false);
    const prepared = i => Promise.all(scenes[i].people.map(p => assets.get(p.id)?.promise));
    function tick(now) {
      timer = 0;
      if (!isHome() || document.hidden) { lastTick = null; return; }
      const dt = lastTick === null ? 0 : (now - lastTick) / 1000; lastTick = now;
      if (introDone) { // the heading starts turning only after the intro
        if (transition) {
          const head = transition.head(dt), face = transition.face(dt);
          if (still()) { shown.style.opacity = '1'; transition.old.remove(); transition = null; }
          else {
            setPose(shown, head.x, true); setPose(transition.old, head.x, false);
            shown.querySelectorAll('img').forEach(img => { img.style.opacity = clamp(face.x); img.style.transform = `scale(${1 + .15 * (1 - face.x)})`; });
            if (head.done && face.done) { transition.old.remove(); shown.removeAttribute('style'); shown.querySelectorAll('img').forEach(i => i.removeAttribute('style')); transition = null; }
          }
        }
        if (!document.querySelector('dialog[open]') && !aiming && !flipBox.querySelector(':focus-visible')) elapsed += dt * 1000; // the heading waits while a card is open or a face is aimed at
        if (elapsed >= 4000 && !transition) {
          const next = (index + 1) % scenes.length;
          if (scenes[next].ready || elapsed >= 10000) {
            const old = shown; index = next; shown = flipNode(scenes[index]);
            flipBox.append(shown); old.setAttribute('aria-hidden', 'true');
            transition = { old, head:spring(1.5, 120, 18), face:spring(1, 175, 20) };
            setPose(shown, 0, true);
            showHint(scenes[index].hint, true); setScene(scenes[index], everyone);
            elapsed = 0;
            prepared((index + 1) % scenes.length).then(() => { scenes[(index + 1) % scenes.length].ready = true; });
          }
        }
      }
      timer = requestAnimationFrame(tick);
    }
    prepared(0).then(() => {
      setScene(scenes[0], everyone);
      prepared(1 % scenes.length).then(() => { scenes[1 % scenes.length].ready = true; });
      const go = home => { run(home); if (home && !timer && !document.hidden) { lastTick = null; timer = requestAnimationFrame(tick); } };
      listeners.add(go); go(isHome());
      document.addEventListener('visibilitychange', () => go(isHome() && !document.hidden));
    });
    let resizeTimer = 0;
    addEventListener('resize', () => { clearTimeout(resizeTimer); resizeTimer = setTimeout(resize, 150); });
  }).catch(() => {});
})();
