# Recipes

Techniques the pieces in `pieces/` proved, as patterns to reuse (not looks to copy). Each is a pure
function of t.

## Structure

**Cue sheet first.** `const g = grid({ bpm }); const b = g.beat;` then every time is `b(n)`. Put the
states in one array (`pieces/morph`: `ST`), derive tracks from it, and pass `cues:` to `piece()` so
`rv plan` prints the beat grid. Format: `cues: [[seconds, 'label'], ...]`, or `{ label: seconds }`
(what `cues()` in time.js returns), or a function returning either.

**Discrete vs continuous.** Motion blur renders several subframes per frame. Anything discrete (a word
that cuts in, text that types, a counter, a flash, a stepped highlight) must read `frameTime()` instead
of `t`, so every subframe agrees and nothing double-exposes. Continuous motion reads `t`. The shutter
opens at the frame time by default (`--shutter-phase start`), so a cut on a beat is clean on that frame.

**Story time vs piece time.** When frame 0 should be mid-story (a poster frame), use
`storyClock({ offset, period })`: choreograph in story time, give cues, sounds and probes piece time.

**Absent values in probes.** Return `null` (or NaN) when a thing is not on screen; `trace` breaks the
line there instead of drawing a fake move.

**Loop-safe values.** `loopTrack(keys, T)` for anything springy, `loopKeys` for eased values,
`phase(t, T)` × whole cycles for rotations, `noise.loop1/loop2` for drift. `rv check` verifies the seam.

**Scenes with hard cuts.** `const sec = Math.floor(t / b(4))` and render one section per bar
(`pieces/measure`). A cut must be fully visible on its beat frame: never fade in from 0 on the beat.

## Non-looping pieces: teasers, launches, end cards

- `piece({ loop: false, holds: [[T - 1.5, T]] })`. `holds` declares intentional stillness (an end card,
  a held title): `motion`/`review` do not call it dead time. No seam is checked or reported.
- Use `springTrack` / `tween` / `keys` (not `loopTrack`), and plain `t` (no wrapping).
- `rv new <name> --no-loop --size 1080x1920` scaffolds one.
- Audio is cut at `duration`; the last 40 ms are faded (`endFade` in the piece to change). Let the final
  chord/sub decay before the end; a ringing tail cut mid-waveform clicks.
- End card: build to it (the hero element *becomes* the logo), hold 1.5-2.5 s with a 2% push, and give
  frame 0 something to look at too (it is the thumbnail).

## Vertical (9:16) and platform UI

- Captions, buttons and the action rail cover roughly the bottom 23%, the top 8% and a right-hand strip
  (`uiZones(W, H)`). Press **C** in the preview to see them; `rv taste` flags text inside them.
- Contact sheets of tall frames get downscaled: pass `--width 300 --cols 6` to `beats`/`stills`.

## Text in paragraphs (`runtime/hand.js`)

- `anchors(el, 'phrase')` returns where a phrase lands (one rect per wrapped line).
- `hand.underline(rect)`, `hand.circle(rect)`, `hand.bracket(x, y0, y1)`, `hand.check(x, y, size)` return
  seeded, slightly imperfect SVG paths with their `length`; animate with `drawOn(length, u)`.
- `writeOn(u)` is a clip-path for a handwritten line (slanted left-to-right wipe).
- Notes that may collide: lay them out once in `setup` (measure, then push down), not per frame.

## UI motion (`pieces/morph`)

- **One shape, never cut**: one element whose `[w, h, r]` is a `loopTrack` over states; contents are
  separate layers inside it with `presence(t, tin, tout)` + `presenceStyle` (exit finishes before enter is legible).
- **Camera fills the frame**: zoom track from the same keys: `fitZoom(W, H, w, h, 0.7)`, softer spring than the shape.
- **Cursor**: `cursorRig(stage, { path, clicks, drags, period })`; it arrives ~0.4 s before each click;
  press dips 70 ms before, releases 40-140 ms after.
- **Direct manipulation**: while held, value = f(cursor x) + grab offset; after release, `dragRelease`
  springs from the release position with its velocity.
- **Rubber band**: overdrag → `rubber(over, 0, 0.6, 70)` added to the container's width; release springs back.
- **Liquid indicator**: left and right edges on two `loopTrack`s; the leading edge (direction of travel)
  gets the fast spring (0.74 / 3.8 Hz), the trailing edge the slow one (0.84 / 2.2 Hz).
- **Labels through a pill**: draw labels twice (light under the pill, dark over it) and clip the dark
  copy to the pill's edges with `clip-path: inset(... round r)`.
- **Light/dark flips**: never fade black↔white (it passes through gray and reads as a cut); grow the new
  ink as a circle from the interaction point, clipped by the shape.
- **Play/pause morph**: two quads per icon with matching point order, lerped by a spring.

## Type (`pieces/measure`, `runtime/type.js`)

- `typeModel(family, weight)` measures each glyph's width at both ends of the width axis; width is ~linear.
- **Fit to the measure**: `fit(text, 960, { wdth })` → font size.
- **Letters as springs**: per-letter target widths on a `springTrack`; when one widens, `giveWay` shrinks
  the others so the line stays justified.
- **Color in Swiss work switches**: threshold, don't mix (mixing red and black makes brown).
- **Show the curve**: a dot moving along the plotted curve of its own easing (time on x, value on y).

## Shaders (`pieces/chrome`, `runtime/gl.js`)

- Choreography in JS (springs on the grid) → uniforms; the fragment shader only draws.
- SDF blob + drops with `smin`; drops grow from a **negative radius** so their pull fades in instead of popping.
- Studio in code: an `env(dir)` of soft rectangles in azimuth/elevation (softboxes, flags, rim strips).
  Chrome needs **dark** to reflect: a black flag on the camera side, the floor ending toward the camera.
- CPU budget: bound the march with a sphere, analytic shadows/occlusion for spheres, few reflection steps.

## Print (`pieces/tide`)

- **Risograph**: each ink is its own canvas of halftone dots on a rotated grid (15°, 75°), drawn
  `multiply` onto paper so overlaps make a third color; offset each ink a few px (misregistration).
- **On twos**: `tq = Math.floor(t * 12) / 12` for organic motion; render with `renderDefaults: { sub: 1 }`.
- Expensive per-pixel functions (noise) → precompute per column/row each frame, then look up.
- A clock or counter that reads the piece's own time ties the picture to its loop.

## Character (`pieces/pip`)

- **One `pose(t)`** returns x, height, rotation, scaleX, scaleY by scanning a list of hops.
- **Arcs**: x linear in air (that *is* ballistic), height on a parabola through both ends with a chosen apex.
- **Anticipation**: crouch `ease.inOutCubic` from `a` to takeoff; the important jump gets the longest.
- **Squash & stretch**: multiply factors, keep volume (sx ≈ 1/sy); landing = `oscillate(t - t1, depth, 0, 0.42, 3.2)`.
- **Overlap**: secondary parts are the same pose evaluated a few frames late (`pose(t - 0.033)`), clamped
  so they trail without detaching.
- **Follow-through**: an antenna angle is a sum of spring impulses (`oscillate(t - event, 0, v, 0.22, 2.4)`)
  at every takeoff and landing.
- **Rule of three**: three attempts, each bigger, the third lands hardest; then the turn.
- **Staging**: zoom about a focal point *inside* the set (the frame only ever crops).

## Helpers worth knowing

- `impulses(t, [[time, velocity], ...], { zeta, freq, period })`: follow-through as a sum of spring kicks.
- `crossings(fn, thresholds, t0, t1)`: when a value passes thresholds (schedule a tick per whole number,
  per detent, per 25%).
- `polyline(pts, { radius })`: rounded routes for canvas with `.at(len)` and `.stroke(g, from, to)` (a
  token travelling a trace that draws itself).
- `typed(text, frameTime(), t0, { perFrame: true })`: typing, blur-safe.
- `fillTextTracked(g, text, x, y, { tracking, align, tabular })`: canvas text with letter-spacing.
  Canvas cannot drive a variable *width* axis (`fontStretch` takes keywords); put width-axis type in DOM.

## Sound

- Hits at `picture + a.frame`. Name each hit; custom ones with `a.mark(name, t)`.
- Pitch follows size (higher hop → higher boing; landings on the ledge pitched up).
- One sound per visible action, quiet; silence before the payoff; a chord on the payoff.

## Reconstruction from real footage (pieces/reality)

Footage → a 3D scene, no GPU training: calibrate the rig → per-frame monocular depth (Depth Anything V2 small, ONNX,
0.25 s/image on CPU) → metric scale by fitting relative inverse depth to the calibrated ground plane → back-project to
flat Gaussian disks → draw them with an EWA splat shader in three.js (`pieces/reality/index.html`, `splatVS`). What it taught:
- **Calibrate against lane lines, not guesses.** Mark points on lane lines, fit yaw/pitch/roll/f/k1 with lines of unknown
  offset as extra unknowns (`prep/fit.py`); draw the prediction over the image (`overlay.py`) after every fit.
- **The pose the video was shot from is free proof.** Put the virtual camera at the source camera's pose and the splats
  reproduce the frame exactly; pulling back from there shows the scene really is 3D.
- **Trust geometry over monocular depth near the ground**, and more so on wide/fisheye lenses: snap pixels to the road
  plane when depth roughly agrees. Road splats must stretch along the viewing ray (length r·pitch/sin(grazing)), or the
  road shows horizontal stripes. Cap that stretch on side/rear cameras: long streaks read as curved "shells".
- **One bad depth fit makes fog.** The rear fisheye's fit capped every range near 6 m, which put its trees in a grey dome behind
  the car. Debug by colouring splats per source camera (`?dbgcam`, via `rv stills --query dbgcam`).
- **Keyframes at 4/s visibly pulse** (motion energy spikes at 4 Hz); 8/s with a crossfade is smooth.
- **three.js draws the opaque list before the transparent list**, whatever `renderOrder` says. An opaque mesh meant to
  sit over unsorted, depth-less splats has to be marked `transparent` to be ordered after them.
- Sorting about 500k splats in JS (16-bit counting sort) plus CPU WebGL runs about 1-1.3 s/frame at 1408x1000.
