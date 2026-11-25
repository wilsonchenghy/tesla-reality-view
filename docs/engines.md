# Engines: what to draw with

The harness does not care how pixels are made. Pick per piece; mix freely inside one stage.

| Engine | Best for | Notes |
| --- | --- | --- |
| DOM + CSS (`el`, `set`) | UI, type, layout, crisp text | Sharpest text. Animate transform/opacity/filter; layout props are fine too (it is offline). `set` writes only changed values. No CSS transitions/animations: compute styles from t. |
| SVG (`svg`, `attrs`, `samplePath`, `resample`, `morph`, `drawOn`) | icons, line art, path morphs, draw-on, charts | Morph any two shapes: `resample` both to N points, `alignRing`, `morph(a, b, u)`. Stroke draw-on via dasharray. |
| Canvas 2D (`stage.canvas()`, `ctx2d`) | generative, thousands of marks, textures, grain | Backing store at `stage.dpr` (supersampling works). Redraw the whole frame from t. `grain()` for film grain. |
| WebGL / three.js (template `three`) | 3D, materials, light, shaders, SDF raymarching | Pinned three 0.160.0 vendored in node_modules. `preserveDrawingBuffer: true`. Headless is CPU (swiftshader): ~1 s/frame at 1080². Use `stills` and low `--sub` while iterating. |
| Raw GLSL full-screen quad (`shader(stage, FRAG)`) | SDF scenes, fluids, halftone, post | `pieces/chrome` is the pattern: choreography in JS springs, uniforms per frame, the shader only draws. Headless GLSL runs on the CPU: replace per-pixel marches with analytic forms when you can (sphere soft shadows/occlusion cut chrome's cost by a third), bound the march with a sphere, render with `--sub 2 --workers 2` (swiftshader already uses every core). |

## Rendering details that matter

- **Supersampling:** `--scale 2` renders at 2× device pixels and downsamples with lanczos in linear
  light. Canvas/WebGL pieces must size by `stage.dpr` (helpers do).
- **Motion blur:** `--sub N` subframes spread over `--shutter` (0.5 = 180°) of the frame, averaged
  in linear light. 4 is the default. **Adaptive:** after the first pass the renderer counts the pixels
  that change strongly across each frame's shutter and re-captures the fast frames with up to
  `--sub-max 16` subframes (fastest first, within `--refine-budget 1` × the base captures), so fast
  moves blur smoothly instead of showing stepped copies. Work animated on twos, pixel art and stepped
  textures want **no** blur: declare `renderDefaults: { sub: 1 }` in the piece (CLI flags still override).
- **Loops:** the renderer wraps subframe times around the loop, so frame 0's blur includes the end.
- **Fonts:** vendored in `runtime/fonts/` (Geist, Geist Mono, Instrument Serif, Fraunces, Archivo
  (width axis 62-125), Bricolage Grotesque, Unbounded, Space Mono, Big Shoulders Display). Add more:
  `node tools/fetch-font.mjs "<Family>" "<axes>"`. Variable axes: `fontVariationSettings: "'wdth' 80, 'wght' 650"`.
- **Assets:** images/models/audio in the piece folder, loaded in `setup` (await them). Renders are
  offline: no network at render time (check flags it).
- **Async render:** `render(t)` may be async (e.g. waiting for an image decode); keep it rare.

## Capture (where render time really goes)

Drawing a frame is cheap (morph: 7 ms); encoding the screenshot was the bottleneck (morph 362 ms per
PNG, tide's halftone 4.8 s). The renderer now captures subframes as **lossless WebP** (pixel-identical,
2-3x faster) and, when the stage is a single opaque full-frame canvas (2D or WebGL with
`preserveDrawingBuffer`), reads the **raw pixels** with no encoding at all (tide 0.86 s, verified
identical). Keep generative/shader pieces to one canvas to get the fast path; DOM pieces use WebP.

## Performance budget

`rv check` prints draw ms and capture ms separately. Capture cost scales with pixels and with how
compressible the frame is: a clean 1080² UI frame captures in ~100-350 ms, a 1080x1920 frame about twice
that, and a full-frame grain/noise/halftone layer can cost 3-10x (check warns above 600 ms). Four
browsers run in parallel, but several renders at once share the same 4 CPUs. Measured here: a 14 s,
60 fps DOM piece took 3-10 min; a 6 s raymarched GLSL loop at 2 subframes, ~20 min. Iterate with
`stills` and `--draft`; spend the full render once.
