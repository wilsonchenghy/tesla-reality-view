set -ex
pip install -q pycolmap scipy opencv-python-headless pillow numpy 2>&1 | tail -1
mkdir -p /tmp/g && tar -xf /data/pack16.tar -C /tmp/g
mkdir -p /tmp/p && cp /data/sfmjob/* /tmp/p/
cd /tmp
G=/tmp/g
python -u /tmp/p/sfm.py $G 2>&1 | grep --line-buffered -v "^I20\|^W20"
python -u /tmp/p/sfm_rig.py $G 2>&1 | grep --line-buffered -v "^I20\|^W20"
python -u /tmp/p/sfm_rig2.py $G 2>&1 | grep --line-buffered -v "^I20\|^W20"
python -u /tmp/p/level.py $G cameras_rig2.json cameras_rig3.json points_rig2.npy points_rig3.npy
python -u /tmp/p/road_init.py $G x cameras_rig3.json
python -c "import numpy as np; a=np.load('$G/points_road.npy'); b=np.load('$G/points_rig3.npy'); np.save('$G/points_v9.npy', np.concatenate([a,b]).astype(np.float32))"
mkdir -p /out/sfm16 && cp $G/cameras_rig*.json $G/points_v9.npy $G/ground.json /out/sfm16/
echo SFM16_DONE
