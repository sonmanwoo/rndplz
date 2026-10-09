/* Landing capability links enter the existing research-map selection flow. */
(function (root, factory) {
  'use strict';
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else factory().mount(root);
}(typeof window !== 'undefined' ? window : globalThis, function () {
  'use strict';

  function capabilityFromLocation(location) {
    if (!location || location.pathname !== '/explore' ||
        (location.hash && location.hash !== '#map')) return '';
    return new URLSearchParams(location.search || '').get('capability') || '';
  }

  function mount(win) {
    const capability = capabilityFromLocation(win.location);
    const host = capability && win.document.getElementById('peopleMapHost');
    if (!host) return function () {};
    let observer = null, timer = null, stopped = false;

    function stop() {
      if (stopped) return;
      stopped = true;
      if (observer) observer.disconnect();
      if (timer !== null) win.clearTimeout(timer);
      win.removeEventListener('pagehide', stop);
    }

    function apply() {
      if (stopped) return;
      if (!host.isConnected) { stop(); return; }
      const controls = host.querySelector('#capability-controls');
      const buttons = controls ? Array.from(controls.querySelectorAll('[data-capability]')) : [];
      if (!buttons.length) return;
      // Compare data values, never put a URL value into a selector or HTML.
      const target = buttons.find(button => button.dataset.capability === capability);
      // An unknown or removed capability leaves the map's ordinary state intact.
      stop();
      if (target && target.getAttribute('aria-pressed') !== 'true') target.click();
    }

    apply();
    if (stopped) return stop;
    // The existing map fetches and mounts asynchronously. Observe only until its
    // controls exist, or 30 seconds; map failures retain the existing retry UI.
    if (typeof win.MutationObserver !== 'function') { stop(); return stop; }
    observer = new win.MutationObserver(apply);
    observer.observe(host, {childList: true, subtree: true});
    timer = win.setTimeout(stop, 30000);
    win.addEventListener('pagehide', stop, {once: true});
    return stop;
  }

  return {capabilityFromLocation, mount};
}));
