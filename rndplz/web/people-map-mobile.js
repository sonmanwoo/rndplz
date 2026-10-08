/* Research map on a phone: the map comes first. A thin bar above it opens the search/conditions and the
 * capability list as bottom sheets; those controls stay where people-map.js renders them and keep their
 * listeners — on a phone people-map.css only shows them as sheets while one is open. */
(() => {
  'use strict';
  const host = document.getElementById('peopleMapHost');
  if (!host) return;
  const phone = matchMedia('(max-width: 700px)');
  const SEARCH = '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true"><circle cx="11" cy="11" r="6.5"/><path d="m16 16 4.5 4.5"/></svg>';
  const CHEVRON = '<svg viewBox="0 0 10 6" width="10" height="6" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true"><path d="m1 1 4 4 4-4"/></svg>';
  let map = null, bar = null, opener = null;

  const sheets = () => ({ filters:map.querySelector('.mp-filters'), capabilities:map.querySelector('.mp-navigation') });
  function close(focus = true) {
    if (!map?.dataset.mpSheet) return;
    delete map.dataset.mpSheet; document.documentElement.classList.remove('mp-sheet-open');
    bar.querySelectorAll('[data-mp-sheet]').forEach(b => b.setAttribute('aria-expanded', 'false'));
    if (focus) opener?.focus({ preventScroll:true });
  }
  function open(name, button) {
    if (map.dataset.mpSheet === name) { close(); return; }
    map.dataset.mpSheet = name; opener = button; document.documentElement.classList.add('mp-sheet-open');
    bar.querySelectorAll('[data-mp-sheet]').forEach(b => b.setAttribute('aria-expanded', String(b === button)));
    const first = sheets()[name]?.querySelector(name === 'filters' ? 'input,select,button:not(.mp-sheet-close)' : '[aria-pressed="true"],[data-capability]');
    first?.focus({ preventScroll:true });
  }
  // The bar shows what is chosen: the capability's name and whether a search or condition is on. Text is only
  // written when it changes, since the bar sits inside the observed map.
  const put = (node, text) => { if (node && node.textContent !== text) node.textContent = text; };
  function sync() {
    if (!bar) return;
    const chosen = map.querySelector('[data-capability][aria-pressed="true"] .mp-capability-label')?.textContent.trim();
    const total = map.querySelectorAll('[data-capability]').length;
    put(bar.querySelector('[data-mp-sheet="capabilities"] .mp-bar-text'), chosen || ('역량 ' + (total || '')));
    bar.querySelector('[data-mp-sheet="capabilities"]').classList.toggle('is-active', Boolean(chosen));
    const query = map.querySelector('#name-search')?.value.trim(), topic = map.querySelector('#topic-controls')?.value, view = map.querySelector('#view-control')?.value;
    const filtered = Boolean(query || topic || (view && view !== 'experience'));
    put(bar.querySelector('[data-mp-sheet="filters"] .mp-bar-text'), query ? '“' + query + '”' : '검색·조건');
    bar.querySelector('[data-mp-sheet="filters"]').classList.toggle('is-active', filtered);
    put(bar.querySelector('.mp-bar-summary'), (map.querySelector('#results-summary')?.textContent || '').split(' · ')[0]);
  }
  function install() {
    map = host.querySelector('#people-map-content');
    const layout = map?.querySelector('.mp-layout'), { filters, capabilities } = map ? sheets() : {};
    if (!layout || !filters || !capabilities || map.querySelector('.mp-mobile-bar')) return;
    filters.id ||= 'mp-filter-sheet'; capabilities.id ||= 'mp-capability-sheet';
    bar = document.createElement('div');
    bar.className = 'mp-mobile-bar'; bar.setAttribute('role', 'toolbar'); bar.setAttribute('aria-label', '연구 맵 조건');
    bar.innerHTML = '<button type="button" class="mp-bar-button" data-mp-sheet="filters" aria-controls="' + filters.id + '" aria-expanded="false">' + SEARCH + '<span class="mp-bar-text">검색·조건</span></button>'
      + '<button type="button" class="mp-bar-button" data-mp-sheet="capabilities" aria-controls="' + capabilities.id + '" aria-expanded="false"><span class="mp-bar-text">역량</span>' + CHEVRON + '</button>'
      + '<span class="mp-bar-summary" aria-hidden="true"></span>';
    layout.before(bar);
    for (const [sheet, title] of [[filters, '검색·조건'], [capabilities, '역량 고르기']]) {
      const head = document.createElement('div'); head.className = 'mp-sheet-head';
      head.innerHTML = '<b>' + title + '</b><button type="button" class="mp-sheet-close">지도 보기</button>';
      sheet.prepend(head);
    }
    const backdrop = document.createElement('div'); backdrop.className = 'mp-sheet-backdrop'; map.append(backdrop);
    bar.addEventListener('click', event => { const button = event.target.closest('[data-mp-sheet]'); if (button) open(button.dataset.mpSheet, button); });
    backdrop.addEventListener('click', () => close());
    map.addEventListener('click', event => {
      if (event.target.closest('.mp-sheet-close')) close();
      // Choosing a capability shows the map at once.
      else if (map.dataset.mpSheet === 'capabilities' && event.target.closest('[data-capability]')) setTimeout(() => close(false), 0);
    });
    map.addEventListener('input', sync); map.addEventListener('change', sync);
    // Changes inside the bar itself are ignored, and updates wait for the next frame, so the bar never feeds itself.
    let queued = 0;
    new MutationObserver(records => {
      if (queued || records.every(r => bar.contains(r.target))) return;
      queued = requestAnimationFrame(() => { queued = 0; sync(); });
    }).observe(map, { subtree:true, childList:true, characterData:true, attributes:true, attributeFilter:['aria-pressed'] });
    sync();
  }
  document.addEventListener('keydown', event => { if (event.key === 'Escape' && map?.dataset.mpSheet) { event.preventDefault(); close(); } });
  phone.addEventListener('change', () => close(false));
  // people-map.js fills the host after its data arrives; install once the content exists.
  new MutationObserver(() => { if (!host.querySelector('.mp-mobile-bar')) install(); }).observe(host, { childList:true, subtree:true });
  install();
})();
