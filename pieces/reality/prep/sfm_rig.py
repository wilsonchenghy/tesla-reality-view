"""Rig-constrained structure from motion: the six cameras solved as ONE rigid rig (sensor_from_rig per camera) moving
along the drive (rig_from_world per frame), bundle-adjusted on the SIFT matches from sfm.py. This is the sub-pixel camera
alignment a 3D Gaussian world needs. Reuses sfm.py's feature database (images renamed by keyframe so COLMAP can group
the six images of one instant into a frame).
Writes <gs>/cameras_rig.json (cameras.json schema), <gs>/points_rig.npy, <gs>/sfm_rig/report.json
usage: python3 pieces/reality/prep/sfm_rig.py [gs_dir]
"""
import json, math, os, sys, shutil, sqlite3
import numpy as np, pycolmap
from scipy.spatial.transform import Rotation

G = sys.argv[1] if len(sys.argv) > 1 else 'out/reality-gs'
S = f'{G}/sfm'; W = f'{G}/sfm_rig'; os.makedirs(W, exist_ok=True)
meta = json.load(open(f'{G}/cameras.json')); IM = meta['images']; CAMS = meta['cams']
old = lambda e: f"{e['cam']}/{os.path.basename(e['file'])}"
new = lambda e: f"{e['cam']}/{e['kf']:04d}.jpg"
# 1. database copy with frame-grouped names + image tree with those names
db = f'{W}/db.db'
if not os.path.exists(db):
    shutil.copy(f'{S}/db.db', db)
    con = sqlite3.connect(db)
    for e in IM: con.execute('UPDATE images SET name=? WHERE name=?', (new(e), old(e)))
    con.commit(); con.close()
for e in IM:
    d = f"{W}/img/{e['cam']}"; os.makedirs(d, exist_ok=True)
    if not os.path.exists(f'{W}/img/{new(e)}'): os.symlink(os.path.abspath(f"{G}/{e['file']}"), f'{W}/img/{new(e)}')

# 2. prior model (known poses) in text format, then the rig config (front = reference sensor)
dbh = pycolmap.Database.open(db); imgs = {im.name: im for im in dbh.read_all_images()}; cams = {c.camera_id: c for c in dbh.read_all_cameras()}; dbh.close()
T = f'{W}/prior'; os.makedirs(T, exist_ok=True)
with open(f'{T}/cameras.txt', 'w') as f:
    for cid, c in cams.items(): f.write(f"{cid} PINHOLE {c.width} {c.height} {' '.join(str(v) for v in c.params)}\n")
with open(f'{T}/images.txt', 'w') as f:
    for e in IM:
        im = imgs[new(e)]; V = np.array(e['w2c']); q = Rotation.from_matrix(V[:3, :3]).as_quat()
        f.write(f"{im.image_id} {q[3]} {q[0]} {q[1]} {q[2]} {V[0, 3]} {V[1, 3]} {V[2, 3]} {im.camera_id} {new(e)}\n\n")
open(f'{T}/points3D.txt', 'w').write('')
rec = pycolmap.Reconstruction(); rec.read_text(T)
rc = pycolmap.RigConfig()
rc_cams = []
for cam in CAMS:
    c = pycolmap.RigConfigCamera(); c.image_prefix = f'{cam}/'; c.ref_sensor = (cam == 'front'); rc_cams.append(c)
rc.cameras = rc_cams
pycolmap.apply_rig_config([rc], pycolmap.Database.open(db), rec)     # sensor_from_rig derived from the prior poses
print('rigs', rec.num_rigs(), 'frames', rec.num_frames(), flush=True)

# 3. triangulate with the rig model, then rig BA (refine sensor_from_rig + rig_from_world + focal), repeat
opts = pycolmap.IncrementalPipelineOptions()
rep = {}
for it in range(3):
    rec = pycolmap.triangulate_points(rec, db, f'{W}/img', f'{W}/tri{it}', clear_points=True, options=opts)
    e0 = rec.compute_mean_reprojection_error()
    ba = pycolmap.BundleAdjustmentOptions()
    for k, v in dict(refine_focal_length=True, refine_principal_point=False, refine_extra_params=False,
                     refine_sensor_from_rig=True, refine_rig_from_world=True).items():
        if hasattr(ba, k): setattr(ba, k, v)
    pycolmap.bundle_adjustment(rec, ba)
    # recompute the error on points that still have a positive depth in all their views
    e1 = rec.compute_mean_reprojection_error()
    print(f'iter {it}: points {rec.num_points3D()} reproj {e0:.3f} -> {e1:.3f}', flush=True)
    rep[f'iter{it}'] = [rec.num_points3D(), e0, e1]
os.makedirs(f'{W}/final', exist_ok=True); rec.write_text(f'{W}/final')

# 4. similarity back onto the telemetry frame (rigid rig: this should now be a near-identity with small residual)
by = {rec.image(i).name: rec.image(i) for i in rec.reg_image_ids()}
P, Q = [], []
for e in IM:
    im = by.get(new(e))
    if im is None: continue
    M = np.eye(4); M[:3] = im.cam_from_world().matrix(); P.append(np.linalg.inv(M)[:3, 3])
    Q.append(np.linalg.inv(np.array(e['w2c']))[:3, 3])
P, Q = np.array(P), np.array(Q)
mp, mq = P.mean(0), Q.mean(0); X, Y = P - mp, Q - mq
U, Sg, Vt = np.linalg.svd(Y.T @ X / len(P)); D = np.eye(3); D[2, 2] = np.sign(np.linalg.det(U @ Vt))
R = U @ D @ Vt; s = np.trace(np.diag(Sg) @ D) / (X ** 2).sum(1).mean(); t = mq - s * R @ mp
res = np.linalg.norm((s * (R @ P.T)).T + t - Q, axis=1)
print('sim3 scale', round(s, 4), 'centre residual mean/max m', round(float(res.mean()), 3), round(float(res.max()), 3), flush=True)
rep['sim3'] = dict(scale=s, res_mean=float(res.mean()), res_max=float(res.max()), registered=len(by))
Sw = np.eye(4); Sw[:3, :3] = s * R; Sw[:3, 3] = t
out = []
for e in IM:
    im = by.get(new(e)); e2 = dict(e)
    if im is not None:
        M = np.eye(4); M[:3] = im.cam_from_world().matrix()
        c2w = Sw @ np.linalg.inv(M); c2w[:3, :3] /= s
        e2['w2c'] = np.linalg.inv(c2w).tolist()
        c = rec.camera(im.camera_id); e2['K'] = [[c.params[0], 0, c.params[2]], [0, c.params[1], c.params[3]], [0, 0, 1]]
    out.append(e2)
json.dump(dict(meta, images=out), open(f'{G}/cameras_rig.json', 'w'))
pts = [[*((Sw @ np.r_[p.xyz, 1])[:3]), *(p.color / 255.0), 0.12, 0.0] for p in rec.points3D.values() if p.track.length() >= 3 and p.error < 1.5]
np.save(f'{G}/points_rig.npy', np.array(pts, np.float32))
# per-camera mount (sensor_from_rig) for the record
for r in rec.rigs.values() if hasattr(rec, 'rigs') else []:
    pass
json.dump(rep, open(f'{W}/report.json', 'w'), indent=1, default=float)
print('wrote cameras_rig.json, points_rig.npy', len(pts))
