/* LANDING r1: below-fold content, loaded only when the introduction enters the viewport. */
(function (root, factory) {
  'use strict';
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else api.init(root);
}(typeof window !== 'undefined' ? window : globalThis, function () {
  'use strict';
  const capabilityURL = id => '/explore?capability=' + encodeURIComponent(id) + '#map';
  const safePortrait = path => typeof path === 'string' && /^\/portraits\/[a-z0-9][a-z0-9_-]*\.(?:webp|png|jpe?g)$/i.test(path)
    ? path.replace(/\.(?:png|jpe?g)$/i, '-thumb.webp') : '';
  function project(data) {
    const people = (Array.isArray(data?.people) ? data.people : []).filter(person => person &&
      typeof person.id === 'string' && person.id.startsWith('PUB-') && safePortrait(person.profile?.portrait?.path))
      .map(person => ({id:person.id, name:person.profile?.display_name || person.name || '연구자',
        portrait:safePortrait(person.profile.portrait.path), field:typeof person.field_label === 'string' ? person.field_label : ''}));
    const byId = new Map(people.map(person => [person.id, person]));
    const fields = (Array.isArray(data?.capabilities) ? data.capabilities : []).filter(field => field &&
      typeof field.id === 'string' && typeof field.label === 'string' && field.label.trim())
      .map(field => ({id:field.id, label:field.label, people:(Array.isArray(field.people) ? field.people : []).map(link => byId.get(link?.id)).filter(Boolean)}));
    // Preserve the API's order, including fields without a public portrait.
    for (const person of people) if (!person.field) person.field = fields.find(field => field.people.some(item => item.id === person.id))?.label || '연구 기록';
    return {people, fields};
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
    const image = (src, className) => {
      const img = node('img', className); img.alt = ''; img.loading = 'lazy'; img.decoding = 'async';
      img.dataset.src = src; return img;
    };
    function lazyImages(host) {
      for (const img of host.querySelectorAll('img[data-src]')) whenVisible(img, () => { img.src = img.dataset.src; delete img.dataset.src; });
    }
    lazyImages($('landingFeatures'));
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
    function render(data) {
      const projected = project(data), people = projected.people; fields = projected.fields;
      start = (fields.length - FOCUS) % Math.max(fields.length, 1); // the first field opens on the highlighted row
      paintFields(); syncTimer();
      const all = $('landingFieldsAll'); all.hidden = !fields.length; all.textContent = '연구 맵에서 분야 ' + fields.length + '개 모두 보기';
      const rail = $('landingPeopleRail'); rail.replaceChildren();
      if (body.dataset.landing === 'people') for (const person of people) {
        const item = node('li', 'landing-person'), collage = node('div', 'landing-collage'); collage.setAttribute('aria-hidden', 'true');
        const related = fields.find(field => field.people.some(peer => peer.id === person.id))?.people || [person];
        const peers = related.filter(peer => peer.id !== person.id).slice(0, 3);
        while (peers.length < 3) peers.push(person);
        peers.forEach(peer => collage.append(image(peer.portrait, '')));
        const avatar = image(person.portrait, 'landing-avatar'); avatar.width = 68; avatar.height = 68;
        const button = node('button', 'landing-pill landing-primary', '카드 보기'); button.type = 'button';
        button.setAttribute('aria-label', person.name + ' 카드 보기');
        button.addEventListener('click', async () => {
          const error = $('landingPersonError'); error.hidden = true; button.setAttribute('aria-busy','true');
          try { await landing.openPersonCard(person.id, button); }
          catch (_) { error.textContent = '인물 카드를 불러오지 못했어요. 다시 눌러 주세요.'; error.hidden = false; }
          finally { button.removeAttribute('aria-busy'); }
        });
        item.append(collage, avatar, node('h3', '', person.name), node('p', '', person.field), button); rail.append(item);
      }
      lazyImages(rail);
      const fieldStatus = fieldsHost.querySelector('[data-landing-data-status]');
      fieldStatus.hidden = fields.length > 0; fieldStatus.textContent = '지금 표시할 분야가 없어요. 연구 맵에서 확인해 주세요.';
      const peopleStatus = $('landingPeople').querySelector('[data-landing-data-status]');
      peopleStatus.hidden = people.length > 0; peopleStatus.textContent = '지금 표시할 공개 인물이 없어요. 연구 맵에서 확인해 주세요.';
    }
    let dataWork = null;
    function loadData() {
      if (dataWork) return dataWork;
      const retry = doc.querySelector('[data-landing-retry]'); retry.hidden = true;
      dataWork = win.fetch('/api/people-map?view=home&landing=1', {credentials:'same-origin'})
        .then(response => { if (!response.ok) throw new Error('map'); return response.json(); })
        .then(data => { if (!Array.isArray(data?.people) || !Array.isArray(data?.capabilities)) throw new Error('map'); render(data); })
        .catch(() => {
          dataWork = null; retry.hidden = false;
          for (const status of doc.querySelectorAll('[data-landing-data-status]')) { status.hidden = false; status.textContent = '자료를 불러오지 못했어요. 잠시 후 다시 시도해 주세요.'; }
        });
      return dataWork;
    }
    doc.querySelector('[data-landing-retry]').addEventListener('click', loadData);
    whenVisible(fieldsHost, loadData);
    if (body.dataset.landing === 'people') whenVisible($('landingPeople'), loadData);
    else whenVisible($('landingMap'), async () => {
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
  return {capabilityURL, safePortrait, project, init};
}));
