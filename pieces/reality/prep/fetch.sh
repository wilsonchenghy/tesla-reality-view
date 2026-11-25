#!/bin/bash
# Download what prep.py needs (clip_00: 6 cameras + telemetry, ~360 MB) and the depth model (~100 MB) into out/fsd-data.
# Dataset: https://huggingface.co/datasets/cfahlgren1/tesla-fsd-drive-5min (CC BY 4.0)
set -e
D=${1:-out/fsd-data}; B=https://huggingface.co/datasets/cfahlgren1/tesla-fsd-drive-5min/resolve/main
mkdir -p $D/data $D/videos/clip_00 $D/models
for f in data/telemetry.parquet data/camera_frames.parquet videos/metadata.jsonl; do curl -sSL -o $D/$f $B/$f; done
for c in front back left_pillar right_pillar left_repeater right_repeater; do curl -sSL -o $D/videos/clip_00/$c.mp4 $B/videos/clip_00/$c.mp4 & done; wait
curl -sSL -o $D/models/da2s.onnx https://huggingface.co/onnx-community/depth-anything-v2-small/resolve/main/onnx/model.onnx
echo "next: pip install numpy pillow pandas pyarrow onnxruntime && python3 pieces/reality/prep/prep.py"
