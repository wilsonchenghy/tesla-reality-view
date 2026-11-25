# The numbers

Motion designers talk in curves and frames. Give every value a number. All of these are available
as runtime functions and tokens (`runtime/motion.js`, `runtime/time.js`).

## Easing tokens (`ease.*`)

| Token | cubic-bezier | Use |
| --- | --- | --- |
| `outExpo` | 0.16, 1, 0.3, 1 | text and logo reveals |
| `outQuint` | 0.22, 1, 0.36, 1 | premium entrances |
| `inOutQuart` | 0.76, 0, 0.24, 1 | moves across the screen, camera pushes |
| `inExpo` | 0.7, 0, 0.84, 0 | fast exits |
| `outBack` | 0.34, 1.56, 0.64, 1 | a playful pop (never on UI chrome) |
| `emphasized` | 0.2, 0, 0, 1 | Material 3 emphasized |

Enter with ease-out, exit with ease-in and make exits 40-50% shorter (400 ms in, 200 ms out).
Move with ease-in-out. Linear only for rotation, progress bars and loop phase.

## Springs (`spring`, `springTrack`, `loopTrack`, `oscillate`, `dragRelease`)

One number translates between all libraries: the **damping ratio** zeta.
1.0 never bounces. 0.75-0.85 premium (tiny overshoot). 0.5-0.65 playful. < 0.3 cartoon.
`freq` is the natural frequency in Hz: 1.5 soft camera, 2.5 UI morph, 3.5-4.5 snappy knobs.
`settleTime(zeta, freq)` tells you how long it takes; plan the grid with it (0.8 / 2.5 → 0.46 s).

Conversions: `dampingRatio(k, d, m)`: Remotion default (100, 10) = 0.5; react-spring default (170, 26) = 1.0.

Material 3: position and size may bounce; **opacity and color never do** (use eased keys for them).

- `springTrack(keys)`: a value retargeted many times is the sum of one spring per change: a pure
  function of t, no simulation.
- `loopTrack(keys, T)`: the same for loops; changes from the previous cycle keep ringing across
  the seam. Use it for anything in a loop.
- `dragRelease(t, tRelease, held, target)`: direct manipulation, then spring from the release
  position *with its velocity*.
- Two edges on two springs (leading faster: zeta 0.74 / 3.8 Hz, trailing 0.84 / 2.2 Hz) = liquid.

## Durations and stagger

| What | Time | At 60 fps | At 24 fps |
| --- | --- | --- | --- |
| UI feedback | 100-200 ms | 6-12 f | 2-5 f |
| UI move | 200-500 ms | 12-30 f | 5-12 f |
| Hero reveal | 600-900 ms | 36-54 f | 14-22 f |
| Letters | 1-2 frames apart | | |
| Words | 60-120 ms | | |
| List items | 40-80 ms | | |
| Content blur swap | out 100-120 ms, in 220-280 ms, 6-8 px | | |

Start the next element when the previous is 30-50% done.

## Beat grid (`grid({ bpm, offset })`)

Frames per beat = fps × 60 / BPM. 120 BPM at 60 fps = 30 frames; at 24 fps = 12.
Compute beats from time (`g.beat(n)`), never by adding rounded frame counts (drift: 2 frames after
32 beats at 128 BPM/30 fps). Sounds land **1 frame after** their picture (`t + a.frame`): sound
before picture feels wrong sooner than sound slightly late.

## Holds and readability

- Text: 0.3 s per word + 0.5 s once fully visible.
- During a hold, a 2% push keeps the frame alive.
- Contrast ≥ 4.5:1 for text on every frame (`contrast(a, b)` in runtime/color.js).
- Never flash more than 3 times per second.

## Camera

Softest curves for the camera (inOutQuart, springs at 0.9 / 1.5 Hz); snappier ones for objects.
Parallax speeds 1.0 / 0.5 / 0.2. 3D lens 30-50° fov. Zoom so the hero fills ~55-75% of the frame.

## Feelings → numbers

| Note | Translation |
| --- | --- |
| "make it pop" | scale 1.0 → 1.08 → 1.0 over 6 frames, peak on the beat |
| "premium" | outQuint entrances, springs at 0.8, no overshoot on text |
| "it drags" | cut each hold by one beat; keep cuts on the grid |
| "too busy" | one hero move at a time; others 150 ms later at 60% travel; remove 30% of motion |
| "looks like AI" | list the defaults it used by name, ban each, render again |
| "abrupt ending" | 36-frame hold with a 2% push, settle on a spring at 0.8 |

## Delivery

| Target | Spec |
| --- | --- |
| X / social video | H.264 High, yuv420p, CRF 16-18, +faststart, AAC, -14 LUFS, -1 dBTP (render default) |
| GIF | one palette, ≤ 15 MB, ≤ 350 frames on X, 24-30 fps, bayer dither (`--gif`) |
| Canvas sizes | 1080×1080 (1:1), 1080×1350 (4:5), 1080×1920 (9:16), 1920×1080 (16:9). Pick before frame one. |
