// hand.js: marks a hand makes on text. Find where a phrase lands in a paragraph, then underline, circle,
// bracket or tick it with a slightly imperfect stroke that draws itself. Everything is seeded (no
// randomness per frame) and returns SVG path strings plus their length for draw-on.
//
//   const r = anchors(paragraphEl, 'never answered it', stage)[0];   // {x, y, w, h} in stage pixels
//   const u = hand.underline(r, { seed: 3 });                          // {d, length}
//   attrs(path, { d: u.d, ...drawOn(u.length, progress) });
import { rng } from './random.js';

// Rects of the first occurrence (or `all`) of `phrase` inside element `el`, relative to `relTo`
// (default: the stage). One rect per line the phrase wraps across. Unaffected by the preview's scaling.
export function anchors(el, phrase, relTo = document.getElementById('rv-stage'), { all = false } = {}) {
  const out = [];
  const base = relTo.getBoundingClientRect();
  const sx = base.width / (relTo.offsetWidth || base.width), sy = base.height / (relTo.offsetHeight || base.height);
  const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
  let node;
  while ((node = walker.nextNode())) {
    let i = node.textContent.indexOf(phrase);
    while (i >= 0) {
      const range = document.createRange();
      range.setStart(node, i); range.setEnd(node, i + phrase.length);
      const group = [...range.getClientRects()].map((r) => ({ x: (r.left - base.left) / sx, y: (r.top - base.top) / sy, w: r.width / sx, h: r.height / sy }));
      out.push(group.length === 1 ? group[0] : Object.assign(group[0], { lines: group }));
      if (!all) return out;
      i = node.textContent.indexOf(phrase, i + 1);
    }
  }
  return out;
}

const fmt = (pts) => 'M' + pts.map((p) => `${p[0].toFixed(1)},${p[1].toFixed(1)}`).join('L');
const lengthOf = (pts) => pts.reduce((s, p, i) => (i ? s + Math.hypot(p[0] - pts[i - 1][0], p[1] - pts[i - 1][1]) : 0), 0);
const result = (pts) => ({ d: fmt(pts), length: lengthOf(pts), points: pts });

export const hand = {
  // a line from (x0, y0) to (x1, y1) with low-frequency wobble and slight overshoot at the ends
  line(x0, y0, x1, y1, { seed = 1, wobble = 2.2, overshoot = 6, n = 28 } = {}) {
    const r = rng(seed), L = Math.hypot(x1 - x0, y1 - y0) || 1, ux = (x1 - x0) / L, uy = (y1 - y0) / L;
    const a0 = r() * 6.28, a1 = r() * 6.28, f0 = 1 + r(), f1 = 2.5 + r() * 2;
    const pts = [];
    for (let i = 0; i <= n; i++) {
      const u = i / n, s = -overshoot * 0.4 + u * (L + overshoot);
      const off = wobble * (0.7 * Math.sin(a0 + u * Math.PI * f0) + 0.3 * Math.sin(a1 + u * Math.PI * f1)) * Math.sin(Math.PI * Math.min(1, u * 1.2));
      pts.push([x0 + ux * s - uy * off, y0 + uy * s + ux * off]);
    }
    return result(pts);
  },
  // underline a rect (or every line of a wrapped phrase), a little below the baseline
  // a wrapped phrase (rect.lines) gets one stroke per line, drawn in reading order as one path
  underline(rect, { seed = 1, drop = 0.12, ...o } = {}) {
    const lines = rect.lines || [rect];
    const parts = lines.map((r, i) => { const y = r.y + r.h * (1 + drop); return hand.line(r.x - 4, y, r.x + r.w + 4, y + (rng(seed + 9 + i)() - 0.5) * 4, { seed: seed + i, ...o }); });
    return { d: parts.map((p) => p.d).join(''), length: parts.reduce((a, p) => a + p.length, 0), points: parts.flatMap((p) => p.points) };
  },
  // an ellipse around a rect that does not quite close (starts and ends overlapping, like a pen loop)
  circle(rect, { seed = 1, pad = 12, turns = 1.12, n = 72, wobble = 0.05 } = {}) {
    const r = rng(seed), cx = rect.x + rect.w / 2, cy = rect.y + rect.h / 2, rx = rect.w / 2 + pad, ry = rect.h / 2 + pad * 0.8;
    const a0 = -2.4 + r() * 0.6, tilt = (r() - 0.5) * 0.12, ph = r() * 6.28;
    const pts = [];
    for (let i = 0; i <= n; i++) {
      const a = a0 + (i / n) * turns * Math.PI * 2, k = 1 + wobble * Math.sin(ph + a * 2.3) + 0.04 * (i / n);
      const x = Math.cos(a) * rx * k, y = Math.sin(a) * ry * k;
      pts.push([cx + x * Math.cos(tilt) - y * Math.sin(tilt), cy + x * Math.sin(tilt) + y * Math.cos(tilt)]);
    }
    return result(pts);
  },
  // a margin bracket spanning a vertical range, opening toward the text (side 'left' or 'right')
  bracket(x, y0, y1, { seed = 1, depth = 14, side = 'left' } = {}) {
    const k = side === 'left' ? 1 : -1, r = rng(seed), j = () => (r() - 0.5) * 2.5;
    const pts = [[x + k * depth + j(), y0 + j()], [x + j(), y0 + 4], [x + j() * 0.6, (y0 + y1) / 2], [x + j(), y1 - 4], [x + k * depth + j(), y1 + j()]];
    // smooth the corners a little
    const sm = [];
    for (let i = 0; i < pts.length - 1; i++) for (let s = 0; s < 6; s++) { const u = s / 6; sm.push([pts[i][0] + (pts[i + 1][0] - pts[i][0]) * u, pts[i][1] + (pts[i + 1][1] - pts[i][1]) * u]); }
    sm.push(pts[pts.length - 1]);
    return result(sm);
  },
  // a tick mark sized to a box
  check(x, y, size = 24, { seed = 1 } = {}) {
    const r = rng(seed), j = () => (r() - 0.5) * size * 0.06;
    return result([[x + j(), y + size * 0.55 + j()], [x + size * 0.38 + j(), y + size * 0.9 + j()], [x + size * 1.05 + j(), y + j()]]);
  },
};

// Handwriting a line of text: a left-to-right wipe whose edge is slightly slanted, like a pen moving.
// Apply as clip-path to the text element. u: 0 -> 1.
export const writeOn = (u, slant = 8) => {
  if (u <= 0) return 'inset(0 100% 0 0)';
  if (u >= 1) return 'none';
  const x = u * (100 + slant);
  return `polygon(0 0, ${(x).toFixed(2)}% 0, ${(x - slant).toFixed(2)}% 100%, 0 100%)`;
};
