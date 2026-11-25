// piece.js: the contract between a piece and the harness.
//
//   import { piece } from '../../runtime/rv.js';
//   piece({
//     width: 1080, height: 1080, fps: 60, duration: 6, loop: true,
//     background: '#EDEBE7', fonts: ['Geist'],
//     setup(stage) { ... build DOM / SVG / canvas / WebGL once ... },
//     render(t, stage) { ... set every pixel from t alone ... },
//     score(a) { ... optional: synthesize the soundtrack with the audio kit ... },
//     probe(t) { ... optional: named numbers to plot (rv trace) ... },
//   });
//
// Anything can draw inside the stage: DOM + CSS, SVG, Canvas 2D, WebGL, three.js, a mix.
// The only rule: what you see at time t depends on t and nothing else.
//
// URL modes:  ?render=1  harness mode (no UI, no clock, guards on)
//             ?t=2.5 / ?frame=150  freeze on one frame (preview UI hidden with &clean=1)
//             default  preview player: space play/pause, arrows step a frame, shift+arrows a beat,
//                      L loop, M mute, G grid overlay, C safe-area overlay, scrub with the bar.
import { loadFonts } from './fonts.js';
import { rng } from './random.js';

const q = new URLSearchParams(location.search);
const RENDER = q.has('render');

// Where platform UI covers the frame (captions, buttons, the right-hand action rail, the top bar), as
// rectangles [x, y, w, h]. Vertical (9:16-ish) uses the union of Reels / TikTok / Shorts chrome; other
// aspects get a 5% title-safe margin. Approximate: platforms change; keep key text and logos clear.
export function uiZones(W, H) {
  if (H / W >= 1.6) return [[0, 0, W, Math.round(H * 0.08)], [0, Math.round(H * 0.77), W, H - Math.round(H * 0.77)], [Math.round(W * 0.86), Math.round(H * 0.42), W - Math.round(W * 0.86), Math.round(H * 0.35)]];
  const m = 0.05; return [[0, 0, W, H * m], [0, H * (1 - m), W, H * m], [0, 0, W * m, H], [W * (1 - m), 0, W * m, H]];
}

// The time of the frame being rendered. With motion blur the harness draws several subframes around a
// frame; anything discrete (text that types, counters, hard cuts, flashes) should read frameTime() so
// every subframe agrees and nothing double-exposes. Continuous motion reads t.
let FRAME_T = 0, FPS = 60;
export const frameTime = () => FRAME_T;
export const frameOf = (t) => Math.round(t * FPS);

export function piece(spec) {
  const P = {
    name: spec.name || location.pathname.split('/').filter(Boolean).slice(-2, -1)[0] || 'piece',
    width: 1080, height: 1080, fps: 60, duration: 6, loop: true, background: '#000', fonts: [], bpm: null,
    ...spec,
  };
  P.frames = Math.round(P.duration * P.fps);
  FPS = P.fps;
  const dpr = +(q.get('dpr') || window.devicePixelRatio || 1);
  const warnings = new Set();
  let inRender = false;

  // ---------- determinism guards (render mode) ----------
  if (RENDER) {
    const seeded = rng(0xC0FFEE);
    // report where the call came from; library internals (three.js ids, etc.) are noted, not blamed
    const note = (what) => {
      if (!inRender) return;
      const st = (new Error().stack || '').split('\n').slice(3).find((l) => !l.includes('/runtime/piece.js')) || '';
      const lib = /node_modules/.test(st);
      const where = st.trim().replace(/^at /, '').replace(location.origin, '').replace(/:\d+:\d+\)?$/, ')').replace(/\(\)$/, '');
      warnings.add(lib ? `[library] ${what} from ${where} (harmless if it does not change pixels; seeded anyway)` : `${what} at ${st.trim().replace(/^at /, '').replace(location.origin, '')}`);
    };
    Math.random = () => { note('Math.random() during render (replaced with a seeded rng; use rng(seed))'); return seeded(); };
    const dn = Date.now.bind(Date);
    Date.now = () => { note('Date.now() during render'); return dn(); };
    const pn = performance.now.bind(performance);
    performance.now = () => { note('performance.now() during render'); return pn(); };
    for (const k of ['setTimeout', 'setInterval']) {
      const orig = window[k].bind(window);
      window[k] = (fn, ms, ...rest) => { note(`${k}() during render`); return orig(fn, ms, ...rest); };
    }
  }

  // ---------- stage ----------
  const css = document.createElement('style');
  css.textContent = `
    html,body{margin:0;background:${RENDER ? P.background : '#111'};overflow:hidden}
    #rv-stage{position:absolute;left:0;top:0;width:${P.width}px;height:${P.height}px;overflow:hidden;background:${P.background};transform-origin:0 0;contain:strict}
    #rv-ui{position:fixed;left:0;right:0;bottom:0;height:44px;display:flex;align-items:center;gap:12px;padding:0 14px;background:#0b0b0bcc;color:#ddd;font:12px/1 ui-monospace,Menlo,monospace;user-select:none;z-index:9}
    #rv-ui button{all:unset;cursor:pointer;padding:6px 10px;border:1px solid #333;border-radius:6px}
    #rv-ui .bar{flex:1;height:18px;position:relative;cursor:pointer}
    #rv-ui .bar i{position:absolute;top:8px;left:0;right:0;height:2px;background:#333}
    #rv-ui .bar b{position:absolute;top:2px;width:2px;height:14px;background:#fff}
    #rv-ui .bar u{position:absolute;top:6px;width:1px;height:6px;background:#555}
    #rv-ov{position:absolute;inset:0;pointer-events:none;z-index:5}
  `;
  document.head.appendChild(css);
  const stage = document.createElement('div');
  stage.id = 'rv-stage';
  document.body.appendChild(stage);
  Object.assign(stage, { W: P.width, H: P.height, dpr, piece: P });

  // helper: a canvas filling the stage, backing store at dpr
  stage.canvas = (opts = {}) => {
    const c = document.createElement('canvas');
    const s = opts.dpr ?? dpr;
    c.width = Math.round(P.width * s); c.height = Math.round(P.height * s);
    c.style.cssText = `position:absolute;left:0;top:0;width:${P.width}px;height:${P.height}px;${opts.style || ''}`;
    stage.appendChild(c);
    c.scale = s;
    return c;
  };

  let state;
  const ready = (async () => {
    await loadFonts(P.fonts);
    if (P.setup) state = await P.setup(stage);
    await document.fonts.ready;
    await renderAt(0);
  })();

  async function renderAt(t, ft = null) {
    FRAME_T = ft ?? Math.round(t * P.fps) / P.fps;
    inRender = true;
    try { await P.render(t, stage, state); } finally { inRender = false; }
  }

  // ---------- audio ----------
  async function renderAudio({ sampleRate = 48000, mute = [] } = {}) {
    if (!P.score) return null;
    const { makeKit, encodeWav } = await import('./audio.js');
    const pre = 1, tail = P.loop ? 6 : 3;
    const len = Math.ceil((pre + P.duration + tail) * sampleRate);
    const ctx = new OfflineAudioContext(2, len, sampleRate);
    const kit = makeKit(ctx, { offset: pre, fps: P.fps, bpm: P.bpm, duration: P.duration, loop: P.loop, mute });
    await P.score(kit, state);
    kit.finish();
    const buf = await ctx.startRendering();
    const N = Math.round(P.duration * sampleRate), off = Math.round(pre * sampleRate);
    const chans = [];
    for (let c = 0; c < 2; c++) {
      const src = buf.getChannelData(c), out = new Float32Array(N);
      if (P.loop) {
        // fold everything before 0 and after the end back into the loop: the seam is seamless by construction
        for (let i = 0; i < src.length; i++) { const k = i - off; out[((k % N) + N) % N] += src[i]; }
      } else {
        for (let i = 0; i < N; i++) out[i] = src[off + i];
        // non-loop: the file ends at duration, so fade the last `endFade` seconds (default 40 ms) instead of
        // cutting a ringing tail mid-waveform. Let the final sound decay before the end for a clean finish.
        const F = Math.round((P.endFade ?? 0.04) * sampleRate);
        for (let i = 0; i < F; i++) out[N - 1 - i] *= 0.5 - 0.5 * Math.cos((Math.PI * i) / F);
      }
      chans.push(out);
    }
    kit.post?.(chans, sampleRate);
    return { chans, sampleRate, hits: kit.hits, wav: () => encodeWav(chans, sampleRate) };
  }

  // ---------- harness API ----------
  window.rv = {
    ready: ready.then(() => true),
    info: () => ({ render: P.renderDefaults || null, name: P.name, width: P.width, height: P.height, fps: P.fps, duration: P.duration, frames: P.frames, loop: P.loop, bpm: P.bpm, hasAudio: !!P.score, hasProbe: !!P.probe, holds: P.holds || [], uiZones: uiZones(P.width, P.height), background: P.background }),
    seek: async (t, ft = null) => { await renderAt(t, ft); return true; },
    probe: (t) => (P.probe ? P.probe(t, state) : null),
    probeSeries: (ts) => (P.probe ? ts.map((t) => P.probe(t, state)) : null),
    warnings: () => [...warnings],
    // Raw readback for pieces whose stage is one full-frame canvas: skips screenshot encoding (the
    // render bottleneck). Returns null when anything else is visible or the canvas is translucent,
    // and the harness falls back to a screenshot. Format: 'W,H,flip;' + base64 RGB.
    pixels: () => {
      const vis = [...stage.children].filter((e) => e.id !== 'rv-ov' && getComputedStyle(e).display !== 'none' && getComputedStyle(e).visibility !== 'hidden');
      if (vis.length !== 1 || vis[0].tagName !== 'CANVAS') return null;
      const c = vis[0], r = c.getBoundingClientRect();
      if (Math.abs(r.width - P.width) > 0.5 || Math.abs(r.height - P.height) > 0.5 || getComputedStyle(c).opacity !== '1' || getComputedStyle(c).transform !== 'none' || getComputedStyle(c).filter !== 'none') return null;
      let data, flip = 0;
      const g2 = c.__rvCtx || (c.__rvCtx = c.getContext('2d') || c.getContext('webgl2') || c.getContext('webgl'));
      if (!g2) return null;
      if (g2.getImageData) data = g2.getImageData(0, 0, c.width, c.height).data;
      else {
        if (!g2.getContextAttributes().preserveDrawingBuffer) return null;
        data = new Uint8Array(c.width * c.height * 4);
        g2.readPixels(0, 0, c.width, c.height, g2.RGBA, g2.UNSIGNED_BYTE, data);
        flip = 1;
      }
      const n = c.width * c.height, rgb = new Uint8Array(n * 3);
      for (let i = 0, j = 0; i < n * 4; i += 4, j += 3) {
        if (data[i + 3] !== 255) return null;   // translucent: let the screenshot composite it
        rgb[j] = data[i]; rgb[j + 1] = data[i + 1]; rgb[j + 2] = data[i + 2];
      }
      let s = '';
      for (let i = 0; i < rgb.length; i += 0x8000) s += String.fromCharCode.apply(null, rgb.subarray(i, i + 0x8000));
      return `${c.width},${c.height},${flip};` + btoa(s);
    },
    // stems: 'sfx' = hits only (clean onsets), 'bed' = everything but the hits (for level over bed)
    audioWav: async (stem = 'full') => {
      const a = await renderAudio({ mute: stem === 'sfx' ? ['music', 'amb'] : stem === 'bed' ? ['sfx'] : [] });
      if (!a) return null;
      const bytes = a.wav();
      let s = '';
      for (let i = 0; i < bytes.length; i += 0x8000) s += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
      return { b64: btoa(s), hits: a.hits };
    },
    // cues: [[seconds, 'label'], ...] or { label: seconds } (e.g. from cues() in time.js), or a function returning either
    cues: () => {
      let c = typeof P.cues === 'function' ? P.cues() : P.cues;
      if (!c) return null;
      if (!Array.isArray(c)) c = Object.entries(c).filter(([, v]) => typeof v === 'number').map(([k, v]) => [v, k]);
      for (const x of c) if (!Array.isArray(x) || typeof x[0] !== 'number') throw new Error('cues must be [[seconds, "label"], ...] or { label: seconds }');
      return c.slice().sort((x, y) => x[0] - y[0]);
    },
    fontsDeclared: () => P.fonts.map((f) => ({ family: f, loaded: document.fonts.check(`16px "${f}"`) && [...document.fonts].some((ff) => ff.family.replace(/"/g, '') === f && ff.status === 'loaded') })),
  };

  if (RENDER) return window.rv;

  // ---------- preview player ----------
  const freezeT = q.has('frame') ? +q.get('frame') / P.fps : q.has('t') ? +q.get('t') : null;
  const ui = document.createElement('div');
  ui.id = 'rv-ui';
  ui.innerHTML = `<button data-k=play>play</button><span class=tc>0.000</span><div class=bar><i></i><b></b></div><button data-k=loop>loop</button><button data-k=mute>sound</button><button data-k=grid>grid</button><button data-k=safe>safe</button>`;
  const clean = q.has('clean');
  if (!clean) document.body.appendChild(ui);
  const ov = document.createElement('canvas');
  ov.id = 'rv-ov'; ov.width = P.width; ov.height = P.height; ov.style.display = 'none';
  stage.appendChild(ov);
  const bar = ui.querySelector('.bar'), head = ui.querySelector('.bar b'), tc = ui.querySelector('.tc');
  if (P.bpm) for (let b = 0; b * 60 / P.bpm < P.duration; b++) { const u = document.createElement('u'); u.style.left = (100 * b * 60 / P.bpm / P.duration) + '%'; if (b % 4 === 0) u.style.height = '10px'; bar.appendChild(u); }

  const fit = () => {
    const H = innerHeight - (clean ? 0 : 44);
    const s = Math.min(innerWidth / P.width, H / P.height);
    stage.style.transform = `translate(${(innerWidth - P.width * s) / 2}px, ${(H - P.height * s) / 2}px) scale(${s})`;
  };
  addEventListener('resize', fit); fit();

  let t = freezeT ?? 0, playing = freezeT === null, looping = true, last = 0, audio = null, actx = null, src = null, muted = true;
  const draw = async () => {
    await renderAt(t);
    const f = Math.round(t * P.fps);
    tc.textContent = `${t.toFixed(3)}s  f${String(f).padStart(4, '0')}/${P.frames}${P.bpm ? `  beat ${(t * P.bpm / 60 + 1).toFixed(2)}` : ''}`;
    head.style.left = (100 * t / P.duration) + '%';
  };
  const startAudio = async () => {
    if (muted || !P.score) return;
    actx ||= new AudioContext({ sampleRate: 48000 });
    if (!audio) { const a = await renderAudio(); const b = actx.createBuffer(2, a.chans[0].length, a.sampleRate); a.chans.forEach((c, i) => b.copyToChannel(c, i)); audio = b; }
    src?.stop(); src = actx.createBufferSource(); src.buffer = audio; src.loop = P.loop && looping; src.connect(actx.destination); src.start(0, t % P.duration);
  };
  const stopAudio = () => { src?.stop(); src = null; };
  const tick = async (now) => {
    if (playing) {
      const dt = last ? (now - last) / 1000 : 0;
      t += dt;
      if (t >= P.duration) { if (looping) t %= P.duration; else { t = P.duration - 1 / P.fps; playing = false; stopAudio(); } }
      await draw();
    }
    last = now;
    requestAnimationFrame(tick);
  };
  const setT = (x) => { t = Math.max(0, Math.min(P.duration - 1e-6, x)); draw(); if (playing) startAudio(); };
  const togglePlay = () => { playing = !playing; last = 0; ui.querySelector('[data-k=play]').textContent = playing ? 'pause' : 'play'; playing ? startAudio() : stopAudio(); };
  let gridOn = false;
  const drawGrid = () => {
    const g = ov.getContext('2d'); g.clearRect(0, 0, P.width, P.height);
    g.strokeStyle = '#ff2d55aa'; g.lineWidth = 1;
    for (let i = 1; i < 12; i++) { g.beginPath(); g.moveTo(P.width * i / 12, 0); g.lineTo(P.width * i / 12, P.height); g.moveTo(0, P.height * i / 12); g.lineTo(P.width, P.height * i / 12); g.stroke(); }
    g.strokeStyle = '#00e5ffaa'; g.strokeRect(P.width * 0.05, P.height * 0.05, P.width * 0.9, P.height * 0.9);
  };
  let safeOn = false;
  const drawSafe = () => {
    const g = ov.getContext('2d'); g.clearRect(0, 0, P.width, P.height);
    if (gridOn) drawGrid();
    g.fillStyle = '#ff2d5533';
    for (const [x, y, w, h] of uiZones(P.width, P.height)) g.fillRect(x, y, w, h);
  };
  ui.addEventListener('click', (e) => {
    const k = e.target.dataset?.k;
    if (k === 'play') togglePlay();
    if (k === 'loop') { looping = !looping; e.target.style.opacity = looping ? 1 : 0.4; }
    if (k === 'mute') { muted = !muted; e.target.style.opacity = muted ? 0.4 : 1; muted ? stopAudio() : playing && startAudio(); }
    if (k === 'grid') { gridOn = !gridOn; ov.style.display = gridOn || safeOn ? 'block' : 'none'; const g = ov.getContext('2d'); g.clearRect(0, 0, P.width, P.height); if (safeOn) drawSafe(); else if (gridOn) drawGrid(); }
    if (k === 'safe') { safeOn = !safeOn; ov.style.display = gridOn || safeOn ? 'block' : 'none'; const g = ov.getContext('2d'); g.clearRect(0, 0, P.width, P.height); if (safeOn) drawSafe(); else if (gridOn) drawGrid(); }
  });
  ui.querySelector('[data-k=mute]').style.opacity = 0.4;
  let scrubbing = false;
  const scrub = (e) => { const r = bar.getBoundingClientRect(); setT(((e.clientX - r.left) / r.width) * P.duration); };
  bar.addEventListener('pointerdown', (e) => { scrubbing = true; bar.setPointerCapture(e.pointerId); scrub(e); });
  bar.addEventListener('pointermove', (e) => scrubbing && scrub(e));
  bar.addEventListener('pointerup', () => (scrubbing = false));
  addEventListener('keydown', (e) => {
    const beat = P.bpm ? 60 / P.bpm : 0.5;
    if (e.code === 'Space') { e.preventDefault(); togglePlay(); }
    if (e.code === 'ArrowRight') setT(t + (e.shiftKey ? beat : 1 / P.fps));
    if (e.code === 'ArrowLeft') setT(t - (e.shiftKey ? beat : 1 / P.fps));
    if (e.code === 'Home') setT(0);
    if (e.key === 'l') ui.querySelector('[data-k=loop]').click();
    if (e.key === 'm') ui.querySelector('[data-k=mute]').click();
    if (e.key === 'g') ui.querySelector('[data-k=grid]').click();
    if (e.key === 'c') ui.querySelector('[data-k=safe]').click();
  });
  ready.then(() => { ui.querySelector('[data-k=play]').textContent = playing ? 'pause' : 'play'; draw(); requestAnimationFrame(tick); });
  return window.rv;
}
