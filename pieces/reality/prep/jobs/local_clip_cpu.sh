#!/bin/bash
# Local single-GPU path (tested on a 16 GB RTX 5070 Ti). Environment:
#   WORK   working directory for packs, runs and logs (default ~/rv-work)
#   PY     python with torch (CUDA), gsplat, ultralytics, diffusers 0.25.1 / transformers 4.38 / peft 0.9 (Difix),
#          pandas, pyarrow, onnxruntime, pycolmap (default: python3)
#   DIFIX_SRC  a clone of github.com/nv-tlabs/Difix3D/src
# New clip, CPU part: prep (frames, depth, path), cars, packaging to pinhole views, rig-constrained COLMAP solve, levelling,
# road init. usage: local_clip_cpu.sh clip_04 270   (drive time of the window start: clip k starts near 60*k s)
set -ex
CLIP=$1; T0=$2; N=${CLIP#clip_}
cd "$(dirname "$0")/../../../.."; R=$PWD
export CLIP; WORK=${WORK:-$HOME/rv-work}; PY=${PY:-python3}; D=out/reality-data-c$N; G=$WORK/gs-c$N
date
$PY pieces/reality/prep/prep.py --t0 $T0 --dur 20 --kfps 16 --out $D
$PY pieces/reality/prep/cars.py --out $D
$PY pieces/reality/prep/prep.py --t0 $T0 --dur 20 --kfps 16 --out $D --skip-frames --skip-depth
MASK_MIN_H=0.02 RV_DATA=$D RV_GS=$G $PY pieces/reality/prep/gs_package.py
date
export SFM_THREADS=10; cd /tmp && for s in sfm sfm_rig sfm_rig2; do $PY -u $R/pieces/reality/prep/$s.py $G 2>&1 | grep --line-buffered -v "^I20\|^W20"; done
$PY -u $R/pieces/reality/prep/level.py $G cameras_rig2.json cameras_rig3.json points_rig2.npy points_rig3.npy
$PY -u $R/pieces/reality/prep/road_init.py $G x cameras_rig3.json
$PY -c "import numpy as np; a=np.load('$G/points_road.npy'); b=np.load('$G/points_rig3.npy'); np.save('$G/points_v9.npy', np.concatenate([a,b]).astype(np.float32))"
date
echo CLIP_CPU_DONE
