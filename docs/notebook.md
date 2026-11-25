# Lab notebook

What building and testing this harness taught, with the numbers. Read it before changing the harness;
add to it when you learn something the hard way.

## Measurements

| Finding | Number | What changed |
| --- | --- | --- |
| Where render time goes | morph: draw 7 ms, PNG capture 362 ms; tide: draw 63 ms, PNG 4.8 s | lossless WebP subframes (pixel-identical, 2-3x faster); raw readback for single-canvas pieces (tide 0.86 s) |
| Motion blur in gamma vs linear | mean error 4.5/255 for naive averaging vs 0.4 for the ffmpeg zscale chain vs numpy reference | blend in linear light (now numpy `tools/blend.py`) |
| 4 uniform subframes on a fast move | visible stepped copies 5 px apart | adaptive: re-capture fast frames with up to 16 (by changed-pixel count, not share) |
| Web Audio DynamicsCompressorNode | every hit 12.8 ms late | offline lookahead limiter: hits within 0.5 ms |
| AAC encode | lifts true peak ~1 dB (-1.5 → -0.9 dBTP) | limit to -2.2 dBFS before encoding |
| Simplex noise kernel 0.6 | discontinuous at simplex boundaries (jump of 1.2e-4 across z = 0) | radius 0.5, rescaled |
| GLSL raymarch on CPU (swiftshader) | 2.5 s/frame; analytic sphere shadows → 1.8 s | bound the march, analytic shadows/AO; `--sub 2 --workers 2` |
| GIF of a halftone piece | 134 MB at 960 px | size-capped GIF fitting; `rv share --max-mb` two-pass encode |
| Seam check vs held / stepped animation | false positive (step before seam 0, seam 22) | compare against the largest step within 12 frames on both sides |
| Song analysis on a track with off-beat hats | beat phase off by half a beat | kick-band weighted phase + joint tempo fit; downbeat reported with a confidence |

## Dogfood runs (a fresh agent, an open brief, only the docs)

**Run 1: "cache hit vs miss" explainer (8 s loop, canvas).** It made a specific concept (a request draws
its own network waterfall) and rejected two others with reasons. Friction it found:
- the cue format was undocumented, and the runtime's `cues()` produced the wrong shape
- the audio onset detector reported overlapping sounds as -30 ms late (an unused high-pass)
- the seam check failed on an event at frame 0
- the centred shutter double-exposed hard cuts
- trace drew NaN gaps as motion
- canvas fonts were never checked
- ETA, units and labels were missing

Fixes: cue normalization, audio stems (hits-only and bed-only) with relative onsets, a two-sided seam
check, start-phase shutter plus `frameTime()`, trace gaps, a font check, and helpers (`impulses`,
`crossings`, `storyClock`, `typed`, `polyline`, `fillTextTracked`).

**Run 2: "Margin" vertical launch teaser (10 s, no loop, DOM).** It made an editorial concept (one red
margin rule becomes the logo). Friction it found: the harness was loop-centric everywhere. The seam was
reported on a non-loop, the end card was flagged as dead time, audio was hard-cut, and no docs covered it.
There were no `new --size`, no safe zones (the advertised `C` overlay didn't exist), no paragraph-text
helpers, and no warning that a grain layer triples capture cost.

Fixes: `holds`, no seam for non-loops, an end fade, `new --size --no-loop`, `uiZones` + preview C +
`taste` flags, a capture-cost note in check, `hand.js` (anchors, underline/circle/bracket/check,
writeOn), and docs.

**Pattern:** every dogfood run finds a *category* the author's own demos never exercised (loop vs
non-loop, square vs vertical, shapes vs paragraphs). Run one per new genre.

**Run 3: Tesla "Reality View" recreation (20 s, three.js + DOM, real dashcam data).** The first piece driven by external
footage and data instead of invented motion. Friction: no way to pass a debug flag to a piece (I toggled code with sed,
which is error-prone), so `stills --query` now appends URL params. Big data lives in `out/` (gitignored) and is rebuilt by
`pieces/reality/prep/`, which is the pattern for any piece built on real data. Recipe notes in `recipes.md`.

## Open problems

- Cut detection in `study` is approximate for motion graphics: springy type after a cut and full-frame
  wipes confuse frame differencing. It is right on clean cuts; check `shots.png`.
- Downbeat ("which beat is 1") is ambiguous when the kick pattern repeats every half bar.
- WebGL is CPU-rendered here; `--gpu` exists for machines with a GPU but is untested.
- `taste` is heuristic. It catches gradients, glow, centring, contrast and safe areas, not "this looks
  generic". The agent's own judgement against `creativity.md` is still the main defence.
- No Blender path yet. The contract that makes one possible: any frame from t, then the same review
  tools on the frames (`study`, `compare` and `motion` already work on any video).
