#!/bin/bash
# Launch 3DGS training on Hugging Face Jobs. Needs an HF write token (HF_TOKEN, or injected by a proxy).
#   bash pieces/reality/prep/gs_launch.sh [flavor] [iters]      e.g.  a10g-large 15000   (smoke test: t4-small 300)
# Inputs: out/reality-gs (gs_package.py) -> private bucket <user>/reality-gs-in, mounted read-only at /data
# Output: private bucket <user>/reality-gs-out, mounted read-write at /out (no token needed inside the job)
set -e
FLAVOR=${1:-a10g-large}; ITERS=${2:-15000}
export HF_TOKEN=${HF_TOKEN:-hf_proxy_injected_placeholder_000000}
USER=$(hf auth whoami 2>/dev/null | grep -o 'user=[^ ]*' | cut -d= -f2); USER=${USER:-wilsonchenghy}
cp pieces/reality/prep/gs_train.py pieces/reality/prep/gs_job.sh out/reality-gs/
hf buckets create $USER/reality-gs-in --private --exist-ok 2>/dev/null || true
hf buckets create $USER/reality-gs-out --private --exist-ok 2>/dev/null || true
hf buckets sync out/reality-gs hf://buckets/$USER/reality-gs-in
hf jobs run --flavor $FLAVOR --timeout 2h --detach --name reality-gs \
  -v hf://buckets/$USER/reality-gs-in:/data:ro -v hf://buckets/$USER/reality-gs-out:/out \
  pytorch/pytorch:2.5.1-cuda12.4-cudnn9-devel bash /data/gs_job.sh --iters $ITERS
echo "logs:     hf jobs logs <id>"
echo "download: hf buckets sync hf://buckets/$USER/reality-gs-out out/reality-gs-out && cp out/reality-gs-out/world_gs.bin out/reality-data/"
