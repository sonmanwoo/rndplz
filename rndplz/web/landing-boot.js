/* Only opt-in HTML loads this small entry. Large below-fold code waits for visibility. */
(() => {
  'use strict';
  const body = document.body;
  if (!['people', 'map'].includes(body.dataset.landing)) return;
  const urls = JSON.parse(body.dataset.landingAssets || '{}'), pending = new Map();
  const quiet = () => matchMedia('(prefers-reduced-motion: reduce)').matches || body.classList.contains('no-motion');
  function loadScript(path) {
    if (!pending.has(path)) pending.set(path, new Promise((resolve, reject) => {
      const script = document.createElement('script');
      script.src = urls[path] || path;
      script.onload = resolve;
      script.onerror = () => { script.remove(); pending.delete(path); reject(new Error('자료를 불러오지 못했어요. 다시 시도해 주세요.')); };
      document.head.append(script);
    }));
    return pending.get(path);
  }
  let mapDependencies;
  function loadMapDependencies() {
    if (!mapDependencies) mapDependencies = (async () => {
      for (const path of ['/people-map-model.js', '/people-map-layout.js', '/people-map-graph.js', '/people-map.js']) await loadScript(path);
    })().catch(error => { mapDependencies = null; throw error; });
    return mapDependencies;
  }
  const openPersonCard = (...args) => window.openPersonCard(...args);
  const loadRecommendation = async () => {
    await loadMapDependencies();
    return import(urls['/recommendation-map.js'] || '/recommendation-map.js');
  };
  window.Landing = {loadScript, quiet, openPersonCard, loadRecommendation};
  const down = document.getElementById('landingDown'), first = document.getElementById('landingFeatures');
  down?.addEventListener('click', event => {
    event.preventDefault(); first.focus({preventScroll:true}); first.scrollIntoView({behavior:quiet() ? 'instant' : 'smooth', block:'start'});
  });
  if (body.dataset.landing === 'map') {
    document.getElementById('landingPeople').hidden = true;
    document.getElementById('landingMap').hidden = false;
  }
  const start = () => loadScript('/landing.js').catch(() => {
    first.querySelector('h2').textContent = '수소문으로 할 수 있는 일';
    // A visible, keyboard reachable retry also covers a transient script request failure.
    if (first.querySelector('[data-landing-start]')) return;
    const retry = document.createElement('button'); retry.type = 'button'; retry.className = 'landing-pill';
    retry.dataset.landingStart = ''; retry.textContent = '소개 다시 불러오기';
    retry.addEventListener('click', () => { retry.remove(); start(); }); first.append(retry);
  });
  if ('IntersectionObserver' in window) {
    const observer = new IntersectionObserver(entries => {
      if (entries.some(entry => entry.isIntersecting && entry.intersectionRatio > 0)) { observer.disconnect(); start(); }
    }, {threshold:0.01});
    observer.observe(first);
  } else start();
})();
