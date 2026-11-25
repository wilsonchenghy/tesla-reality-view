// motion.js: easing, springs and keyframes as pure functions of time.
// Nothing here keeps state between frames: frame 84 renders the same whether or not frame 83 ran.

export const clamp = (x, a = 0, b = 1) => (x < a ? a : x > b ? b : x);
export const lerp = (a, b, u) => a + (b - a) * u;
export const invLerp = (a, b, x) => (b === a ? 0 : (x - a) / (b - a));
export const remap = (x, a, b, c, d, ease = null) => {
  const u = clamp(invLerp(a, b, x));
  return lerp(c, d, ease ? ease(u) : u);
};
export const smoothstep = (a, b, x) => { const u = clamp(invLerp(a, b, x)); return u * u * (3 - 2 * u); };
export const smootherstep = (a, b, x) => { const u = clamp(invLerp(a, b, x)); return u * u * u * (u * (u * 6 - 15) + 10); };

// ---------- cubic-bezier, solved like the browser does ----------
export function cubicBezier(x1, y1, x2, y2) {
  const cx = 3 * x1, bx = 3 * (x2 - x1) - cx, ax = 1 - cx - bx;
  const cy = 3 * y1, by = 3 * (y2 - y1) - cy, ay = 1 - cy - by;
  const sx = (s) => ((ax * s + bx) * s + cx) * s;
  const sy = (s) => ((ay * s + by) * s + cy) * s;
  const dx = (s) => (3 * ax * s + 2 * bx) * s + cx;
  const solve = (x) => {
    let s = x;
    for (let i = 0; i < 8; i++) {
      const e = sx(s) - x;
      if (Math.abs(e) < 1e-7) return s;
      const d = dx(s);
      if (Math.abs(d) < 1e-6) break;
      s -= e / d;
    }
    let lo = 0, hi = 1; s = x;
    for (let i = 0; i < 40; i++) { const v = sx(s); if (Math.abs(v - x) < 1e-7) break; if (v < x) lo = s; else hi = s; s = (lo + hi) / 2; }
    return s;
  };
  const f = (x) => (x <= 0 ? 0 : x >= 1 ? 1 : sy(solve(x)));
  f.css = `cubic-bezier(${x1}, ${y1}, ${x2}, ${y2})`;
  return f;
}

// Tokens. Use names, not inline curves: the whole piece then speaks one motion language.
export const ease = {
  linear: (u) => u,
  outExpo: cubicBezier(0.16, 1, 0.3, 1),      // reveals
  outQuint: cubicBezier(0.22, 1, 0.36, 1),    // premium entrances
  outCubic: cubicBezier(0.33, 1, 0.68, 1),
  inOutQuart: cubicBezier(0.76, 0, 0.24, 1),  // moves, camera
  inOutCubic: cubicBezier(0.65, 0, 0.35, 1),
  inOutSine: cubicBezier(0.37, 0, 0.63, 1),
  inExpo: cubicBezier(0.7, 0, 0.84, 0),       // fast exits
  inCubic: cubicBezier(0.32, 0, 0.67, 0),
  inQuart: cubicBezier(0.5, 0, 0.75, 0),
  outBack: cubicBezier(0.34, 1.56, 0.64, 1),  // a playful pop
  // the "emphasized" pair from Material 3
  emphasized: cubicBezier(0.2, 0, 0, 1),
  emphasizedAccel: cubicBezier(0.3, 0, 0.8, 0.15),
};

// progress of a tween that starts at t0 and lasts dur, eased
export const tween = (t, t0, dur, e = ease.outQuint) => e(clamp((t - t0) / dur));

// Keyframes: [[t, value, easeIntoThisKey?], ...]. Values may be numbers or arrays of numbers.
export function keys(frames) {
  const ks = frames.map((k) => ({ t: k[0], v: k[1], e: k[2] || ease.inOutCubic }));
  ks.sort((a, b) => a.t - b.t);
  return (t) => {
    if (t <= ks[0].t) return ks[0].v;
    const last = ks[ks.length - 1];
    if (t >= last.t) return last.v;
    let i = 1;
    while (ks[i].t < t) i++;
    const a = ks[i - 1], b = ks[i];
    const u = b.e(clamp((t - a.t) / (b.t - a.t)));
    return Array.isArray(a.v) ? a.v.map((x, j) => lerp(x, b.v[j], u)) : lerp(a.v, b.v, u);
  };
}

// ---------- springs ----------
// A damped oscillator released from displacement e0 (from its target) with velocity v0.
// zeta: damping ratio (1 = no bounce, 0.7-0.85 premium, 0.4-0.6 playful). freq: natural frequency in Hz.
// Returns the displacement from target at time t. Closed form: no simulation, any t in any order.
export function oscillate(t, e0, v0 = 0, zeta = 0.8, freq = 2.5) {
  if (t <= 0) return e0;
  const w = 2 * Math.PI * freq;
  if (zeta < 1) {
    const wd = w * Math.sqrt(1 - zeta * zeta);
    return Math.exp(-zeta * w * t) * (e0 * Math.cos(wd * t) + ((v0 + zeta * w * e0) / wd) * Math.sin(wd * t));
  }
  if (zeta === 1) return Math.exp(-w * t) * (e0 + (v0 + w * e0) * t);
  const s = Math.sqrt(zeta * zeta - 1);
  const r1 = -w * (zeta - s), r2 = -w * (zeta + s);
  const A = (v0 - r2 * e0) / (r1 - r2);
  return A * Math.exp(r1 * t) + (e0 - A) * Math.exp(r2 * t);
}

// Step response 0 -> 1, the article's spring(t).
export const spring = (t, zeta = 0.8, freq = 2.5) => (t <= 0 ? 0 : 1 - oscillate(t, 1, 0, zeta, freq));

// Damping ratio from any library's stiffness/damping/mass (Remotion default -> 0.5, react-spring default -> 1.0)
export const dampingRatio = (k, d, m = 1) => d / (2 * Math.sqrt(k * m));
export const naturalFreq = (k, m = 1) => Math.sqrt(k / m) / (2 * Math.PI);

// Time for a spring to settle within `tol` of its target (useful to plan the grid).
export function settleTime(zeta = 0.8, freq = 2.5, tol = 0.005) {
  for (let t = 0; t < 20; t += 1 / 240) {
    let ok = true;
    for (let k = 0; k < 24; k++) if (Math.abs(oscillate(t + k / 240, 1, 0, zeta, freq)) > tol) { ok = false; break; }
    if (ok) return t;
  }
  return 20;
}

// A value that changes target many times: the sum of one spring per change (linear superposition),
// so it stays a pure function of t. keys: [[t, target, {zeta, freq}?], ...]; the first key is the start value.
// Use for anything retargeted on a beat grid: sizes, radii, positions, colors (per channel).
export function springTrack(keyframes, defaults = {}) {
  const ks = keyframes.map((k) => ({ t: k[0], v: k[1], o: { zeta: 0.8, freq: 2.5, ...defaults, ...(k[2] || {}) } }));
  ks.sort((a, b) => a.t - b.t);
  const vec = Array.isArray(ks[0].v);
  const f = (t) => {
    if (vec) {
      const out = ks[0].v.slice();
      for (let i = 1; i < ks.length && ks[i].t <= t; i++) {
        const s = spring(t - ks[i].t, ks[i].o.zeta, ks[i].o.freq);
        for (let j = 0; j < out.length; j++) out[j] += (ks[i].v[j] - ks[i - 1].v[j]) * s;
      }
      return out;
    }
    let x = ks[0].v;
    for (let i = 1; i < ks.length && ks[i].t <= t; i++) x += (ks[i].v - ks[i - 1].v) * spring(t - ks[i].t, ks[i].o.zeta, ks[i].o.freq);
    return x;
  };
  f.keys = ks;
  f.velocity = (t, h = 1e-4) => (vec ? f(t + h).map((x, j) => (x - f(t - h)[j]) / (2 * h)) : (f(t + h) - f(t - h)) / (2 * h));
  return f;
}

// Direct manipulation then release: while held, value comes from `held(t)` (e.g. cursor position).
// After tRelease it springs from wherever it was, with the velocity it had, to `target`.
export function dragRelease(t, tRelease, held, target, zeta = 0.75, freq = 3) {
  if (t < tRelease) return held(t);
  const h = 1e-3;
  const x0 = held(tRelease), v0 = (held(tRelease) - held(tRelease - h)) / h;
  return target + oscillate(t - tRelease, x0 - target, v0, zeta, freq);
}

// Rubber band: past `limit`, displacement is compressed (iOS overscroll feel). c ~ 0.55.
export const rubber = (x, limit, c = 0.55, dim = 200) => {
  if (x <= limit) return x;
  const over = x - limit;
  return limit + (1 - 1 / ((over * c) / dim + 1)) * dim;
};

// One-shot envelope with attack and exponential decay (flashes, pops, shakes). 0 before the event.
export const burst = (age, rise = 0.06, fall = 0.15) => (age <= 0 ? 0 : age < rise ? smoothstep(0, rise, age) : Math.exp(-(age - rise) / fall));

// Stagger helper: start time of item i of n spread over `spread` seconds, with optional easing of the spread.
export const stagger = (i, n, spread, e = ease.linear) => (n <= 1 ? 0 : e(i / (n - 1)) * spread);

// Periodic spring track for loops: the same as springTrack, but the changes of the previous cycles keep
// ringing into this one, so a spring still settling at the end of the loop carries across the seam.
// keys: [[t, value, opts?], ...] within [0, period); the first key is the value at the start of the cycle.
// If the last value differs from the first, a change back to it happens at `period` (or at `closeAt`).
export function loopTrack(keyframes, period, defaults = {}, { cycles = 3, closeAt = null } = {}) {
  const ks = keyframes.map((k) => ({ t: k[0], v: k[1], o: { zeta: 0.8, freq: 2.5, ...defaults, ...(k[2] || {}) } })).sort((a, b) => a.t - b.t);
  const vec = Array.isArray(ks[0].v);
  const v0 = ks[0].v;
  const changes = [];
  for (let i = 1; i < ks.length; i++) changes.push({ t: ks[i].t, d: vec ? ks[i].v.map((x, j) => x - ks[i - 1].v[j]) : ks[i].v - ks[i - 1].v, o: ks[i].o });
  const last = ks[ks.length - 1];
  const differs = vec ? last.v.some((x, j) => Math.abs(x - v0[j]) > 1e-9) : Math.abs(last.v - v0) > 1e-9;
  if (differs) changes.push({ t: closeAt ?? period, d: vec ? v0.map((x, j) => x - last.v[j]) : v0 - last.v, o: { ...last.o, ...(keyframes.closeOpts || {}) } });
  const f = (t) => {
    t = ((t % period) + period) % period;
    const out = vec ? v0.slice() : [v0];
    for (let c = -cycles; c <= 0; c++) {
      for (const ch of changes) {
        const tt = t - (ch.t + c * period);
        if (tt <= 0) continue;
        const s = spring(tt, ch.o.zeta, ch.o.freq);
        if (vec) for (let j = 0; j < out.length; j++) out[j] += ch.d[j] * s;
        else out[0] += ch.d * s;
      }
    }
    // changes of earlier cycles have fully settled: they add sum(d) per cycle = 0 by construction
    return vec ? out : out[0];
  };
  f.velocity = (t, h = 1e-4) => (vec ? f(t + h).map((x, j) => (x - f(t - h)[j]) / (2 * h)) : (f(t + h) - f(t - h)) / (2 * h));
  return f;
}

// Periodic eased keyframes (no bounce): for colors and opacity in loops. keys like keys(), wraps at period.
export function loopKeys(frames, period) {
  const ks = frames.map((k) => [k[0], k[1], k[2]]).sort((a, b) => a[0] - b[0]);
  const first = ks[0], last = ks[ks.length - 1];
  const ext = [[last[0] - period, last[1], last[2]], ...ks, [first[0] + period, first[1], first[2]]];
  const k = keys(ext);
  return (t) => k(((t % period) + period) % period);
}

// Sum of spring kicks: each event [time, velocity] (or {t, v, zeta, freq}) starts a damped oscillation
// from 0 with that velocity. Follow-through on antennas, ears, tails, hanging signs. period: loop wrap.
export function impulses(t, events, { zeta = 0.25, freq = 2.4, period = 0 } = {}) {
  let x = 0;
  for (const e of events) {
    const te = Array.isArray(e) ? e[0] : e.t, v = Array.isArray(e) ? e[1] : e.v;
    const z = e.zeta ?? zeta, f = e.freq ?? freq;
    if (period) { for (const c of [-1, 0]) { const a = (((t - te) % period) + period) % period + c * period; if (a > 0) x += oscillate(a, 0, v, z, f); } }
    else if (t > te) x += oscillate(t - te, 0, v, z, f);
  }
  return x;
}

// When does fn(t) cross each threshold between t0 and t1? Returns [{t, value, dir}]: schedule a tick
// every time a counter passes a whole number, a knob passes a detent, a progress bar passes 25%.
export function crossings(fn, thresholds, t0, t1, { step = 1 / 480 } = {}) {
  const out = [];
  let prev = fn(t0);
  for (let t = t0 + step; t <= t1 + 1e-9; t += step) {
    const v = fn(t);
    for (const th of thresholds) if ((prev < th && v >= th) || (prev > th && v <= th)) {
      // refine by bisection
      let a = t - step, b = t;
      for (let i = 0; i < 20; i++) { const m = (a + b) / 2, vm = fn(m); if ((prev < th) === (vm < th)) a = m; else b = m; }
      out.push({ t: b, value: th, dir: v > prev ? 1 : -1 });
    }
    prev = v;
  }
  return out.sort((x, y) => x.t - y.t);
}
