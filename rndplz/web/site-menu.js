/* The header's one "more" menu: new chat, model settings, promo material, motion and feedback.
 * Each item keeps the id or data attribute its own script listens to; this only opens and closes the list.
 * 2026-10-13, after Cadence's Gooey Menu: the items are grey pills that melt out of the ··· button through an SVG
 * goo filter and slide down into a column hanging from it, each leaving as a circle and stretching to the column's
 * one width as it breaks free; closing pulls them back in. With motion off the column just appears; a screen too
 * short for the column keeps the plain panel. */
(() => {
  'use strict';
  const toggle = document.getElementById('siteMenuToggle'), menu = document.getElementById('siteMenu');
  if (!toggle || !menu) return;
  const usable = () => [...menu.querySelectorAll('a,button,select')].filter(node => !node.disabled && node.getClientRects().length);
  const quiet = () => document.body.classList.contains('no-motion') || matchMedia('(prefers-reduced-motion: reduce)').matches;
  // Cadence: 44 px pills; the gap stays wider than the distance at which the goo fuses two shapes (≈1.5 × the blur).
  // One width for every pill (the widest label), and room for the model choice when it is there.
  const NS = 'http://www.w3.org/2000/svg', PILL = 44, GAP = 18, CLEAR = 15, ROOM = 24, MODEL = 200;
  const goo = document.createElementNS(NS, 'svg');
  goo.setAttribute('class', 'site-menu-goo'); goo.setAttribute('aria-hidden', 'true');
  goo.innerHTML = '<filter id="siteMenuGoo" filterUnits="userSpaceOnUse" x="0" y="0" width="100%" height="100%">' +
    '<feGaussianBlur in="SourceGraphic" stdDeviation="8" result="blur"/>' +
    '<feColorMatrix in="blur" mode="matrix" values="1 0 0 0 0  0 1 0 0 0  0 0 1 0 0  0 0 0 60 -27" result="goo"/>' +
    '<feComposite in="SourceGraphic" in2="goo" operator="atop"/></filter><g filter="url(#siteMenuGoo)"></g>';
  const blobs = goo.lastElementChild;
  toggle.querySelector('svg')?.insertAdjacentHTML('beforeend', '<path class="site-menu-x" d="M7.5 7.5l9 9M16.5 7.5l-9 9" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>');
  const ease = {
    out3: t => 1 - (1 - t) ** 3,
    inOut3: t => t < .5 ? 4 * t ** 3 : 1 - (-2 * t + 2) ** 3 / 2,
    out2: t => 1 - (1 - t) ** 2,
    sine: t => -(Math.cos(Math.PI * t) - 1) / 2,
  };
  // One progress value drives the whole column; the button dips while it lets go.
  let p = 0, target = 0, dip = 1, layout = null;
  const runs = {};
  function run(name, from, to, ms, curve, set, done) {
    cancelAnimationFrame(runs[name] || 0);
    const t0 = performance.now();
    const step = now => {
      const u = Math.min(1, (now - t0) / ms);
      set(u < 1 ? from + (to - from) * curve(u) : to); paint();   // lands exactly on `to`: the hover waits for p === 1
      if (u < 1) runs[name] = requestAnimationFrame(step); else { runs[name] = 0; if (done) done(); }
    };
    runs[name] = requestAnimationFrame(step);
  }
  const rect = () => { const shape = document.createElementNS(NS, 'rect'); blobs.append(shape); return shape; };
  const place = (shape, x, y, w, h) => {
    shape.setAttribute('x', x.toFixed(1)); shape.setAttribute('y', y.toFixed(1));
    shape.setAttribute('width', w.toFixed(1)); shape.setAttribute('height', h.toFixed(1));
    shape.setAttribute('rx', (Math.min(w, h, PILL) / 2).toFixed(1));
  };
  // Measured each time the menu opens, in the button's own coordinates: the pills hang right-aligned under it.
  function measure() {
    const items = [...menu.querySelectorAll('.site-menu-item')].filter(item => getComputedStyle(item).display !== 'none');
    const box = toggle.getBoundingClientRect(), tw = toggle.offsetWidth, th = toggle.offsetHeight;
    const right = tw / 2 + PILL / 2, rest = th / 2 - PILL / 2;
    const room = Math.floor(box.left + right - 12);   // never past the screen's left edge
    menu.style.setProperty('--room', room + 'px');
    for (const item of items) item.style.width = item.style.height = '';
    // fractional widths: a label rounded down by a hair gets an ellipsis
    const width = Math.min(room, Math.max(PILL, ...items.map(item => item.classList.contains('site-menu-model') ? MODEL : Math.ceil(item.getBoundingClientRect().width + .5))));
    let top = th + GAP;
    const rows = items.map(item => {
      item.style.width = width + 'px';
      const row = {item, w: width, h: Math.max(PILL, Math.ceil(item.getBoundingClientRect().height)), top};
      top += row.h + GAP; return row;
    });
    const bottom = top - GAP;
    if (!rows.length || box.top + bottom + ROOM > innerHeight) return null;   // the column and the blur's room fit the screen
    const left = Math.max(-box.left, Math.min(0, ...rows.map(row => right - row.w)) - ROOM);   // the blur's room, but on screen
    blobs.replaceChildren();
    const button = rect();
    for (const row of rows) { row.shape = rect(); row.item.style.height = row.h + 'px'; row.item.style.left = (right - row.w - left) + 'px'; }
    Object.assign(menu.style, {left: left + 'px', top: (rest - ROOM) + 'px', width: (right - left + ROOM) + 'px', height: (bottom - rest + 2 * ROOM) + 'px'});
    return {rows, button, tw, th, right, rest, left, travel: rows.at(-1).top - rest};
  }
  function paint() {
    const L = layout;
    if (!L) return;
    const ox = L.left, oy = L.rest - ROOM, bw = L.tw * dip, bh = L.th * dip;
    place(L.button, L.tw / 2 - bw / 2 - ox, L.th / 2 - bh / 2 - oy, bw, bh);
    toggle.style.transform = dip === 1 ? '' : `scale(${dip.toFixed(4)})`;
    for (const row of L.rows) {
      // Picture the finished column sliding down out of the button as one strip: a pill waits inside until the
      // strip reaches it, then rides along at its final spacing, so pills melt into the button, never each other.
      const top = Math.max(L.rest, row.top - L.travel * (1 - p));
      const out = Math.min(1, (top - L.rest) / (L.th + CLEAR - L.rest)), grow = out * out * (3 - 2 * out);
      const w = PILL + (row.w - PILL) * grow, h = PILL + (row.h - PILL) * grow;
      place(row.shape, L.right - w - ox, top - oy, w, h);
      row.item.style.top = (top - oy) + 'px';
      row.item.style.opacity = Math.max(0, (out - .6) / .4).toFixed(3);
    }
    menu.classList.toggle('is-landed', p >= .9);   // pressable as it settles; the ink hover waits for p === 1 (heat)
  }
  function settle() {
    for (const item of menu.querySelectorAll('.site-menu-item')) for (const key of ['width', 'height', 'left', 'top', 'opacity']) item.style[key] = '';
    for (const key of ['left', 'top', 'width', 'height']) menu.style[key] = '';
    for (const hot of menu.querySelectorAll('.is-hot')) hot.classList.remove('is-hot');
    menu.classList.remove('is-goo', 'is-landed'); toggle.style.transform = ''; blobs.replaceChildren(); layout = null;
  }
  function open() {
    target = 1;
    menu.hidden = false; toggle.setAttribute('aria-expanded', 'true');
    if (!layout) {
      menu.classList.add('is-goo');
      if (!menu.contains(goo)) menu.prepend(goo);
      layout = measure();
      if (!layout) { settle(); p = 1; return; }   // too short a screen: the plain panel
      // Labels never shown before may still be fetching their font subset: measure again once it is here.
      requestAnimationFrame(() => document.fonts?.ready.then(() => { if (target === 1 && layout) { layout = measure(); if (!layout) settle(); else paint(); } }));
    }
    if (quiet()) { p = 1; dip = 1; paint(); return; }
    run('p', p, 1, 1100, ease.out3, value => { p = value; });
    run('dip', dip, .94, 350, ease.sine, value => { dip = value; }, () => run('dip', dip, 1, 700, ease.out2, value => { dip = value; }));
  }
  const close = focus => {
    if (target === 0) return;
    target = 0; toggle.setAttribute('aria-expanded', 'false');
    for (const hot of menu.querySelectorAll('.is-hot')) hot.classList.remove('is-hot');
    if (focus) toggle.focus();
    const done = () => { if (target === 0) { menu.hidden = true; p = 0; dip = 1; settle(); } };
    if (!layout || quiet()) { cancelAnimationFrame(runs.p || 0); cancelAnimationFrame(runs.dip || 0); done(); return; }
    run('p', p, 0, 750, ease.inOut3, value => { p = value; }, done);
    run('dip', dip, 1, 300, ease.out2, value => { dip = value; });
  };
  toggle.addEventListener('click', () => {
    if (target === 0) { open(); usable()[0]?.focus(); } else close(false);
  });
  // A landed pill turns ink under the pointer or keyboard focus (the model choice stays a plain pill).
  const heat = (item, on) => {
    const row = layout?.rows.find(r => r.item === item);
    if (!row || item.classList.contains('site-menu-model')) return;
    item.classList.toggle('is-hot', on && p === 1); row.shape.classList.toggle('is-hot', on && p === 1);
  };
  menu.addEventListener('pointerover', event => { const item = event.target.closest('.site-menu-item'); if (item) heat(item, true); });
  menu.addEventListener('pointerout', event => { const item = event.target.closest('.site-menu-item'); if (item && !item.contains(event.relatedTarget)) heat(item, false); });
  menu.addEventListener('focusin', event => { const item = event.target.closest('.site-menu-item'); if (item && item.matches(':focus-visible')) heat(item, true); });
  menu.addEventListener('focusout', event => { const item = event.target.closest('.site-menu-item'); if (item) heat(item, false); });
  addEventListener('resize', () => { if (target === 1 && layout) { layout = measure(); if (!layout) settle(); else paint(); } });
  // An item's own handler runs first; the menu closes after, except for the motion switch, which stays to show its state.
  document.addEventListener('click', event => {
    if (!event.target.closest('.site-menu-control')) close(false);
    else if (event.target.closest('#siteMenu a,#siteMenu button:not([data-motion-toggle])')) close(false);
  });
  document.addEventListener('keydown', event => {
    if (target === 0) return;
    if (event.key === 'Escape') { event.preventDefault(); close(true); return; }
    if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') return;
    if (!menu.contains(document.activeElement) && document.activeElement !== toggle) return;
    if (document.activeElement?.tagName === 'SELECT') return;
    const items = usable(), at = items.indexOf(document.activeElement);
    if (!items.length) return;
    event.preventDefault();
    items[(at + (event.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length].focus();
  });
})();
