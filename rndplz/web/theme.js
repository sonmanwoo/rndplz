/* Appearance only: no conversation, profile, filtering, or motion state changes. */
(() => {
  'use strict';
  const key = 'susomun.theme';
  const root = document.documentElement;
  const normalize = value => value === 'dark' ? 'dark' : 'light';
  let mode = 'light';
  let readyDone = false;
  const meta = document.querySelector('meta[name="theme-color"]');
  const lightMeta = meta?.content || '#f4f2eb';
  try { mode = normalize(localStorage.getItem(key)); } catch {}

  function paint(next) {
    const value = normalize(next);
    const changed = root.dataset.theme !== value;
    mode = value;
    if (changed) root.dataset.theme = mode;
    if (root.style.colorScheme !== mode) root.style.colorScheme = mode;
    if (meta) {
      const color = mode === 'dark' ? '#181d1a' : lightMeta;
      if (meta.content !== color) meta.content = color;
    }
    document.querySelectorAll('[data-theme-set]').forEach(button => {
      const pressed = String(button.dataset.themeSet === mode);
      if (button.getAttribute('aria-pressed') !== pressed) button.setAttribute('aria-pressed', pressed);
    });
    if (changed && readyDone) window.dispatchEvent(new CustomEvent('susomun:themechange', {detail: {mode}}));
  }

  // External blocking head script: set the root before any stylesheet is loaded.
  paint(mode);
  function ready() {
    if (readyDone) return;
    paint(mode);
    readyDone = true;
    document.querySelectorAll('[data-theme-controls]').forEach(group => { group.hidden = false; });
    document.querySelectorAll('[data-theme-set]').forEach(button => {
      button.addEventListener('click', () => {
        if (!['light', 'dark'].includes(button.dataset.themeSet)) return;
        paint(button.dataset.themeSet);
        // A blocked store must not prevent changing this tab's appearance.
        try { localStorage.setItem(key, mode); } catch {}
      });
    });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', ready, {once: true});
  else ready();
  window.addEventListener('storage', event => {
    if (event.key !== key && event.key !== null) return;
    try { if (event.storageArea !== localStorage) return; } catch { return; }
    paint(event.key === null ? 'light' : event.newValue);
  });
})();
