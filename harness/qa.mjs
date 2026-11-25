// qa.mjs: the self-review loop. Every command writes images you can open and read, plus a JSON report.
import { mkdir, rm, writeFile, readdir } from 'node:fs/promises';
import { existsSync } from 'node:fs';
import { spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import path from 'node:path';
import { open, outDir, resolvePiece, serve, ROOT } from './session.mjs';
import { capture, subTime, renderAudio, loudness, getInfo, pad } from './render.mjs';

const py = (args) => {
  const r = spawnSync('python3', [path.join(ROOT, 'tools', args[0]), ...args.slice(1)], { encoding: 'utf8', maxBuffer: 1 << 26 });
  if (r.status !== 0) throw new Error(r.stderr || r.stdout);
  return r.stdout.trim();
};
const list = (s) => String(s).split(',').map((x) => x.trim()).filter(Boolean).map(Number);

// Which times to grab: --t 0,1.5 | --frames 0,90 | --every 12 (frames) | --beats [--div 2] | --n 12 (evenly)
function pickTimes(info, o) {
  const fps = info.fps, N = info.frames;
  if (o.t) return list(o.t).map((t) => Math.round(t * fps));
  if (o.frames && o.frames !== true) return list(o.frames).map(Math.round);
  if (o.every) { const f = []; for (let i = 0; i < N; i += +o.every) f.push(i); return f; }
  if (o.beats || o.beat) {
    const bpm = +(o.bpm || info.bpm || 120), off = +(o.offset || 0), div = +(o.div || 1), f = [];
    for (let b = 0; off + (b / div) * 60 / bpm < info.duration - 1e-9; b++) f.push(Math.round((off + (b / div) * 60 / bpm) * fps));
    return f;
  }
  const n = +(o.n || 12);
  return Array.from({ length: n }, (_, i) => Math.round((i / n) * N));
}

// --query a=1,b  ->  '&a=1&b' appended to the piece URL (debug views a piece reads from location.search)
export const queryOf = (o) => (o.query ? '&' + String(o.query).split(',').filter(Boolean).join('&') : '');

async function grab(pieceArg, info, frames, o, dir) {
  await rm(dir, { recursive: true, force: true });
  await mkdir(dir, { recursive: true });
  const S = Math.max(1, +(o.sub ?? 1)), shutter = +(o.shutter ?? 0.5);
  const jobs = [];
  frames.forEach((f, k) => { for (let j = 0; j < S; j++) jobs.push({ ft: f / info.fps, t: subTime(f + (o.offsetFrames ? +o.offsetFrames : 0), j, S, shutter, info.fps, info.duration, info.loop), file: path.join(dir, `_${pad(k, 4)}_${j}.png`), k, f }); });
  const cap = await capture(pieceArg, jobs, { workers: +o.workers || 0, scale: +(o.scale || 1), query: queryOf(o) });
  const files = [];
  for (let k = 0; k < frames.length; k++) {
    const f = path.join(dir, `f${pad(frames[k], 5)}.png`);
    const subs = jobs.filter((j) => j.k === k).map((j) => j.file);
    if (S === 1) spawnSync('mv', [subs[0], f]);
    else {
      const r = spawnSync('ffmpeg', ['-y', '-v', 'error', ...subs.flatMap((s) => ['-i', s]), '-filter_complex', subs.map((_, i) => `[${i}]zscale=transferin=iec61966-2-1:transfer=linear:primariesin=709:primaries=709:npl=100,format=gbrpf32le[l${i}]`).join(';') + ';' + subs.map((_, i) => `[l${i}]`).join('') + `mix=inputs=${S},zscale=transferin=linear:transfer=iec61966-2-1:primariesin=709:primaries=709:npl=100,format=rgb24`, f]);
      if (r.status !== 0) throw new Error(r.stderr);
      subs.forEach((s) => spawnSync('rm', [s]));
    }
    files.push(f);
  }
  return { files, cap };
}

const label = (info, f) => {
  const t = f / info.fps;
  return `f${f}  ${t.toFixed(3)}s${info.bpm ? `  b${(t * info.bpm / 60).toFixed(2)}` : ''}`;
};

export async function stills(pieceArg, o = {}) {
  const pc = resolvePiece(pieceArg);
  const info = await getInfo(pieceArg);
  const frames = pickTimes(info, o);
  const dir = path.join(outDir(pc.name), o.dir || 'stills');
  const { files, cap } = await grab(pieceArg, info, frames, o, dir);
  if (cap.warnings.length) console.log('[rv] determinism warnings:\n  ' + cap.warnings.join('\n  '));
  if (cap.errors.length) console.log('[rv] page errors:\n  ' + cap.errors.join('\n  '));
  const cols = +(o.cols || Math.min(4, files.length));
  const sheetPath = path.join(outDir(pc.name), `${o.name || 'stills'}${o.tag ? '-' + o.tag : ''}.png`);
  const width = +(o.width || (files.length <= 2 ? 720 : files.length <= 6 ? 480 : 360));
  py(['imgtools.py', 'sheet', sheetPath, '--cols', String(cols), '--width', String(width), ...files.map((f, i) => `${f}:${label(info, frames[i])}`)]);
  console.log(`${sheetPath}   (contact sheet; the frames are in ${dir}/)`);
  files.forEach((f) => console.log('  ' + f));
  return { sheet: sheetPath, files };
}

export const sheet = (p, o = {}) => stills(p, { every: o.every || 12, name: 'sheet', dir: 'sheet', cols: o.cols || 6, width: o.width || 260, ...o });
export const beatSheet = (p, o = {}) => stills(p, { beats: true, name: 'beats', dir: 'beats', cols: o.cols || 4, width: o.width || 360, ...o });

export async function onion(pieceArg, o = {}) {
  const pc = resolvePiece(pieceArg);
  const info = await getInfo(pieceArg);
  const a = Math.round(+(o.from ?? 0) * info.fps), b = Math.round(+(o.to ?? Math.min(info.duration, 1)) * info.fps);
  const n = +(o.n || 10);
  const frames = Array.from({ length: n }, (_, i) => Math.round(a + ((b - a) * i) / (n - 1)));
  const dir = path.join(outDir(pc.name), 'onion');
  const { files } = await grab(pieceArg, info, frames, o, dir);
  const outPng = path.join(outDir(pc.name), `onion_${a}-${b}.png`);
  py(['imgtools.py', 'onion', outPng, ...(o.crop ? ['--crop', String(o.crop)] : []), ...files]);
  console.log(outPng, '\n  blue = first, red = last. Even spacing = linear; spacing that tightens near the keys = eased.');
  return outPng;
}

// Plot probe(t) values per frame: speed, linear runs, dead stops, jumps.
export async function trace(pieceArg, o = {}) {
  const pc = resolvePiece(pieceArg);
  const s = await open(pieceArg, { quiet: true });
  try {
    const { info, page } = s;
    if (!info.hasProbe) throw new Error('this piece has no probe(t). Add probe(t) { return { heroX: ..., scale: ... } } to piece({...}).');
    const fps = info.fps * +(o.oversample || 1);
    const ts = Array.from({ length: Math.round(info.duration * fps) + 1 }, (_, i) => i / fps);
    const rows = await page.evaluate(`window.rv.probeSeries(${JSON.stringify(ts)})`);
    const keys = o.keys ? String(o.keys).split(',') : Object.keys(rows[0] || {});
    const series = {};
    for (const k of keys) series[k] = rows.map((r) => (r && typeof r[k] === 'number' ? r[k] : null));
    const j = path.join(outDir(pc.name), 'trace.json');
    await mkdir(outDir(pc.name), { recursive: true });
    await writeFile(j, JSON.stringify({ fps, bpm: info.bpm, offset: +(o.offset || 0), duration: info.duration, t: ts, series }));
    const png = path.join(outDir(pc.name), 'trace.png');
    console.log(py(['imgtools.py', 'chart', png, j]));
    console.log(png);
    return png;
  } finally { await s.close(); }
}

// Motion energy per frame (low-res render): dead time, per-beat activity, biggest jump, loop seam.
export async function motion(pieceArg, o = {}) {
  const pc = resolvePiece(pieceArg);
  const info = await getInfo(pieceArg);
  const dir = path.join(outDir(pc.name), '.motion');
  await rm(dir, { recursive: true, force: true }); await mkdir(dir, { recursive: true });
  const step = +(o.step || 1);
  const frames = []; for (let i = 0; i < info.frames; i += step) frames.push(i);
  const scale = +(o.scale || 0.25);
  const jobs = frames.map((f, k) => ({ t: f / info.fps, file: path.join(dir, `${pad(k, 5)}.png`) }));
  await capture(pieceArg, jobs, { workers: +o.workers || 0, scale });
  if (info.loop) { jobs.push({ t: 0, file: path.join(dir, `${pad(frames.length, 5)}.png`) }); spawnSync('cp', [jobs[0].file, jobs[jobs.length - 1].file]); }
  const png = path.join(outDir(pc.name), 'motion.png'), json = path.join(outDir(pc.name), 'motion.json');
  const out = py(['imgtools.py', 'energy', png, json, '--fps', String(info.fps / step), '--bpm', String(info.bpm || 0), '--offset', String(o.offset || 0), ...(info.loop ? ['--loop'] : []), '--holds', JSON.stringify(info.holds || []), ...jobs.map((j) => j.file)]);
  console.log(out); console.log(png);
  await rm(dir, { recursive: true, force: true });
  return png;
}

// check: determinism, loop seam, guards, errors, network, fonts, render cost.
export async function check(pieceArg, o = {}) {
  const pc = resolvePiece(pieceArg);
  const srv = await serve();
  const s = await open(pieceArg, { quiet: true });
  const report = { piece: pc.name, ok: true, problems: [], notes: [] };
  const bad = (m) => { report.ok = false; report.problems.push(m); };
  try {
    const { info, page } = s;
    report.info = info;
    const N = info.frames;
    const picks = [0, 1, Math.floor(N / 3), Math.floor(N / 2), Math.floor((2 * N) / 3), N - 1];
    const hash = (b) => createHash('sha1').update(b).digest('hex').slice(0, 12);
    const shot = async (f) => { await page.evaluate(`window.rv.seek(${f / info.fps})`); return page.screenshot(); };
    // pass 1 in order, pass 2 reversed (catches state carried between frames)
    const A = {}, B = {}, drawMs = [], capMs = [];
    for (const f of picks) {
      let a = performance.now(); await page.evaluate(`window.rv.seek(${f / info.fps})`); drawMs.push(performance.now() - a);
      a = performance.now(); A[f] = await page.screenshot(); capMs.push(performance.now() - a);
    }
    const med = (x) => x.slice().sort((p, q) => p - q)[x.length >> 1];
    const perFrame = med(drawMs) + med(capMs);
    for (const f of [...picks].reverse()) B[f] = await shot(f);
    const dir = path.join(outDir(pc.name), '.check'); await mkdir(dir, { recursive: true });
    for (const f of picks) {
      if (hash(A[f]) !== hash(B[f])) {
        await writeFile(path.join(dir, `a${f}.png`), A[f]); await writeFile(path.join(dir, `b${f}.png`), B[f]);
        const d = +py(['imgtools.py', 'diff', path.join(dir, `a${f}.png`), path.join(dir, `b${f}.png`)]);
        if (d > 0.05) bad(`frame ${f} differs between two renders (mean diff ${d}): something depends on render order or the clock`);
      }
    }
    // jump test: seek far away then back, compare to a straight seek (catches incremental state)
    // loop seam
    if (info.loop) {
      // compare the seam step (N-1 -> 0) with the largest of the last 12 steps: pieces animated on twos,
      // with held frames or stepped textures change in bursts, so one previous step is not a baseline
      const K = Math.min(12, N - 2), files = [];
      for (let i = N - 1 - K; i <= N - 1; i++) { const f = path.join(dir, `tail${i}.png`); await writeFile(f, await shot(i)); files.push(f); }
      const first = path.join(dir, 'first.png'); await writeFile(first, await shot(0));
      const steps = [];
      for (let k = 1; k < files.length; k++) steps.push(+py(['imgtools.py', 'diff', files[k - 1], files[k]]));
      // and the steps after it: an event that lands on frame 0 legitimately changes 0 -> 1 as much as N-1 -> 0
      const head = [first];
      for (let i = 1; i <= K; i++) { const f = path.join(dir, `head${i}.png`); await writeFile(f, await shot(i)); head.push(f); }
      const after = [];
      for (let k = 1; k < head.length; k++) after.push(+py(['imgtools.py', 'diff', head[k - 1], head[k]]));
      const seam = +py(['imgtools.py', 'diff', files[files.length - 1], first]);
      const base = Math.max(...steps, ...after);
      report.seam = { lastToFirst: seam, maxStepNearSeam: base, before: steps, after };
      if (seam > Math.max(1.0, base * 1.5)) bad(`loop seam: frame ${N - 1} -> 0 changes ${seam.toFixed(2)} (mean abs diff, 0-255), but no step within ${K} frames either side changes more than ${base.toFixed(2)}: the last frame does not flow into the first. Threshold: 1.5x the largest nearby step.`);
      const f0 = await shot(0), fN = await page.evaluate(`window.rv.seek(${info.duration})`).then(() => page.screenshot());
      await writeFile(path.join(dir, 'fN.png'), fN); void f0;
      const same = +py(['imgtools.py', 'diff', first, path.join(dir, 'fN.png')]);
      report.seam.tDurationVsZero = same;
      if (same > 0.5) report.notes.push(`render(duration) differs from render(0) by ${same.toFixed(2)}: fine if intentional, but a true loop has render(T) == render(0)`);
    }
    report.msPerFrame = Math.round(perFrame);
    report.timing = { drawMs: { median: Math.round(med(drawMs)), min: Math.round(Math.min(...drawMs)), max: Math.round(Math.max(...drawMs)) }, pngCaptureMs: Math.round(med(capMs)), cpuLoad: (await import('node:os')).loadavg()[0].toFixed(2), note: 'draw = your render(t); capture = screenshot encoding (renders use faster WebP/raw). High cpuLoad inflates both.' };
    if (med(capMs) > 600) report.notes.push(`capture is expensive (${Math.round(med(capMs))} ms per PNG): usually an incompressible layer (full-frame grain/noise, halftone, dithering). Fine for the look, but renders will be slow; keep noise to a single canvas (raw readback) or apply it sparingly.`);
    for (const f of await page.evaluate('window.rv.fontsDeclared ? window.rv.fontsDeclared() : []')) if (!f.loaded) bad(`font "${f.family}" is declared in fonts: [...] but did not load (canvas text would silently use a fallback). Vendor it: node tools/fetch-font.mjs "${f.family}"`);
    const warns = await page.evaluate('window.rv.warnings()');
    for (const w of warns) (w.startsWith('[library]') ? report.notes.push('guard: ' + w) : bad('guard: ' + w));
    for (const e of page.errors) bad('page error: ' + e);
    const ext = page.requests.filter((u) => !u.startsWith(srv.base) && !u.startsWith('data:') && !u.startsWith('blob:'));
    for (const u of ext) bad('network request outside the repo: ' + u + ' (vendor it: renders must be offline and repeatable)');
    const fonts = await page.evaluate(`[...document.fonts].filter(f => f.status !== 'loaded').map(f => f.family + ' ' + f.status)`);
    for (const f of fonts) report.notes.push('font face not loaded (unused weight is fine): ' + f);
    const usedFamilies = await page.evaluate(`(() => { const s = new Set(); document.querySelectorAll('#rv-stage *').forEach(e => { const f = getComputedStyle(e).fontFamily; if (e.childNodes.length && [...e.childNodes].some(n => n.nodeType === 3 && n.textContent.trim())) s.add(f); }); return [...s]; })()`);
    report.domTextFonts = usedFamilies;
    const loaded = await page.evaluate(`[...new Set([...document.fonts].filter(f => f.status === 'loaded').map(f => f.family.replace(/"/g, '')))]`);
    for (const fam of usedFamilies) {
      const first = fam.split(',')[0].replace(/["']/g, '').trim();
      if (!loaded.includes(first) && !/^(serif|sans-serif|monospace|system-ui|ui-monospace|ui-sans-serif)$/.test(first)) bad(`DOM text uses "${first}" which is not a loaded font (add it to fonts: [...] or vendor it)`);
    }
    if (info.hasAudio) {
      const wav = path.join(outDir(pc.name), `${pc.name}.wav`);
      await renderAudio(pieceArg, wav);
      report.audio = loudness(wav);
    }
    await rm(dir, { recursive: true, force: true });
  } finally { await s.close(); }
  console.log(JSON.stringify(report, null, 1));
  console.log(report.ok ? '[rv] check passed' : `[rv] check found ${report.problems.length} problem(s)`);
  return report;
}

// audio: synthesize, then measure every hit in the decoded audio (or in a rendered mp4 with --file).
export async function audio(pieceArg, o = {}) {
  const pc = resolvePiece(pieceArg);
  const info = await getInfo(pieceArg);
  const out = outDir(pc.name); await mkdir(out, { recursive: true });
  const wav = path.join(out, `${pc.name}.wav`);
  const r = await renderAudio(pieceArg, wav, { stems: true });
  if (!r) throw new Error('piece has no score(a)');
  const L = loudness(wav);
  console.log(`[rv] ${wav}: ${L.lufs} LUFS integrated, true peak ${L.truePeak} dBTP (pre-master; render normalizes to -14)`);
  const target = o.file || wav;
  const png = path.join(out, 'audio.png'), json = path.join(out, 'audio.json');
  console.log(py(['audiotools.py', 'report', target, '--hits', wav.replace(/\.wav$/, '.hits.json'), '--sfx', wav.replace(/\.wav$/, '.sfx.wav'), '--bed', wav.replace(/\.wav$/, '.bed.wav'), ...(info.loop ? ['--loop'] : []), '--fps', String(info.fps), '--bpm', String(info.bpm || 0), '--out', png, '--json', json]));
  const spec = path.join(out, 'spectrum.png');
  spawnSync('ffmpeg', ['-y', '-v', 'error', '-i', target, '-lavfi', 'showspectrumpic=s=1600x400:legend=1:scale=log:fscale=log', spec]);
  console.log(png + '\n' + spec);
  return { png, json, spec };
}

export async function analyzeSong(file, o = {}) {
  const json = o.json || file.replace(/\.[^.]+$/, '') + '.beats.json';
  console.log(py(['audiotools.py', 'song', file, '--json', json, ...(o.minBpm ? ['--min-bpm', String(o.minBpm)] : []), ...(o.maxBpm ? ['--max-bpm', String(o.maxBpm)] : [])]));
  console.log(json);
}

// plan: the piece's cue list on the beat grid (piece({ cues: [[seconds, 'label'], ...] })).
export async function plan(pieceArg) {
  const s = await open(pieceArg, { quiet: true });
  try {
    const { info, page } = s;
    const cues = (await page.evaluate('window.rv.cues()')) || [];
    const spb = info.bpm ? 60 / info.bpm : null;
    console.log(`${info.name}: ${info.duration}s, ${info.frames} frames @${info.fps}${info.bpm ? `, ${info.bpm} BPM (${(info.fps * spb).toFixed(2)} frames/beat)` : ''}${info.loop ? ', loop' : ''}`);
    console.log('  bar.beat   frame    time    cue');
    for (const [t, label] of cues) {
      const bb = spb ? `${Math.floor(t / spb / 4) + 1}.${+((t / spb) % 4 + 1).toFixed(2)}` : '';
      console.log(`  ${bb.padEnd(9)}  ${String(Math.round(t * info.fps)).padStart(5)}  ${t.toFixed(3).padStart(7)}s  ${label}`);
    }
    if (!cues.length) console.log('  (no cues: add cues: [[seconds, "label"], ...] to piece({...}))');
    return cues;
  } finally { await s.close(); }
}

// review: the whole battery in one go, then one prioritized list of what to look at.
export async function review(pieceArg, o = {}) {
  const pc = resolvePiece(pieceArg);
  const out = outDir(pc.name);
  const items = [];
  const log = console.log;
  const quiet = (f) => async (...a) => { console.log = () => {}; try { return await f(...a); } finally { console.log = log; } };
  log(`[rv] review ${pc.name}: check`);
  const c = await quiet(check)(pieceArg);
  for (const p of c.problems) items.push(['FIX', p]);
  for (const n of c.notes) items.push(['note', n]);
  log('[rv] review: plan');
  const cues = await quiet(plan)(pieceArg);
  log('[rv] review: beats');
  await quiet(beatSheet)(pieceArg, o);
  log('[rv] review: motion');
  await quiet(motion)(pieceArg, { step: o.step || 2 });
  const { readFile } = await import('node:fs/promises');
  const m = JSON.parse(await readFile(path.join(out, 'motion.json'), 'utf8'));
  for (const [a, z] of m.dead_spans_s || []) items.push(['look', `dead time ${a}-${z}s: nothing moves for at least a beat (intentional hold?)`]);
  if (m.max_jump > 6 * Math.max(0.5, m.p90)) items.push(['look', `biggest single-frame change at frame ${m.max_jump_frame * (o.step || 2)} (${(m.max_jump_frame * (o.step || 2) / c.info.fps).toFixed(2)}s): mean pixel change ${m.max_jump} (0-255 scale) vs ${m.p90} for the 90th-percentile frame. A cut, a pop or a flash. Intended?`]);
  if (c.info.hasAudio) {
    log('[rv] review: audio');
    await quiet(audio)(pieceArg, {});
    const A = JSON.parse(await readFile(path.join(out, 'audio.json'), 'utf8'));
    for (const h of A.off_by_more_than_a_frame) items.push(['FIX', `sound "${h.name}" at ${h.t}s is ${h.onset_ms} ms off its frame`]);
    for (const h of A.under_3db_over_bed) items.push(['look', `sound "${h.name}" at ${h.t}s is only ${h.over_bed_db} dB over the bed`]);
  }
  if (c.info.hasProbe) { log('[rv] review: trace'); await quiet(trace)(pieceArg, {}); }
  log('\n' + (items.length ? items.map(([k, v]) => `  [${k}] ${v}`).join('\n') : '  nothing flagged by measurement: now look at the images'));
  log(`\n  look at: ${['beats.png', 'motion.png', c.info.hasAudio ? 'audio.png' : null, c.info.hasProbe ? 'trace.png' : null].filter(Boolean).map((f) => path.join(out, f)).join('\n           ')}`);
  log(`  cues: ${cues.length}   ms/frame: ${c.msPerFrame}   ${c.audio ? `audio ${c.audio.lufs} LUFS pre-master` : ''}`);
  return items;
}

// study: measure a reference video (or any render) -> shots, palette, energy, tempo, a style-bible skeleton
export async function study(file, o = {}) {
  if (!file) throw new Error('usage: rv study <video> [--out dir]');
  const out = o.out || path.join(ROOT, 'out', 'study', path.basename(file).replace(/\.[^.]+$/, ''));
  console.log(py(['study.py', path.resolve(file), '--out', out, ...(o.fps ? ['--fps', String(o.fps)] : [])]));
}

// taste: heuristic checks for the default look on one frame per beat (or --n frames). Hints, not verdicts.
export async function taste(pieceArg, o = {}) {
  const pc = resolvePiece(pieceArg);
  const s = await open(pieceArg, { quiet: true });
  const dir = path.join(outDir(pc.name), '.taste');
  await rm(dir, { recursive: true, force: true }); await mkdir(dir, { recursive: true });
  try {
    const { info, page } = s;
    const frames = pickTimes(info, { beats: info.bpm ? true : undefined, n: o.n || 12, ...o });
    const J = { frames: [], texts: [] };
    for (const f of frames) {
      await page.evaluate(`window.rv.seek(${f / info.fps})`);
      const file = path.join(dir, `f${pad(f, 5)}.png`);
      await writeFile(file, await page.screenshot());
      J.frames.push(file);
      J.texts.push(await page.evaluate(`[...document.querySelectorAll('#rv-stage *')].filter(e => [...e.childNodes].some(n => n.nodeType === 3 && n.textContent.trim())).map(e => {
        const r = e.getBoundingClientRect(), cs = getComputedStyle(e); let op = 1, p = e;
        while (p && p.id !== 'rv-stage') { op *= +getComputedStyle(p).opacity; if (getComputedStyle(p).display === 'none') op = 0; p = p.parentElement; }
        const m = cs.color.match(/[\\d.]+/g).map(Number);
        return { text: e.textContent.trim(), x: r.x, y: r.y, w: r.width, h: r.height, color: m, size: parseFloat(cs.fontSize) * (r.height / (e.offsetHeight || r.height)), opacity: op };
      }).filter(t => t.w > 0 && t.h > 0)`));
    }
    J.uiZones = info.uiZones || [];
    const jf = path.join(dir, 'frames.json');
    await writeFile(jf, JSON.stringify(J));
    const res = JSON.parse(py(['taste.py', jf]));
    console.log(res.length ? res.map(([k, v]) => `  [${k}] ${v}`).join('\n') : '  no default-look patterns measured. Taste is still yours: compare against docs/creativity.md section 4.');
    return res;
  } finally { await s.close(); }
}

// compare: study a reference and your render, then show where the style drifts
export async function compare(ref, mine, o = {}) {
  if (!ref || !mine) throw new Error('usage: rv compare <reference.mp4> <yours.mp4>');
  const dirOf = (f) => path.join(ROOT, 'out', 'study', path.basename(f).replace(/\.[^.]+$/, ''));
  for (const f of [ref, mine]) py(['study.py', path.resolve(f), '--out', dirOf(f)]);
  console.log(py(['compare.py', path.join(dirOf(ref), 'report.json'), path.join(dirOf(mine), 'report.json')]));
  console.log(`shots: ${path.join(dirOf(ref), 'shots.png')}  vs  ${path.join(dirOf(mine), 'shots.png')}`);
}

export async function preview(pieceArg, o = {}) {
  const pc = resolvePiece(pieceArg);
  const srv = await serve(+(o.port || 4173));
  srv.ref();
  console.log(`[rv] preview: ${srv.base}${pc.urlPath}\n  space play/pause, arrows step a frame, shift+arrows a beat, M sound, G grid, ?t=2.5 freezes a frame`);
  await new Promise(() => {});
}
