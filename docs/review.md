# The lab loop: render, look, fix

The first render is a draft. You cannot watch video, but you can read images and numbers precisely,
so the harness turns motion into images and numbers. Two to four rounds is normal; post-launch
pieces that look effortless took 4-15 follow-ups.

## The order

1. `rv check <piece>` — before anything else. Determinism, seam, guards, errors, fonts, network.
   A failing check makes every other review meaningless.
2. `rv beats <piece>` — one frame per beat (`--div 2` for eighths). Is something happening on
   every beat? Is every state legible at its beat? Is frame 0 a poster?
3. `rv stills <piece> --t ...` at the **transitions**, not just the holds: 2-5 frames after each
   change is where overlaps, mud and clipping live. Use `--sub 4` to see what the motion blur does.
4. `rv motion <piece>` — the energy graph: dead spans (red), quiet beats, the biggest single-frame
   jump (often a pop that should have been eased), the loop seam.
5. `rv trace <piece>` — plots of your `probe(t)` values with speed: linear runs (robotic), dead
   stops (no settle), jumps (discontinuities). Expose every hero value in `probe`.
6. `rv onion <piece> --from a --to b` — spacing: even = linear; tightening near keys = eased.
7. `rv audio <piece>` — renders stems (hits only, bed only) and measures every hit's onset on the
   hits stem and its level over the bed stem. Gray markers are ambiguous onsets (overlapping hits), not errors.
8. `rv taste <piece>` — heuristic default-look checks on one frame per beat: purple/blue gradients,
   glow halos, centred-everything, text contrast against the pixels actually behind it, no lead accent.
   Hints for your judgement, not verdicts.
9. `rv render <piece>` — then `rv sheet <piece>` or read frames from `--frames`.

Write notes with frame numbers, fix, re-render **only** what changed (`stills`, `--from/--to`).

## How to look at a frame

Describe it in one sentence as a first-time viewer would, then compare with the shot list. Then:

- **Focal point:** where does the eye go? Is that the hero?
- **Legibility:** can every word be read at this frame? Contrast ≥ 4.5:1?
- **Overlap:** two content states visible at once inside one container? (needs separate in/out timing)
- **Mud:** a color passing through gray because two far colors are mixed slowly? (flip faster, while content is hidden)
- **Clipping:** anything cut by the frame edge or a container that shouldn't be?
- **Default look:** which banned item crept in? Ban it by name.
- **Finish:** would this frame hold up as a poster? If not, what would a top designer fix?

## Prompts to give yourself (pick 1-2 per round)

- Render stills at the five most important frames. Describe each in one sentence. Does it match the shot list?
- Contact sheet every 12th frame. Mark every frame where two things move at once; fix the hierarchy.
- Onion-skin the hero move. Spacing should tighten near the keys.
- Trace the hero's x and scale. Where is it linear or does it stop dead?
- Review as a senior motion designer: 10 notes by impact, each with a frame number and the code change. Apply the top 5.
- Remove 30% of the motion; keep only moves that guide the eye.
- What here could be in any other piece? Replace it with something only this piece could have.

## When a fix doesn't hold

Render the frames either side of the problem, list every difference, find the one line that causes
it, fix only that line, render both again.

## Failures you will hit

| Symptom | Fix |
| --- | --- |
| `check` says frames differ between passes | state carried between frames: compute from t; seeded rng; no `+=` across frames |
| loop seam flagged | `loopTrack`/`loopKeys`, whole cycles per loop (`phase(t, T)`), noise via `loop1/loop2`, last frame flows into first |
| guard: Math.random / Date.now / setTimeout | use `rng(seed)`, t, and nothing else |
| wrong or fallback font | add to `fonts: [...]`; vendor with `node tools/fetch-font.mjs "<Family>" "<axes>"` |
| text blurry while the camera scales | never put `will-change` on scaled things; let DOM text re-raster |
| two states overlap inside a container | exit finishes before enter is legible: exit 100 ms starting 60 ms before the change, enter starting 80 ms after |
| color passes through mud | flip far colors in ~120 ms while content is hidden; mix in OKLab (`mix`) |
| steppy motion blur on very fast moves | adaptive blur handles it (raise `--sub-max` / `--refine-budget`); or slow the move |
| audio hits late | never use DynamicsCompressorNode (adds ~6 ms); the kit limits offline. Check `rv audio` |
| hit buried in the bed | aim 3-6 dB over bed (`over_bed_db`); duck the music bus (`a.duck`) |
| WebGL frame blank | `preserveDrawingBuffer: true`, render synchronously in `render(t)` |
| WebGL slow (1-3 s/frame on CPU) | iterate with `stills`; final with `--sub 2 --workers 2 --refine-budget 0.25`; replace marches with analytic shadows/AO |
| check flags the seam | the seam step (N-1 -> 0, mean abs diff 0-255) is compared with the largest step within 12 frames on *both* sides, threshold 1.5x; an event on frame 0 or on-twos animation passes. If it fires, the loop really jumps |
| a hard cut or typed text double-exposes under motion blur | read `frameTime()` for discrete things; the default shutter opens at the frame time so cuts on beats are clean |
| a sound is meant to start early (flam, swell) | `a.mark(name, t, { early: 0.03 })` so the audio report does not flag it |
| GIF banding | flat colors or dithered palette (render uses bayer); avoid big gradients |
| text moves while being read | hold 0.3 s/word + 0.5 s before moving it |
