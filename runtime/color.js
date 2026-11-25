// color.js: parse, mix in OKLab (perceptual: no muddy midpoints), and format.
export function hex(h) {
  h = h.replace('#', '');
  if (h.length === 3) h = h.split('').map((c) => c + c).join('');
  const n = parseInt(h.slice(0, 6), 16);
  const a = h.length === 8 ? parseInt(h.slice(6, 8), 16) / 255 : 1;
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255, a];
}
const toLin = (c) => { c /= 255; return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4; };
const toSrgb = (c) => 255 * (c <= 0.0031308 ? 12.92 * c : 1.055 * c ** (1 / 2.4) - 0.055);
export function rgbToOklab([r, g, b, a = 1]) {
  r = toLin(r); g = toLin(g); b = toLin(b);
  const l = Math.cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b);
  const m = Math.cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b);
  const s = Math.cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b);
  return [0.2104542553 * l + 0.793617785 * m - 0.0040720468 * s, 1.9779984951 * l - 2.428592205 * m + 0.4505937099 * s, 0.0259040371 * l + 0.7827717662 * m - 0.808675766 * s, a];
}
export function oklabToRgb([L, A, B, a = 1]) {
  const l = (L + 0.3963377774 * A + 0.2158037573 * B) ** 3;
  const m = (L - 0.1055613458 * A - 0.0638541728 * B) ** 3;
  const s = (L - 0.0894841775 * A - 1.291485548 * B) ** 3;
  const cl = (x) => Math.max(0, Math.min(255, x));
  return [cl(toSrgb(4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s)), cl(toSrgb(-1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s)), cl(toSrgb(-0.0041960863 * l - 0.7034186147 * m + 1.707614701 * s)), a];
}
const parse = (c) => (typeof c === 'string' ? hex(c) : c);
export function mix(c1, c2, u) {
  const a = rgbToOklab(parse(c1)), b = rgbToOklab(parse(c2));
  return oklabToRgb(a.map((x, i) => x + (b[i] - x) * u));
}
export const css = (c, alpha) => { c = parse(c); const a = alpha ?? c[3] ?? 1; return `rgba(${c[0] | 0},${c[1] | 0},${c[2] | 0},${+a.toFixed(4)})`; };
export const mixCss = (c1, c2, u, alpha) => css(mix(c1, c2, u), alpha);
// relative luminance + WCAG contrast (keep text >= 4.5:1 on every frame)
export const luminance = (c) => { c = parse(c); return 0.2126 * toLin(c[0]) + 0.7152 * toLin(c[1]) + 0.0722 * toLin(c[2]); };
export const contrast = (a, b) => { const x = luminance(a), y = luminance(b); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); };
