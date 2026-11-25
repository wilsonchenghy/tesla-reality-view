// render.mjs: frames -> video. Parallel workers (each its own Chromium), subframe motion blur blended in
// linear light, supersampling, audio synthesized by the piece and muxed with loudness normalization.
import { mkdir, writeFile, rm, readdir, readFile } from 'node:fs/promises';
import { existsSync } from 'node:fs';
import { spawn, spawnSync } from 'node:child_process';
import os from 'node:os';
import path from 'node:path';
import { open, outDir, resolvePiece } from './session.mjs';
import { launch } from './browser.mjs';
import { ROOT } from './session.mjs';

const pyOut = (args) => {
  const r = spawnSync('python3', [path.join(ROOT, 'tools', args[0]), ...args.slice(1)], { encoding: 'utf8', maxBuffer: 1 << 28 });
  if (r.status !== 0) throw new Error(r.stderr || r.stdout);
  return r.stdout.trim();
};

export const pad = (n, w = 6) => String(n).padStart(w, '0');

export function ff(args, { quiet = true } = {}) {
  return new Promise((res, rej) => {
    const p = spawn('ffmpeg', ['-y', '-hide_banner', '-loglevel', quiet ? 'error' : 'info', ...args], { stdio: ['ignore', 'inherit', 'pipe'] });
    let err = '';
    p.stderr.on('data', (d) => (err += d));
    p.on('exit', (c) => (c === 0 ? res(err) : rej(new Error('ffmpeg failed: ' + err.slice(-3000)))));
  });
}

// Time of subframe j of frame i, spread over `shutter` of the frame interval. The shutter OPENS at the
// frame time (phase 'start', the default): a hard cut on a beat is then clean on that beat's frame instead
// of double-exposing old and new state. 'center' straddles the frame time (film-camera convention).
let PHASE = 'start';
export const setShutterPhase = (p) => { PHASE = p === 'center' ? 'center' : 'start'; };
export function subTime(i, j, S, shutter, fps, duration, loop) {
  const off = S > 1 ? (PHASE === 'center' ? ((j + 0.5) / S - 0.5) * shutter : (j / S) * shutter) : 0;
  let t = (i + off) / fps;
  if (loop) t = ((t % duration) + duration) % duration;
  else t = Math.max(0, Math.min(duration, t));
  return t;
}

// Capture a list of jobs [{t, file}] with W parallel browsers. Returns info.
export async function capture(pieceArg, jobs, { workers = 0, scale = 1, gpu = false, onProgress = null, query = '' } = {}) {
  const W = Math.max(1, Math.min(workers || Math.min(4, os.cpus().length), jobs.length));
  let next = 0, done = 0, info = null, rawOk = null;   // rawOk: does this piece support raw readback?
  const warnings = new Set(), errors = new Set();
  const t0 = Date.now();
  await Promise.all(Array.from({ length: W }, async (_, w) => {
    const s = await open(pieceArg, { scale, gpu, quiet: w > 0, query });
    info ||= s.info;
    try {
      while (next < jobs.length) {
        const job = jobs[next++];
        await s.page.evaluate(`window.rv.seek(${job.t}${job.ft != null ? ', ' + job.ft : ''})`);
        // fastest first: raw pixels from a single full-frame canvas (no encoding at all), written as .rgb
        // with a 12-byte header; else lossless WebP (pixel-identical to PNG, 2-3x cheaper); PNG for stills
        let got = false;
        if (job.file.endsWith('.webp') && rawOk !== false) {
          const px = await s.page.evaluate('window.rv.pixels ? window.rv.pixels() : null');
          if (px) {
            const k = px.indexOf(';'), [w, h, flip] = px.slice(0, k).split(',').map(Number);
            const head = Buffer.alloc(12); head.writeUInt32LE(w, 0); head.writeUInt32LE(h, 4); head.writeUInt32LE(flip, 8);
            await writeFile(job.file.replace(/\.webp$/, '.rgb'), Buffer.concat([head, Buffer.from(px.slice(k + 1), 'base64')]));
            job.file = job.file.replace(/\.webp$/, '.rgb'); rawOk = true; got = true;
          } else if (rawOk === null) rawOk = false;
        }
        if (!got) {
          const img = await s.page.screenshot(job.file.endsWith('.webp') ? { format: 'webp', quality: 100 } : {});
          await writeFile(job.file, img);
        }
        done++;
        if (onProgress) onProgress(done, jobs.length, (Date.now() - t0) / 1000);
      }
      for (const x of await s.page.evaluate('window.rv.warnings()')) warnings.add(x);
      for (const e of s.page.errors) errors.add(e);
    } finally { await s.close(); }
  }));
  return { info, warnings: [...warnings], errors: [...errors], seconds: (Date.now() - t0) / 1000 };
}

export async function getInfo(pieceArg) {
  const s = await open(pieceArg, { quiet: true });
  try { return s.info; } finally { await s.close(); }
}

// Render audio in its own browser session (keeps memory of long frame captures separate).
export async function renderAudio(pieceArg, dest, { stems = false } = {}) {
  const s = await open(pieceArg, { quiet: true });
  try {
    const r = await s.page.evaluate('window.rv.audioWav()');
    if (!r) return null;
    await writeFile(dest, Buffer.from(r.b64, 'base64'));
    await writeFile(dest.replace(/\.wav$/, '.hits.json'), JSON.stringify(r.hits, null, 1));
    if (stems) for (const stem of ['sfx', 'bed']) {
      const x = await s.page.evaluate(`window.rv.audioWav('${stem}')`);
      await writeFile(dest.replace(/\.wav$/, `.${stem}.wav`), Buffer.from(x.b64, 'base64'));
    }
    return { wav: dest, hits: r.hits };
  } finally { await s.close(); }
}

// Integrated loudness (LUFS) and true peak (dBTP) of an audio file.
export function loudness(file) {
  const r = spawnSync('ffmpeg', ['-hide_banner', '-nostats', '-i', file, '-af', 'ebur128=peak=true', '-f', 'null', '-'], { encoding: 'utf8' });
  const s = r.stderr || '';
  const I = +(s.match(/I:\s+(-?[\d.]+) LUFS/g)?.pop()?.match(/-?[\d.]+/)?.[0] ?? NaN);
  const TP = +(s.match(/Peak:\s+(-?[\d.]+) dBFS/g)?.pop()?.match(/-?[\d.]+/)?.[0] ?? NaN);
  return { lufs: I, truePeak: TP };
}

const progress = (label) => {
  let last = -1e9;
  return (d, n, s) => {
    const eta = d ? ((n - d) * s) / d : 0;
    const etaS = d / n < 0.1 && s < 20 ? 'eta ...' : `eta ${eta < 90 ? eta.toFixed(0) + 's' : (eta / 60).toFixed(1) + 'min'}`;   // early ETAs include browser startup
    const line = `${label} ${d}/${n}  ${(d / s).toFixed(1)}/s  ${etaS}`;
    if (process.stdout.isTTY) { if (d === n || d % 8 === 0) process.stdout.write(`\r${line}   ${d === n ? '\n' : ''}`); return; }
    if (s - last >= 15 || d === n) { last = s; console.log(line); }
  };
};

export async function render(pieceArg, o = {}) {
  const pc = resolvePiece(pieceArg);
  const info = await getInfo(pieceArg);
  // the piece's own render defaults (e.g. { sub: 1 } for work animated on twos), under the CLI flags
  if (info.render) { o = { ...info.render, ...o }; console.log('[rv] piece render defaults:', JSON.stringify(info.render)); }
  // --draft: a fast pacing check (half size, 30 fps, no blur), written as <name>-draft.mp4
  if (o.draft) o = { sub: 1, adaptive: false, fps: Math.min(30, info.fps), scale: 0.5, outScale: 0.5, crf: 26, preset: 'veryfast', out: o.out || `${pc.name}-draft`, ...o, draft: true };
  const outW = Math.round(info.width * +(o.outScale || 1) / 2) * 2, outH = Math.round(info.height * +(o.outScale || 1) / 2) * 2;
  // --patch a-b: re-render only that time range into the frame cache of the last full render, re-encode all
  const cacheDir = path.join(outDir(pc.name), '.cache');
  let patch = null;
  if (o.patch) {
    const [a, z] = String(o.patch).split('-').map(Number);
    let meta = null;
    try { meta = JSON.parse(await readFile(path.join(cacheDir, 'meta.json'), 'utf8')); } catch {}
    const want = { fps: +(o.fps || info.fps), outW, outH, frames: Math.round(info.duration * +(o.fps || info.fps)) };
    if (!meta || meta.fps !== want.fps || meta.outW !== outW || meta.outH !== outH || meta.frames !== want.frames) throw new Error('--patch needs a full render with the same fps/size first (no frame cache found or it does not match)');
    patch = { a, z, meta };
    o = { ...meta.opts, ...o, from: a, to: z, out: `${pc.name}-patchrange` };
  }
  setShutterPhase(o.shutterPhase);
  const fps = +(o.fps || info.fps), S = Math.max(1, +(o.sub ?? 4)), shutter = +(o.shutter ?? 0.5), scale = +(o.scale ?? 1);
  const from = o.from != null ? Math.round(+o.from * fps) : 0;
  const total = Math.round(info.duration * fps);
  const to = o.to != null ? Math.round(+o.to * fps) : total;
  const out = outDir(pc.name);
  const tmp = path.join(out, '.frames');
  await rm(tmp, { recursive: true, force: true });
  await mkdir(tmp, { recursive: true });
  const name = o.out || (o.from != null || o.to != null ? 'preview' : pc.name);
  const full = from === 0 && to === total && !o.draft;
  console.log(`[rv] ${pc.name}: ${info.width}x${info.height} -> output ${outW}x${outH} @${fps}fps, frames ${from}-${to - 1} of ${total}, ${S} subframes (shutter ${shutter * 360}°), scale ${scale}`);

  // audio first, in its own session
  let audio = null;
  const wavPath = path.join(out, `${pc.name}.wav`);
  if (info.hasAudio && o.audio !== false && !o.noAudio) {   // --no-audio parses as audio=false
    if (o.reuseAudio && existsSync(wavPath)) audio = { wav: wavPath };
    else { process.stdout.write('[rv] synthesizing audio... '); audio = await renderAudio(pieceArg, wavPath); const L = loudness(wavPath); console.log(`${L.lufs} LUFS, peak ${L.truePeak} dBTP (pre-master)`); }
  }

  // pass 1: S subframes per frame
  const jobs = [], manifest = [];
  for (let i = from; i < to; i++) {
    const files = [];
    for (let j = 0; j < S; j++) { const file = path.join(tmp, `s${pad(i, 6)}_${pad(j, 2)}.webp`); jobs.push({ t: subTime(i, j, S, shutter, fps, info.duration, info.loop), ft: (i % total) / fps, file }); files.push(file); }
    manifest.push(files);
  }
  const query = o.query ? '&' + String(o.query).split(',').filter(Boolean).join('&') : '';   // --query a=1,b: debug/plate views
  const cap = await capture(pieceArg, jobs, { workers: +o.workers || 0, scale, gpu: o.gpu, onProgress: progress('[rv] capture'), query });
  // pass 2 (adaptive blur): frames whose shutter smears far get re-captured with more subframes
  const subMax = Math.max(S, +(o.subMax ?? 16));
  if (S > 1 && o.adaptive !== false && subMax > S) {
    const man = path.join(tmp, 'manifest.json');
    await writeFile(man, JSON.stringify(manifest));
    const spreads = JSON.parse(pyOut(['blend.py', 'analyze', man]));
    // a frame whose first and last subframes differ in many pixels is moving fast: more subframes
    // (by pixel count, not share: a small object moving fast steps visibly too). Fastest first, within budget.
    const budget = Math.round(jobs.length * +(o.refineBudget ?? 1));
    const want = spreads.map((raw, k) => raw / (scale * scale)).map((px, k) => ({ k, px, S2: px > 6000 ? subMax : px > 1500 ? Math.min(subMax, S * 2) : S })).filter((x) => x.S2 > S).sort((x, y) => y.px - x.px);
    const extra = [];
    let used = 0;
    for (const w of want) {
      if (used + w.S2 > budget) continue;
      used += w.S2;
      const i = from + w.k, files = [];
      for (let j = 0; j < w.S2; j++) { const file = path.join(tmp, `r${pad(i, 6)}_${pad(j, 2)}.webp`); extra.push({ t: subTime(i, j, w.S2, shutter, fps, info.duration, info.loop), ft: (i % total) / fps, file }); files.push(file); }
      manifest[w.k] = files;
    }
    if (extra.length) {
      const nf = new Set(extra.map((e) => e.file.replace(/_\d+\.\w+$/, ''))).size;
      console.log(`[rv] adaptive blur: ${nf} fast frame(s) re-captured with up to ${subMax} subframes`);
      const c2 = await capture(pieceArg, extra, { workers: +o.workers || 0, scale, gpu: o.gpu, onProgress: progress('[rv] refine') });
      cap.seconds += c2.seconds;
    }
  }
  if (cap.warnings.length) console.log('[rv] determinism warnings:\n  ' + cap.warnings.join('\n  '));
  if (cap.errors.length) console.log('[rv] page errors:\n  ' + cap.errors.join('\n  '));
  const manPath = path.join(tmp, 'manifest.json');
  await writeFile(manPath, JSON.stringify(manifest));

  // blend in linear light (numpy, verified against the reference math) and stream raw frames into ffmpeg
  const mp4 = path.join(out, `${name}.mp4`);
  const startT = from / fps, dur = (to - from) / fps;
  const aArgs = audio ? ['-ss', String(startT), '-t', String(dur), '-i', audio.wav] : [];
  let af = [];
  if (audio) {
    const L = loudness(audio.wav);
    const gain = isFinite(L.lufs) ? Math.max(-30, Math.min(20, (o.lufs ?? -14) - L.lufs)) : 0;
    // AAC lifts inter-sample peaks ~1 dB: limit to -2.2 dBFS so the decoded file stays under -1 dBTP
    af = ['-af', `volume=${gain.toFixed(2)}dB,alimiter=limit=${10 ** (-2.2 / 20)}:attack=1:release=50:level=disabled`, '-c:a', 'aac', '-b:a', '256k', '-ar', '48000'];
  }
  process.stdout.write('[rv] blending + encoding... ');
  await new Promise((res, rej) => {
    const keepCache = full || patch;
    const blender = spawn('python3', [path.join(ROOT, 'tools', 'blend.py'), 'stream', manPath, String(outW), String(outH), ...(keepCache ? [cacheDir, String(from)] : [])], { stdio: ['ignore', 'pipe', 'inherit'] });
    const enc = spawn('ffmpeg', ['-y', '-hide_banner', '-loglevel', 'error', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', `${outW}x${outH}`, '-r', String(fps), '-i', '-', ...aArgs,
      '-vf', 'scale=out_color_matrix=bt709:out_range=tv:flags=accurate_rnd+full_chroma_int,format=yuv420p',
      '-c:v', 'libx264', '-preset', o.preset || 'slow', '-crf', String(o.crf ?? 16), '-profile:v', 'high', '-pix_fmt', 'yuv420p',
      '-colorspace', 'bt709', '-color_primaries', 'bt709', '-color_trc', 'bt709', '-color_range', 'tv',
      ...af, '-movflags', '+faststart', '-shortest', mp4], { stdio: ['pipe', 'inherit', 'inherit'] });
    blender.stdout.pipe(enc.stdin);
    blender.on('exit', (c) => { if (c !== 0) rej(new Error('blend.py failed')); });
    enc.on('exit', (c) => (c === 0 ? res() : rej(new Error('ffmpeg encode failed'))));
  });
  if (patch) {
    // splice: the cache now holds the new range; encode the whole piece from it (audio re-rendered above)
    const fullMp4 = path.join(out, `${pc.name}.mp4`);
    const fa = audio ? ['-i', audio.wav] : [];
    await ff(['-framerate', String(fps), '-i', path.join(cacheDir, '%05d.png'), ...fa,
      '-vf', 'scale=out_color_matrix=bt709:out_range=tv:flags=accurate_rnd+full_chroma_int,format=yuv420p',
      '-c:v', 'libx264', '-preset', o.preset || 'slow', '-crf', String(o.crf ?? 16), '-profile:v', 'high', '-pix_fmt', 'yuv420p',
      '-colorspace', 'bt709', '-color_primaries', 'bt709', '-color_trc', 'bt709', '-color_range', 'tv', ...af, '-movflags', '+faststart', '-shortest', fullMp4]);
    await rm(mp4, { force: true });
    console.log(`[rv] patched ${patch.a}-${patch.z}s into ${fullMp4}`);
  } else console.log(mp4);
  if (full) await writeFile(path.join(cacheDir, 'meta.json'), JSON.stringify({ fps, outW, outH, frames: total, opts: { sub: S, shutter, scale, subMax: o.subMax, refineBudget: o.refineBudget, crf: o.crf, lufs: o.lufs } }));

  if (o.frames) {
    // keep the blended frames as PNGs (for stills, onion skins, motion analysis)
    const fdir = path.join(out, 'frames');
    await rm(fdir, { recursive: true, force: true });
    pyOut(['blend.py', 'pngs', manPath, fdir, String(from), `${outW}x${outH}`]);
  }
  if (o.gif) await toGif(mp4, path.join(out, `${name}.gif`), { width: +o.gifWidth || Math.min(info.width, 960), fps: +o.gifFps || 30 });
  if (!o.keep) await rm(tmp, { recursive: true, force: true });
  const meta = { piece: pc.name, file: mp4, fps, subframes: S, subMax, shutter, scale, from, to, seconds: cap.seconds, warnings: cap.warnings, errors: cap.errors, audio: audio ? loudness(mp4) : null, when: new Date().toISOString() };
  await writeFile(path.join(out, `${name}.render.json`), JSON.stringify(meta, null, 1));
  if (audio) console.log(`[rv] master: ${meta.audio.lufs} LUFS, true peak ${meta.audio.truePeak} dBTP`);
  console.log(`[rv] done in ${cap.seconds.toFixed(1)}s capture`);
  return meta;
}

// GIF for X / docs: one palette for the whole clip, bayer dither. Shrinks until it fits `maxMB` (X: 15 MB).
export async function toGif(mp4, gif, { width = 960, fps = 30, maxMB = 15 } = {}) {
  const { statSync } = await import('node:fs');
  for (let k = 0; k < 5; k++) {
    await ff(['-i', mp4, '-vf', `fps=${fps},scale=${width}:-1:flags=lanczos,split[a][b];[a]palettegen=stats_mode=diff:max_colors=256[p];[b][p]paletteuse=dither=bayer:bayer_scale=4:diff_mode=rectangle`, '-loop', '0', gif]);
    const mb = statSync(gif).size / 1e6;
    if (mb <= maxMB) { console.log(`${gif} (${mb.toFixed(1)} MB, ${width}px, ${fps} fps)`); return; }
    console.log(`[rv] gif ${mb.toFixed(1)} MB > ${maxMB} MB at ${width}px/${fps}fps, shrinking`);
    // GIF size scales ~ with pixels x frames: jump straight to an estimate (with margin) instead of creeping
    const f = (maxMB / mb) * 0.85;
    if (fps > 24 && f > 0.6) fps = 24;
    else width = Math.max(240, Math.round((width * Math.sqrt(Math.min(0.8, f * (fps > 24 ? 30 / 24 : 1)))) / 2) * 2);
    if (fps > 24) fps = 24;
  }
  console.log(gif + ' (still over the size limit)');
}

// share: re-encode to fit a size budget (chat uploads, platform caps) with two-pass x264 at the exact bitrate.
export async function share(mp4, { maxMb = 25, out = null } = {}) {
  const dur = +spawnSync('ffprobe', ['-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', mp4], { encoding: 'utf8' }).stdout.trim();
  const hasAudio = spawnSync('ffprobe', ['-v', 'error', '-select_streams', 'a', '-show_entries', 'stream=index', '-of', 'csv=p=0', mp4], { encoding: 'utf8' }).stdout.trim().length > 0;
  const aK = hasAudio ? 160 : 0;
  const vK = Math.floor((+maxMb * 8e3 * 0.94) / dur - aK);   // kbit/s, 6% container margin
  if (vK < 300) throw new Error(`budget too small: ${vK} kbit/s video for ${dur}s`);
  out ||= mp4.replace(/\.mp4$/, `-${maxMb}mb.mp4`);
  const passlog = path.join(os.tmpdir(), `rv-share-${process.pid}`);
  const common = ['-i', mp4, '-c:v', 'libx264', '-preset', 'slow', '-b:v', `${vK}k`, '-maxrate', `${Math.round(vK * 1.5)}k`, '-bufsize', `${vK * 2}k`, '-pix_fmt', 'yuv420p', '-passlogfile', passlog];
  await ff([...common, '-pass', '1', '-an', '-f', 'mp4', os.devNull]);
  await ff([...common, '-pass', '2', ...(hasAudio ? ['-c:a', 'aac', '-b:a', `${aK}k`] : ['-an']), '-movflags', '+faststart', out]);
  const { statSync } = await import('node:fs');
  console.log(`${out} (${(statSync(out).size / 1e6).toFixed(1)} MB, ${vK} kbit/s video)`);
  return out;
}
