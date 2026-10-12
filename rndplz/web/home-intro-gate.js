/* Home opening gate (2026-10-12): decided in <head> before the first paint, so neither the page nor a blank screen
   flashes first. A visitor sees the opening on every visit to the home, a signed-in browser once a day
   (rndplz.account.look from account-menu.js, rndplz.intro.seen from home-cosmos.js, written only once the opening
   plays; the earlier rndplz.intro.day was also written by openings a slow line never showed). Motion off, an opened
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
    if (localStorage.getItem('rndplz.account.look') === 'account' && localStorage.getItem('rndplz.intro.seen') === day) return;
    document.documentElement.dataset.homeIntro = 'play';
    // The opening starts from the people, so they are asked for now, ahead of the fonts and the scripts that a phone line
    // otherwise spends seconds on first (2026-10-13). home-cosmos.js takes this answer instead of asking again.
    window.rndplzHomeData = fetch('/api/people-map?view=home', { credentials:'same-origin' }).then(r => r.ok ? r.json() : null).catch(() => null);
  } catch { /* storage blocked: the home appears without the opening */ }
})();
