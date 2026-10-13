/* Below-fold content, loaded only when the introduction enters the viewport. */
(function (root, factory) {
  'use strict';
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else api.init(root);
}(typeof window !== 'undefined' ? window : globalThis, function () {
  'use strict';
  const capabilityURL = id => '/explore?capability=' + encodeURIComponent(id) + '#map';
  const validCount = value => Number.isSafeInteger(value) && value >= 0;
  function project(data) {
    const fields = (Array.isArray(data?.capabilities) ? data.capabilities : []).filter(field => field &&
      typeof field.id === 'string' && typeof field.label === 'string' && field.label.trim())
      .map(field => ({id:field.id, label:field.label}));
    const counts = [['people', '공개 연구자', '명'], ['capabilities', '연구 분야', '개'], ['records', '근거 기록', '건']]
      .filter(([key]) => validCount(data?.counts?.[key]))
      .map(([key, label, unit]) => ({label, value:data.counts[key], unit}));
    return {fields, counts};
  }
  function init(win) {
    const doc = win.document, body = doc.body, landing = win.Landing;
    if (!landing || !['people', 'map'].includes(body.dataset.landing)) return;
    const $ = id => doc.getElementById(id), quiet = landing.quiet;
    const node = (tag, className, text) => {
      const item = doc.createElement(tag); if (className) item.className = className;
      if (text != null) item.textContent = text; return item;
    };
    const whenVisible = (element, callback) => {
      if (!('IntersectionObserver' in win)) { callback(); return; }
      const observer = new win.IntersectionObserver(entries => {
        if (entries.some(entry => entry.isIntersecting && entry.intersectionRatio > 0)) { observer.disconnect(); callback(); }
      }, {threshold:0.01}); observer.observe(element);
    };
    function lazyImages(host) {
      for (const img of host.querySelectorAll('img[data-src]')) whenVisible(img, () => { img.src = img.dataset.src; delete img.dataset.src; });
    }
    lazyImages($('landingFeatures'));
    const player = $('landingFeatureRail') ? scenes($('landingFeatureRail'), win, quiet) : null;
    function moveRail(rail, direction) {
      rail.scrollBy({left:direction * (rail.firstElementChild?.getBoundingClientRect().width || rail.clientWidth * .8) + direction * 24,
        behavior:quiet() ? 'instant' : 'smooth'});
    }
    for (const rail of doc.querySelectorAll('.landing-rail')) rail.addEventListener('keydown', event => {
      if (player?.rail === rail) return;   // the scene rail moves itself
      if (event.altKey || event.ctrlKey || event.metaKey || !['ArrowLeft','ArrowRight','Home','End'].includes(event.key)) return;
      event.preventDefault();
      if (event.key === 'Home' || event.key === 'End') rail.scrollTo({left:event.key === 'Home' ? 0 : rail.scrollWidth, behavior:quiet() ? 'instant' : 'smooth'});
      else moveRail(rail, event.key === 'ArrowRight' ? 1 : -1);
    });
    for (const next of doc.querySelectorAll('[data-landing-next]')) {
      const rail = $(next.dataset.landingNext);
      if (player?.rail === rail) { next.addEventListener('click', player.next); continue; }
      next.addEventListener('click', () => moveRail(rail, 1));
      const sync = () => { next.disabled = rail.scrollWidth <= rail.clientWidth + rail.scrollLeft + 3; };
      rail.addEventListener('scroll', sync, {passive:true}); win.addEventListener('resize', sync); sync();
    }
    let fieldLinks = [], fields = [], start = 0, current = 0, timer = 0, rolling = 0, fieldsVisible = false, held = false;
    const reduced = win.matchMedia('(prefers-reduced-motion: reduce)');
    function selectField(index) {
      current = index;
      fieldLinks.forEach((link, i) => link.classList.toggle('is-current', i === current));
    }
    // A ticker: 6 rows on a phone, 8 wider. The highlight stays on the second row and the list slides up one field per step,
    // so the next fields are always waiting just below it. With motion off, every field stands still.
    const narrow = win.matchMedia('(max-width:700px)'), FOCUS = 1;
    let rows = 0;
    const windowSize = () => quiet() ? fields.length : Math.min(narrow.matches ? 6 : 8, fields.length);
    const ticking = () => windowSize() < fields.length;
    const rowHeight = item => { const r = item.getBoundingClientRect(); return (r.bottom - r.top) || 0; };
    function paintFields() {
      const list = $('landingFieldList'), frame = $('landingFieldWindow'); list.replaceChildren(); fieldLinks = []; rows = windowSize();
      for (let k = 0; k < rows + (ticking() ? 1 : 0); k++) {
        const field = fields[((ticking() ? start : 0) + k) % fields.length];
        const item = node('li'), link = node('a', '', field.label); link.href = capabilityURL(field.id);
        item.append(link); list.append(item); fieldLinks.push(link);
      }
      selectField(ticking() ? FOCUS : 0);
      // The frame shows exactly the visible rows; the extra one below waits to slide in.
      frame.style.height = ticking() ? [...list.children].slice(0, rows).reduce((sum, item) => sum + rowHeight(item), 0) + 'px' : '';
    }
    function step() {
      if (!ticking()) { selectField((current + 1) % fieldLinks.length); return; }
      const list = $('landingFieldList'), shift = rowHeight(list.firstElementChild);
      selectField(FOCUS + 1);
      list.style.transition = 'transform .45s ease'; list.style.transform = 'translateY(' + (-shift) + 'px)';
      win.clearTimeout(rolling);
      rolling = win.setTimeout(() => {
        start = (start + 1) % fields.length; list.style.transition = 'none'; list.style.transform = ''; paintFields();
      }, 460);
    }
    function syncTimer() {
      win.clearInterval(timer); timer = 0;
      if (fields.length && rows !== windowSize()) paintFields();
      if (!quiet() && !doc.hidden && fieldsVisible && !held && body.classList.contains('home-welcome') && fieldLinks.length > 1) {
        timer = win.setInterval(step, 1600);
      }
    }
    const fieldsHost = $('landingFields');
    if ('IntersectionObserver' in win) new win.IntersectionObserver(entries => { fieldsVisible = entries.some(entry => entry.isIntersecting && entry.intersectionRatio > 0); syncTimer(); }, {threshold:0.01}).observe(fieldsHost);
    else fieldsVisible = true;
    for (const event of ['pointerenter','focusin']) fieldsHost.addEventListener(event, () => { held = true; syncTimer(); });
    fieldsHost.addEventListener('pointerleave', () => { held = fieldsHost.contains(doc.activeElement); syncTimer(); });
    fieldsHost.addEventListener('focusout', event => { held = fieldsHost.contains(event.relatedTarget); syncTimer(); });
    reduced.addEventListener('change', syncTimer); narrow.addEventListener('change', () => { if (fields.length) paintFields(); syncTimer(); }); doc.addEventListener('visibilitychange', syncTimer);
    new win.MutationObserver(syncTimer).observe(body, {attributes:true, attributeFilter:['class']});
    win.addEventListener('pagehide', () => win.clearInterval(timer)); win.addEventListener('pageshow', syncTimer);
    const sourcesHost = $('landingSources');
    function render(data) {
      const projected = project(data); fields = projected.fields;
      start = (fields.length - FOCUS) % Math.max(fields.length, 1); // the first field opens on the highlighted row
      paintFields(); syncTimer();
      const all = $('landingFieldsAll'); all.hidden = !fields.length; all.textContent = '연구 맵에서 분야 ' + fields.length + '개 모두 보기';
      const counts = $('landingCounts'); counts.replaceChildren();
      for (const count of projected.counts) {
        const item = node('li');
        item.append(node('span', '', count.label + ' '), node('strong', '', count.value.toLocaleString('ko-KR') + count.unit));
        counts.append(item);
      }
      counts.hidden = false;
      const fieldStatus = fieldsHost.querySelector('[data-landing-data-status]');
      fieldStatus.hidden = fields.length > 0; fieldStatus.textContent = '지금 표시할 분야가 없어요. 연구 맵에서 확인해 주세요.';
      sourcesHost.querySelector('[data-landing-data-status]').hidden = true;
    }
    let dataWork = null;
    function loadData() {
      if (dataWork) return dataWork;
      for (const retry of doc.querySelectorAll('[data-landing-retry]')) retry.hidden = true;
      dataWork = win.fetch('/api/people-map?view=home&landing=1', {credentials:'same-origin'})
        .then(response => { if (!response.ok) throw new Error('map'); return response.json(); })
        .then(data => {
          if (!Array.isArray(data?.capabilities) || !validCount(data?.counts?.people) || !validCount(data?.counts?.capabilities)) throw new Error('map');
          render(data);
        })
        .catch(() => {
          dataWork = null;
          for (const retry of doc.querySelectorAll('[data-landing-retry]')) retry.hidden = false;
          for (const status of doc.querySelectorAll('[data-landing-data-status]')) { status.hidden = false; status.textContent = '자료를 불러오지 못했어요. 잠시 후 다시 시도해 주세요.'; }
        });
      return dataWork;
    }
    for (const retry of doc.querySelectorAll('[data-landing-retry]')) retry.addEventListener('click', loadData);
    whenVisible(fieldsHost, loadData);
    whenVisible(sourcesHost, loadData);
    whenVisible($('landingMap'), async () => {
      const host = $('landingMapCanvas');
      const startMap = async () => {
        try {
          await landing.loadScript('/landing-map-preview.js');
          if (!await win.LandingMapPreview.mount(host)) throw new Error('map');
        }
        catch (_) {
          host.replaceChildren(node('p', 'landing-load', '연구 맵을 불러오지 못했어요.'));
          const retry = node('button', 'landing-pill', '다시 불러오기'); retry.type = 'button'; retry.addEventListener('click', startMap); host.append(retry);
        }
      }; await startMap();
    });
    for (const ask of doc.querySelectorAll('[data-landing-ask]')) ask.addEventListener('click', event => {
      event.preventDefault(); const message = $('message'); message.focus({preventScroll:true});
      win.scrollTo({top:0, behavior:quiet() ? 'instant' : 'smooth'});
    });
    doc.querySelector('[data-landing-login]').addEventListener('click', event => {
      // The existing account menu closes on a click outside .account-control.
      event.stopPropagation();
      win.scrollTo({top:0, behavior:'instant'});
      if ($('accountMenu').hidden) $('accountToggle').click();
      const login = $('googleLogin');
      if (login && !login.hidden) login.focus({preventScroll:true});
    });
    const feedback = doc.querySelector('[data-landing-feedback]');
    feedback.addEventListener('click', () => {
      doc.querySelector('[data-feedback-open]')?.click();
      const dialog = $('feedbackDialog');
      if (dialog?.open) dialog.addEventListener('close', () => feedback.focus({preventScroll:true}), {once:true});
    });
  }
  // The scene rail (2026-10-13, after Cadence's Swipe Reveal and Contact Sheet): the six scenes stand in one endless
  // row, the middle card full size and the rest at 92%. Only the middle card shows its recording; the others wear a
  // plain cover with their number and title, so the row stays calm. When a clip ends the row slides one card left,
  // and the cards on the incoming side start 40 ms apart, so the gaps stretch and close. The first time the rail is
  // in view the middle card opens through a slit while its neighbours gather in from the middle. Drag, a tap on a
  // side card, the arrow keys or a sideways trackpad swipe move it too; a hand on the rail replays a scene instead of
  // sliding away. Clips download one at a time (2026-10-11) and start only once the row has stopped. The rail out of
  // view or a hidden tab pauses it; with motion off nothing moves on its own and every move is instant.
  function scenes(rail, win, quiet) {
    const doc = win.document, cards = [...rail.children], n = cards.length;
    const videos = cards.map(card => card.querySelector('video'));
    if (!videos.some(Boolean) || !('IntersectionObserver' in win)) return null;
    const now = () => Date.now(), clock = () => win.performance ? win.performance.now() : Date.now();
    let active = -1, onScreen = false, opened = false, touchedAt = -Infinity, hold = 0;
    const start = video => { const started = video.play && video.play(); if (started && started.catch) started.catch(() => {}); };
    const live = video => videos[active] === video && onScreen && opened && !doc.hidden && !quiet();
    // Slow phone networks (2026-10-11): clips download one at a time, the playing one first and then the next,
    // and a still shows until a clip can play through, so nothing stutters halfway.
    function prepare(index, fetch) {
      const video = videos[index];
      if (!video) return;
      if (!video.poster && video.dataset.poster) video.poster = video.dataset.poster;
      if (fetch && !video.src) { video.preload = 'auto'; video.src = video.dataset.src; if (video.load) video.load(); }
    }
    const loadedFully = video => { const got = video.buffered; return !!(got && got.length && video.duration && got.end(got.length - 1) >= video.duration - .25); };
    function play(index) {
      const video = videos[index];
      if (!video || quiet() || !onScreen || !opened || doc.hidden) return;
      prepare(index, true);
      try { video.currentTime = 0; } catch (_) { /* not loaded yet: it starts from 0 anyway */ }
      if (video.readyState >= 4) start(video);
      else video.addEventListener('canplaythrough', () => { if (live(video)) start(video); }, {once: true});
    }
    function activate(index) {
      win.clearTimeout(hold); active = index; prepare(index, false);
      videos.forEach((video, k) => { if (video && k !== index && video.pause) video.pause(); });
      cards.forEach((card, k) => card.classList.toggle('is-playing', k === index && !!videos[k]));
      // While the row slides the card shows its still; the clip starts once the row has settled, so starting a
      // video never competes with the slide (2026-10-13: the slide stuttered on phones).
      if (videos[index]) settled(() => { if (active === index) play(index); });
      else if (!quiet()) hold = win.setTimeout(advance, 4000);   // a still card rests, then the story starts again
    }
    // The row. Each card keeps its own slide (from, to, start, delay) in card slots from the middle, before wrapping,
    // so a new move starts from wherever each card is.
    const SLIDE = 700, LAG = 40, ease = bezier(.22, .61, .36, 1);
    const at = cards.map((card, k) => ({from: k, to: k, start: 0, delay: 0}));
    const wrap = slot => ((slot + n / 2) % n + n) % n - n / 2;
    let size = {stage: 0, card: 0, slot: 1, falloff: 1}, drag = 0, frame = 0, waiting = [];
    const settled = fn => { if (frame) waiting.push(fn); else fn(); };
    function place(t, k) {
      const a = at[k], u = (t - a.start - a.delay) / SLIDE;
      return u <= 0 ? a.from : u >= 1 ? a.to : a.from + (a.to - a.from) * ease(u);
    }
    function measure() {
      const card = cards[0].offsetWidth || 1;
      size = {stage: rail.clientWidth, card, slot: card * 1.043, falloff: card * 1.24};   // Cadence: gap 18, falloff 520 at a 420-wide card
      rail.style.setProperty('--rail-h', Math.max(...cards.map(item => item.offsetHeight || 0)) + 'px');
    }
    function paint() {
      const t = clock(); let moving = false;
      cards.forEach((card, k) => {
        const slot = place(t, k); if (slot !== at[k].to) moving = true;
        const x = wrap(slot + drag) * size.slot, scale = .92 + .08 * Math.max(0, 1 - Math.abs(x) / size.falloff);
        card.style.transform = `translate3d(${((size.stage - size.card) / 2 + x).toFixed(1)}px,0,0) scale(${scale.toFixed(4)})`;
        card.style.setProperty('--cap', Math.max(0, 1 - Math.abs(x) / (size.slot * .6)).toFixed(3));
        card.toggleAttribute('inert', Math.abs(x) > size.slot * 2.5);   // wrapped out of sight
      });
      frame = moving && win.requestAnimationFrame ? win.requestAnimationFrame(paint) : 0;
      if (!frame && waiting.length) waiting.splice(0).forEach(fn => fn());
    }
    function go(index) {
      index = (index % n + n) % n;
      const t = clock(), quick = quiet() || !win.requestAnimationFrame;
      const from = cards.map((card, k) => place(t, k) + drag);
      const by = wrap(-from[index]);   // the chosen card's way to the middle; every card travels the same
      cards.forEach((card, k) => {
        const slot = Math.round(wrap(from[k])), behind = by < 0 ? slot : -slot, to = Math.round(from[k] + by);
        at[k] = quick ? {from: to, to, start: t, delay: 0} : {from: from[k], to, start: t, delay: LAG * Math.min(6, Math.max(0, behind))};
      });
      drag = 0;
      if (frame && win.cancelAnimationFrame) win.cancelAnimationFrame(frame);
      paint();
      if (index !== active) activate(index);
    }
    function advance() {
      if (quiet() || !onScreen || doc.hidden) return;
      if (now() - touchedAt < 2500) { play(active); return; }    // someone is reading: replay instead of sliding away
      go(active + 1);
    }
    // The opening, once: the middle card opens through a horizontal slit, the side cards gather in from the middle,
    // turned and small, and the middle card's caption rises. The first clip starts as it settles.
    function open() {
      if (opened) return;
      const finish = () => { opened = true; if (active >= 0) play(active); };
      if (quiet() || !cards[0].animate) { finish(); return; }
      const curve = 'cubic-bezier(.2,.7,.2,1)';
      cards.forEach((card, k) => {
        const slot = Math.round(wrap(at[k].to)), media = card.querySelector('.landing-scene-media');
        if (!media || Math.abs(slot) > 2) return;
        if (!slot) {
          media.animate([{clipPath: 'inset(50% 0 50% 0)', opacity: 0}, {clipPath: 'inset(0 0 0 0)', opacity: 1}], {duration: 1500, easing: curve, fill: 'backwards'});
          [...card.querySelectorAll('h3,p')].forEach((line, j) => line.animate([{opacity: 0, transform: 'translateY(35px)'}, {opacity: 1, transform: 'none'}],
            {duration: 900, delay: 750 + j * 90, easing: curve, fill: 'backwards'}));
          return;
        }
        const dx = -slot * size.slot / .92;
        media.animate([{opacity: 0, transform: `perspective(1800px) translateX(${dx.toFixed(0)}px) scale(.8) rotateY(${slot < 0 ? 24 : -24}deg)`}, {opacity: 1, transform: 'none'}],
          {duration: 1900, delay: 170 + (Math.abs(slot) - .5) * 90, easing: curve, fill: 'backwards'});
      });
      win.setTimeout(finish, 1300);
    }
    videos.forEach((video, index) => {
      if (!video) return;
      video.addEventListener('ended', () => { if (index === active) advance(); });
      // Once the playing clip is all here, the next one starts downloading (the cards farther off are under their covers).
      const ahead = () => { if (index === active && loadedFully(video)) prepare((index + 1) % n, true); };
      video.addEventListener('progress', ahead); video.addEventListener('canplaythrough', ahead);
      video.addEventListener('timeupdate', () => {
        const bar = cards[index].querySelector('.landing-scene-time i');
        if (bar && video.duration) bar.style.width = (video.currentTime / video.duration * 100).toFixed(1) + '%';
      });
      video.parentElement.addEventListener('click', () => {
        touchedAt = now(); prepare(index, true);
        if (index !== active) { go(index); if (quiet()) start(video); return; }
        if (video.paused) start(video); else if (video.pause) video.pause();
      });
    });
    // Hands: a drag follows at half the pointer's distance; past 40 px or a flick it moves one card, shorter drags
    // settle back. A tap (under 6 px) stays a click; the click that ends a drag is swallowed.
    let press = null, dragged = false, swipe = 0, swipedAt = -Infinity;
    rail.addEventListener('pointerdown', event => {
      if (event.button > 0) return;
      press = {id: event.pointerId, x: event.clientX, y: event.clientY, t: clock(), moving: false};
    });
    rail.addEventListener('pointermove', event => {
      if (!press || press.id !== event.pointerId) return;
      const dx = event.clientX - press.x, dy = event.clientY - press.y;
      if (!press.moving) {
        if (Math.abs(dx) < 6 || Math.abs(dx) < Math.abs(dy)) return;
        press.moving = true; rail.classList.add('is-dragging');
        if (rail.setPointerCapture) try { rail.setPointerCapture(event.pointerId); } catch (_) { /* already released */ }
        const t = clock(); cards.forEach((card, k) => { const slot = place(t, k); at[k] = {from: slot, to: slot, start: t, delay: 0}; });
      }
      drag = quiet() ? 0 : dx * .5 / size.slot; paint();
    });
    const release = event => {
      if (!press || press.id !== event.pointerId) return;
      const was = press; press = null; rail.classList.remove('is-dragging');
      if (!was.moving) return;
      dragged = true; touchedAt = now();
      const dx = event.clientX - was.x, speed = dx / Math.max(1, clock() - was.t);
      const step = event.type === 'pointercancel' ? 0 : dx < -40 || speed < -.45 ? 1 : dx > 40 || speed > .45 ? -1 : 0;
      go(active + step);
    };
    rail.addEventListener('pointerup', release); rail.addEventListener('pointercancel', release);
    rail.addEventListener('click', event => { if (dragged) { dragged = false; event.preventDefault(); event.stopPropagation(); } }, true);
    rail.addEventListener('wheel', event => {
      if (Math.abs(event.deltaX) <= Math.abs(event.deltaY)) return;   // the page's own scroll
      event.preventDefault(); touchedAt = now();
      if (clock() - swipedAt < 450) return;
      swipe += event.deltaX;
      if (Math.abs(swipe) >= 30) { go(active + Math.sign(swipe)); swipe = 0; swipedAt = clock(); }
    }, {passive: false});
    rail.addEventListener('keydown', event => {
      if (event.altKey || event.ctrlKey || event.metaKey) return;
      const to = {ArrowRight: active + 1, ArrowLeft: active - 1, Home: 0, End: n - 1}[event.key];
      if (to === undefined) return;
      event.preventDefault(); touchedAt = now(); go(to);
    });
    for (const type of ['pointerdown', 'touchstart']) rail.addEventListener(type, () => { touchedAt = now(); }, {passive: true});
    for (const card of cards) {
      const media = card.querySelector('.landing-scene-media'), title = card.querySelector('h3');
      if (!media || !title) continue;
      const cover = doc.createElement('div'), number = title.querySelector('.landing-scene-no');
      cover.className = 'landing-scene-cover'; cover.setAttribute('aria-hidden', 'true');
      const no = doc.createElement('span'), name = doc.createElement('b');
      no.textContent = number ? number.textContent : ''; name.textContent = [...title.childNodes].filter(node => node !== number).map(node => node.textContent).join('').trim();
      cover.append(no, name); media.append(cover);
    }
    rail.classList.add('is-swipe'); measure(); paint();
    win.addEventListener('resize', () => { measure(); paint(); });
    if (doc.fonts && doc.fonts.ready) doc.fonts.ready.then(() => { measure(); paint(); });
    new win.IntersectionObserver(entries => {
      onScreen = entries.some(entry => entry.isIntersecting && entry.intersectionRatio > 0);
      if (!onScreen) { videos.forEach(video => video && video.pause && video.pause()); return; }
      if (active < 0) activate(0); else play(active);
    }, {threshold: .25}).observe(rail);
    const opening = new win.IntersectionObserver(entries => {
      if (!entries.some(entry => entry.isIntersecting && entry.intersectionRatio >= .45)) return;
      opening.disconnect(); measure(); paint(); open();
    }, {threshold: .45});
    opening.observe(rail);
    // A screen before the rail: the first clip starts downloading.
    const near = new win.IntersectionObserver(entries => {
      if (!entries.some(entry => entry.isIntersecting)) return;
      near.disconnect(); prepare(0, !quiet());
    }, {rootMargin: '600px 0px'});
    near.observe(rail);
    doc.addEventListener('visibilitychange', () => {
      const video = videos[active];
      if (video && doc.hidden && video.pause) video.pause(); else if (video && onScreen && opened && !quiet()) start(video);
    });
    return {rail, go, advance, next: () => { touchedAt = now(); go(active + 1); }, get active() { return active; }};
  }
  // CSS cubic-bezier timing: Newton steps on x, then y.
  function bezier(x1, y1, x2, y2) {
    const axis = (a, b) => t => ((1 - 3 * b + 3 * a) * t + (3 * b - 6 * a)) * t * t + 3 * a * t;
    const x = axis(x1, x2), y = axis(y1, y2), slope = t => (3 * (1 - 3 * x2 + 3 * x1) * t + 2 * (3 * x2 - 6 * x1)) * t + 3 * x1;
    return u => {
      let t = u;
      for (let i = 0; i < 6; i++) { const s = slope(t); if (Math.abs(s) < 1e-6) break; t -= (x(t) - u) / s; }
      return y(Math.min(1, Math.max(0, t)));
    };
  }
  return {capabilityURL, project, init, scenes};
}));
