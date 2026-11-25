#!/bin/bash
# Local single-GPU path (tested on a 16 GB RTX 5070 Ti). Environment:
#   WORK   working directory for packs, runs and logs (default ~/rv-work)
#   PY     python with torch (CUDA), gsplat, ultralytics, diffusers 0.25.1 / transformers 4.38 / peft 0.9 (Difix),
#          pandas, pyarrow, onnxruntime, pycolmap (default: python3)
#   DIFIX_SRC  a clone of github.com/nv-tlabs/Difix3D/src
# Assemble out/reality-data for the piece from the local prep (reality-data16) and a trained world, then render.
# usage: build_piece.sh WORLD_DIR ROAD_DIR FRAMES_DIR TAG [static_in_world]
set -ex
exec 9>${TMPDIR:-/tmp}/rv_piece.lock; flock 9      # one build at a time: they share out/reality-data
W=$1; R=$2; FR=$3; TAG=$4; STATIC_IN_WORLD=${5:-0}
cd "$(dirname "$0")/../../../.."
WORK=${WORK:-$HOME/rv-work}; PY=${PY:-python3}
rm -rf out/reality-data && mkdir -p out/reality-data
DATA16=${DATA16:-out/reality-data16}; PACK=${PACK:-$WORK/d}
cp $DATA16/index.json $DATA16/cars.json out/reality-data/
for f in $DATA16/*; do b=$(basename $f); [ -e out/reality-data/$b ] || ln -s $(realpath $f) out/reality-data/$b; done
$PY pieces/reality/prep/sfm_align.py --gs $PACK --data out/reality-data --cams cameras_rig3.json --ground 0
if [ -z "$CAMDUMP_ONLY" ]; then   # the chase path needs no world
  cp $W/world_gs.bin out/reality-data/world_gs.bin; cp $R/road_gs.bin out/reality-data/road_gs.bin
  ln -s $(realpath $FR) out/reality-data/enhanced
fi
$PY - <<PY
import json
p = 'out/reality-data/index.json'; d = json.load(open(p))
d['gs'] = True; d['enhanced'] = {'n': 600, 'dir': 'enhanced'}
if $STATIC_IN_WORLD:     # parked vehicles are photoreal in the world: draw only traffic as models
    n0 = len(d['cars']); d['cars'] = [c for c in d['cars'] if not c.get('static')]; print('cars', n0, '->', len(d['cars']))
import os
if os.environ.get('TRACKS'):   # traffic3d.py tracks (solved frame): draw exactly the vehicles hidden from the world
    T = json.load(open(os.environ['TRACKS'])); d['cars'] = [t for t in T if t.get('hidden', True)]; print('traffic3d cars', len(d['cars']))
json.dump(d, open(p, 'w'))
PY
[ -n "$TRACKS" ] || $PY pieces/reality/prep/car_colors.py out/reality-data/index.json out/reality-data
$PY pieces/reality/prep/dedupe_cars.py out/reality-data/index.json
[ -n "$TRACKS" ] || $PY pieces/reality/prep/car_regularize.py out/reality-data/index.json
$PY pieces/reality/prep/car_sanity.py out/reality-data/index.json
[ -f out/reality-data/pano.json ] || CLIP=${CLIP:-clip_00} $PY pieces/reality/prep/pano.py
[ -n "$CAMDUMP_ONLY" ] && { node pieces/reality/prep/camdump.mjs; echo CAMDUMP_DONE; exit 0; }
node bin/rv.mjs check reality
node bin/rv.mjs render reality
cp out/reality/reality.mp4 $WORK/demo_$TAG.mp4
ls -la out/*.mp4 pieces/reality/*.mp4 2>/dev/null || true
echo BUILD_DONE $TAG
