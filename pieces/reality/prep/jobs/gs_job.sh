#!/bin/bash
# runs inside the HF Job (pytorch devel image). /data = packaged inputs (read-only bucket), /out = bucket (read-write)
set -e
nvidia-smi --query-gpu=name,memory.total --format=csv
(pip install -q gsplat 2>&1 | grep -v WARNING | tail -1) || true
python -c "import gsplat; print('gsplat', gsplat.__version__)"
# one archive off the bucket mount, unpacked to local disk: thousands of small reads over the mount are slow
mkdir -p /tmp/data && time tar -xf /data/${PACK:-pack.tar} -C /tmp/data && cp /data/gs_train.py /tmp/data/
python /tmp/data/gs_train.py --data /tmp/data --out /out "$@"
