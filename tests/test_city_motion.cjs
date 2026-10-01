// Run: node tests/test_city_motion.cjs
// Lifecycle contract tests; rendering/cropping still require the browser preview.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../design/white-city/city-motion.js'), 'utf8');

function mount({ reduced = false, fine = true, broken = false, native = true } = {}) {
  const node = () => ({
    events: {}, style: {}, dataset: {}, attrs: {},
    addEventListener(name, fn) { (this.events[name] ??= []).push(fn); },
    emit(name, event = {}) { for (const fn of this.events[name] ?? []) fn(event); },
    setAttribute(name, value) { this.attrs[name] = value; },
  });
  const hero = node(), drift = node(), pointer = node(), image = node(), button = node(), composer = node();
  const input = node(), label = node(), icon = node(), doc = node(), win = node();
  const reduce = Object.assign(node(), { matches: reduced });
  const finePointer = Object.assign(node(), { matches: fine });
  let now = 0, serial = 0;
  const timers = new Map(), frames = new Map(), animations = [];
  hero.getBoundingClientRect = () => ({ left: 0, top: 0, width: 1536, height: 864 });
  Object.assign(image, { complete: true, naturalWidth: broken ? 0 : 1672 });
  composer.contains = (element) => element === input;
  button.querySelector = (selector) => selector === 'span' ? label : icon;
  doc.hidden = false;
  doc.activeElement = null;
  const elements = { '.hero': hero, '.city-drift': drift, '.city-pointer': pointer, '.city': image, '#toggle-motion': button, '.composer': composer };
  doc.querySelector = (selector) => elements[selector];
  if (native) drift.animate = () => {
    const a = { currentTime: 0, playState: 'running', play() { this.playState = 'running'; }, pause() { this.playState = 'paused'; } };
    animations.push(a);
    return a;
  };
  const schedule = (fn, delay, repeat) => { const id = ++serial; timers.set(id, { fn, at: now + delay, delay, repeat }); return id; };
  const context = {
    document: doc, window: win,
    matchMedia: (query) => query.includes('reduced') ? reduce : finePointer,
    performance: { now: () => now },
    setTimeout: (fn, ms) => schedule(fn, ms, false), setInterval: (fn, ms) => schedule(fn, ms, true),
    clearTimeout: (id) => timers.delete(id), clearInterval: (id) => timers.delete(id),
    requestAnimationFrame: (fn) => { const id = ++serial; frames.set(id, fn); return id; },
    cancelAnimationFrame: (id) => frames.delete(id), queueMicrotask: (fn) => fn(),
  };
  vm.runInNewContext(source, context);
  function tick(ms) {
    const until = now + ms;
    while (true) {
      const next = [...timers].sort((a, b) => a[1].at - b[1].at)[0];
      if (!next || next[1].at > until) break;
      const [id, task] = next;
      now = task.at;
      if (task.repeat) task.at += task.delay; else timers.delete(id);
      task.fn();
    }
    now = until;
  }
  return { hero, button, composer, input, doc, win, reduce, finePointer, timers, frames, animations, tick };
}

let checks = 0;
function check(name, fn) { fn(); checks++; console.log(`PASS ${name}`); }

check('reduced motion starts static and changing the setting starts/stops once', () => {
  const m = mount({ reduced: true });
  assert.equal(m.hero.dataset.motionState, 'reduced');
  assert.equal(m.animations.length, 0);
  assert.equal(m.timers.size, 0);
  m.reduce.matches = false; m.reduce.emit('change');
  assert.equal(m.hero.dataset.motionState, 'playing');
  assert.equal(m.animations.length, 1);
  m.reduce.matches = true; m.reduce.emit('change');
  assert.equal(m.animations[0].playState, 'paused');
  assert.equal(m.timers.size, 0);
});

check('pause persists across input focus, visibility changes and resume', () => {
  const m = mount();
  m.button.emit('click');
  const time = m.animations[0].currentTime;
  m.doc.activeElement = m.input; m.composer.emit('focusin');
  m.doc.hidden = true; m.doc.emit('visibilitychange');
  m.doc.hidden = false; m.doc.activeElement = null; m.doc.emit('visibilitychange');
  assert.equal(m.hero.dataset.motionState, 'paused');
  m.tick(5000);
  assert.equal(m.animations[0].currentTime, time);
  assert.equal(m.timers.size, 0);
  m.button.emit('click');
  assert.equal(m.hero.dataset.motionState, 'playing');
  assert.equal(m.animations.length, 1);
});

check('typing and hidden documents stop motion without losing the playback position', () => {
  const m = mount();
  m.animations[0].currentTime = 18320;
  m.doc.activeElement = m.input; m.composer.emit('focusin');
  assert.equal(m.hero.dataset.motionState, 'typing');
  assert.equal(m.animations[0].playState, 'paused');
  m.doc.activeElement = null; m.composer.emit('focusout');
  assert.equal(m.hero.dataset.motionState, 'playing');
  assert.equal(m.animations[0].currentTime, 18320);
  m.doc.hidden = true; m.doc.emit('visibilitychange');
  assert.equal(m.timers.size, 0);
  assert.equal(m.frames.size, 0);
});

check('frozen native timelines use one fallback clock and do not jump after pausing', () => {
  const m = mount();
  m.tick(1700);
  assert.equal(m.hero.dataset.motionClock, 'timer');
  assert(m.animations[0].currentTime > 12000);
  assert.equal(m.timers.size, 1);
  m.button.emit('click');
  const time = m.animations[0].currentTime;
  m.tick(20000);
  assert.equal(m.animations[0].currentTime, time);
  assert.equal(m.timers.size, 0);
  m.button.emit('click'); m.tick(100);
  assert(m.animations[0].currentTime - time <= 101);
  assert.equal(m.timers.size, 1);
});

check('working native clocks are not replaced by the fallback', () => {
  const m = mount();
  m.animations[0].currentTime += 1400;
  m.tick(1400);
  assert.equal(m.hero.dataset.motionClock, 'native');
  assert.equal(m.timers.size, 0);
});

check('unsupported animation and broken cached images remain usable static previews', () => {
  for (const options of [{ native: false }, { broken: true }]) {
    const m = mount(options);
    assert.equal(m.hero.dataset.motionState, 'unavailable');
    assert.equal(m.button.disabled, true);
    assert.equal(m.timers.size, 0);
  }
});

check('touch input cannot start decorative pointer tracking', () => {
  const m = mount({ fine: false });
  m.doc.activeElement = m.input; m.composer.emit('focusin');
  m.doc.activeElement = null; m.composer.emit('focusout');
  m.hero.emit('pointermove', { pointerType: 'touch', clientX: 100, clientY: 100 });
  assert.equal(m.hero.dataset.motionState, 'playing');
  // Only the optional reset-to-centre frame may be scheduled, never another loop per touch.
  assert(m.frames.size <= 1);
});

console.log(`${checks} motion lifecycle checks passed.`);
