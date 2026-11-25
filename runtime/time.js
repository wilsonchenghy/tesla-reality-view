// time.js: beat grids and cue sheets. Every event time in a piece should come from here,
// never a literal scattered across files: re-timing then means editing one anchor.

// Grid: beats computed from time (n * 60 / bpm), never by adding rounded frame counts (that drifts).
export function grid({ bpm = 120, offset = 0, beatsPerBar = 4, fps = 60 } = {}) {
  const spb = 60 / bpm;
  const g = {
    bpm, offset, beatsPerBar, fps, spb,
    beat: (n) => offset + n * spb,                       // time of beat n (fractional ok: 2.5 = the "and" of 3)
    bar: (n, beat = 0) => offset + (n * beatsPerBar + beat) * spb,
    beatAt: (t) => (t - offset) / spb,                    // fractional beat index at t
    barAt: (t) => (t - offset) / (spb * beatsPerBar),
    frame: (t) => Math.round(t * fps),                    // nearest frame of a time
    snap: (t, div = 1) => offset + Math.round(((t - offset) / spb) * div) / div * spb,
    // progress through the current beat (0..1) and an envelope that peaks on each beat
    beatPhase: (t) => { const b = (t - offset) / spb; return b - Math.floor(b); },
    pulse: (t, decay = 0.12) => { const b = (t - offset) / spb; if (b < 0) return 0; return Math.exp(-((b - Math.floor(b)) * spb) / decay); },
    framesPerBeat: (fps * 60) / bpm,
  };
  return g;
}

// Cue sheet: named times. cues({ hit: 1.0, open: g.beat(3) }) returns the object plus helpers.
// age(t, name) = seconds since the cue (negative before it); between(t, a, b) = 0..1 progress.
export function cues(map) {
  const c = { ...map };
  Object.defineProperty(c, 'age', { value: (t, name) => t - c[name] });
  Object.defineProperty(c, 'between', { value: (t, a, b) => { const ta = typeof a === 'string' ? c[a] : a, tb = typeof b === 'string' ? c[b] : b; return Math.min(1, Math.max(0, (t - ta) / (tb - ta))); } });
  Object.defineProperty(c, 'list', { value: () => Object.entries(c).sort((a, b) => a[1] - b[1]) });
  return c;
}

// Loop phase: whole-number cycles per loop land back on frame 0.
export const phase = (t, period) => ((t % period) + period) % period / period;
export const loopSin = (t, period, cycles = 1, ph = 0) => Math.sin(2 * Math.PI * (cycles * t / period + ph));

// A scene list: [{ name, at, dur }] -> which scene is live at t, and local time inside it.
export function scenes(list) {
  const s = list.map((x, i) => ({ ...x, i, end: x.at + x.dur }));
  return {
    list: s,
    at(t) { for (let i = s.length - 1; i >= 0; i--) if (t >= s[i].at) return { ...s[i], local: t - s[i].at, u: Math.min(1, (t - s[i].at) / s[i].dur) }; return { ...s[0], local: t - s[0].at, u: 0 }; },
    live(t, name, pre = 0, post = 0) { const x = s.find((q) => q.name === name); return x && t >= x.at - pre && t < x.end + post; },
  };
}

// Story time vs piece time, for loops whose frame 0 is not the start of the story (a poster frame
// mid-action). story = piece + offset (wrapped). Use story time for choreography, piece time for
// cues, sounds and probes (the harness speaks piece time).
export function storyClock({ offset = 0, period }) {
  const wrap = (x) => ((x % period) + period) % period;
  return {
    story: (t) => wrap(t + offset),            // piece -> story
    piece: (s) => wrap(s - offset),            // story -> piece (cue sheets and scores)
    age: (t, s0) => wrap(t + offset - s0),     // seconds since story moment s0, wrapping
  };
}
