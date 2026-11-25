"""Level the solved world: fit a plane through all front-camera centres (the car drives on a road ~flat over 300 m),
rotate that plane to horizontal and put it 1.48 m (the front mount) above y=0. One rigid transform: every camera keeps
its sub-pixel agreement. usage: level.py gs_dir in_cams.json out_cams.json in_points.npy out_points.npy"""
import json, sys, numpy as np
G, ci, co, pi, po = sys.argv[1:6]
meta = json.load(open(f'{G}/{ci}')); IM = meta['images']
C2W = [np.linalg.inv(np.array(e['w2c'])) for e in IM]
F = np.array([c[:3, 3] for c, e in zip(C2W, IM) if e['cam'] == 'front'])
A = np.c_[F[:, 0], F[:, 2], np.ones(len(F))]; a, b, c = np.linalg.lstsq(A, F[:, 1], rcond=None)[0]   # y = a x + b z + c
n = np.array([-a, 1.0, -b]); n /= np.linalg.norm(n)
v = np.cross(n, [0, 1, 0]); s = np.linalg.norm(v); co_ = n[1]
V = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])
R = np.eye(3) + V + V @ V * ((1 - co_) / max(s * s, 1e-12))
Fr = (R @ F.T).T; t = np.array([0, 1.48 - np.median(Fr[:, 1]), 0])
T = np.eye(4); T[:3, :3] = R; T[:3, 3] = t
res = Fr[:, 1] + t[1] - 1.48
print('tilt removed (deg)', round(float(np.degrees(np.arccos(np.clip(co_, -1, 1)))), 3), ' front height after: p5/p95', np.round(np.percentile(res, [5, 95]), 2))
out = []
for e, c2w in zip(IM, C2W):
    e2 = dict(e); e2['w2c'] = np.linalg.inv(T @ c2w).tolist(); out.append(e2)
json.dump(dict(meta, images=out), open(f'{G}/{co}', 'w'))
P = np.load(f'{G}/{pi}'); P[:, :3] = (R @ P[:, :3].T).T + t; np.save(f'{G}/{po}', P.astype(np.float32))
