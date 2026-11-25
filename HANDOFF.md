# Handoff: Tesla Reality View recreation

For the next working session, which has GPU access. Read this file first, then `pieces/reality/prep/README.md`.

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

## Where it stands (best = v16)

Scene: clip_00, drive time 6–26 s (a left turn through an intersection, then 47 mph on a divided road and a right lane change).

| Stage | State | Numbers |
|---|---|---|
| Camera rig | 6 cameras, lane-line calibration, then a **rig-constrained COLMAP solve** (solved mount rotations, measured mount positions, gravity-levelled) | 0.6–0.7 px reprojection; front camera 1.48 m above the road (±0.1–0.2 m) |
| World | 3D Gaussian splatting (gsplat) on 2,166 views (16 fps keyframes × 6 cams), depth-supervised, near vehicles masked | held-out PSNR **23.4** (v10); 8 fps runs 21.6 |
| Road | separate layer: 4.2 M flat 5 cm Gaussians cast from the nearest views, lane-line (ECC) registration, per-camera shading maps | sharp paint, small residual quilt |
| Clean-up | Difix3D+ (`nvidia/difix_ref`): render the chase path → Difix → fine-tune the world on cleaned views + real photos → render → Difix → RAFT deflicker | removes most splat blur; flicker controlled |
| Traffic | YOLO11s on all cameras → lift to ground → track → 31 CAD models (`pieces/reality/models/*.glb`); road-regularised, path sanity check, coasting in/out | positions still the weakest part (see below) |
| HUD | speed, PRND, blinkers, Self-Driving state, maneuver card, sky chevrons, blue path; all values from telemetry | done |

## The open problems, in priority order

1. **Blurry real cars baked into the world (most visible).** The v10 world was trained with only vehicles taller than
   7% of the image masked; mid-distance cars stayed in it, and Difix copies cars from its reference photo.
   **Ready to run:** `jobs/chain11.sh` retrains with nearly every vehicle masked (`MASK_MIN_H=0.02` in `gs_package.py`)
   and uses car-free Difix references (`ref_nocars.py`). The inputs are already uploaded (`pack16mm.tar`, `refm.tar`).
   It was cancelled when the Hugging Face credit ran out. Rerun it, then point the piece at `/out/refine11/frames`.
2. **Traffic accuracy is heuristic.** Each car's 3D position comes from one 2D box plus a flat-ground assumption, and
   frames are linked by a nearest-neighbour rule. That is fine near the car and metres off far away or in turns. It is
   patched by rules (`car_sanity.py`, `car_regularize.py`, `dedupe_cars.py`) but has never been *measured*. Do this properly:
   1. **Measure:** project every modelled car into all 6 cameras every keyframe and score its overlap (IoU) with the
      detections. Report a per-car and per-frame accuracy table, and build every later step against it.
   2. **Better 3D:** take the metric depth at the detection (Depth Anything, already scaled per image) and combine
      the cameras that see the car at the same moment, instead of the box bottom on a flat ground.
   3. **Real tracking:** a constant-velocity Kalman filter per vehicle in world coordinates, fed by all cameras, with
      Hungarian association. Headings come from the filter, not from frame differences.
   4. **Fit:** refine each car's pose so its projected box or silhouette matches the detections (or use segmentation masks).
   A monocular 3D detector (for example an Omni3D / Cube R-CNN-style model) is worth trying for orientation.
3. **Highway generalisation fails.** On clip_02 (60 mph highway, drive time 140–160 s) the world scores held-out PSNR
   **18.1** against 23.4 on clip_00. Causes: 8 fps keyframes are 3.4 m apart at that speed; the solve drifts along a
   straight road with repetitive dashes (11 m mean residual to telemetry); there is little parallax.
   Fix: 16–36 fps keyframes; telemetry speed and heading as pose priors in the bundle adjustment; then rerun the
   full chain. The data is ready in `out/reality-c2`, and `CLIP=clip_02` works for every prep script.
4. **Speed.** Make the camera solve GPU-based (COLMAP CUDA build for SIFT matching; the pip `pycolmap` is CPU only),
   run Difix in fp16 with real batching (the attempted batching fell back to one frame at a time), and keep a warm job
   image so setup (5–7 min of pip and model downloads) is not paid every run. Preview on about 20 frames for
   2-minute rounds.
5. **CAD vehicle look.** The models are clean but read as CG next to the photographic street. Consider matched
   lighting from the per-second street panoramas (`pano.py`, already used as the environment map), slightly softer
   reflections, and a light diffusion pass on the composite (tried once: Difix at its fixed strength barely changes
   the cars, so a stronger image-to-image pass would be needed).

## How to run

The pipeline diagram is in the [README](README.md#pipeline).


Everything heavy runs as Hugging Face Jobs (`hf jobs run`) with two private buckets on the owner's account:
`wilsonchenghy/reality-gs-in` (inputs, scripts) and `wilsonchenghy/reality-gs-out` (results). They are mounted at `/data`
(read-only) and `/out` in the job. Images: `pytorch/pytorch:2.5.1-cuda12.4-cudnn9-devel` for GPU and `python:3.12`
for the CPU solve. Difix needs `diffusers==0.25.1 transformers==4.38.0 huggingface-hub==0.25.1 peft==0.9.0` and
`torch==2.5.1 torchvision==0.20.1` pinned, plus `git clone https://github.com/nv-tlabs/Difix3D`.

Local preparation (CPU, about 15 min per clip), from the repo root:
```bash
bash pieces/reality/prep/fetch.sh                      # dataset clip + depth model into out/fsd-data
CLIP=clip_00 python3 pieces/reality/prep/prep.py --t0 6 --dur 20 --kfps 16 --out out/reality-data16
CLIP=clip_00 python3 pieces/reality/prep/cars.py --out out/reality-data16
CLIP=clip_00 python3 pieces/reality/prep/prep.py --t0 6 --dur 20 --kfps 16 --out out/reality-data16 --skip-frames --skip-depth
MASK_MIN_H=0.02 RV_DATA=out/reality-data16 RV_GS=out/reality-gs16 python3 pieces/reality/prep/gs_package.py
```
Camera solve (CPU job, about 25–60 min): `jobs/sfm_job.sh` (`sfm.py` → `sfm_rig.py` → `sfm_rig2.py` → `level.py` → `road_init.py`).
World + road + clean-up (GPU job): `jobs/chain11.sh` (`gs_train.py` → `roadsplat_gpu.py` → `refine_job.py` with
`difix_worker.py` on every GPU and `deflicker_gpu.py`). `refine_job.py` needs `chase_cams.json`, which comes from the
piece: `node pieces/reality/prep/camdump.mjs`.

Into the piece (local):
```bash
python3 pieces/reality/prep/sfm_align.py --gs out/reality-gs16 --data out/reality-data16 --cams cameras_rig3.json --ground 0
# merge frames/path/cars into out/reality-data/index.json, then:
python3 pieces/reality/prep/car_colors.py out/reality-data/index.json out/reality-data
python3 pieces/reality/prep/dedupe_cars.py out/reality-data/index.json
python3 pieces/reality/prep/car_regularize.py out/reality-data/index.json
python3 pieces/reality/prep/car_sanity.py out/reality-data/index.json
# enhanced frames -> out/reality-data/enhanced/NNNN.jpg, index.json "enhanced": {"n": 600, "dir": "enhanced"}
node bin/rv.mjs check reality && node bin/rv.mjs render reality
```
Debug views: `rv stills reality --t 6 --query nosplat|plate|platecars|dbgcam|proj|raw`.

## Lessons that cost time (do not repeat)

- **Camera geometry first.** Every foggy world before v6 came from hand calibration being 2–8° off per camera, and
  the solved world being tilted 0.74°. Rig-constrained structure from motion, fixed measured mount positions and a
  levelled world fixed it.
- **The road needs its own layer.** Training cannot resolve paint seen at grazing angles; cast it from the nearest views.
- **Per-frame diffusion flickers.** Distil it into the 3D world (fine-tune on cleaned views), then deflicker.
- **Mask vehicles before training.** Otherwise they bake in as blobs that the clean-up turns into half-real cars.
- **The dev container resets when idle.** Run anything longer than a few minutes as an HF Job, never locally.
- **Shared lists in Python:** `sfm_align.py` once aliased the telemetry keyframes to the solved ones, so traffic was
  never moved into the solved frame (fixed with deep copies). Check that transforms change the data.
- Two jobs were silently **cancelled when the HF credit ran out**: check the balance before long runs.

## Files

- `pieces/reality/index.html`: the piece (Gaussian splat renderer, CAD vehicles, path, HUD, plate and debug modes).
- `pieces/reality/prep/`: the whole pipeline (README there). `rig.json` is the lane-line calibration.
- `pieces/reality/cad/` + `models/`: the CAD vehicle programs (build123d, written for a separate CAD harness) and their GLBs.
- `pieces/reality/BRIEF.md`: the creative brief (layout, palette, timing).
- `docs/`: the motion harness (workflow, review, recipes; `recipes.md` has the reconstruction notes).
