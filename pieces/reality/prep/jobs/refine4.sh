set -ex
nvidia-smi --query-gpu=name --format=csv
apt-get update -qq >/dev/null && apt-get install -y -qq git >/dev/null
git clone -q https://github.com/nv-tlabs/Difix3D /tmp/Difix3D
pip install -q gsplat opencv-python-headless diffusers==0.25.1 transformers==4.38.0 huggingface-hub==0.25.1 peft==0.9.0 accelerate einops torch==2.5.1 torchvision==0.20.1 2>&1 | tail -1
mkdir -p /tmp/d && tar -xf /data/pack16m.tar -C /tmp/d && tar -xf /data/plate2.tar -C /tmp/d ref
cp /data/chase_cams.json /data/deflicker_gpu.py /data/difix_worker.py /tmp/d/
python -u /data/refine_job.py --data /tmp/d --ply /out/v10/splats.ply --road /out/road10/road_gs.bin --out /tmp/refine10
mkdir -p /out/refine10 && cp -r /tmp/refine10/frames /out/refine10/ && cp /tmp/refine10/world_gs.bin /out/refine10/
echo REFINE_DONE
