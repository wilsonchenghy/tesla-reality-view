// draw.js: small drawing helpers for DOM, SVG and Canvas 2D. Optional: use what helps, ignore the rest.

// ---------- DOM ----------
// el('div', { left: '10px' }, parent, 'text') -> element. Absolutely positioned by default.
export function el(tag, style = {}, parent = null, text = null) {
  const e = tag.startsWith('svg:') ? document.createElementNS('http://www.w3.org/2000/svg', tag.slice(4)) : document.createElement(tag);
  if (!tag.startsWith('svg:')) e.style.position = 'absolute';
  set(e, style);
  if (text != null) e.textContent = text;
  if (parent) parent.appendChild(e);
  return e;
}
// set(el, styles): writes only values that changed since the last frame (cheap per-frame updates).
// Numbers get 'px' for length-like properties. Keys starting with '@' are attributes, '--' custom props.
const UNITLESS = new Set(['opacity', 'zIndex', 'fontWeight', 'lineHeight', 'flex', 'scale', 'order']);
export function set(e, styles) {
  const prev = (e.__rv ||= {});
  for (const k in styles) {
    let v = styles[k];
    if (prev[k] === v) continue;
    prev[k] = v;
    if (k[0] === '@') { e.setAttribute(k.slice(1), v); continue; }
    if (typeof v === 'number' && !UNITLESS.has(k)) v = v + 'px';
    if (k.startsWith('--')) e.style.setProperty(k, v); else e.style[k] = v;
  }
  return e;
}
// Text in the DOM is the sharpest text you can get. Keep resting text on whole pixels.
export const px = (x) => Math.round(x);

// ---------- SVG ----------
export function svg(parent, w, h, attrs = {}) {
  const s = el('svg:svg', {}, parent);
  s.setAttribute('width', w); s.setAttribute('height', h); s.setAttribute('viewBox', `0 0 ${w} ${h}`);
  s.style.cssText = 'position:absolute;left:0;top:0;overflow:visible';
  for (const k in attrs) s.setAttribute(k, attrs[k]);
  return s;
}
export function attrs(e, a) { for (const k in a) e.setAttribute(k, a[k]); return e; }

// ---------- paths (strings usable in SVG `d` and new Path2D) ----------
// Rounded rect with per-corner radii [tl, tr, br, bl] (or one number). Radii are clamped like CSS.
export function roundRectPath(x, y, w, h, r) {
  let [a, b, c, d] = Array.isArray(r) ? r : [r, r, r, r];
  const f = Math.min(1, w / Math.max(1e-6, a + b), w / Math.max(1e-6, c + d), h / Math.max(1e-6, a + d), h / Math.max(1e-6, b + c));
  a *= f; b *= f; c *= f; d *= f;
  return `M${x + a},${y}H${x + w - b}A${b},${b} 0 0 1 ${x + w},${y + b}V${y + h - c}A${c},${c} 0 0 1 ${x + w - c},${y + h}H${x + d}A${d},${d} 0 0 1 ${x},${y + h - d}V${y + a}A${a},${a} 0 0 1 ${x + a},${y}Z`;
}
// Squircle / superellipse (n = 2 ellipse, 4-5 iOS-like, large = rectangle). Returns points.
export function superellipse(cx, cy, rx, ry, n = 4, steps = 96) {
  const pts = [];
  for (let i = 0; i < steps; i++) {
    const a = (i / steps) * Math.PI * 2, c = Math.cos(a), s = Math.sin(a);
    pts.push([cx + rx * Math.sign(c) * Math.abs(c) ** (2 / n), cy + ry * Math.sign(s) * Math.abs(s) ** (2 / n)]);
  }
  return pts;
}
export const pointsToPath = (pts, closed = true) => 'M' + pts.map((p) => `${p[0].toFixed(2)},${p[1].toFixed(2)}`).join('L') + (closed ? 'Z' : '');

// Resample a closed polyline to n points evenly spaced by arc length (for morphing between any two shapes).
export function resample(pts, n) {
  const segs = [], L = [0];
  for (let i = 0; i < pts.length; i++) { const a = pts[i], b = pts[(i + 1) % pts.length]; const d = Math.hypot(b[0] - a[0], b[1] - a[1]); segs.push(d); L.push(L[i] + d); }
  const total = L[L.length - 1], out = [];
  let j = 0;
  for (let i = 0; i < n; i++) {
    const s = (i / n) * total;
    while (L[j + 1] < s) j++;
    const u = (s - L[j]) / (segs[j] || 1), a = pts[j], b = pts[(j + 1) % pts.length];
    out.push([a[0] + (b[0] - a[0]) * u, a[1] + (b[1] - a[1]) * u]);
  }
  return out;
}
// Morph between two point lists of equal length; rotates b to best align with a (minimal travel).
export function alignRing(a, b) {
  let best = 0, bestD = Infinity;
  for (let k = 0; k < b.length; k++) { let d = 0; for (let i = 0; i < a.length; i += 4) { const q = b[(i + k) % b.length]; d += (a[i][0] - q[0]) ** 2 + (a[i][1] - q[1]) ** 2; } if (d < bestD) { bestD = d; best = k; } }
  return a.map((_, i) => b[(i + best) % b.length]);
}
export const morph = (a, b, u) => a.map((p, i) => [p[0] + (b[i][0] - p[0]) * u, p[1] + (b[i][1] - p[1]) * u]);

// Sample an SVG path string into points (uses the browser's geometry engine).
let _probe;
export function samplePath(d, n = 200) {
  _probe ||= document.createElementNS('http://www.w3.org/2000/svg', 'path');
  _probe.setAttribute('d', d);
  const L = _probe.getTotalLength(), pts = [];
  for (let i = 0; i < n; i++) { const p = _probe.getPointAtLength((i / n) * L); pts.push([p.x, p.y]); }
  return pts;
}
// Partial stroke draw-on: returns stroke-dasharray/offset for progress u of a path of length L.
// (hidden entirely at 0: a zero-length dash still paints a dot with round caps)
export const drawOn = (L, u) => ({ 'stroke-dasharray': `${L} ${L}`, 'stroke-dashoffset': L * (1 - u), 'stroke-opacity': u > 0 ? 1 : 0 });

// ---------- Canvas 2D ----------
export function ctx2d(canvas) {
  const g = canvas.getContext('2d');
  g.setTransform(canvas.scale || 1, 0, 0, canvas.scale || 1, 0, 0);
  return g;
}
// Layout glyphs of a string; returns [{ch, x, w}] with kerning-aware advances (measures prefixes).
export function layoutGlyphs(g, text, letterSpacing = 0) {
  const out = [];
  const chars = [...text];
  let prev = 0;
  for (let i = 0; i < chars.length; i++) {
    const w = g.measureText(chars.slice(0, i + 1).join('')).width;
    out.push({ ch: chars[i], x: prev + i * letterSpacing, w: w - prev });
    prev = w;
  }
  out.width = prev + (chars.length - 1) * letterSpacing;
  return out;
}

// Film grain for a canvas, seeded by frame so it is deterministic. amount 0..0.1
export function grain(g, w, h, frame, amount = 0.03, scale = 1) {
  const tile = 256;
  grain._c ||= {};
  const key = frame % 24;
  let c = grain._c[key];
  if (!c) {
    c = document.createElement('canvas'); c.width = c.height = tile;
    const x = c.getContext('2d'), img = x.createImageData(tile, tile);
    let s = (key + 1) * 2654435761 >>> 0;
    for (let i = 0; i < img.data.length; i += 4) { s ^= s << 13; s ^= s >>> 17; s ^= s << 5; const v = (s >>> 0) / 4294967296 * 255; img.data[i] = img.data[i + 1] = img.data[i + 2] = v; img.data[i + 3] = 255; }
    x.putImageData(img, 0, 0); grain._c[key] = c;
  }
  g.save(); g.globalAlpha = amount; g.globalCompositeOperation = 'overlay';
  g.fillStyle = g.createPattern(c, 'repeat'); g.setTransform(scale, 0, 0, scale, 0, 0); g.fillRect(0, 0, w, h); g.restore();
}

// A polyline with rounded corners and arc-length lookup, for canvas: traces, routes, paths that a token
// travels and that draw themselves. pts: [[x, y], ...]; radius rounds every corner.
//   const p = polyline(pts, { radius: 24 });  p.at(len) -> {x, y, angle};  p.stroke(g, from, to)
export function polyline(pts, { radius = 0, samples = 12 } = {}) {
  const out = [pts[0]];
  for (let i = 1; i < pts.length - 1; i++) {
    const [ax, ay] = pts[i - 1], [bx, by] = pts[i], [cx, cy] = pts[i + 1];
    const l1 = Math.hypot(bx - ax, by - ay), l2 = Math.hypot(cx - bx, cy - by);
    const r = Math.min(radius, l1 / 2, l2 / 2);
    if (r <= 0) { out.push(pts[i]); continue; }
    const p0 = [bx - ((bx - ax) / l1) * r, by - ((by - ay) / l1) * r], p1 = [bx + ((cx - bx) / l2) * r, by + ((cy - by) / l2) * r];
    for (let k = 0; k <= samples; k++) { const u = k / samples, a = 1 - u; out.push([a * a * p0[0] + 2 * a * u * bx + u * u * p1[0], a * a * p0[1] + 2 * a * u * by + u * u * p1[1]]); }
  }
  out.push(pts[pts.length - 1]);
  const L = [0];
  for (let i = 1; i < out.length; i++) L.push(L[i - 1] + Math.hypot(out[i][0] - out[i - 1][0], out[i][1] - out[i - 1][1]));
  const total = L[L.length - 1];
  const at = (len) => {
    len = Math.max(0, Math.min(total, len));
    let i = 1; while (i < L.length - 1 && L[i] < len) i++;
    const u = (len - L[i - 1]) / ((L[i] - L[i - 1]) || 1), a = out[i - 1], b = out[i];
    return { x: a[0] + (b[0] - a[0]) * u, y: a[1] + (b[1] - a[1]) * u, angle: Math.atan2(b[1] - a[1], b[0] - a[0]) };
  };
  const stroke = (g, from = 0, to = total) => {
    if (to <= from) return;
    g.beginPath(); const s = at(from); g.moveTo(s.x, s.y);
    for (let i = 0; i < out.length; i++) if (L[i] > from && L[i] < to) g.lineTo(out[i][0], out[i][1]);
    const e = at(to); g.lineTo(e.x, e.y); g.stroke();
  };
  return { points: out, length: total, at, stroke, path: pointsToPath(out, false) };
}

// Canvas text with tracking (letter-spacing in px) and optional tabular figures; returns the width.
export function fillTextTracked(g, text, x, y, { tracking = 0, align = 'left', tabular = false } = {}) {
  if ('letterSpacing' in g) {
    g.letterSpacing = `${tracking}px`; g.fontVariantNumeric = tabular ? 'tabular-nums' : 'normal';
    const w = g.measureText(text).width - (text.length ? tracking : 0);
    const x0 = align === 'center' ? x - w / 2 : align === 'right' ? x - w : x;
    const prev = g.textAlign; g.textAlign = 'left'; g.fillText(text, x0, y); g.textAlign = prev; g.letterSpacing = '0px';
    return w;
  }
  const gl = layoutGlyphs(g, text, tracking), x0 = align === 'center' ? x - gl.width / 2 : align === 'right' ? x - gl.width : x;
  const prev = g.textAlign; g.textAlign = 'left'; gl.forEach((c) => g.fillText(c.ch, x0 + c.x, y)); g.textAlign = prev;
  return gl.width;
}
