"""Metric rig solve, stage 2: camera mount ROTATIONS from the free rig solve (sfm_rig.py, well conditioned), mount
POSITIONS fixed to the measured mounting points (the free solve let them drift: all six lenses sit within ~2 m while the
scene is 20-50 m away), then only the car's motion (rig_from_world per frame) and the points are re-solved.
Writes <gs>/cameras_rig2.json, <gs>/points_rig2.npy and prints camera heights (front should be ~1.48 m above the road).
"""
import json, math, os, sys, shutil
import numpy as np, pycolmap
from scipy.spatial.transform import Rotation
HERE = os.path.dirname(os.path.abspath(__file__))
G = sys.argv[1] if len(sys.argv) > 1 else 'out/reality-gs'
W1 = f'{G}/sfm_rig'; W = f'{G}/sfm_rig2'; os.makedirs(W, exist_ok=True)
RIG = json.load(open(os.path.join(HERE, 'rig.json')))
meta = json.load(open(f'{G}/cameras.json')); IM = meta['images']; CAMS = meta['cams']
new = lambda e: f"{e['cam']}/{e['kf']:04d}.jpg"
free = pycolmap.Reconstruction(f'{W1}/final')
# camera rotation in the rig (front) frame from the free solve: median over frames of R_c * R_front^T
rot = {c: [] for c in CAMS}
by_name = {free.image(i).name: free.image(i) for i in free.reg_image_ids()}
for k in sorted({e['kf'] for e in IM}):
    f = by_name.get(f'front/{k:04d}.jpg')
    if f is None: continue
    Rf = f.cam_from_world().rotation.matrix()
    for c in CAMS:
        im = by_name.get(f'{c}/{k:04d}.jpg')
        if im is not None: rot[c].append(im.cam_from_world().rotation.matrix() @ Rf.T)
Rcf = {c: Rotation.from_matrix(np.array(v)).mean().as_matrix() for c, v in rot.items()}
# mount positions: measured, in the car frame -> front-camera frame (front rotation from the prior calibration)
def basis(c):
    y, p, r = np.radians([c['yaw'], c['pitch'], c.get('roll', 0)])
    f = np.array([np.sin(y) * np.cos(p), np.sin(p), -np.cos(y) * np.cos(p)])
    rt = np.cross(f, [0, 1, 0]); rt /= np.linalg.norm(rt); d = np.cross(f, rt); cr, sr = np.cos(r), np.sin(r)
    return f, cr * rt + sr * d, -sr * rt + cr * d
fw, rt, dn = basis(RIG['front']); R_front_from_car = np.stack([rt, dn, fw], 0)
pf = np.array(RIG['front']['pos'])
cfg_cams = []
for c in CAMS:
    cc = R_front_from_car @ (np.array(RIG[c]['pos']) - pf)          # camera centre in the rig (front) frame
    R = Rcf[c]; t = -R @ cc
    rc = pycolmap.RigConfigCamera(); rc.image_prefix = f'{c}/'; rc.ref_sensor = (c == 'front')
    if c != 'front': rc.cam_from_rig = pycolmap.Rigid3d(pycolmap.Rotation3d(R), t)
    cfg_cams.append(rc)
    print(c, 'rot vs front (deg)', round(math.degrees(Rotation.from_matrix(R).magnitude()), 2), 'centre in rig', cc.round(2))
cfg = pycolmap.RigConfig(); cfg.cameras = cfg_cams
db = f'{W}/db.db'
if not os.path.exists(db): shutil.copy(f'{W1}/db.db', db)
# start from the free solve's frame poses (images text), re-rigged with the fixed mounts
if os.path.exists(f'{W}/final/images.txt'):
    rec = pycolmap.Reconstruction(f'{W}/final'); ITERS = 0; print('reusing solved model')
else:
    rec = pycolmap.Reconstruction(f'{W1}/prior')
    pycolmap.apply_rig_config([cfg], pycolmap.Database.open(db), rec); ITERS = 3
opts = pycolmap.IncrementalPipelineOptions()
# the triangulator runs its own global BA: keep the mounts (and intrinsics) fixed there too
opts.ba_refine_sensor_from_rig = False; opts.ba_refine_focal_length = False; opts.ba_refine_principal_point = False; opts.ba_refine_extra_params = False
for it in range(ITERS):
    rec = pycolmap.triangulate_points(rec, db, f'{W1}/img', f'{W}/tri{it}', clear_points=True, options=opts)
    ba = pycolmap.BundleAdjustmentOptions()
    for k, v in dict(refine_focal_length=(it == 2), refine_principal_point=False, refine_extra_params=False,
                     refine_sensor_from_rig=False, refine_rig_from_world=True).items():
        if hasattr(ba, k): setattr(ba, k, v)
    pycolmap.bundle_adjustment(rec, ba)
    errs = [p.error for p in rec.points3D.values() if np.isfinite(p.error)]
    print(f'iter {it}: points {rec.num_points3D()} median reproj {np.median(errs):.3f}', flush=True)
os.makedirs(f'{W}/final', exist_ok=True)
if ITERS: rec.write_text(f'{W}/final')
by = {rec.image(i).name: rec.image(i) for i in rec.reg_image_ids()}
# orientation from gravity: the car's up axis in every solved frame (through the fixed rig), averaged -> world +y;
# height from the front camera's mount (1.48 m over the road); heading/position by a 2D fit to telemetry (HUD alignment)
ups, Pf, Qf = [], [], []
for e in IM:
    im = by.get(new(e))
    if im is None or e['cam'] != 'front': continue
    M = np.eye(4); M[:3] = im.cam_from_world().matrix(); c2w = np.linalg.inv(M)
    ups.append(c2w[:3, :3] @ R_front_from_car @ np.array([0, 1.0, 0])); Pf.append(c2w[:3, 3]); Qf.append(np.linalg.inv(np.array(e['w2c']))[:3, 3])
up = np.mean(ups, 0); up /= np.linalg.norm(up)
v = np.cross(up, [0, 1, 0]); sn = np.linalg.norm(v); cs = up @ [0, 1, 0]
Vx = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])
R1 = np.eye(3) + Vx + Vx @ Vx * ((1 - cs) / max(sn ** 2, 1e-12))     # rotates up -> +y
Pf = (R1 @ np.array(Pf).T).T; Qf = np.array(Qf)
yoff = 1.48 - np.median(Pf[:, 1])                                     # front camera 1.48 m above the road (road = y 0)
# 2D rigid fit (rotation about y + xz translation) of the front path onto telemetry
pm, qm = Pf[:, [0, 2]].mean(0), Qf[:, [0, 2]].mean(0); X = Pf[:, [0, 2]] - pm; Y = Qf[:, [0, 2]] - qm
H2 = X.T @ Y; th = math.atan2(H2[0, 1] - H2[1, 0], H2[0, 0] + H2[1, 1])
c_, s_ = math.cos(th), math.sin(th); R2 = np.array([[c_, 0, -s_], [0, 1, 0], [s_, 0, c_]])
# sign check: pick the rotation direction that fits better
def fit(Rr):
    Z = (Rr @ np.c_[X[:, 0], np.zeros(len(X)), X[:, 1]].T).T[:, [0, 2]]; return np.linalg.norm(Z - Y, axis=1).mean()
R2b = R2.T
if fit(R2b) < fit(R2): R2 = R2b
res = fit(R2)
R = R2 @ R1
tx = qm - (R2 @ np.r_[pm[0], 0, pm[1]])[[0, 2]]
t = np.array([tx[0], yoff, tx[1]])
print('gravity align: tilt corrected (deg)', round(math.degrees(math.acos(np.clip(cs, -1, 1))), 2), ' 2D path residual mean m', round(float(res), 2))
Sw = np.eye(4); Sw[:3, :3] = R; Sw[:3, 3] = t
out = []; hts = {c: [] for c in CAMS}
for e in IM:
    im = by.get(new(e)); e2 = dict(e)
    if im is not None:
        M = np.eye(4); M[:3] = im.cam_from_world().matrix(); c2w = Sw @ np.linalg.inv(M)
        e2['w2c'] = np.linalg.inv(c2w).tolist(); hts[e['cam']].append(c2w[1, 3])
        c = rec.camera(im.camera_id); e2['K'] = [[c.params[0], 0, c.params[2]], [0, c.params[1], c.params[3]], [0, 0, 1]]
    out.append(e2)
print('camera heights (median):', {c: round(float(np.median(v)), 2) for c, v in hts.items()})
json.dump(dict(meta, images=out), open(f'{G}/cameras_rig2.json', 'w'))
pts = [[*((Sw @ np.r_[p.xyz, 1])[:3]), *(p.color / 255.0), 0.12, 0.0] for p in rec.points3D.values() if p.track.length() >= 3 and np.isfinite(p.error) and p.error < 1.5]
np.save(f'{G}/points_rig2.npy', np.array(pts, np.float32)); print('points', len(pts))
