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
    if ($('landingFeatureRail')) scenes($('landingFeatureRail'), win, quiet);
    function moveRail(rail, direction) {
      rail.scrollBy({left:direction * (rail.firstElementChild?.getBoundingClientRect().width || rail.clientWidth * .8) + direction * 24,
        behavior:quiet() ? 'instant' : 'smooth'});
    }
    for (const rail of doc.querySelectorAll('.landing-rail')) rail.addEventListener('keydown', event => {
      if (event.altKey || event.ctrlKey || event.metaKey || !['ArrowLeft','ArrowRight','Home','End'].includes(event.key)) return;
      event.preventDefault();
      if (event.key === 'Home' || event.key === 'End') rail.scrollTo({left:event.key === 'Home' ? 0 : rail.scrollWidth, behavior:quiet() ? 'instant' : 'smooth'});
      else moveRail(rail, event.key === 'ArrowRight' ? 1 : -1);
    });
    for (const next of doc.querySelectorAll('[data-landing-next]')) {
      const rail = $(next.dataset.landingNext);
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
  // The scene rail (2026-10-10): the first card in view plays from its start; when it ends the rail slides to the
  // next card and plays it, and after the last card returns to the first. A hand on the rail, the rail out of view,
  // a hidden tab or motion off stops the sliding; with motion off a tap plays a scene.
  function scenes(rail, win, quiet) {
    const doc = win.document, cards = [...rail.children];
    const videos = cards.map(card => card.querySelector('video'));
    if (!videos.some(Boolean) || !('IntersectionObserver' in win)) return null;
    const ratio = new Map(), now = () => Date.now();
    let active = -1, onScreen = false, loaded = false, touchedAt = -Infinity, glidedAt = -Infinity, hold = 0;
    const visible = index => (ratio.get(cards[index]) || 0) >= .6;
    const firstVisible = () => cards.findIndex((card, index) => visible(index));
    const start = video => { const started = video.play && video.play(); if (started && started.catch) started.catch(() => {}); };
    function load() {
      if (loaded) return; loaded = true;
      for (const video of videos) if (video) { video.poster = video.dataset.poster; video.src = video.dataset.src; }
    }
    function play(index) {
      const video = videos[index];
      if (!video || quiet() || !onScreen || doc.hidden) return;
      try { video.currentTime = 0; } catch (_) { /* not loaded yet: it starts from 0 anyway */ }
      start(video);
    }
    function activate(index) {
      win.clearTimeout(hold); active = index;
      videos.forEach((video, k) => { if (video && k !== index && video.pause) video.pause(); });
      cards.forEach((card, k) => card.classList.toggle('is-playing', k === index && !!videos[k]));
      if (videos[index]) play(index);
      else if (!quiet()) hold = win.setTimeout(advance, 4000);   // a still card rests, then the story starts again
    }
    function advance() {
      if (quiet() || !onScreen || doc.hidden) return;
      if (now() - touchedAt < 2500) { play(active); return; }    // someone is reading: replay instead of sliding away
      const next = (active + 1) % cards.length, first = rail.firstElementChild;
      glidedAt = now();
      rail.scrollTo({left: Math.max(0, cards[next].offsetLeft - first.offsetLeft), behavior: quiet() ? 'instant' : 'smooth'});
      activate(next);
    }
    videos.forEach((video, index) => {
      if (!video) return;
      video.addEventListener('ended', () => { if (index === active) advance(); });
      video.addEventListener('timeupdate', () => {
        const bar = cards[index].querySelector('.landing-scene-time i');
        if (bar && video.duration) bar.style.width = (video.currentTime / video.duration * 100).toFixed(1) + '%';
      });
      video.parentElement.addEventListener('click', () => {
        touchedAt = now(); load();
        if (index !== active) { activate(index); if (quiet()) start(video); return; }
        if (video.paused) start(video); else if (video.pause) video.pause();
      });
    });
    for (const type of ['pointerdown', 'touchstart', 'wheel', 'keydown']) rail.addEventListener(type, () => { touchedAt = now(); }, {passive: true});
    const seen = new win.IntersectionObserver(entries => {
      for (const entry of entries) ratio.set(entry.target, entry.intersectionRatio);
      if (now() - glidedAt < 900 || (active >= 0 && visible(active))) return;   // our own slide settles first
      const index = firstVisible();
      if (index >= 0 && index !== active) activate(index);
    }, {root: rail, threshold: [.3, .6, .9]});
    cards.forEach(card => seen.observe(card));
    new win.IntersectionObserver(entries => {
      onScreen = entries.some(entry => entry.isIntersecting && entry.intersectionRatio > 0);
      if (!onScreen) { videos.forEach(video => video && video.pause && video.pause()); return; }
      load();
      if (active < 0) { const index = firstVisible(); activate(index >= 0 ? index : 0); }
      else play(active);
    }, {threshold: .25}).observe(rail);
    doc.addEventListener('visibilitychange', () => {
      const video = videos[active];
      if (video && doc.hidden && video.pause) video.pause(); else if (video && onScreen && !quiet()) start(video);
    });
    return {activate, advance, get active() { return active; }};
  }
  return {capabilityURL, project, init, scenes};
}));
