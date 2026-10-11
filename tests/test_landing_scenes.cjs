'use strict';
// The scene rail in a small DOM double: download one clip at a time, play only what can play through,
// slide on when a clip ends, respect a hand on the rail and motion off.
const assert = require('node:assert/strict');
const {scenes} = require('../rndplz/web/landing.js');

function rig({quiet = false, ready = 4} = {}) {
  const on = (target, type, fn) => { target.events = target.events || new Map(); target.events.set(type, [...(target.events.get(type) || []), fn]); };
  const emit = (target, type) => ((target.events && target.events.get(type)) || []).splice(0).forEach(fn => { fn({}); if (!fn.once) on(target, type, fn); });
  const element = (extra = {}) => ({
    classList: {set: new Set(), toggle(name, value) { if (value) this.set.add(name); else this.set.delete(name); }},
    addEventListener(type, fn, options) { if (options && options.once) fn.once = true; on(this, type, fn); }, ...extra});
  const video = n => element({dataset: {src: '/clip-' + n + '.mp4', poster: '/still-' + n + '.webp'}, plays: 0, pauses: 0, loads: 0, paused: true,
    readyState: ready, currentTime: 3, duration: 5, buffered: {length: 1, end: () => 5},
    load() { this.loads++; }, play() { this.plays++; this.paused = false; this.currentTime = 0; return Promise.resolve(); }, pause() { this.pauses++; this.paused = true; }});
  const cards = [0, 1, 2].map(index => {
    const media = element(), clip = index < 2 ? video(index) : null, bar = {style: {}};
    if (clip) clip.parentElement = media;
    return element({offsetLeft: 2 + index * 300, media, clip, querySelector: selector => selector === 'video' ? clip : bar});
  });
  const rail = element({children: cards, firstElementChild: cards[0], scrolls: [], scrollTo(options) { this.scrolls.push(options); }});
  const observers = [], timers = [];
  const win = {
    document: {hidden: false, addEventListener(type, fn) { on(this, type, fn); }},
    IntersectionObserver: class {
      constructor(callback, options) { this.callback = callback; this.options = options || {}; this.targets = []; observers.push(this); }
      observe(target) { this.targets.push(target); } disconnect() { this.targets = []; }
    },
    setTimeout(fn) { timers.push(fn); return timers.length; }, clearTimeout() {},
  };
  const player = scenes(rail, win, () => quiet);
  const seenCards = observers.find(o => o.options.root === rail);
  const nearRail = observers.find(o => o.options.rootMargin), seenRail = observers.find(o => o.options.root !== rail && !o.options.rootMargin);
  const show = (...ratios) => seenCards.callback(ratios.map((intersectionRatio, index) => ({target: cards[index], intersectionRatio})));
  const near = () => nearRail.callback([{target: rail, isIntersecting: true, intersectionRatio: 0}]);
  const onScreen = value => seenRail.callback([{target: rail, isIntersecting: value, intersectionRatio: value ? 1 : 0}]);
  return {player, cards, rail, timers, show, near, onScreen, emit};
}

// Nothing downloads until the rail is a screen away; then only the first clip, and the second card's still.
let r = rig();
r.show(1, .2, 0);
assert.equal(r.cards[0].clip.src, undefined);
r.near();
assert.equal(r.cards[0].clip.src, '/clip-0.mp4'); assert.equal(r.cards[0].clip.preload, 'auto'); assert.equal(r.cards[0].clip.loads, 1);
assert.equal(r.cards[1].clip.poster, '/still-1.webp'); assert.equal(r.cards[1].clip.src, undefined, 'one download at a time');
r.onScreen(true);
assert.equal(r.player.active, 0); assert.equal(r.cards[0].clip.plays, 1);
assert(r.cards[0].classList.set.has('is-playing'));

// Once the playing clip is all here, the next one starts downloading.
r.emit(r.cards[0].clip, 'progress');
assert.equal(r.cards[1].clip.src, '/clip-1.mp4');

// When a clip ends the rail slides to the next card and plays it; the previous one stops.
r.emit(r.cards[0].clip, 'ended');
assert.deepEqual(r.rail.scrolls.at(-1), {left: 300, behavior: 'smooth'});
assert.equal(r.player.active, 1); assert.equal(r.cards[1].clip.plays, 1); assert(r.cards[0].clip.pauses >= 1);
// The last clip slides to the still card, which rests and then returns the story to the first card.
r.emit(r.cards[1].clip, 'ended');
assert.equal(r.player.active, 2); assert.deepEqual(r.rail.scrolls.at(-1), {left: 600, behavior: 'smooth'});
assert.equal(r.timers.length, 1); r.timers[0]();
assert.equal(r.player.active, 0); assert.deepEqual(r.rail.scrolls.at(-1), {left: 0, behavior: 'smooth'});

// A slow network: the still stays until the clip can play through, then it plays.
r = rig({ready: 1}); r.show(1, 0, 0); r.near(); r.onScreen(true);
assert.equal(r.cards[0].clip.plays, 0, 'no start before it can play through');
r.cards[0].clip.readyState = 4; r.emit(r.cards[0].clip, 'canplaythrough');
assert.equal(r.cards[0].clip.plays, 1);

// A hand on the rail: the scene replays instead of sliding away.
r = rig(); r.show(1, 0, 0); r.onScreen(true);
r.emit(r.rail, 'pointerdown'); r.emit(r.cards[0].clip, 'ended');
assert.equal(r.rail.scrolls.length, 0); assert.equal(r.player.active, 0); assert.equal(r.cards[0].clip.plays, 2);

// Out of view, everything pauses and nothing slides.
r.onScreen(false); assert(r.cards[0].clip.pauses >= 1);
r.emit(r.cards[0].clip, 'ended'); assert.equal(r.rail.scrolls.length, 0);

// Motion off: nothing downloads ahead, no autoplay, no sliding; a tap loads and plays that scene.
r = rig({quiet: true}); r.show(1, 0, 0); r.near(); r.onScreen(true);
assert.equal(r.cards[0].clip.src, undefined); assert.equal(r.cards[0].clip.plays, 0);
r.emit(r.cards[1].media, 'click'); assert.equal(r.player.active, 1);
assert.equal(r.cards[1].clip.src, '/clip-1.mp4'); assert.equal(r.cards[1].clip.plays, 1);
r.emit(r.cards[1].clip, 'ended'); assert.equal(r.rail.scrolls.length, 0);

// A rail without clips gets no player at all.
assert.equal(scenes({children: [{querySelector: () => null}]}, {IntersectionObserver: class {}}, () => false), null);
console.log('landing scenes: passed');
