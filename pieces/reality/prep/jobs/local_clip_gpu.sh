#!/bin/bash
# Local single-GPU path (tested on a 16 GB RTX 5070 Ti). Environment:
#   WORK   working directory for packs, runs and logs (default ~/rv-work)
#   PY     python with torch (CUDA), gsplat, ultralytics, diffusers 0.25.1 / transformers 4.38 / peft 0.9 (Difix),
#          pandas, pyarrow, onnxruntime, pycolmap (default: python3)
#   DIFIX_SRC  a clone of github.com/nv-tlabs/Difix3D/src
# New clip, GPU part (after clip_cpu.sh): motion masks, chase camera path, multi-camera traffic tracks, track-consistent
# masks, Difix references with only moving cars removed, world + road + refine, traffic again, the piece.
# usage: local_clip_gpu.sh clip_04 270   (after local_clip_cpu.sh)
set -ex
CLIP=$1; T0=$2; N=${CLIP#clip_}; export CLIP
W=${WORK:-$HOME/rv-work}; G=$W/gs-c$N; D=out/reality-data-c$N; PR=pieces/reality/prep
cd "$(dirname "$0")/../../../.."; R=$PWD
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True; PY=${PY:-python3}; J=$R/pieces/reality/prep/jobs
date
$PY -u $PR/motion_masks.py --pack $G --cams cameras_rig3.json --out $G/masks_static
DATA16=$D PACK=$G CAMDUMP_ONLY=1 $J/local_piece.sh $G $G $G c$N 0
cp out/reality-data/chase_cams.json $G/chase_cams.json; cp out/reality-data/index.json $W/index_solved_c$N.json
$PY -u $PR/force_moving.py --pack $G --index $W/index_solved_c$N.json --masks $G/masks_static --out $G/masks_fused
$PY -u $PR/detect_pinhole.py --pack $G --out $W/dets_c$N.json
$PY $PR/traffic3d.py --dets $W/dets_c$N.json --cams $G/cameras_rig3.json --index $W/index_solved_c$N.json --static-masks $G/masks_fused --out $W/tracks_c$N.json
$PY -u $PR/track_masks.py --pack $G --tracks $W/tracks_c$N.json --masks $G/masks_fused --out $G/masks_tracks
$PY -c "
import json; m = json.load(open('$G/cameras_rig3.json'))
for e in m['images']: e['mask'] = 'masks_tracks/' + e['mask'].split('/')[-1]
json.dump(m, open('$G/cameras_rig3_t.json', 'w'))"
$PY $PR/make_refs.py --t0 $T0 --out $G/ref_raw
$PY -u $PR/motion_masks.py --frames $G/ref_raw --out $G/ref --inpaint
cp $PR/difix_worker.py $PR/deflicker_gpu.py $G/
date
cd $W
$PY -u $R/$PR/gs_train.py --data $G --out $W/v-c$N --cams cameras_rig3_t.json --points points_v9.npy --max-init 2500000 --pose-opt 0 --ego-prune 1 --sh 2 --iters 30000 --scale 1.0 --depth-w 0.05 --opac-w 0.0005
$PY -u $R/$PR/roadsplat_gpu.py --gs $G --cams cameras_rig3_t.json --world $W/v-c$N/world_gs.bin --out $W/road-c$N --align 3
$PY -u $R/$PR/refine_job.py --data $G --cams cameras_rig3_t.json --ply $W/v-c$N/splats.ply --road $W/road-c$N/road_gs.bin --out $W/refine-c$N || $PY -u $R/$PR/refine_finish.py $W/refine-c$N $G
date
cd $R
$PY $PR/traffic3d.py --dets $W/dets_c$N.json --cams $G/cameras_rig3.json --index $W/index_solved_c$N.json --static-masks $G/masks_tracks --out $W/tracks_c${N}_final.json
TRACKS=$W/tracks_c${N}_final.json DATA16=$D PACK=$G $J/local_piece.sh $W/refine-c$N $W/road-c$N $W/refine-c$N/frames c$N 0
echo CLIP_GPU_DONE
