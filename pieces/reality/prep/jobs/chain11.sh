set -ex
nvidia-smi --query-gpu=name --format=csv
apt-get update -qq >/dev/null && apt-get install -y -qq git >/dev/null
git clone -q https://github.com/nv-tlabs/Difix3D /tmp/Difix3D
pip install -q gsplat opencv-python-headless diffusers==0.25.1 transformers==4.38.0 huggingface-hub==0.25.1 peft==0.9.0 accelerate einops torch==2.5.1 torchvision==0.20.1 2>&1 | tail -1
mkdir -p /tmp/d && tar -xf /data/pack16mm.tar -C /tmp/d && tar -xf /data/refm.tar -C /tmp/d
cp /data/chase_cams.json /data/deflicker_gpu.py /data/difix_worker.py /tmp/d/ && cp /data/gs_train_v6.py /tmp/d/gs_train.py
python -u /tmp/d/gs_train.py --data /tmp/d --out /tmp/v11 --cams cameras_rig3.json --points points_v9.npy --max-init 2500000 --pose-opt 0 --ego-prune 0 --sh 2 --iters 30000 --scale 1.0 --depth-w 0.05 --opac-w 0.0005
mkdir -p /out/v11 && cp /tmp/v11/log.txt /tmp/v11/world_gs.bin /tmp/v11/splats.ply /out/v11/
python -u /data/roadsplat_gpu.py --gs /tmp/d --cams cameras_rig3.json --world /tmp/v11/world_gs.bin --out /tmp/road11 --align 3
mkdir -p /out/road11 && cp /tmp/road11/road_gs.bin /tmp/road11/world_gs.bin /out/road11/
python -u /data/refine_job.py --data /tmp/d --ply /tmp/v11/splats.ply --road /tmp/road11/road_gs.bin --out /tmp/refine11
mkdir -p /out/refine11 && cp -r /tmp/refine11/frames /out/refine11/ && cp /tmp/refine11/world_gs.bin /out/refine11/
echo CHAIN10_DONE
