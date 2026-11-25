// Runtime math: the parts every frame depends on. node --test test/
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { spring, springTrack, loopTrack, loopKeys, oscillate, cubicBezier, ease, dampingRatio, settleTime, dragRelease, rubber, keys } from '../runtime/motion.js';
import { grid, phase } from '../runtime/time.js';
import { rng, noise, hash } from '../runtime/random.js';
import { mix, contrast } from '../runtime/color.js';

const near = (a, b, eps = 1e-6) => assert.ok(Math.abs(a - b) < eps, `${a} != ${b}`);

test('spring step response: 0 at start, settles to 1, overshoots only when underdamped', () => {
  near(spring(0), 0); near(spring(5), 1, 1e-4);
  let max = 0; for (let t = 0; t < 3; t += 1 / 240) max = Math.max(max, spring(t, 1, 2.5));
  assert.ok(max <= 1 + 1e-9, 'critically damped never overshoots');
  max = 0; for (let t = 0; t < 3; t += 1 / 240) max = Math.max(max, spring(t, 0.5, 2.5));
  assert.ok(max > 1.1, 'zeta 0.5 overshoots');
});

test('oscillate: initial displacement and velocity are honoured (all damping regimes)', () => {
  for (const z of [0.4, 1, 1.6]) {
    near(oscillate(0, 3, 0, z, 2), 3);
    const h = 1e-6, v = (oscillate(h, 0, 5, z, 2) - oscillate(0, 0, 5, z, 2)) / h;
    near(v, 5, 1e-3);
  }
});

test('springTrack is a pure function of t and lands on each target', () => {
  const f = springTrack([[0, 0], [1, 10], [3, -4]]);
  near(f(0.5), 0); near(f(2.99), 10, 1e-2); near(f(8), -4, 1e-3);
  assert.equal(f(1.7), f(1.7));
});

test('loopTrack is continuous across the seam even while a spring is moving', () => {
  const T = 4, f = loopTrack([[0, 0], [1, 100], [3.9, 50]], T, { zeta: 0.5, freq: 1 });
  near(f(0), f(T - 1e-9), 1e-4);
  near(f(1.5), f(1.5 + T), 1e-9);
  const g = loopTrack([[0, [1, 2]], [2, [5, 6]]], T);
  near(g(0)[0], g(T - 1e-9)[0], 1e-4);
});

test('loopKeys wraps', () => {
  const f = loopKeys([[0, 0], [2, 10]], 4);
  near(f(0), f(4)); near(f(2), 10);
});

test('cubicBezier matches known easing values and endpoints', () => {
  const e = cubicBezier(0.25, 0.1, 0.25, 1); // CSS "ease"
  near(e(0), 0); near(e(1), 1); near(e(0.5), 0.8024, 2e-3);
  near(ease.inOutQuart(0.5), 0.5, 1e-3);
});

test('library conversions', () => {
  near(dampingRatio(100, 10), 0.5); near(dampingRatio(170, 26), 0.997, 1e-3);
  const s = settleTime(0.8, 2.5); assert.ok(s > 0.3 && s < 0.7);
});

test('dragRelease continues from the release position with its velocity', () => {
  const held = (t) => 100 * t;
  near(dragRelease(1, 1, held, 0), 100, 1e-9);
  const v = (dragRelease(1 + 1e-5, 1, held, 0) - dragRelease(1, 1, held, 0)) / 1e-5;
  near(v, 100, 0.5);
});

test('rubber band compresses past the limit and never exceeds limit + dim', () => {
  near(rubber(50, 100), 50); assert.ok(rubber(1000, 100, 0.55, 200) < 300); assert.ok(rubber(150, 100) < 150);
});

test('keys interpolates numbers and arrays', () => {
  const k = keys([[0, 0], [1, 10, ease.linear]]); near(k(0.5), 5);
  const a = keys([[0, [0, 0]], [1, [2, 4], ease.linear]]); near(a(0.5)[1], 2);
});

test('beat grid computes beats from time (no drift)', () => {
  const g = grid({ bpm: 128, offset: 0.25 });
  near(g.beat(32), 0.25 + 32 * 60 / 128);
  near(g.beatAt(g.beat(7.5)), 7.5);
  near(phase(5, 4), 0.25);
});

test('rng and noise are seeded and repeatable; loop noise is periodic', () => {
  const a = rng(42), b = rng(42); assert.equal(a(), b());
  assert.equal(hash(1, 2, 3), hash(1, 2, 3));
  const n = noise(3);
  near(n.loop1(0, 6, 0.3), n.loop1(6, 6, 0.3), 1e-9);
  near(n.loop2(0, 6, 0.3, 0.7), n.loop2(6, 6, 0.3, 0.7), 1e-9);
});

test('OKLab mix endpoints and WCAG contrast', () => {
  const m0 = mix('#ff0000', '#0000ff', 0), m1 = mix('#ff0000', '#0000ff', 1);
  near(m0[0], 255, 0.6); near(m1[2], 255, 0.6);
  near(contrast('#000', '#fff'), 21, 1e-6);
});

import { impulses, crossings } from '../runtime/motion.js';
import { storyClock } from '../runtime/time.js';

test('impulses: zero before the event, rings after, periodic when asked', () => {
  near(impulses(0.5, [[1, 5]]), 0);
  assert.ok(Math.abs(impulses(1.05, [[1, 5]])) > 0.1);
  near(impulses(0.2, [[3.9, 5]], { period: 4 }), impulses(4.2, [[3.9, 5]], { period: 4 }), 1e-9);
});

test('crossings finds threshold passes with bisection accuracy', () => {
  const c = crossings((t) => t * 10, [2.5, 7], 0, 1);
  assert.equal(c.length, 2); near(c[0].t, 0.25, 1e-5); near(c[1].t, 0.7, 1e-5);
});

test('storyClock maps both ways', () => {
  const s = storyClock({ offset: 1.5, period: 8 });
  near(s.story(7), 0.5); near(s.piece(s.story(3.2)), 3.2); near(s.age(0, 7.5), 2);   // story(0) = 1.5, which is 2 s after story moment 7.5 (wrapping at 8)
});
