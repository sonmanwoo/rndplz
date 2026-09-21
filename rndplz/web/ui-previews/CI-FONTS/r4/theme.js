/* Appearance only. Does not recreate content, select an H, or control motion. */
(() => {
  'use strict';
  const key = 'susomun.theme';
  const root = document.documentElement;
  const valid = value => value === 'dark' ? 'dark' : 'light';
  let mode = 'light';
  try { mode = valid(localStorage.getItem(key)); } catch {}
  function paint(next) {
    mode = valid(next);
    root.dataset.theme = mode;
    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.content = mode === 'dark' ? '#181d1a' : '#f4f2eb';
    document.querySelectorAll('[data-theme-set]').forEach(button => {
      button.setAttribute('aria-pressed', String(button.dataset.themeSet === mode));
    });
  }
  paint(mode);
  function ready() {
    paint(mode);
    document.querySelectorAll('[data-theme-controls]').forEach(group => { group.hidden = false; });
    document.querySelectorAll('[data-theme-set]').forEach(button => {
      button.addEventListener('click', () => {
        if (!['light', 'dark'].includes(button.dataset.themeSet)) return;
        paint(button.dataset.themeSet);
        let saved = true;
        try { localStorage.setItem(key, mode); } catch { saved = false; }
        const status = document.getElementById('themeStatus');
        if (status) status.textContent = (mode === 'dark' ? '다크' : '라이트') + ' 모드' + (saved ? '' : ' · 이 화면에 적용했습니다.');
      });
    });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', ready, {once: true});
  else ready();
  window.addEventListener('storage', event => {
    if (event.key !== key && event.key !== null) return;
    try { if (event.storageArea !== localStorage) return; } catch { return; }
    paint(event.key === null ? 'light' : event.newValue);
    const status = document.getElementById('themeStatus');
    if (status) status.textContent = (mode === 'dark' ? '다크' : '라이트') + ' 모드';
  });
})();
