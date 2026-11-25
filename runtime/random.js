// random.js: seeded randomness and noise. Math.random is banned in pieces (it makes frames differ per run).

export function rng(seed = 1) {
  let a = typeof seed === 'string' ? hashString(seed) : seed >>> 0;
  const next = () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
  next.range = (a, b) => a + (b - a) * next();
  next.int = (a, b) => Math.floor(a + (b - a + 1) * next());
  next.pick = (arr) => arr[Math.floor(next() * arr.length)];
  next.sign = () => (next() < 0.5 ? -1 : 1);
  next.gauss = () => { let u = 0, v = 0; while (u === 0) u = next(); v = next(); return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v); };
  next.shuffle = (arr) => { const a2 = arr.slice(); for (let i = a2.length - 1; i > 0; i--) { const j = Math.floor(next() * (i + 1)); [a2[i], a2[j]] = [a2[j], a2[i]]; } return a2; };
  return next;
}

export function hashString(s) {
  let h = 2166136261 >>> 0;
  for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); }
  return h >>> 0;
}
// stateless hash of integers -> [0,1): for per-item constants without carrying an rng around
export function hash(...n) {
  let h = 0x9e3779b9;
  for (const x of n) { h ^= Math.imul((x | 0) ^ 0x85ebca6b, 0xc2b2ae35); h = Math.imul(h ^ (h >>> 13), 0x27d4eb2f); h ^= h >>> 16; }
  return (h >>> 0) / 4294967296;
}

// ---------- simplex noise (2D/3D/4D), seeded permutation ----------
const F2 = 0.5 * (Math.sqrt(3) - 1), G2 = (3 - Math.sqrt(3)) / 6, F3 = 1 / 3, G3 = 1 / 6;
const F4 = (Math.sqrt(5) - 1) / 4, G4 = (5 - Math.sqrt(5)) / 20;
const grad3 = [1,1,0,-1,1,0,1,-1,0,-1,-1,0,1,0,1,-1,0,1,1,0,-1,-1,0,-1,0,1,1,0,-1,1,0,1,-1,0,-1,-1];
const grad4 = [0,1,1,1,0,1,1,-1,0,1,-1,1,0,1,-1,-1,0,-1,1,1,0,-1,1,-1,0,-1,-1,1,0,-1,-1,-1,1,0,1,1,1,0,1,-1,1,0,-1,1,1,0,-1,-1,-1,0,1,1,-1,0,1,-1,-1,0,-1,1,-1,0,-1,-1,1,1,0,1,1,1,0,-1,1,-1,0,1,1,-1,0,-1,-1,1,0,1,-1,1,0,-1,-1,-1,0,1,-1,-1,0,-1,1,1,1,0,1,1,-1,0,1,-1,1,0,1,-1,-1,0,-1,1,1,0,-1,1,-1,0,-1,-1,1,0,-1,-1,-1,0];

export function noise(seed = 0) {
  const r = rng(seed + 7919);
  const p = new Uint8Array(256);
  for (let i = 0; i < 256; i++) p[i] = i;
  for (let i = 255; i > 0; i--) { const j = Math.floor(r() * (i + 1)); [p[i], p[j]] = [p[j], p[i]]; }
  const perm = new Uint8Array(512), pm12 = new Uint8Array(512);
  for (let i = 0; i < 512; i++) { perm[i] = p[i & 255]; pm12[i] = perm[i] % 12; }

  function n2(x, y) {
    const s = (x + y) * F2, i = Math.floor(x + s), j = Math.floor(y + s);
    const t = (i + j) * G2, x0 = x - (i - t), y0 = y - (j - t);
    const i1 = x0 > y0 ? 1 : 0, j1 = 1 - i1;
    const x1 = x0 - i1 + G2, y1 = y0 - j1 + G2, x2 = x0 - 1 + 2 * G2, y2 = y0 - 1 + 2 * G2;
    const ii = i & 255, jj = j & 255;
    let n = 0, tt, g;
    tt = 0.5 - x0 * x0 - y0 * y0; if (tt > 0) { g = pm12[ii + perm[jj]] * 3; tt *= tt; n += tt * tt * (grad3[g] * x0 + grad3[g + 1] * y0); }
    tt = 0.5 - x1 * x1 - y1 * y1; if (tt > 0) { g = pm12[ii + i1 + perm[jj + j1]] * 3; tt *= tt; n += tt * tt * (grad3[g] * x1 + grad3[g + 1] * y1); }
    tt = 0.5 - x2 * x2 - y2 * y2; if (tt > 0) { g = pm12[ii + 1 + perm[jj + 1]] * 3; tt *= tt; n += tt * tt * (grad3[g] * x2 + grad3[g + 1] * y2); }
    return 70 * n;
  }
  function n3(x, y, z) {
    const s = (x + y + z) * F3, i = Math.floor(x + s), j = Math.floor(y + s), k = Math.floor(z + s);
    const t = (i + j + k) * G3, x0 = x - (i - t), y0 = y - (j - t), z0 = z - (k - t);
    let i1, j1, k1, i2, j2, k2;
    if (x0 >= y0) { if (y0 >= z0) { i1=1;j1=0;k1=0;i2=1;j2=1;k2=0; } else if (x0 >= z0) { i1=1;j1=0;k1=0;i2=1;j2=0;k2=1; } else { i1=0;j1=0;k1=1;i2=1;j2=0;k2=1; } }
    else { if (y0 < z0) { i1=0;j1=0;k1=1;i2=0;j2=1;k2=1; } else if (x0 < z0) { i1=0;j1=1;k1=0;i2=0;j2=1;k2=1; } else { i1=0;j1=1;k1=0;i2=1;j2=1;k2=0; } }
    const c = [[x0, y0, z0, 0, 0, 0], [x0 - i1 + G3, y0 - j1 + G3, z0 - k1 + G3, i1, j1, k1], [x0 - i2 + 2 * G3, y0 - j2 + 2 * G3, z0 - k2 + 2 * G3, i2, j2, k2], [x0 - 1 + 3 * G3, y0 - 1 + 3 * G3, z0 - 1 + 3 * G3, 1, 1, 1]];
    const ii = i & 255, jj = j & 255, kk = k & 255;
    let n = 0;
    for (const [a, b, d, oi, oj, ok] of c) {
      let tt = 0.5 - a * a - b * b - d * d;
      if (tt > 0) { const g = pm12[ii + oi + perm[jj + oj + perm[kk + ok]]] * 3; tt *= tt; n += tt * tt * (grad3[g] * a + grad3[g + 1] * b + grad3[g + 2] * d); }
    }
    return 76 * n;   // kernel radius 0.5 (continuous); scaled to ~[-1, 1]
  }
  function n4(x, y, z, w) {
    const s = (x + y + z + w) * F4;
    const i = Math.floor(x + s), j = Math.floor(y + s), k = Math.floor(z + s), l = Math.floor(w + s);
    const t = (i + j + k + l) * G4;
    const x0 = x - (i - t), y0 = y - (j - t), z0 = z - (k - t), w0 = w - (l - t);
    let rx = 0, ry = 0, rz = 0, rw = 0;
    if (x0 > y0) rx++; else ry++; if (x0 > z0) rx++; else rz++; if (x0 > w0) rx++; else rw++;
    if (y0 > z0) ry++; else rz++; if (y0 > w0) ry++; else rw++; if (z0 > w0) rz++; else rw++;
    const off = [];
    for (const th of [3, 2, 1]) off.push([rx >= th ? 1 : 0, ry >= th ? 1 : 0, rz >= th ? 1 : 0, rw >= th ? 1 : 0]);
    const pts = [[0, 0, 0, 0], ...off, [1, 1, 1, 1]];
    const ii = i & 255, jj = j & 255, kk = k & 255, ll = l & 255;
    let n = 0;
    pts.forEach((o, idx) => {
      const a = x0 - o[0] + idx * G4, b = y0 - o[1] + idx * G4, c = z0 - o[2] + idx * G4, d = w0 - o[3] + idx * G4;
      let tt = 0.5 - a * a - b * b - c * c - d * d;
      if (tt > 0) { const g = (perm[ii + o[0] + perm[jj + o[1] + perm[kk + o[2] + perm[ll + o[3]]]]] % 32) * 4; tt *= tt; n += tt * tt * (grad4[g] * a + grad4[g + 1] * b + grad4[g + 2] * c + grad4[g + 3] * d); }
    });
    return 62 * n;   // kernel radius 0.5 (continuous); scaled to ~[-1, 1]
  }
  // Loop noise: sample along a circle in an extra dimension so the value at t = period equals t = 0.
  // radius sets how fast it wanders (bigger = more change per loop).
  const loop1 = (t, period, x = 0, radius = 1) => { const a = (2 * Math.PI * t) / period; return n3(x, Math.cos(a) * radius, Math.sin(a) * radius); };
  const loop2 = (t, period, x, y, radius = 1) => { const a = (2 * Math.PI * t) / period; return n4(x, y, Math.cos(a) * radius, Math.sin(a) * radius); };
  const fbm2 = (x, y, oct = 4, lac = 2, gain = 0.5) => { let s = 0, a = 1, f = 1, m = 0; for (let o = 0; o < oct; o++) { s += a * n2(x * f, y * f); m += a; a *= gain; f *= lac; } return s / m; };
  return { n2, n3, n4, loop1, loop2, fbm2 };
}
