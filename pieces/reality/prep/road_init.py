"""Road sheet seed in the solved (rig SfM) frame: road pixels of every packaged view cast onto the local ground, fused
into 10 cm cells. Ground height per keyframe = mode of trained gaussians under the rig (v5 world), smoothed along the route.
writes <gs>/points_road.npy (x,y,z,r,g,b,size,road=1) and <gs>/ground.json
usage: python3 pieces/reality/prep/road_init.py [gs_dir] [world_gs.bin]
"""
import json, sys, numpy as np
from PIL import Image
from scipy.spatial import cKDTree
G = sys.argv[1] if len(sys.argv) > 1 else 'out/reality-gs'
WB = sys.argv[2] if len(sys.argv) > 2 else 'out/reality-gs-out/v5/world_gs.bin'
CAMF = sys.argv[3] if len(sys.argv) > 3 else 'cameras_rig2.json'
M = json.load(open(f'{G}/{CAMF}'))['images']
C2W = {e['i']: np.linalg.inv(np.array(e['w2c'])) for e in M}
kfs = sorted({e['kf'] for e in M})
rig = {k: np.mean([C2W[e['i']][:3, 3] for e in M if e['kf'] == k], 0) for k in kfs}
# ground under the car = front camera height minus its 1.48 m mount (metric rig), smoothed along the route
front = {e['kf']: C2W[e['i']][1, 3] for e in M if e['cam'] == 'front'}
gy = np.array([front[k] - 1.48 for k in kfs])
gys = np.convolve(np.pad(gy, 4, mode='edge'), np.ones(9) / 9, mode='valid')
GROUND = {int(k): float(v) for k, v in zip(kfs, gys)}
json.dump(dict(ground=GROUND, rig={int(k): rig[k].tolist() for k in kfs}), open(f'{G}/ground.json', 'w'))
print('ground y range', round(gys.min(), 2), round(gys.max(), 2))
pts, cols = [], []
for e in M:
    if e['cam'] == 'back' and e['kf'] % 2: continue
    d = np.load(f"{G}/{e['depth']}").astype(np.float32) if e.get('depth') else None
    if d is None: continue
    road = d[1] >= 0.99                                     # conf 1 = calibrated road pixels (half res)
    ys, xs = np.nonzero(road[::3, ::3]); ys *= 3; xs *= 3
    if len(xs) == 0: continue
    img = np.asarray(Image.open(f"{G}/{e['file']}").convert('RGB'))
    K = np.array(e['K']); c2w = C2W[e['i']]; o = c2w[:3, 3]
    u = (xs + 0.5) * 2; v = (ys + 0.5) * 2                  # half-res -> full-res pixel centres
    rays = np.stack([(u - K[0, 2]) / K[0, 0], (v - K[1, 2]) / K[1, 1], np.ones_like(u, dtype=float)], 1) @ c2w[:3, :3].T
    gyl = GROUND[e['kf']]
    t = (gyl - o[1]) / np.where(np.abs(rays[:, 1]) < 1e-6, -1e-6, rays[:, 1])
    okp = (t > 0) & (t < 40)
    P = o + rays[okp] * t[okp, None]
    pts.append(P); cols.append(img[v[okp].astype(int).clip(0, img.shape[0] - 1), u[okp].astype(int).clip(0, img.shape[1] - 1)] / 255.0)
P = np.concatenate(pts); Cc = np.concatenate(cols)
# fuse into 10 cm cells (median colour of the nearest observations is overkill here: mean of all)
key = np.floor(P[:, [0, 2]] / 0.10).astype(np.int64); kk = key[:, 0] * 10000003 + key[:, 1]
uk, inv, cnt = np.unique(kk, return_inverse=True, return_counts=True)
acc = lambda a: np.bincount(inv, weights=a, minlength=len(uk)) / cnt
F = np.stack([acc(P[:, 0]), acc(P[:, 1]), acc(P[:, 2]), acc(Cc[:, 0]), acc(Cc[:, 1]), acc(Cc[:, 2]), np.full(len(uk), 0.07), np.ones(len(uk))], 1)
F = F[cnt >= 2]
np.save(f'{G}/points_road.npy', F.astype(np.float32)); print('road sheet points', len(F))
