// type.js: typography helpers for kinetic type. Measure real glyph widths (DOM layout, so kerning-free
// per-glyph advances), model the width axis of variable fonts, fit words to a measure, split text.
//
//   const m = typeModel('Archivo', 800);                  // per-glyph width = a + b * wdth (at 100 px)
//   const fit = m.fit('RHYTHM', 960, { wdth: 90 });       // -> { size, widths, wdths }
//   m.layout(spans, fit.widths, x0)                       // position glyph spans, set their font-stretch
//
// Width is close to linear in the wdth axis for most variable fonts; check one glyph if precision matters.
import { set } from './draw.js';

let meas;
function measurer() {
  if (meas) return meas;
  meas = document.createElement('span');
  meas.style.cssText = 'position:absolute;left:-99999px;top:0;white-space:pre;line-height:1;font-size:100px';
  document.body.appendChild(meas);
  return meas;
}
export function measure(text, font, { stretch = null, variation = null } = {}) {
  const m = measurer();
  m.style.font = font; m.style.fontStretch = stretch ? stretch + '%' : ''; m.style.fontVariationSettings = variation || '';
  m.textContent = text;
  return m.getBoundingClientRect().width;
}

export function typeModel(family, weight = 400, { wmin = 62, wmax = 125, style = 'normal' } = {}) {
  const cache = new Map();
  const glyph = (ch) => {
    if (cache.has(ch)) return cache.get(ch);
    const f = `${style} ${weight} 100px "${family}"`;
    const lo = measure(ch, f, { stretch: wmin }), hi = measure(ch, f, { stretch: wmax });
    const b = (hi - lo) / (wmax - wmin);
    const g = { a: lo - b * wmin, b };
    cache.set(ch, g);
    return g;
  };
  const width = (ch, wdth, size) => { const g = glyph(ch); return ((g.a + g.b * wdth) * size) / 100; };
  const wdthFor = (ch, w, size) => { const g = glyph(ch); return Math.min(wmax, Math.max(wmin, ((w * 100) / size - g.a) / (g.b || 1e-9))); };
  return {
    family, weight, wmin, wmax, glyph, width, wdthFor,
    // font size so `text` at `wdth` spans exactly `measure` px
    fit(text, measurePx, { wdth = 100 } = {}) {
      const chars = [...text];
      const at100 = chars.reduce((s, c) => s + width(c, wdth, 100), 0);
      const size = (100 * measurePx) / at100;
      return { size, chars, widths: chars.map((c) => width(c, wdth, size)), wdth };
    },
    // place glyph spans left to right with given pixel widths (sets left + font-stretch)
    layout(spans, chars, widths, size, x0 = 0) {
      let x = x0;
      spans.forEach((s, i) => { set(s, { left: x, fontStretch: wdthFor(chars[i], widths[i], size).toFixed(2) + '%' }); x += widths[i]; });
      return x - x0;
    },
    // redistribute: glyph `i` takes `w`, the rest give way proportionally so the total stays the same
    giveWay(widths, i, w) {
      const extra = w - widths[i], rest = widths.reduce((s, x, k) => s + (k === i ? 0 : x), 0);
      return widths.map((x, k) => (k === i ? w : x - (extra * x) / rest));
    },
  };
}

// Cap height and ascent ratios of a font (canvas metrics), for optical vertical centering.
export function metrics(font) {
  const c = document.createElement('canvas').getContext('2d');
  c.font = font;
  const H = c.measureText('H'), x = c.measureText('x'), g = c.measureText('g');
  return { cap: H.actualBoundingBoxAscent, xHeight: x.actualBoundingBoxAscent, descent: g.actualBoundingBoxDescent };
}

// Split text into graphemes / words for per-unit animation.
export const graphemes = (s) => (typeof Intl !== 'undefined' && Intl.Segmenter ? [...new Intl.Segmenter().segment(s)].map((x) => x.segment) : [...s]);
export const words = (s) => s.split(/(\s+)/).filter((w) => w.length);

// Typed text: how much of `text` is visible at frame time ft, typing `cps` characters per second from t0
// (or one per frame with perFrame). Use frameTime() so motion-blur subframes agree (no ghost letters).
export function typed(text, ft, t0, { cps = 30, perFrame = false, fps = 60, t1 = null, eraseCps = 60 } = {}) {
  const chars = graphemes(text);
  if (ft < t0) return '';
  let n = perFrame ? Math.floor((ft - t0) * fps) + 1 : Math.floor((ft - t0) * cps) + 1;
  if (t1 != null && ft >= t1) n = Math.max(0, chars.length - Math.floor((ft - t1) * eraseCps) - 1);
  return chars.slice(0, Math.max(0, Math.min(chars.length, n))).join('');
}
