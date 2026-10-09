/* Home before the first message (main.welcome without .is-chat): researcher portraits drift along a spiral
 * toward the centre, the second heading line turns over every 4 s to another research field (its people take
 * over the spiral), a "re·search" intro plays once per browser, and the composer shows a rotating example.
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
  const intro = stage.querySelector('.home-intro');
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
  let path = [], N = 0;
  function buildPath() {
    R = .75 * cameraSize();
    const raw = [], lengths = new Float64Array(steps + 1);
    for (let i = 0; i <= steps; i++) {
      const t = i / steps, r = R * (1 - t), a = t * turns * 2 * Math.PI, x = r * Math.cos(a), y = r * Math.sin(a);
      raw.push({ x, y }); if (i) lengths[i] = lengths[i - 1] + Math.hypot(x - raw[i - 1].x, y - raw[i - 1].y);
    }
    const length = lengths[steps]; N = Math.max(10, Math.ceil(length / 250)); path = [];
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
  const assets = new Map(), lists = new Map();
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
  }
  function sceneList(scene, everyone) {
    if (lists.has(scene.id)) return lists.get(scene.id);
    let seed = 2166136261;
    for (const ch of scene.id) seed = Math.imul(seed ^ ch.charCodeAt(0), 16777619) >>> 0;
    const random = () => { seed ^= seed << 13; seed ^= seed >>> 17; seed ^= seed << 5; return (seed >>> 0) / 4294967296; };
    const shuffle = arr => { for (let i = arr.length - 1; i > 0; i--) { const j = Math.floor(random() * (i + 1)); [arr[i], arr[j]] = [arr[j], arr[i]]; } return arr; };
    const mine = shuffle(scene.people.map(p => p.id)), others = shuffle(everyone.map(p => p.id).filter(id => !mine.includes(id)));
    const half = Math.ceil(N / 2), list = [];
    for (let i = 0; i < N; i++) list.push(i < half || !others.length ? mine[i % mine.length] : others[(i - half) % others.length]);
    shuffle(list); lists.set(scene.id, list); return list;
  }
  function setScene(scene, everyone) {
    const next = sceneList(scene, everyone);
    previous = current.length && !still() ? current : null;
    current = next; transitionAt = performance.now();
    if (start === null) { start = transitionAt; canvas.classList.add('ready'); }
  }
  function frame(now) {
    raf = 0;
    if (!running || document.hidden) return;
    const dt = last === null ? 0 : Math.min((now - last) / 1000, .15); last = now;
    const elapsed = now - start, f = Math.min(elapsed / 3200, 1), ramp = Math.min(elapsed / 700, 1) ** 2;
    const burst = still() ? 1 : (1 - ramp) + (1 + 23 * (1 - f) ** 2) * ramp;
    offset = (offset + (still() ? 0 : .32) * burst * dt) % 100;
    ctx.setTransform(1, 0, 0, 1, 0, 0); ctx.clearRect(0, 0, W, H);
    const progress = still() ? 1 : Math.min((now - transitionAt) / 850, 1);
    if (progress === 1) previous = null;
    const blend = progress * progress * (3 - 2 * progress), zoom = 1 + .12 * (1 - progress) ** 3;
    for (let i = 0; i < N; i++) {
      const p = (offset + (i / N - .5) * 100 + 100) % 100;
      let alpha = p < 8 ? p / 8 : p > 92 ? (100 - p) / 8 : 1;
      if (alpha < .01) continue;
      const u = p / 100 * samples, j = Math.min(Math.floor(u), samples - 1), mix = u - j, a = path[j], b = path[j + 1];
      let x = a.x + (b.x - a.x) * mix, y = a.y + (b.y - a.y) * mix;
      const d = Math.hypot(x, y), k = d ? R * (d / R) ** (1 / .95) / d : 0; x *= k; y *= k;
      const s = Math.min(d / R, 1) ** .35, factor = s * scale, { w, h } = sizes[i % 3], radius = Math.hypot(w, h) * factor / 2;
      const sx = W / 2 + x * scale, sy = H / 2 + y * scale;
      if (sx + radius < 0 || sx - radius > W || sy + radius < 0 || sy - radius > H) continue;
      if (Math.hypot((sx - W / 2) / (.45 * W), (sy - H / 2) / (.45 * H)) + radius / (.45 * Math.min(W, H)) < .505) continue;
      const asset = assets.get(current[i]); if (!asset?.ready) continue;
      if (firstSeen[i] < 0) firstSeen[i] = now;
      if (!still()) alpha *= Math.min((now - firstSeen[i]) / 400, 1);
      const angle = Math.atan2(a.ty + (b.ty - a.ty) * mix, a.tx + (b.tx - a.tx) * mix), cos = Math.cos(angle), sin = Math.sin(angle);
      ctx.setTransform(cos * factor, sin * factor, -sin * factor, cos * factor, sx, sy); ctx.globalAlpha = alpha;
      if (previous) {
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

  // ---- re·search intro: on every load of the home screen, from the first frame, without waiting for data ----
  // (2026-10-09: the owner wants it on each visit and refresh; a tap or a key skips it.)
  let introDone = false;
  let motionOff = false;
  try { motionOff = sessionStorage.getItem('rndplz-motion') === 'off'; } catch {} // craft.js applies the same switch later
  if (!intro || reduced.matches || motionOff || !isHome()) introDone = true;
  let introAt = null, introLast = null, introFlip = null;
  const splitSpring = spring(1.5, 120, 18);
  function finishIntro() {
    if (introDone) return;
    introDone = true; stage.classList.remove('home-intro-on'); intro.remove();
    heading.style.removeProperty('opacity'); heading.style.removeProperty('transform'); heading.style.removeProperty('filter');
  }
  function introTick(now) {
    if (introDone) return;
    if (!isHome()) { finishIntro(); return; }
    if (introAt === null) introAt = now;
    const dt = introLast === null ? 0 : Math.min((now - introLast) / 1000, .1), age = now - introAt; introLast = now;
    if (age >= 600 && !introFlip) { intro.style.setProperty('--split', clamp(splitSpring(dt).x)); intro.classList.add('split'); }
    if (age >= 2400 && !introFlip) introFlip = spring(1.5, 120, 18);
    if (introFlip) {
      const { x:q, done } = introFlip(dt);
      setPose(heading, q, true); setPose(intro, q, false);
      if (done) finishIntro();
    }
    requestAnimationFrame(introTick);
  }
  if (introDone) intro?.remove();
  else {
    stage.classList.add('home-intro-on');
    for (const type of ['pointerdown', 'keydown']) addEventListener(type, finishIntro, { once:true, capture:true, passive:true });
    message?.addEventListener('focus', finishIntro, { once:true });
    requestAnimationFrame(introTick);
  }

  // ---- data and loop ------------------------------------------------------
  const thumb = path => typeof path === 'string' && /^\/portraits\/[a-z0-9-]+\.(png|jpe?g)$/i.test(path) ? path.replace(/\.(png|jpe?g)$/i, '-thumb.webp') : null;
  fetch('/api/people-map?view=home', { credentials:'same-origin' }).then(r => r.ok ? r.json() : null).then(data => {
    if (!data || !Array.isArray(data.people)) return;
    const everyone = data.people.map(p => ({ id:p.id, name:p.profile?.display_name || p.name, image:thumb(p.profile?.portrait?.path) })).filter(p => p.image);
    const byId = new Map(everyone.map(p => [p.id, p]));
    const scenes = SCENES.map(scene => {
      const capability = (data.capabilities || []).find(c => c.id === scene.id);
      const people = capability ? capability.people.map(link => byId.get(link.id)).filter(Boolean) : [];
      return { ...scene, people, thumbs:people.slice(0, 2) };
    }).filter(scene => scene.people.length >= 2);
    if (!scenes.length || !everyone.length) return;
    buildPath(); firstSeen = new Float64Array(N).fill(-1); resize();
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
