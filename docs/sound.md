# Sound

The feed plays muted until tapped, so the picture must work in silence first. Then sound doubles
the impact. Everything is synthesized from the same cue sheet as the picture, offline, so it is
sample-accurate. You cannot listen: you measure (`rv audio`), and you tell the user you did.

## The kit (`score(a)` in the piece, `runtime/audio.js`)

Times are piece seconds. `a.frame` = one frame; land every hit at `picture time + a.frame`.

| Group | Calls |
| --- | --- |
| Drums | `kick(t)`, `snare(t)`, `clap(t)`, `hat(t, {open})`, `shaker(t)` |
| UI foley | `click`, `tick`, `tock`, `pop`, `bloop({note})`, `ting({note})`, `bell`, `thud`, `key({seed})`, `zip(t, {up})` |
| Moves | `whoosh(t0, t1, {from, to, peak})`, `riser(t0, t1)` |
| Weight | `sub(t, {note})`, `clang(t)`, `gloop(t, {note, wobble})` |
| Tonal | `pad(t, dur, notes)`, `pluck(t, note)`, `bass(t, dur, note)`, `note(t, dur, note, {type})` |
| Space | `room(t0, t1)` (never true silence), `duck(t, {depth})` (sidechain the music bus) |
| Raw | `a.ctx`, `a.out(node, {bus, pan, verb})`, `a.tonal(t, partials)`, `a.noise(t, dur)`, `a.at(t)`, `a.mark(name, t)` |

Every tonal hit is a buffer whose first peak lands exactly on its time (cosine phase, no
waveshaper). Loops are folded: anything that rings past the end wraps to the start, so the seam is
seamless by construction. The master is limited offline with lookahead (no latency), then the
render normalizes to -14 LUFS, -1.5 dBTP.

Build your own instruments from `a.ctx` whenever the piece needs a sound the kit lacks; mark them
with `a.mark('name', t)` so `rv audio` checks their timing.

## Using a supplied song

`rv new <name> --template song`, put the track in the piece folder as `song.wav`, then
`rv analyze pieces/<name>/song.wav` writes `song.beats.json` (bpm, every beat, downbeats). The template
reads it, sets the grid so piece time 0 is the first downbeat, and places the song with
`await a.sample('./song.wav', 0, { from: START, dur: T })`: decoded offline, sample-accurate.

Beat times are reliable (kick-weighted onsets, tempo refined by fitting the whole grid). Which beat is
"1" is an estimate: check `downbeat_confidence`; near 0 (e.g. kicks on 1 and 3) look for where the
arrangement changes, or ask the user. You can still not hear it: verify with `rv audio` and by
re-analyzing your render (beats should land at piece time 0, 0.5, ...).

## Mix rules

- Hits 3-6 dB over the bed (`over_bed_db` in the report). Duck the bed under big hits.
- Phone speakers play almost nothing under 150 Hz: give kicks a 150-200 Hz knock, keep bass audible
  above 100 Hz, pads bright enough to carry.
- Nothing harsh above 8 kHz for long; hats short.
- Arrange: stop-time and drop-outs are storytelling. Silence before the reveal; the hit on the reveal.
- Give every visible action a sound, quietly. A tiny tick on a toggle is worth more than a louder bed.

## Verify

`rv audio <piece>` renders three versions of the score: the full mix, a **hits stem** (sfx bus only)
and a **bed stem** (everything else). Onsets are measured on the hits stem (high-passed, relative to the
level just before each hit, wrapping around the loop), so a ringing pad or sub cannot fake a late hit;
"over bed" compares the hits stem with the bed stem over the same 60 ms. Drums, plucks on the music bus,
hats and shakers are marked `bed` and are not judged. `audio.png`: orange on time, red off by more than a
frame or under 3 dB over bed, gray = ambiguous (two hits overlap). A flam or swell that is meant to start
early: `a.mark(name, t, { early: 0.03 })`. Route your own hits with `a.out(node, { bus: a.sfx })` so the
stems split them correctly.
