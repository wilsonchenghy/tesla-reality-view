// audio.js: a synthesizer kit for scoring pieces offline (OfflineAudioContext), sample-locked to picture.
//
//   score(a) {
//     a.kick(a.beat(0));                       // times are piece seconds; a.beat/bar from bpm
//     a.click(cue.press + a.frame);            // UI hit: land 1 frame after its picture
//     a.pad(0, 8, ['D3','F#3','A3'], { gain: 0.2 });
//   }
//
// Every hit is recorded in a.hits with the time its peak is meant to land, so `rv audio` can
// measure the decoded file and report how far each one is off.
// All instruments are plain Web Audio graphs. Build your own with a.ctx / a.out / a.at(t) when the
// piece needs a sound the kit does not have: the kit is a starting palette, not a limit.

const NOTE = { C: 0, D: 2, E: 4, F: 5, G: 7, A: 9, B: 11 };
export function hz(n) {
  if (typeof n === 'number') return n;
  const m = /^([A-G])([#b]?)(-?\d)$/.exec(n);
  if (!m) throw new Error('bad note ' + n);
  const semi = NOTE[m[1]] + (m[2] === '#' ? 1 : m[2] === 'b' ? -1 : 0) + (+m[3] + 1) * 12;
  return 440 * 2 ** ((semi - 69) / 12);
}
export const chord = (root, kind = 'maj', octave = 3) => {
  const r = typeof root === 'string' && !/\d/.test(root) ? hz(root + octave) : hz(root);
  const iv = { maj: [0, 4, 7], min: [0, 3, 7], maj7: [0, 4, 7, 11], min7: [0, 3, 7, 10], sus2: [0, 2, 7], sus4: [0, 5, 7], add9: [0, 4, 7, 14], dom7: [0, 4, 7, 10], min9: [0, 3, 7, 10, 14] }[kind];
  return iv.map((s) => r * 2 ** (s / 12));
};

export function makeKit(ctx, { offset = 1, fps = 60, bpm = null, duration = 6, loop = true, mute = [] } = {}) {
  const sr = ctx.sampleRate;
  const hits = [];
  // master: buses -> master -> highpass -> destination. Dynamics run offline in post() (lookahead limiter
  // that does not delay the signal). A DynamicsCompressorNode would shift every hit ~6 ms late.
  const master = ctx.createGain(); master.gain.value = 0.9;
  const hp = ctx.createBiquadFilter(); hp.type = 'highpass'; hp.frequency.value = 28;
  master.connect(hp).connect(ctx.destination);

  const bus = (g) => { const b = ctx.createGain(); b.gain.value = g; b.connect(master); return b; };
  const music = bus(0.8), sfx = bus(1.0), amb = bus(0.6);
  // reverb: generated decaying stereo noise IR
  const reverb = ctx.createConvolver();
  reverb.buffer = (() => {
    const len = Math.floor(sr * 2.6), b = ctx.createBuffer(2, len, sr);
    let s = 12345;
    for (let c = 0; c < 2; c++) { const d = b.getChannelData(c); for (let i = 0; i < len; i++) { s = (s * 1664525 + 1013904223) >>> 0; d[i] = ((s / 4294967296) * 2 - 1) * Math.exp(-i / (sr * 0.55)) * (i < sr * 0.01 ? i / (sr * 0.01) : 1); } }
    return b;
  })();
  const verbReturn = ctx.createGain(); verbReturn.gain.value = 0.35;
  const verbHP = ctx.createBiquadFilter(); verbHP.type = 'highpass'; verbHP.frequency.value = 250;
  reverb.connect(verbHP).connect(verbReturn).connect(master);
  const send = (node, amount) => { if (amount > 0) { const g = ctx.createGain(); g.gain.value = amount; node.connect(g).connect(reverb); } };

  // seeded noise buffer (white), shared
  const noiseBuf = (() => { const len = sr * 2, b = ctx.createBuffer(1, len, sr), d = b.getChannelData(0); let s = 987654321; for (let i = 0; i < len; i++) { s ^= s << 13; s ^= s >>> 17; s ^= s << 5; d[i] = ((s >>> 0) / 4294967296) * 2 - 1; } return b; })();

  const at = (t) => t + offset;                // piece time -> context time
  const pan = (node, p = 0) => { if (!p) return node; const pn = ctx.createStereoPanner(); pn.pan.value = p; node.connect(pn); return pn; };
  // stems: a muted bus (and its reverb sends) is simply not connected
  const busName = (b) => (b === music ? 'music' : b === amb ? 'amb' : 'sfx');
  const out = (node, { bus: b = sfx, pan: p = 0, verb = 0 } = {}) => { const n = pan(node, p); if (mute.includes(busName(b))) return n; n.connect(b); send(n, verb); return n; };
  const env = (param, t, a, peak, d, floor = 0.0001) => {
    param.setValueAtTime(floor, t);
    param.linearRampToValueAtTime(peak, t + a);
    param.setTargetAtTime(floor, t + a, d / 3);
  };
  const noise = (t, dur) => { const s = ctx.createBufferSource(); s.buffer = noiseBuf; s.loop = true; s.start(t, (t * 7.31) % 1.5); s.stop(t + dur + 0.05); return s; };
  const osc = (type, f, t, dur) => { const o = ctx.createOscillator(); o.type = type; o.frequency.setValueAtTime(f, t); o.start(t); o.stop(t + dur + 0.05); return o; };
  // A tonal hit whose first peak lands exactly on time t: a buffer built in code, cosine phase, no waveshaper.
  // partials: [[freqHz, amp, decaySec, phase?]], pitch glide via `glide` (ratio at start -> 1).
  const tonal = (t, partials, { attack = 0.0005, glide = 1, glideTime = 0.03, len = 0.6, gain = 1, ...o } = {}) => {
    const n = Math.ceil(len * sr), b = ctx.createBuffer(1, n, sr), d = b.getChannelData(0);
    const preN = Math.round(attack * sr);
    for (const [f, amp, dec, ph = 0] of partials) {
      let phase = ph;
      for (let i = 0; i < n; i++) {
        const tt = (i - preN) / sr;
        const g = tt < 0 ? 0.5 - 0.5 * Math.cos(Math.PI * (i / Math.max(1, preN))) : Math.exp(-tt / dec);
        const ff = f * (glide === 1 ? 1 : 1 + (glide - 1) * Math.exp(-Math.max(0, tt) / glideTime));
        d[i] += amp * g * Math.cos(phase);
        phase += (2 * Math.PI * ff) / sr;
      }
    }
    const s = ctx.createBufferSource(); s.buffer = b;
    const g = ctx.createGain(); g.gain.value = gain;
    s.connect(g); s.start(Math.max(0, at(t) - attack));
    return out(g, o);
  };
  // a hit records when its peak is meant to land; `early` (s) = intentional pre-onset (flams, swells)
  const mark = (name, t, extra = {}) => hits.push({ name, t, ...extra });

  const kit = {
    ctx, sr, fps, bpm, duration, loop, hits, music, sfx, amb, master, reverb,
    frame: 1 / fps,
    at, out, env, noise, osc, tonal, mark, send,
    spb: bpm ? 60 / bpm : 0.5,
    beat: (n) => n * (bpm ? 60 / bpm : 0.5),
    bar: (n, b = 0) => (n * 4 + b) * (bpm ? 60 / bpm : 0.5),

    // ---------- drums ----------
    kick(t, { gain = 0.9, pitch = 1, len = 0.42, click = 0.25, ...o } = {}) {
      mark('kick', t, { bed: true });
      tonal(t, [[52 * pitch, 1, len * 0.55], [104 * pitch, 0.18, 0.06]], { glide: 3.2, glideTime: 0.028, len: len + 0.1, gain, bus: o.bus || music, ...o });
      if (click) { const n = noise(at(t), 0.02); const f = ctx.createBiquadFilter(); f.type = 'highpass'; f.frequency.value = 3000; const g = ctx.createGain(); env(g.gain, at(t), 0.0005, click * gain, 0.012); n.connect(f).connect(g); out(g, { bus: o.bus || music }); }
    },
    snare(t, { gain = 0.5, tone = 200, verb = 0.2, ...o } = {}) {
      mark('snare', t, { bed: true });
      tonal(t, [[tone, 0.6, 0.05], [tone * 1.5, 0.25, 0.04]], { gain, len: 0.25, bus: music, verb, ...o });
      const n = noise(at(t), 0.25), f = ctx.createBiquadFilter(); f.type = 'bandpass'; f.frequency.value = 2200; f.Q.value = 0.8;
      const g = ctx.createGain(); env(g.gain, at(t), 0.001, gain * 0.9, 0.16); n.connect(f).connect(g); out(g, { bus: music, verb, ...o });
    },
    clap(t, { gain = 0.45, verb = 0.3, ...o } = {}) {
      mark('clap', t, { bed: true, early: 0.03 });
      const f = ctx.createBiquadFilter(); f.type = 'bandpass'; f.frequency.value = 1400; f.Q.value = 1.2;
      const g = ctx.createGain(); g.gain.value = 0;
      [-0.022, -0.012, -0.004, 0].forEach((dt, i) => { g.gain.setValueAtTime(gain * (i === 3 ? 1 : 0.6), at(t + dt)); g.gain.setTargetAtTime(0.0001, at(t + dt) + 0.002, i === 3 ? 0.05 : 0.004); });
      noise(at(t) - 0.03, 0.4).connect(f).connect(g); out(g, { bus: music, verb, ...o });
    },
    hat(t, { gain = 0.16, open = false, ...o } = {}) {
      mark('hat', t, { bed: true });
      const n = noise(at(t), open ? 0.35 : 0.06), f = ctx.createBiquadFilter(); f.type = 'highpass'; f.frequency.value = 7500;
      const g = ctx.createGain(); env(g.gain, at(t), 0.0008, gain, open ? 0.25 : 0.035); n.connect(f).connect(g); out(g, { bus: music, ...o });
    },
    shaker(t, { gain = 0.08, ...o } = {}) {
      mark('shaker', t, { bed: true, early: 0.02 });
      const n = noise(at(t) - 0.02, 0.12), f = ctx.createBiquadFilter(); f.type = 'bandpass'; f.frequency.value = 6500; f.Q.value = 1.5;
      const g = ctx.createGain(); g.gain.setValueAtTime(0.0001, at(t) - 0.02); g.gain.linearRampToValueAtTime(gain, at(t)); g.gain.setTargetAtTime(0.0001, at(t), 0.025);
      n.connect(f).connect(g); out(g, { bus: music, ...o });
    },

    // ---------- UI foley (short, clean, designed) ----------
    click(t, { gain = 0.5, pitch = 1, ...o } = {}) {
      mark('click', t);
      tonal(t, [[2200 * pitch, 0.5, 0.008], [1250 * pitch, 0.6, 0.018], [380 * pitch, 0.5, 0.03]], { gain, len: 0.12, ...o });
    },
    tick(t, { gain = 0.3, pitch = 1, ...o } = {}) {
      mark('tick', t);
      tonal(t, [[3400 * pitch, 0.6, 0.006], [1700 * pitch, 0.4, 0.01]], { gain, len: 0.06, ...o });
    },
    tock(t, { gain = 0.5, pitch = 1, ...o } = {}) {
      mark('tock', t);
      tonal(t, [[620 * pitch, 0.8, 0.04], [1240 * pitch, 0.25, 0.02], [180 * pitch, 0.4, 0.05]], { gain, len: 0.2, ...o });
    },
    pop(t, { gain = 0.5, pitch = 1, ...o } = {}) {
      mark('pop', t);
      tonal(t, [[480 * pitch, 1, 0.05], [960 * pitch, 0.2, 0.03]], { gain, glide: 0.55, glideTime: 0.025, len: 0.25, ...o });
    },
    bloop(t, { gain = 0.45, note = 'A5', ...o } = {}) {
      mark('bloop', t);
      tonal(t, [[hz(note), 1, 0.09], [hz(note) * 2, 0.12, 0.05]], { gain, glide: 0.6, glideTime: 0.02, len: 0.35, ...o });
    },
    ting(t, { gain = 0.3, note = 'E6', verb = 0.35, ...o } = {}) {
      mark('ting', t);
      const f = hz(note);
      tonal(t, [[f, 0.7, 0.6], [f * 2.756, 0.3, 0.3], [f * 5.404, 0.12, 0.15]], { gain, len: 1.5, verb, ...o });
    },
    bell(t, { gain = 0.3, note = 'C6', verb = 0.4, ...o } = {}) {
      mark('bell', t);
      const f = hz(note);
      tonal(t, [[f, 0.6, 1.2], [f * 2, 0.25, 0.7], [f * 3.01, 0.12, 0.4], [f * 4.17, 0.08, 0.25]], { gain, len: 2.4, verb, ...o });
    },
    thud(t, { gain = 0.7, pitch = 1, ...o } = {}) {
      mark('thud', t);
      tonal(t, [[70 * pitch, 1, 0.12], [140 * pitch, 0.3, 0.05]], { gain, glide: 2, glideTime: 0.02, len: 0.4, ...o });
    },
    key(t, { gain = 0.35, seed = 0, ...o } = {}) {
      mark('key', t);
      const v = 0.85 + ((seed * 0.6180339) % 1) * 0.3;
      tonal(t, [[3900 * v, 0.4, 0.004], [260 * v, 0.6, 0.025], [520 * v, 0.2, 0.015]], { gain, len: 0.1, ...o });
    },
    // whoosh: band-passed noise sweeping across [t0, t1], peaking near `peak` (0..1 of the span)
    whoosh(t0, t1, { gain = 0.25, from = 400, to = 3000, peak = 0.7, q = 1.2, ...o } = {}) {
      const dur = t1 - t0, n = noise(at(t0), dur + 0.1), f = ctx.createBiquadFilter(); f.type = 'bandpass'; f.Q.value = q;
      f.frequency.setValueAtTime(from, at(t0)); f.frequency.exponentialRampToValueAtTime(to, at(t0 + dur * peak)); f.frequency.exponentialRampToValueAtTime(Math.max(60, from * 0.8), at(t1));
      const g = ctx.createGain(); g.gain.setValueAtTime(0.0001, at(t0)); g.gain.exponentialRampToValueAtTime(gain, at(t0 + dur * peak)); g.gain.exponentialRampToValueAtTime(0.0001, at(t1));
      n.connect(f).connect(g); out(g, o);
    },
    riser(t0, t1, { gain = 0.2, from = 300, to = 4000, ...o } = {}) {
      kit.whoosh(t0, t1, { gain, from, to, peak: 0.98, q: 3, ...o });
      const s = osc('sawtooth', from / 2, at(t0), t1 - t0), lp = ctx.createBiquadFilter(); lp.type = 'lowpass'; lp.frequency.value = 1800;
      s.frequency.exponentialRampToValueAtTime(to / 4, at(t1));
      const g = ctx.createGain(); g.gain.setValueAtTime(0.0001, at(t0)); g.gain.exponentialRampToValueAtTime(gain * 0.25, at(t1)); g.gain.linearRampToValueAtTime(0, at(t1) + 0.01);
      s.connect(lp).connect(g); out(g, o);
    },
    // swoosh "zip" up or down, for fast UI travel
    zip(t, { gain = 0.2, dur = 0.12, up = true, ...o } = {}) {
      kit.whoosh(t - dur * 0.8, t + dur * 0.2, { gain, from: up ? 800 : 5000, to: up ? 5000 : 800, peak: 0.8, q: 2, ...o });
    },
    sub(t, { gain = 0.6, note = 'A1', len = 1.2, ...o } = {}) {
      mark('sub', t, { bed: true });
      tonal(t, [[hz(note), 1, len * 0.5]], { gain, glide: 1.6, glideTime: 0.06, len, bus: music, ...o });
    },
    // metallic, inharmonic
    clang(t, { gain = 0.3, base = 310, ...o } = {}) {
      mark('clang', t);
      tonal(t, [1, 1.687, 2.861, 4.32, 7.13].map((r, i) => [base * r, 0.6 / (i + 1), 0.45 / (1 + i * 0.4)]), { gain, len: 1.4, verb: 0.3, ...o });
    },
    // liquid "gloop": falling pitch with wobble
    gloop(t, { gain = 0.5, note = 'D4', wobble = 2.4, ...o } = {}) {
      mark('gloop', t);
      const f = hz(note), n = Math.ceil(0.7 * sr), b = ctx.createBuffer(1, n, sr), d = b.getChannelData(0);
      let ph = 0;
      for (let i = 0; i < n; i++) { const tt = i / sr; const ff = f * (1.8 - 0.8 * (1 - Math.exp(-tt / 0.05))) * (1 + 0.05 * Math.sin(2 * Math.PI * wobble * tt) * Math.exp(-tt / 0.3)); d[i] = Math.cos(ph) * Math.exp(-tt / 0.18) + 0.2 * Math.cos(2 * ph) * Math.exp(-tt / 0.08); ph += (2 * Math.PI * ff) / sr; }
      const s = ctx.createBufferSource(); s.buffer = b; const g = ctx.createGain(); g.gain.value = gain; s.connect(g); s.start(at(t)); out(g, o);
    },

    // ---------- tonal instruments ----------
    // Pad: detuned saws through a slow lowpass. notes: names or Hz.
    pad(t, dur, notes, { gain = 0.12, cutoff = 1200, attack = 0.4, release = 0.8, detune = 9, ...o } = {}) {
      const g = ctx.createGain(); const lp = ctx.createBiquadFilter(); lp.type = 'lowpass'; lp.frequency.value = cutoff; lp.Q.value = 0.4;
      g.gain.setValueAtTime(0.0001, at(t)); g.gain.linearRampToValueAtTime(gain, at(t) + attack); g.gain.setValueAtTime(gain, at(t + dur)); g.gain.setTargetAtTime(0.0001, at(t + dur), release / 3);
      for (const nn of notes) for (const dt of [-detune, 0, detune]) { const s = osc('sawtooth', hz(nn), at(t), dur + release * 2); s.detune.value = dt; s.connect(lp); }
      lp.connect(g); out(g, { bus: music, verb: 0.3, ...o });
    },
    // Pluck: Karplus-Strong in a buffer.
    pluck(t, note, { gain = 0.3, bright = 0.5, decay = 0.996, len = 1.2, ...o } = {}) {
      const f = hz(note), n = Math.ceil(len * sr), b = ctx.createBuffer(1, n, sr), d = b.getChannelData(0);
      const P = Math.max(2, Math.round(sr / f)); const line = new Float32Array(P);
      let s = Math.round(f * 1000) | 1;
      for (let i = 0; i < P; i++) { s ^= s << 13; s ^= s >>> 17; s ^= s << 5; line[i] = ((s >>> 0) / 4294967296) * 2 - 1; }
      for (let i = 0; i < n; i++) {
        const j = i % P, v = line[j], avg = 0.5 * (v + line[(j + 1) % P]);
        d[i] = v * Math.min(1, i / 24);
        line[j] = decay * (bright * 0.35 * v + (1 - bright * 0.35) * avg);
      }
      const src = ctx.createBufferSource(); src.buffer = b; const g = ctx.createGain(); g.gain.value = gain; src.connect(g); src.start(at(t)); out(g, { bus: music, ...o });
      mark('pluck', t, { bed: !o.bus || o.bus === kit.music });
    },
    // Bass: saw + sine sub through an enveloped lowpass.
    bass(t, dur, note, { gain = 0.3, cutoff = 900, ...o } = {}) {
      const f = hz(note), lp = ctx.createBiquadFilter(); lp.type = 'lowpass'; lp.Q.value = 2;
      lp.frequency.setValueAtTime(cutoff * 2.5, at(t)); lp.frequency.setTargetAtTime(cutoff * 0.5, at(t), 0.08);
      const g = ctx.createGain(); g.gain.setValueAtTime(0.0001, at(t)); g.gain.linearRampToValueAtTime(gain, at(t) + 0.005); g.gain.setValueAtTime(gain * 0.8, at(t + dur * 0.8)); g.gain.linearRampToValueAtTime(0.0001, at(t + dur));
      const a = osc('sawtooth', f, at(t), dur), b = osc('sine', f / 2, at(t), dur), bg = ctx.createGain(); bg.gain.value = 0.7;
      a.connect(lp); b.connect(bg).connect(lp); lp.connect(g); out(g, { bus: music, ...o });
    },
    // Lead/arp note: square or triangle with a short filter envelope.
    note(t, dur, note, { gain = 0.15, type = 'triangle', cutoff = 3000, verb = 0.2, ...o } = {}) {
      const s = osc(type, hz(note), at(t), dur + 0.3), lp = ctx.createBiquadFilter(); lp.type = 'lowpass';
      lp.frequency.setValueAtTime(cutoff, at(t)); lp.frequency.setTargetAtTime(cutoff * 0.3, at(t), dur * 0.5);
      const g = ctx.createGain(); env(g.gain, at(t), 0.004, gain, dur);
      s.connect(lp).connect(g); out(g, { bus: music, verb, ...o });
    },
    // Room tone under silence (never fully dead air): brown-ish noise at very low level.
    room(t0, t1, { gain = 0.012, ...o } = {}) {
      const n = noise(at(t0), t1 - t0), lp = ctx.createBiquadFilter(); lp.type = 'lowpass'; lp.frequency.value = 380;
      const g = ctx.createGain(); g.gain.value = gain; n.connect(lp).connect(g); out(g, { bus: amb, ...o });
    },
    // Duck the music bus (sidechain-style) around t: depth in dB, recover over `release` seconds.
    duck(t, { depth = 6, attack = 0.005, release = 0.18 } = {}) {
      const p = music.gain, base = p.value, lo = base * 10 ** (-depth / 20);
      p.setValueAtTime(base, at(t) - attack); p.linearRampToValueAtTime(lo, at(t)); p.setTargetAtTime(base, at(t), release / 3);
    },
    // A supplied audio file (song, voice-over, recorded foley) placed at piece time t. Decoded offline,
    // so it is sample-accurate to the picture. from: seconds into the file; dur: how much to play.
    // Goes on the music bus by default (it is the bed); pass { bus: kit.sfx } for a hit.
    async sample(url, t = 0, { from = 0, dur = null, gain = 1, fadeIn = 0.005, fadeOut = 0.02, ...o } = {}) {
      const buf = await ctx.decodeAudioData(await (await fetch(url)).arrayBuffer());
      const src = ctx.createBufferSource(); src.buffer = buf;
      const g = ctx.createGain(), len = dur ?? buf.duration - from, t0 = at(t);
      g.gain.setValueAtTime(0, Math.max(0, t0)); g.gain.linearRampToValueAtTime(gain, t0 + fadeIn);
      g.gain.setValueAtTime(gain, t0 + Math.max(fadeIn, len - fadeOut)); g.gain.linearRampToValueAtTime(0, t0 + len);
      src.connect(g); out(g, { bus: music, ...o });
      src.start(Math.max(0, t0), from + Math.max(0, -t0), len);
      return buf;
    },
    finish() {},
    // Offline lookahead peak limiter: gain is computed from the samples ahead, the signal is not delayed.
    post(chans, rate, { ceiling = 10 ** (-1.5 / 20), lookahead = 0.003, release = 0.08 } = {}) {
      const n = chans[0].length, L = Math.max(1, Math.round(lookahead * rate));
      const need = new Float32Array(n);
      for (let i = 0; i < n; i++) { let p = 0; for (const c of chans) p = Math.max(p, Math.abs(c[i])); need[i] = p > ceiling ? ceiling / p : 1; }
      // running min over the lookahead window (wrapping for loops), then smooth release
      const g = new Float32Array(n);
      for (let i = 0; i < n; i++) { let m = 1; for (let k = 0; k <= L; k++) { const j = loop ? (i + k) % n : Math.min(n - 1, i + k); if (need[j] < m) m = need[j]; } g[i] = m; }
      // smooth: falls as fast as the lookahead min demands, recovers over `release`; a loop runs twice so the seam is settled
      const rc = Math.exp(-1 / (release * rate));
      let cur = 1;
      const sm = new Float32Array(n);
      for (let pass = 0; pass < (loop ? 2 : 1); pass++) for (let i = 0; i < n; i++) { cur = g[i] < cur ? g[i] : g[i] + (cur - g[i]) * rc; sm[i] = cur; }
      for (const c of chans) for (let i = 0; i < n; i++) c[i] *= Math.min(sm[i], need[i]);
    },
  };
  return kit;
}

// Float32 stereo WAV (keeps headroom; ffmpeg limits and encodes at mux time).
export function encodeWav(chans, sampleRate) {
  const n = chans[0].length, nc = chans.length, bytes = 4;
  const buf = new ArrayBuffer(44 + n * nc * bytes), v = new DataView(buf);
  const w = (o, s) => { for (let i = 0; i < s.length; i++) v.setUint8(o + i, s.charCodeAt(i)); };
  w(0, 'RIFF'); v.setUint32(4, 36 + n * nc * bytes, true); w(8, 'WAVE'); w(12, 'fmt ');
  v.setUint32(16, 16, true); v.setUint16(20, 3, true); v.setUint16(22, nc, true); v.setUint32(24, sampleRate, true);
  v.setUint32(28, sampleRate * nc * bytes, true); v.setUint16(32, nc * bytes, true); v.setUint16(34, 32, true);
  w(36, 'data'); v.setUint32(40, n * nc * bytes, true);
  let o = 44;
  for (let i = 0; i < n; i++) for (let c = 0; c < nc; c++) { v.setFloat32(o, chans[c][i], true); o += 4; }
  return new Uint8Array(buf);
}
