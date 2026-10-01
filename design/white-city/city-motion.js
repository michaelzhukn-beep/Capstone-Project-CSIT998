/* Decorative first-screen motion only. The approved bitmap and all reading/input UI stay intact. */
(() => {
  'use strict';
  const hero = document.querySelector('.hero');
  const drift = document.querySelector('.city-drift');
  const pointerLayer = document.querySelector('.city-pointer');
  const image = document.querySelector('.city');
  const button = document.querySelector('#toggle-motion');
  const composer = document.querySelector('.composer');
  if (!hero || !drift || !pointerLayer || !image || !button || !composer) return;

  const reduce = matchMedia('(prefers-reduced-motion: reduce)');
  const finePointer = matchMedia('(hover: hover) and (pointer: fine)');
  // 48 seconds per round trip. Fixed 3.2% overscan contains drift + pointer + spring overshoot.
  // Marketing movement uses the shared animate skill's on-screen ease-in-out curve.
  const DURATION = 24000;
  const keyframes = [
    { transform: 'translate3d(-0.65%, 0.2%, 0) scale(1.032)' },
    { transform: 'translate3d(0.65%, -0.2%, 0) scale(1.032)' },
  ];
  const timing = { duration: DURATION, iterations: Infinity, direction: 'alternate', easing: 'cubic-bezier(0.77, 0, 0.175, 1)' };
  let animation = null;
  let ready = image.complete && image.naturalWidth > 0;
  let failed = image.complete && image.naturalWidth === 0;
  let paused = false;
  let inView = true;
  let running = false;
  let manualClock = false;
  let timer = 0;
  let clockCheck = 0;
  let lastTick = 0;
  let pointerFrame = 0;
  let pointerTime = 0;
  let rect = hero.getBoundingClientRect();
  const spring = { x: 0, y: 0, vx: 0, vy: 0, targetX: 0, targetY: 0 };

  function stopPointer() {
    cancelAnimationFrame(pointerFrame);
    pointerFrame = 0;
    pointerTime = 0;
  }

  function resetPointer() {
    stopPointer();
    Object.keys(spring).forEach((key) => { spring[key] = 0; });
    pointerLayer.style.transform = 'translate3d(0, 0, 0)';
  }

  // Native spring: mass 1, stiffness 100, damping 10. Pointer offsets are bounded independently.
  function stepPointer(now) {
    pointerFrame = 0;
    if (!running || !finePointer.matches || reduce.matches) return;
    const dt = Math.min((now - (pointerTime || now - 16)) / 1000, 0.032);
    pointerTime = now;
    for (const [axis, velocity, target] of [['x', 'vx', 'targetX'], ['y', 'vy', 'targetY']]) {
      spring[velocity] += ((spring[target] - spring[axis]) * 100 - spring[velocity] * 10) * dt;
      spring[axis] += spring[velocity] * dt;
    }
    const x = Math.max(-rect.width * 0.004, Math.min(rect.width * 0.004, spring.x));
    const y = Math.max(-rect.height * 0.0025, Math.min(rect.height * 0.0025, spring.y));
    pointerLayer.style.transform = `translate3d(${x.toFixed(3)}px, ${y.toFixed(3)}px, 0)`;
    if (Math.abs(spring.x - spring.targetX) + Math.abs(spring.y - spring.targetY) + Math.abs(spring.vx) + Math.abs(spring.vy) > 0.02) {
      pointerFrame = requestAnimationFrame(stepPointer);
    } else {
      pointerTime = 0;
    }
  }

  function aim(x, y) {
    spring.targetX = x;
    spring.targetY = y;
    if (running && !pointerFrame) pointerFrame = requestAnimationFrame(stepPointer);
  }

  function clearClocks() {
    clearInterval(timer);
    clearTimeout(clockCheck);
    timer = 0;
    clockCheck = 0;
  }

  // Some embedded previews freeze the native animation timeline. Only in that case,
  // advance the same WAAPI effect at 30 fps. No second animation/easing implementation.
  function startManualClock() {
    animation.pause();
    lastTick = performance.now();
    timer = setInterval(() => {
      if (!running) return;
      const now = performance.now();
      const dt = Math.min(now - lastTick, 100);
      lastTick = now;
      animation.currentTime = Number(animation.currentTime || 0) + dt;
    }, 1000 / 30);
  }

  function startClocks() {
    if (manualClock) {
      startManualClock();
      return;
    }
    const before = Number(animation.currentTime || 0);
    animation.play();
    clockCheck = setTimeout(() => {
      clockCheck = 0;
      if (!running || Number(animation.currentTime || 0) - before > 80) return;
      manualClock = true;
      hero.dataset.motionClock = 'timer';
      startManualClock();
    }, 1400);
  }

  function status() {
    if (failed) return 'unavailable';
    if (reduce.matches) return 'reduced';
    if (!ready) return 'loading';
    if (paused) return 'paused';
    if (document.hidden || !inView) return 'hidden';
    if (composer.contains(document.activeElement)) return 'typing';
    return 'playing';
  }

  function sync() {
    const state = status();
    const shouldRun = state === 'playing';
    hero.dataset.motionState = state;
    button.hidden = false;
    button.disabled = ['reduced', 'unavailable', 'loading'].includes(state);
    button.setAttribute('aria-pressed', String(paused));
    const label = state === 'reduced' ? '已减少动态' : state === 'unavailable' ? '静态模式' : state === 'loading' ? '准备动态' : paused ? '继续动态' : state === 'typing' ? '输入时暂停' : '暂停动态';
    button.setAttribute('aria-label', label);
    button.querySelector('span').textContent = label;
    button.querySelector('path').setAttribute('d', paused ? 'M3 1.5 10 6 3 10.5z' : 'M3 2h2v8H3zm4 0h2v8H7z');
    if (reduce.matches) resetPointer();
    if (shouldRun === running) return;
    running = shouldRun;
    clearClocks();
    if (running) {
      if (!animation) {
        if (typeof drift.animate !== 'function') { failed = true; running = false; sync(); return; }
        animation = drift.animate(keyframes, timing);
        animation.pause();
        animation.currentTime = DURATION / 2;
        hero.dataset.motionClock = 'native';
      }
      startClocks();
      aim(0, 0);
    } else {
      if (animation) animation.pause();
      stopPointer();
    }
  }

  hero.addEventListener('pointermove', (event) => {
    if (!running || !finePointer.matches || event.pointerType !== 'mouse') return;
    const x = Math.max(-1, Math.min(1, ((event.clientX - rect.left) / rect.width - 0.5) * 2));
    const y = Math.max(-1, Math.min(1, ((event.clientY - rect.top) / rect.height - 0.5) * 2));
    aim(-x * Math.min(7, rect.width * 0.0025), -y * Math.min(3, rect.height * 0.0015));
  }, { passive: true });
  hero.addEventListener('pointerleave', () => { if (running) aim(0, 0); });
  button.addEventListener('click', () => { paused = !paused; sync(); });
  composer.addEventListener('focusin', sync);
  composer.addEventListener('focusout', () => queueMicrotask(sync));
  document.addEventListener('visibilitychange', sync);
  reduce.addEventListener('change', sync);
  finePointer.addEventListener('change', resetPointer);
  window.addEventListener('resize', () => { rect = hero.getBoundingClientRect(); resetPointer(); }, { passive: true });
  window.addEventListener('scroll', () => { rect = hero.getBoundingClientRect(); }, { passive: true });
  if (typeof IntersectionObserver === 'function') {
    new IntersectionObserver(([entry]) => { inView = entry.isIntersecting; sync(); }).observe(hero);
  }
  image.addEventListener('load', () => { ready = true; sync(); }, { once: true });
  image.addEventListener('error', () => { failed = true; sync(); }, { once: true });
  window.addEventListener('pagehide', () => { inView = false; sync(); });
  window.addEventListener('pageshow', () => { inView = true; sync(); });
  sync();
})();
