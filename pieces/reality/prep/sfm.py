"""Structure from motion on the packaged drive: the cameras made to agree to the pixel (vogel: "find the same thing in two
cameras ... align until that crack matches"). Starts from the calibrated rig x telemetry trajectory, so no image has to
be registered from scratch:
  SIFT on every pinhole image (sky / ego / moving cars masked) -> match pairs chosen from the prior poses
  (same camera over time + overlapping neighbours) -> triangulate with the prior poses -> bundle-adjust poses + focal
  -> retriangulate -> BA -> similarity-align the refined camera centres back onto the telemetry frame.
Writes <gs>/cameras_sfm.json (same schema as cameras.json) and <gs>/points_sfm.npy (x,y,z,r,g,b,size,road=0).
usage: python3 pieces/reality/prep/sfm.py [gs_dir]    (gs_dir from gs_package.py; default out/reality-gs)
"""
import json, math, os, sys, shutil
import numpy as np, pycolmap
from scipy.spatial.transform import Rotation

G = sys.argv[1] if len(sys.argv) > 1 else 'out/reality-gs'
W = f'{G}/sfm'; os.makedirs(W, exist_ok=True)
meta = json.load(open(f'{G}/cameras.json')); IM = meta['images']
CAMS = meta['cams']
# ---- image tree: <W>/img/<cam>/NNNN.jpg + masks <W>/mask/<cam>/NNNN.jpg.png (colmap mask naming)
for e in IM:
    for sub, src, ext in (('img', e['file'], ''), ('mask', e['mask'], '.png')):
        d = f"{W}/{sub}/{e['cam']}"; os.makedirs(d, exist_ok=True)
        dst = f"{d}/{os.path.basename(e['file'])}{ext}"
        if not os.path.exists(dst): os.symlink(os.path.abspath(f'{G}/{src}'), dst)
db = f'{W}/db.db'
if not os.path.exists(db):
    for cam in CAMS:
        es = [e for e in IM if e['cam'] == cam]; K = es[0]['K']
        ro = pycolmap.ImageReaderOptions(); ro.camera_model = 'PINHOLE'
        ro.camera_params = f"{K[0][0]},{K[1][1]},{K[0][2]},{K[1][2]}"; ro.mask_path = f'{W}/mask'
        eo = pycolmap.FeatureExtractionOptions(); eo.sift.max_num_features = 4096; eo.num_threads = 4
        pycolmap.extract_features(db, f'{W}/img', image_names=[f"{cam}/{os.path.basename(e['file'])}" for e in es],
                                  camera_mode=pycolmap.CameraMode.SINGLE, reader_options=ro, extraction_options=eo)
        print('features', cam, flush=True)
# ---- pairs from the prior poses
name = lambda e: f"{e['cam']}/{os.path.basename(e['file'])}"
C2W = [np.linalg.inv(np.array(e['w2c'])) for e in IM]
cen = np.array([c[:3, 3] for c in C2W]); fwd = np.array([c[:3, 2] for c in C2W])
NB = {'front': ['left_pillar', 'right_pillar'], 'left_pillar': ['front', 'left_repeater'], 'right_pillar': ['front', 'right_repeater'],
      'left_repeater': ['left_pillar', 'back'], 'right_repeater': ['right_pillar', 'back'], 'back': ['left_repeater', 'right_repeater']}
pairs = set()
for i, a in enumerate(IM):
    for j, b in enumerate(IM):
        if j <= i: continue
        dk = abs(a['kf'] - b['kf'])
        same = a['cam'] == b['cam'] and 1 <= dk <= 4
        cross = b['cam'] in NB[a['cam']] and dk <= 3
        wide = a['cam'] == b['cam'] and dk in (6, 10) and np.dot(fwd[i], fwd[j]) > 0.8   # longer baselines for depth
        if same or cross or wide: pairs.add((name(a), name(b)))
open(f'{W}/pairs.txt', 'w').write('\n'.join(f'{a} {b}' for a, b in sorted(pairs)))
print('pairs', len(pairs), flush=True)
if not os.path.exists(f'{W}/matched'):
    po = pycolmap.ImportedPairingOptions(); po.match_list_path = f'{W}/pairs.txt'
    mo = pycolmap.FeatureMatchingOptions(); mo.num_threads = 4
    pycolmap.match_image_pairs(db, matching_options=mo, pairing_options=po)
    open(f'{W}/matched', 'w').write('ok')
    print('matched', flush=True)
# ---- known-pose model in colmap text format (ids from the database)
dbh = pycolmap.Database.open(db)
imgs = {im.name: im for im in dbh.read_all_images()}; cams = {c.camera_id: c for c in dbh.read_all_cameras()}
dbh.close()
T = f'{W}/prior'; os.makedirs(T, exist_ok=True)
with open(f'{T}/cameras.txt', 'w') as f:
    for cid, c in cams.items(): f.write(f"{cid} PINHOLE {c.width} {c.height} {' '.join(str(v) for v in c.params)}\n")
with open(f'{T}/images.txt', 'w') as f:
    for e in IM:
        im = imgs[name(e)]; V = np.array(e['w2c']); q = Rotation.from_matrix(V[:3, :3]).as_quat()   # x y z w
        f.write(f"{im.image_id} {q[3]} {q[0]} {q[1]} {q[2]} {V[0, 3]} {V[1, 3]} {V[2, 3]} {im.camera_id} {name(e)}\n\n")
open(f'{T}/points3D.txt', 'w').write('')
rec = pycolmap.Reconstruction(); rec.read_text(T)
opts = pycolmap.IncrementalPipelineOptions()
start = 0
if os.path.exists(f'{W}/tri2/images.bin') or os.path.exists(f'{W}/tri2/images.txt'):     # resume: last triangulation on disk
    rec = pycolmap.Reconstruction(f'{W}/tri2'); start = 3
    ba = pycolmap.BundleAdjustmentOptions(); ba.refine_focal_length = True; ba.refine_principal_point = False; ba.refine_extra_params = False
    pycolmap.bundle_adjustment(rec, ba); print('resumed tri2 + BA, reproj', round(rec.compute_mean_reprojection_error(), 3), flush=True)
for it in range(start, 3):
    rec = pycolmap.triangulate_points(rec, db, f'{W}/img', f'{W}/tri{it}', clear_points=True, options=opts)
    print('iter', it, 'points', rec.num_points3D(), 'reproj', round(rec.compute_mean_reprojection_error(), 3), flush=True)
    ba = pycolmap.BundleAdjustmentOptions(); ba.refine_focal_length = True; ba.refine_principal_point = False; ba.refine_extra_params = False
    pycolmap.bundle_adjustment(rec, ba)
    print('  after BA reproj', round(rec.compute_mean_reprojection_error(), 3), flush=True)
os.makedirs(f'{W}/final', exist_ok=True); rec.write_text(f'{W}/final')
# ---- back to the telemetry frame: similarity from refined centres to prior centres (Umeyama)
by = {rec.image(i).name: rec.image(i) for i in rec.reg_image_ids()}
P, Q = [], []
for e, c in zip(IM, C2W):
    im = by.get(name(e))
    if im is None: continue
    M = np.eye(4); M[:3] = im.cam_from_world().matrix(); P.append(np.linalg.inv(M)[:3, 3]); Q.append(c[:3, 3])
P, Q = np.array(P), np.array(Q)
mp, mq = P.mean(0), Q.mean(0); X, Y = P - mp, Q - mq
U, S, Vt = np.linalg.svd(Y.T @ X / len(P)); D = np.eye(3); D[2, 2] = np.sign(np.linalg.det(U @ Vt))
R = U @ D @ Vt; s = np.trace(np.diag(S) @ D) / (X ** 2).sum(1).mean(); t = mq - s * R @ mp
print('sim3 scale', round(s, 4), 'rot deg', round(math.degrees(math.acos(np.clip((np.trace(R) - 1) / 2, -1, 1))), 3),
      'centre residual m', round(float(np.linalg.norm((s * (R @ P.T)).T + t - Q, axis=1).mean()), 3))
Sw = np.eye(4); Sw[:3, :3] = s * R; Sw[:3, 3] = t          # sfm-world -> telemetry-world
out = []
for e in IM:
    im = by.get(name(e)); e2 = dict(e)
    if im is not None:
        M = np.eye(4); M[:3] = im.cam_from_world().matrix()
        c2w = Sw @ np.linalg.inv(M); c2w[:3, :3] /= s          # remove scale from the rotation part
        e2['w2c'] = np.linalg.inv(c2w).tolist()
        c = rec.camera(im.camera_id); e2['K'] = [[c.params[0], 0, c.params[2]], [0, c.params[1], c.params[3]], [0, 0, 1]]
        e2['sfm'] = True
    out.append(e2)
json.dump(dict(meta, images=out), open(f'{G}/cameras_sfm.json', 'w'))
pts = []
for pid, p in rec.points3D.items():
    if p.track.length() < 3 or p.error > 2.0: continue
    xyz = (Sw @ np.r_[p.xyz, 1])[:3]; pts.append([*xyz, *(p.color / 255.0), 0.15, 0.0])
pts = np.array(pts, np.float32); np.save(f'{G}/points_sfm.npy', pts)
print('wrote cameras_sfm.json, points_sfm.npy', len(pts), 'registered', len(by), '/', len(IM))
