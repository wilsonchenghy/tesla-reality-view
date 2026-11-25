# Handoff: Tesla Reality View recreation

For the next working session. Read this file first, then `pieces/reality/prep/README.md`.

## Goal

Make a 20 s video that looks like Tesla FSD v15 **Reality View**: a smooth, photoreal 3D world of the street rendered
from a chase camera behind our car. Every other vehicle is a clean, correctly placed 3D model, and the blue planned path
and the HUD are drawn on top. The bar is the Tesla in-car screen: crisp road paint, no blur, no flicker, no seams, and
no car that is wrong in position, heading or existence.

The owner's standing requirements:
- **Quality:** a real 3D Gaussian-splat world, not projected video. Sharp, temporally stable, no baked-in blurry cars.
- **Traffic:** every vehicle modelled, at its true position and heading, appearing smoothly (no pop-in), never in our own path.
- **Speed:** everything heavy on GPU, iterate fast (target about 2 min per preview round; full rebuild under about 35 min).
- **Honesty:** measure before claiming (held-out PSNR, crops at 100%, reprojection checks), and report what is still wrong.
- **Git:** commits authored by the owner only (Wilson Cheng), with no assistant or tool attribution anywhere.

## Where it stands (best = v13)

Scene: clip_00, drive time 6–26 s (a left turn through an intersection, then 47 mph on a divided road and a right lane change).

| Stage | State | Numbers |
|---|---|---|
| Camera rig | 6 cameras, lane-line calibration, then a **rig-constrained COLMAP solve** (solved mount rotations, measured mount positions, gravity-levelled) | 0.6–0.7 px reprojection; front camera 1.48 m above the road (±0.1–0.2 m) |
| Vehicle masks | **only moving vehicles are hidden from training** (parked ones stay photoreal in the world): optical-flow test per instance (`motion_masks.py`), then the 3D tracks decide for every instance they cover (`track_masks.py`) | world and drawn models never show the same vehicle twice |
| World | 3D Gaussian splatting (gsplat) on 2,166 views (16 fps keyframes × 6 cams), depth-supervised, ego-volume floater pruning | held-out PSNR **23.46** |
| Road | separate layer: 4.2 M flat 5 cm Gaussians cast from the nearest views, lane-line (ECC) registration, per-camera shading maps | sharp paint, small residual quilt |
| Clean-up | Difix3D+ (`nvidia/difix_ref`): render the chase path → Difix → fine-tune the world on cleaned views + real photos → render → Difix → RAFT deflicker; references are real front frames with only **moving** cars inpainted | removes most splat blur; flicker controlled |
| Traffic | `traffic3d.py`: YOLO11-seg on every solved view → ground lift through the solved pose, fused with a known-height range cue and a box fit along the bearing → per-keyframe multi-camera fusion → constant-velocity Kalman filter + Hungarian association + RTS smoother; parked vs moving by bearing triangulation; track pieces going the same way are joined (`stitch`), and tracks fade in/out over 0.3 s instead of coasting; `road_map.py` (SegFormer road / sidewalk / terrain votes cast onto the ground, from the rendered chase views first and the camera views as fallback) and every off-road sample slides along its viewing ray onto the road; no two vehicles may overlap | `proj_eval.py` (drawn 3D boxes projected into every view against the 2D detections, IoU ≥ 0.3, scoring what the page draws): precision **0.41**, recall **0.42**; 4.7% of drawn samples off the road |
| HUD | speed, PRND, blinkers, Self-Driving state, maneuver card, sky chevrons, blue path; all values from telemetry | done |

Everything runs on one 16 GB desktop GPU (RTX 5070 Ti): world 25 min, road 10 min, clean-up 35 min, traffic + piece 10 min.

Other clips: **clip_04** (drive time 270–290 s, a different town) runs through the same jobs with no tuning: held-out
PSNR **22.93**; traffic precision 0.46, recall 0.36, about 11% of drawn samples off the road (two oncoming cars sit on the
median grass at 14 s and 16 s). Demo: `out/reality/reality.mp4` after `local_clip_gpu.sh clip_04 270`.
**clip_02** (drive time 140 s, highway) also runs end to end, but its traffic is weak: precision 0.26, recall 0.09, only 9
cars drawn, two of them overlapping at 2–5 s and one sideways at 5 s.

## The open problems, in priority order

1. **Traffic range.** About 40% of drawn cars match a real car, and the main error is range: it comes from a 2D box plus
   a flat-ground lift, so half a degree of slope or pitch is metres at 50 m. Projected boxes are also 1.2–2.2× wider
   than the detections (back camera 2.2×), and the lead car lands about 1 m right. The road map and ray slide only patch
   this. A production stack (e.g. Tesla's) instead runs one learned multi-camera network that outputs 3D objects directly,
   trained on auto-labelled 3D data. Next, in order:
   - a metric depth model (Depth Anything V2 Metric, UniDepth or Metric3D) sampled inside each detection as the range
     cue; the packs' `depth/*.npy` are relative (0..1), not metric. It needs a separate Python env (the Difix pins hold
     `transformers` at 4.38);
   - a pretrained monocular 3D detector (Omni3D / Cube R-CNN) for range and heading.
   Measure each with `proj_eval.py` plus the off-road share on clip_00, clip_04 and clip_02, and check every second of
   the render.
2. **Highway traffic (clip_02).** Recall 0.09: at highway range the flat-ground lift fails first. Item 1 is the fix.
3. **Far vehicles on the road.** Beyond ~40 m the flow test cannot tell a waiting car from a parked one and no track
   reaches it, so an occasional far car stays in the world. Tracks with longer range (item 1) fix this. clip_00 has
   one at the intersection (3–5 s): a blurry grey car baked into the world.
4. **Road map on the far side.** The trained world puts the far oncoming lanes about 3 m left of where the camera
   ground projection does, so the camera map can disagree with what the viewer sees; the chase map is used first.
5. **CAD vehicle look.** The models read as CG next to the photographic street (lighting comes from the per-second
   street panoramas, `pano.py`).

## How to run

The pipeline diagram is in the [README](README.md#pipeline). Everything runs on one desktop GPU with 16 GB.

Environment: Python 3.12 with a CUDA build of torch (cu13x for RTX 50-series), `gsplat` (compiles its CUDA kernels on
first use: needs `nvcc`, e.g. the `cuda-toolkit[nvcc,cudart,cccl,crt]` wheels, with `CUDA_HOME` pointing at them),
`ultralytics`, `diffusers==0.25.1 transformers==4.38.0 huggingface-hub==0.25.1 peft==0.9.0` for Difix plus a clone of
`https://github.com/nv-tlabs/Difix3D` (`DIFIX_SRC=<clone>/src`), `pycolmap`, `pandas pyarrow onnxruntime scipy opencv`,
ffmpeg, and Node 22 with `npm install` and a Playwright headless Chromium (`npx playwright install chromium-headless-shell`)
for the piece.

One clip, end to end (`WORK` = a working directory, `PY` = that Python):
```bash
bash pieces/reality/prep/fetch.sh                                    # clip_00 + depth model into out/fsd-data
pieces/reality/prep/jobs/local_clip_cpu.sh clip_04 270               # prep, cars, packaging, COLMAP rig solve (~1-1.5 h CPU)
pieces/reality/prep/jobs/local_clip_gpu.sh clip_04 270               # masks, tracks, world, road, clean-up, piece (~2.5 h GPU)
```
`t0` is drive time across the whole drive (clip k starts near 60·k s; `videos/metadata.jsonl` has `start_s`). Other
clips' videos download like clip_00's (`videos/clip_NN/<camera>.mp4`). The result is `$WORK/demo_cNN.mp4`.

The steps inside, in order: `prep.py` → `cars.py` → `prep.py --skip-frames --skip-depth` → `gs_package.py` →
`sfm.py` → `sfm_rig.py` → `sfm_rig2.py` → `level.py` → `road_init.py` (CPU); then `motion_masks.py` (flow verdict per
vehicle instance) → `camdump.mjs` (chase path, via `local_piece.sh` with `CAMDUMP_ONLY=1`) → `force_moving.py` →
`detect_pinhole.py` → `traffic3d.py` → `track_masks.py` (3D verdict per instance) → `make_refs.py` + `motion_masks.py
--frames --inpaint` (Difix references) → `gs_train.py` → `roadsplat_gpu.py` → `refine_job.py` (`refine_finish.py`
resumes it after an interrupted Difix pass) → `road_map.py` (camera views, then `--chase` on the rendered frames) →
`traffic3d.py` again with the final masks and both road maps → `local_piece.sh` (`sfm_align.py`,
tracks into `index.json`, `dedupe_cars.py`, `car_sanity.py`, `pano.py`, `rv check`, `rv render`).

`proj_eval.py` scores any track set against the detections (precision, recall, IoU of projected 3D boxes).

The same steps also run as Hugging Face Jobs (`jobs/sfm_job.sh`, `jobs/chain11.sh`) with the buckets
`wilsonchenghy/reality-gs-in` / `wilsonchenghy/reality-gs-out` mounted at `/data` and `/out`.

Debug views: `rv stills reality --t 6 --query nosplat|plate|platecars|dbgcam|proj|raw`.

## Lessons that cost time (do not repeat)

- **Camera geometry first.** Every foggy world before v6 came from hand calibration being 2–8° off per camera, and
  the solved world being tilted 0.74°. Rig-constrained structure from motion, fixed measured mount positions and a
  levelled world fixed it.
- **The road needs its own layer.** Training cannot resolve paint seen at grazing angles; cast it from the nearest views.
- **Per-frame diffusion flickers.** Distil it into the 3D world (fine-tune on cleaned views), then deflicker.
- **Mask vehicles before training.** Otherwise they bake in as blobs that the clean-up turns into half-real cars.
- **Moving, not all, vehicles must be hidden from training.** Hiding every vehicle empties the parking lots; hiding none
  bakes traffic in as ghosts. Decide per instance (flow) and per vehicle (3D tracks), and draw exactly what is hidden.
- **Ground-lift range is biased, bearings are not.** A 10% range bias makes a parked car slide as we drive past; decide
  parked vs moving from bearings (triangulation), not from fitted speed.
- **16 GB cards:** keep training images, depth targets and flow fields in pinned host memory and copy one view per step.
- **Disk:** a clip needs ~15 GB while it is solved (COLMAP databases); delete `sfm*/db.db` once `cameras_rig3.json` exists.
- **Shared lists in Python:** `sfm_align.py` once aliased the telemetry keyframes to the solved ones, so traffic was
  never moved into the solved frame (fixed with deep copies). Check that transforms change the data.
- Two jobs were silently **cancelled when the HF credit ran out**: check the balance before long runs.

## Files

- `pieces/reality/index.html`: the piece (Gaussian splat renderer, CAD vehicles, path, HUD, plate and debug modes).
- `pieces/reality/prep/`: the whole pipeline (README there). `rig.json` is the lane-line calibration.
- `pieces/reality/cad/` + `models/`: the CAD vehicle programs (build123d, made with the Prometheus CAD harness) and their GLBs.
- `pieces/reality/BRIEF.md`: the creative brief (layout, palette, timing).
- `docs/`: the motion harness (workflow, review, recipes; `recipes.md` has the reconstruction notes).
