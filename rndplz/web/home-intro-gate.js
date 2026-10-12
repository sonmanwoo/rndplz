/* Home opening gate (2026-10-12): decided in <head> before the first paint, so neither the page nor a blank screen
   flashes first. A visitor sees the opening on every visit to the home, a signed-in browser once a day
   (rndplz.account.look from account-menu.js, rndplz.intro.day from home-cosmos.js). Motion off, an opened
   conversation (?chat=) and localStorage rndplz.intro = "off" (automation, an operator) skip it.
   home-cosmos.js plays it while <html data-home-intro="play">. */
(() => {
  'use strict';
  try {
    const url = new URL(location.href);
    if (url.pathname !== '/' || url.searchParams.has('chat')) return;
    if (matchMedia('(prefers-reduced-motion: reduce)').matches || sessionStorage.getItem('rndplz-motion') === 'off') return;
    if (localStorage.getItem('rndplz.intro') === 'off') return;
    const day = new Date().toLocaleDateString('sv-SE');
    if (localStorage.getItem('rndplz.account.look') === 'account' && localStorage.getItem('rndplz.intro.day') === day) return;
    document.documentElement.dataset.homeIntro = 'play';
  } catch { /* storage blocked: the home appears without the opening */ }
})();
