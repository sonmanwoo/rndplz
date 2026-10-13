'use strict';
// The scene rail in a small DOM double (2026-10-13 endless row): download one clip at a time, play only what can play
// through, open once before the first clip, slide on when a clip ends with the incoming cards lagging, wrap endlessly,
// move by hand (drag, keys, a tap on a side card), cover the side cards, respect a hand on the rail and motion off.
const assert = require('node:assert/strict');
const {scenes} = require('../rndplz/web/landing.js');

function rig({quiet = false, ready = 4, count = 6, stills = 0} = {}) {
  const on = (target, type, fn) => { target.events = target.events || new Map(); target.events.set(type, [...(target.events.get(type) || []), fn]); };
  const emit = (target, type, event = {}) => ((target.events && target.events.get(type)) || []).splice(0).forEach(fn => { fn(event); if (!fn.once) on(target, type, fn); });
  const element = (extra = {}) => ({
    classList: {set: new Set(), add(name) { this.set.add(name); }, remove(name) { this.set.delete(name); }, contains(name) { return this.set.has(name); },
      toggle(name, value) { if (value) this.set.add(name); else this.set.delete(name); }},
    style: {props: {}, setProperty(name, value) { this.props[name] = value; }},
    attributes: {}, setAttribute(name, value) { this.attributes[name] = value; }, toggleAttribute(name, value) { this.attributes[name] = !!value; },
    children: [], append(...nodes) { this.children.push(...nodes); },
    addEventListener(type, fn, options) { if (options && options.once) fn.once = true; on(this, type, fn); }, ...extra});
  const video = n => element({dataset: {src: '/clip-' + n + '.mp4', poster: '/still-' + n + '.webp'}, plays: 0, pauses: 0, loads: 0, paused: true,
    readyState: ready, currentTime: 3, duration: 5, buffered: {length: 1, end: () => 5},
    load() { this.loads++; }, play() { this.plays++; this.paused = false; this.currentTime = 0; return Promise.resolve(); }, pause() { this.pauses++; this.paused = true; }});
  const cards = Array.from({length: count}, (_, index) => {
    const media = element(), clip = index < count - stills ? video(index) : null, bar = {style: {}};
    const no = {textContent: '0' + (index + 1)}, title = {childNodes: [no, {textContent: '장면 ' + (index + 1)}], querySelector: () => no};
    if (clip) clip.parentElement = media;
    return element({offsetWidth: 300, offsetHeight: 520, media, clip, title, querySelector: selector =>
      selector === 'video' ? clip : selector === '.landing-scene-media' ? media : selector === 'h3' ? title : bar});
  });
  const rail = element({children: cards, clientWidth: 1200});
  const observers = [], timers = [], frames = [];
  let now = 1000;
  const win = {
    document: {hidden: false, addEventListener(type, fn) { on(this, type, fn); }, createElement: () => element({textContent: ''})},
    IntersectionObserver: class {
      constructor(callback, options) { this.callback = callback; this.options = options || {}; this.targets = []; observers.push(this); }
      observe(target) { this.targets.push(target); } disconnect() { this.targets = []; }
    },
    performance: {now: () => now},
    requestAnimationFrame(fn) { frames.push(fn); return frames.length; }, cancelAnimationFrame() {},
    addEventListener() {}, setTimeout(fn) { timers.push(fn); return timers.length; }, clearTimeout() {},
  };
  const player = scenes(rail, win, () => quiet);
  const watch = threshold => observers.find(o => o.options.threshold === threshold);
  const near = () => observers.find(o => o.options.rootMargin).callback([{target: rail, isIntersecting: true, intersectionRatio: 0}]);
  const onScreen = value => watch(.25).callback([{target: rail, isIntersecting: value, intersectionRatio: value ? 1 : 0}]);
  const open = () => watch(.45).callback([{target: rail, isIntersecting: true, intersectionRatio: .6}]);
  // Run the animation frames until the row settles, the clock moving 16 ms a frame.
  const settle = (limit = 200) => { for (let k = 0; k < limit && frames.length; k++) { now += 16; frames.shift()(); } };
  const x = index => Number(/translate3d\((-?[\d.]+)px/.exec(cards[index].style.transform)[1]) - (1200 - 300) / 2;   // from the middle
  return {player, cards, rail, timers, frames, near, onScreen, open, settle, x, emit, tick: ms => { now += ms; }};
}
const SLOT = 300 * 1.043;

// The row: the first card in the middle, the next ones to its right, the last ones wrapped round to its left.
let r = rig();
assert(r.rail.classList.contains('is-swipe'));
assert.equal(r.x(0), 0); assert.equal(Math.round(r.x(1)), Math.round(SLOT)); assert.equal(Math.round(r.x(5)), Math.round(-SLOT));
assert.equal(r.cards[0].style.transform.endsWith('scale(1.0000)'), true, 'the middle card is full size');
assert.equal(r.cards[2].style.transform.endsWith('scale(0.9200)'), true, 'two away is at 92%');
assert.equal(r.cards[0].style.props['--cap'], '1.000'); assert.equal(r.cards[1].style.props['--cap'], '0.000');
assert.equal(r.rail.style.props['--rail-h'], '520px');
// Each card wears a cover with its number and title, hidden from screen readers.
const cover = r.cards[2].media.children[0];
assert.equal(cover.className, 'landing-scene-cover'); assert.equal(cover.attributes['aria-hidden'], 'true');
assert.deepEqual(cover.children.map(node => node.textContent), ['03', '장면 3']);

// Nothing downloads until the rail is a screen away; then only the first clip.
assert.equal(r.cards[0].clip.src, undefined);
r.near();
assert.equal(r.cards[0].clip.src, '/clip-0.mp4'); assert.equal(r.cards[0].clip.preload, 'auto'); assert.equal(r.cards[0].clip.loads, 1);
assert.equal(r.cards[1].clip.src, undefined, 'one download at a time');
// In view, the first clip waits for the opening; with no Web Animations the opening ends at once and it plays.
r.onScreen(true);
assert.equal(r.player.active, 0); assert.equal(r.cards[0].clip.plays, 0, 'no clip before the opening');
r.open();
assert.equal(r.cards[0].clip.plays, 1); assert(r.cards[0].classList.contains('is-playing'));

// Once the playing clip is all here, the next one starts downloading.
r.emit(r.cards[0].clip, 'progress');
assert.equal(r.cards[1].clip.src, '/clip-1.mp4'); assert.equal(r.cards[2].clip.src, undefined, 'only the next one');

// When a clip ends the row slides one card left and the next one becomes the active card; the previous one stops.
r.emit(r.cards[0].clip, 'ended');
assert.equal(r.player.active, 1); assert(r.cards[0].clip.pauses >= 1);
assert.equal(r.cards[1].clip.plays, 0, 'no clip starts while the row slides (2026-10-13)');
// The cards on the incoming side start later, 40 ms a slot: early on, the middle card has moved and the next has not.
r.tick(20); r.frames.shift()();
assert(r.x(0) < -1, 'the middle card is under way'); assert.equal(Math.round(r.x(2)), Math.round(2 * SLOT), 'the incoming card still waits');
assert.equal(r.cards[1].clip.plays, 0);
r.settle();
assert.equal(Math.round(r.x(1)), 0); assert.equal(Math.round(r.x(0)), Math.round(-SLOT)); assert.equal(r.frames.length, 0, 'the frames stop once settled');
assert.equal(r.cards[1].clip.plays, 1, 'the clip starts once the row has stopped');
// A move that is overtaken before it settles never starts the card it left behind.
r.player.go(2); r.tick(100); r.frames.shift()(); r.player.go(3); r.settle();
assert.equal(r.player.active, 3); assert.equal(r.cards[2].clip.plays, 0); assert.equal(r.cards[3].clip.plays, 1);
r.player.go(1); r.settle();

// Endless: a far card comes the short way round (card 5, two slots to the left, moves right), and from the last card
// the row goes on to the first, which arrives from the right.
r.player.go(5); r.tick(120); r.frames.shift()();
assert(r.x(0) > -SLOT, 'the row moves right, the short way'); r.settle();
assert.equal(r.player.active, 5); assert.equal(Math.round(r.x(5)), 0); assert.equal(Math.round(r.x(0)), Math.round(SLOT));
r.player.advance(); r.settle();
assert.equal(r.player.active, 0); assert.equal(Math.round(r.x(0)), 0); assert.equal(Math.round(r.x(5)), Math.round(-SLOT));

// A hand on the rail: the scene replays instead of sliding away.
r = rig(); r.near(); r.onScreen(true); r.open();
r.emit(r.rail, 'pointerdown', {button: 0, pointerId: 1, clientX: 600, clientY: 300}); r.emit(r.rail, 'pointerup', {pointerId: 1, clientX: 600, clientY: 300});
r.emit(r.cards[0].clip, 'ended');
assert.equal(r.player.active, 0); assert.equal(r.cards[0].clip.plays, 2);

// Out of view, everything pauses and nothing slides.
r.onScreen(false); assert(r.cards[0].clip.pauses >= 1);
r = rig(); r.near(); r.onScreen(true); r.open(); r.onScreen(false);
r.emit(r.cards[0].clip, 'ended'); assert.equal(r.player.active, 0);

// Hands: a drag follows at half the pointer's distance, past 40 px it moves one card, and the click it ends with is
// swallowed; a short drag settles back.
r = rig(); r.near(); r.onScreen(true); r.open();
r.emit(r.rail, 'pointerdown', {button: 0, pointerId: 7, clientX: 700, clientY: 300});
r.emit(r.rail, 'pointermove', {pointerId: 7, clientX: 600, clientY: 304});
assert(r.rail.classList.contains('is-dragging')); assert.equal(Math.round(r.x(0)), -50, 'half the pointer distance');
r.emit(r.rail, 'pointerup', {pointerId: 7, clientX: 600, clientY: 304});
assert.equal(r.player.active, 1); assert(!r.rail.classList.contains('is-dragging'));
let swallowed = 0; r.emit(r.rail, 'click', {preventDefault() { swallowed++; }, stopPropagation() {}}); assert.equal(swallowed, 1);
r.settle(); assert.equal(Math.round(r.x(1)), 0);
r.emit(r.rail, 'pointerdown', {button: 0, pointerId: 8, clientX: 700, clientY: 300});
r.emit(r.rail, 'pointermove', {pointerId: 8, clientX: 680, clientY: 300});
r.tick(400); r.emit(r.rail, 'pointerup', {pointerId: 8, clientX: 680, clientY: 300});
r.settle(); assert.equal(r.player.active, 1, 'a short slow drag settles back'); assert.equal(Math.round(r.x(1)), 0);
// A mostly vertical move is the page's scroll, not a drag.
r.emit(r.rail, 'pointerdown', {button: 0, pointerId: 9, clientX: 700, clientY: 300});
r.emit(r.rail, 'pointermove', {pointerId: 9, clientX: 690, clientY: 380});
assert(!r.rail.classList.contains('is-dragging'));
r.emit(r.rail, 'pointerup', {pointerId: 9, clientX: 690, clientY: 380});
// Keys move it too; a tap on a side card brings that card to the middle.
const keys = [];
r.emit(r.rail, 'keydown', {key: 'ArrowLeft', preventDefault() { keys.push('left'); }}); assert.equal(r.player.active, 0);
r.emit(r.rail, 'keydown', {key: 'End', preventDefault() {}}); assert.equal(r.player.active, 5);
r.emit(r.rail, 'keydown', {key: 'Home', preventDefault() {}}); assert.equal(r.player.active, 0);
r.emit(r.rail, 'keydown', {key: 'Tab', preventDefault() { keys.push('tab'); }}); assert.deepEqual(keys, ['left']);
r.settle(); r.emit(r.cards[1].media, 'click'); assert.equal(r.player.active, 1); assert.equal(r.cards[1].clip.src, '/clip-1.mp4');
r.settle(); assert.equal(Math.round(r.x(1)), 0);

// A slow network: the still stays until the clip can play through, then it plays.
r = rig({ready: 1}); r.near(); r.onScreen(true); r.open();
assert.equal(r.cards[0].clip.plays, 0, 'no start before it can play through'); assert.equal(r.cards[0].clip.poster, '/still-0.webp');
r.cards[0].clip.readyState = 4; r.emit(r.cards[0].clip, 'canplaythrough');
assert.equal(r.cards[0].clip.plays, 1);

// A still card rests, then the story goes on.
r = rig({count: 3, stills: 1}); r.near(); r.onScreen(true); r.open();
r.emit(r.cards[0].clip, 'ended'); r.emit(r.cards[1].clip, 'ended');
assert.equal(r.player.active, 2); assert.equal(r.timers.length, 1); r.timers[0]();
assert.equal(r.player.active, 0);

// Motion off: nothing downloads ahead, no autoplay, no sliding, every move instant; a tap loads and plays that scene.
r = rig({quiet: true}); r.near(); r.onScreen(true); r.open();
assert.equal(r.cards[0].clip.src, undefined); assert.equal(r.cards[0].clip.plays, 0); assert.equal(r.cards[0].clip.poster, '/still-0.webp');
r.emit(r.cards[1].media, 'click'); assert.equal(r.player.active, 1);
assert.equal(r.frames.length, 0, 'no animation frames'); assert.equal(Math.round(r.x(1)), 0);
assert.equal(r.cards[1].clip.src, '/clip-1.mp4'); assert.equal(r.cards[1].clip.plays, 1);
r.emit(r.cards[1].clip, 'ended'); assert.equal(r.player.active, 1);
r.emit(r.rail, 'pointerdown', {button: 0, pointerId: 3, clientX: 700, clientY: 300});
r.emit(r.rail, 'pointermove', {pointerId: 3, clientX: 600, clientY: 300}); assert.equal(Math.round(r.x(1)), 0, 'no follow with motion off');
r.emit(r.rail, 'pointerup', {pointerId: 3, clientX: 600, clientY: 300}); assert.equal(r.player.active, 2); assert.equal(Math.round(r.x(2)), 0);

// A rail without clips gets no player at all.
assert.equal(scenes({children: [{querySelector: () => null}]}, {IntersectionObserver: class {}}, () => false), null);
console.log('landing scenes: passed');
