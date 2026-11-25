
# Motion with rv

You direct, build, review and finish a motion piece. The harness (`bin/rv.mjs`) handles the
mechanics: deterministic frames, parallel rendering, linear-light motion blur, sound synthesis,
loudness, and a review loop that turns motion into images and numbers you can read. Your job is the
part the harness cannot do: **decisions**. Read `docs/creativity.md` before the first piece of a session,
and `docs/recipes.md` for techniques the existing pieces proved (UI morphs, type, shaders, print, character).

## Workflow

1. **Brief.** Fill `pieces/<name>/BRIEF.md` (created by `rv new`). Every line a number or a name:
   ```
   GOAL:    what the viewer should feel or do, one sentence
   CONCEPT: the one signature move (docs/creativity.md §2)
   OUTPUT:  engine (dom | canvas | three | glsl | mix), W x H
   TIME:    seconds x fps = frames, BPM, loop yes/no
   LOOK:    palette in hex with roles, one accent, typeface + weight + size + tracking
   MOTION:  easings by token, springs as zeta/freq, durations in frames
   SHOTS:   beat ranges, one hero move each, how each hands off
   SOUND:   bed + hits, which event gets which sound
   BANNED:  the defaults you will not use (start from docs/creativity.md §4)
   QA:      the frames you will check
   ```
   For an open brief, diverge first: three concepts on different axes, pick one, say why.
   Ask the user only for what you cannot decide (their product facts, a supplied song, a hard
   format). Show the state list on the beat grid before building when the user asked to see it.
2. **Scaffold.** `node bin/rv.mjs new <name> --template dom|canvas|three`.
3. **Cue sheet first.** All times come from `grid({ bpm })` and named states; no literal times
   scattered in code. Loops: `loopTrack`/`loopKeys` and whole cycles.
4. **Build the picture** in `setup(stage)` (once) and `render(t)` (every frame, pure function of t).
   Expose hero values in `probe(t)` (null when absent). Pass `cues: [[seconds, 'label'], ...]`. Discrete
   things (cuts, typed text, counters) read `frameTime()`, continuous motion reads `t`. Use the runtime (`runtime/rv.js`): `springTrack`,
   `loopTrack`, `dragRelease`, `rubber`, `ease.*`, `grid`, `rng`, `noise` (`loop1`/`loop2`), `mix` (OKLab), `el`/`set`, `svg`, path morphs.
5. **Review loop** (`docs/review.md`): `rv review <piece>` runs the battery and lists what to fix;
   then `taste` (default-look and contrast hints), `stills` at transitions, `onion`, `trace` → fix → repeat. Look at every PNG you make. Notes cite
   frame numbers. For an "in the style of" brief, `rv study <reference.mp4>` first.
   Use `rv render <piece> --draft` for a fast pacing check before the full render.
6. **Sound** in `score(a)` (`docs/sound.md`): hits at `picture + a.frame`. Verify with `rv audio`.
7. **Render**: `rv render <name> [--gif]`. Read a few frames of the final. Send the MP4 to the user.
8. **Report** honestly: what you checked by measurement, what you could not (you cannot hear).

## The render contract (enforced by `rv check`)

- Every frame is a pure function of t. No `Date.now`, timers, `Math.random` (use `rng(seed)`),
  CSS transitions/animations, or state carried between frames.
- Loops: frame N-1 flows into frame 0; `render(T)` equals `render(0)`.
- Fonts and assets are vendored; no network at render time.
- WebGL: `preserveDrawingBuffer: true`; draw synchronously in `render`.
- Never `will-change` on anything the camera scales (blurry text).

## Commands

`node bin/rv.mjs help` lists everything. Outputs land in `out/<piece>/`.

## Quality bar

Dribbble/studio-grade. Every frame holds up as a still. One hero per moment. Something happens on
every beat, but on most beats only one thing changes. If a frame could belong to any other piece,
it is not finished.
