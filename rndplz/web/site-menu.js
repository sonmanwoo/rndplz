/* The header's one "more" menu: new chat, model settings, promo material, motion and feedback.
 * Each item keeps the id or data attribute its own script listens to; this only opens and closes the list. */
(() => {
  'use strict';
  const toggle = document.getElementById('siteMenuToggle'), menu = document.getElementById('siteMenu');
  if (!toggle || !menu) return;
  const usable = () => [...menu.querySelectorAll('a,button')].filter(node => !node.disabled && node.getClientRects().length);
  const close = focus => {
    if (menu.hidden) return;
    menu.hidden = true; toggle.setAttribute('aria-expanded', 'false');
    if (focus) toggle.focus();
  };
  toggle.addEventListener('click', () => {
    const open = menu.hidden;
    menu.hidden = !open; toggle.setAttribute('aria-expanded', String(open));
    if (open) usable()[0]?.focus();
  });
  // An item's own handler runs first; the menu closes after, except for the motion switch, which stays to show its state.
  document.addEventListener('click', event => {
    if (!event.target.closest('.site-menu-control')) close(false);
    else if (event.target.closest('#siteMenu a,#siteMenu button:not([data-motion-toggle])')) close(false);
  });
  document.addEventListener('keydown', event => {
    if (menu.hidden) return;
    if (event.key === 'Escape') { event.preventDefault(); close(true); return; }
    if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') return;
    if (!menu.contains(document.activeElement) && document.activeElement !== toggle) return;
    const items = usable(), at = items.indexOf(document.activeElement);
    if (!items.length) return;
    event.preventDefault();
    items[(at + (event.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length].focus();
  });
})();
