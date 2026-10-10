'use strict';
// The scene rail in a small DOM double: play in view, slide on when a clip ends, respect a hand on the rail and motion off.
const assert = require('node:assert/strict');
const {scenes} = require('../rndplz/web/landing.js');

function rig({quiet = false} = {}) {
  const on = (target, type, fn) => { target.events = target.events || new Map(); target.events.set(type, [...(target.events.get(type) || []), fn]); };
  const emit = (target, type) => ((target.events && target.events.get(type)) || []).forEach(fn => fn({}));
  const element = (extra = {}) => ({
    classList: {set: new Set(), toggle(name, value) { if (value) this.set.add(name); else this.set.delete(name); }},
    addEventListener(type, fn) { on(this, type, fn); }, ...extra});
  const video = () => element({dataset: {src: '/clip.mp4', poster: '/clip.jpg'}, plays: 0, pauses: 0, paused: true, currentTime: 3, duration: 5,
    play() { this.plays++; this.paused = false; this.currentTime = 0; return Promise.resolve(); }, pause() { this.pauses++; this.paused = true; }});
  const cards = [0, 1, 2].map(index => {
    const media = element(), clip = index < 2 ? video() : null, bar = {style: {}};
    if (clip) clip.parentElement = media;
    return element({offsetLeft: 2 + index * 300, media, clip, querySelector: selector => selector === 'video' ? clip : bar});
  });
  const rail = element({children: cards, firstElementChild: cards[0], scrolls: [], scrollTo(options) { this.scrolls.push(options); }});
  const observers = [], timers = [];
  const win = {
    document: {hidden: false, addEventListener(type, fn) { on(this, type, fn); }},
    IntersectionObserver: class {
      constructor(callback, options) { this.callback = callback; this.options = options; this.targets = []; observers.push(this); }
      observe(target) { this.targets.push(target); }
    },
    setTimeout(fn) { timers.push(fn); return timers.length; }, clearTimeout() {},
  };
  const player = scenes(rail, win, () => quiet);
  const seenCards = observers.find(o => o.options.root === rail), seenRail = observers.find(o => o.options.root !== rail);
  const show = (...ratios) => seenCards.callback(ratios.map((intersectionRatio, index) => ({target: cards[index], intersectionRatio})));
  const onScreen = value => seenRail.callback([{target: rail, isIntersecting: value, intersectionRatio: value ? 1 : 0}]);
  return {player, cards, rail, timers, show, onScreen, emit};
}

// Nothing loads or plays until the rail is on screen; then the first card in view plays from its start.
let r = rig();
r.show(1, .2, 0);
assert.equal(r.cards[0].clip.src, undefined, 'clips load only when the rail is on screen');
r.onScreen(true);
assert.equal(r.cards[0].clip.src, '/clip.mp4'); assert.equal(r.cards[0].clip.poster, '/clip.jpg');
assert.equal(r.player.active, 0); assert.equal(r.cards[0].clip.plays, 1);
assert(r.cards[0].classList.set.has('is-playing'));

// When a clip ends the rail slides to the next card and plays it; the previous one stops.
r.emit(r.cards[0].clip, 'ended');
assert.deepEqual(r.rail.scrolls.at(-1), {left: 300, behavior: 'smooth'});
assert.equal(r.player.active, 1); assert.equal(r.cards[1].clip.plays, 1); assert(r.cards[0].clip.pauses >= 1);
// The last clip slides to the still card, which rests and then returns the story to the first card.
r.emit(r.cards[1].clip, 'ended');
assert.equal(r.player.active, 2); assert.deepEqual(r.rail.scrolls.at(-1), {left: 600, behavior: 'smooth'});
assert.equal(r.timers.length, 1); r.timers[0]();
assert.equal(r.player.active, 0); assert.deepEqual(r.rail.scrolls.at(-1), {left: 0, behavior: 'smooth'});

// A hand on the rail: the scene replays instead of sliding away.
r = rig(); r.show(1, 0, 0); r.onScreen(true);
r.emit(r.rail, 'pointerdown'); r.emit(r.cards[0].clip, 'ended');
assert.equal(r.rail.scrolls.length, 0); assert.equal(r.player.active, 0); assert.equal(r.cards[0].clip.plays, 2);

// Out of view, everything pauses and nothing slides.
r.onScreen(false); assert(r.cards[0].clip.pauses >= 1);
r.emit(r.cards[0].clip, 'ended'); assert.equal(r.rail.scrolls.length, 0);

// Motion off: no autoplay, no sliding; a tap plays that scene.
r = rig({quiet: true}); r.show(1, 0, 0); r.onScreen(true);
assert.equal(r.cards[0].clip.plays, 0);
r.emit(r.cards[1].media, 'click'); assert.equal(r.player.active, 1); assert.equal(r.cards[1].clip.plays, 1);
r.emit(r.cards[1].clip, 'ended'); assert.equal(r.rail.scrolls.length, 0);

// A rail without clips gets no player at all.
assert.equal(scenes({children: [{querySelector: () => null}]}, {IntersectionObserver: class {}}, () => false), null);
console.log('landing scenes: passed');
