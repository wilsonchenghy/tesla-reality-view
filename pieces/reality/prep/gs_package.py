"""Package the drive for 3D Gaussian Splatting training (gs_train.py on a GPU).

Writes out/reality-gs/:
  images/NNNN.jpg   keyframe images undistorted to pinhole (calibrated Kannala-Brandt model -> pinhole)
  masks/NNNN.png    255 = use in the loss; 0 = sky, ego body, plate mask, vignette, moving vehicles
  cameras.json      per image: K (3x3), world-to-camera 4x4 (OpenCV: x right, y down, z forward), cam, kf, t
  points.npy        initial points (fused world: x,y,z,r,g,b,size)
usage: python3 pieces/reality/prep/gs_package.py  (after prep.py and cars.py)
"""
import json, math, os, sys
import numpy as np, cv2
from PIL import Image
import os as _os; CLIP = _os.environ.get('CLIP', 'clip_00')    # which one-minute clip of the drive

HERE = os.path.dirname(os.path.abspath(__file__))
D = os.environ.get('RV_DATA', 'out/reality-data'); O = os.environ.get('RV_GS', 'out/reality-gs')
os.makedirs(f'{O}/images', exist_ok=True); os.makedirs(f'{O}/masks', exist_ok=True); os.makedirs(f'{O}/depth', exist_ok=True)
RIG = json.load(open(os.path.join(HERE, 'rig.json')))
idx = json.load(open(f'{D}/index.json'))
cars = json.load(open(f'{D}/cars.json')) if os.path.exists(f'{D}/cars.json') else {'masks': {}}
# mask EVERY detected vehicle (parked or moving), not only the tracked movers: the world learns empty road, and every
# vehicle is drawn as a CAD model instead (MASK_ALL=0 for the old behaviour)
if os.environ.get('MASK_ALL', '1') == '1' and os.path.exists(f'{D}/detections.json'):
    allm = {}
    for dd in json.load(open(f'{D}/detections.json')):
        x1, y1, x2, y2 = dd['box']; pw, ph = 0.08 * (x2 - x1), 0.08 * (y2 - y1)
        if y2 - y1 < float(os.environ.get('MASK_MIN_H', '0.07')): continue      # far (parking-lot) cars stay in the world
        allm.setdefault(str(dd['kf']), {}).setdefault(dd['cam'], []).append([x1 - pw, y1 - ph, x2 + pw, y2 + ph])
    cars = {'masks': allm}; print('masking all detections:', sum(len(v) for m in allm.values() for v in m.values()))
CAMS = ['front', 'left_pillar', 'right_pillar', 'left_repeater', 'right_repeater', 'back']
W, H = 1448, 938
OW, OH = 1448, 938
HFOV = {'front': 52, 'left_pillar': 110, 'right_pillar': 110, 'left_repeater': 104, 'right_repeater': 104, 'back': 118}

def basis(c):
    y, p, r = np.radians([c['yaw'], c['pitch'], c.get('roll', 0)])
    f = np.array([np.sin(y) * np.cos(p), np.sin(p), -np.cos(y) * np.cos(p)])
    rt = np.cross(f, [0, 1, 0]); rt /= np.linalg.norm(rt)
    d = np.cross(f, rt); cr, sr = np.cos(r), np.sin(r)
    return f, cr * rt + sr * d, -sr * rt + cr * d

MAPS = {}
for cam in CAMS:
    c = RIG[cam]
    fx = (OW / 2) / math.tan(math.radians(HFOV[cam] / 2)); K = np.array([[fx, 0, OW / 2], [0, fx, OH / 2], [0, 0, 1.0]])
    ys, xs = np.mgrid[0:OH, 0:OW].astype(np.float64)
    X, Y = (xs + 0.5 - OW / 2) / fx, (ys + 0.5 - OH / 2) / fx
    rho = np.hypot(X, Y); th = np.arctan(rho)
    rp = c['f'] * (th + c.get('k1', 0) * th ** 3 + c.get('k2', 0) * th ** 5)
    u = 0.5 + c.get('cx', 0) + rp * X / np.maximum(rho, 1e-12)
    v = 0.5 + c.get('cy', 0) + rp * Y / np.maximum(rho, 1e-12) * (W / H)
    mx, my = (u * W - 0.5).astype(np.float32), (v * H - 0.5).astype(np.float32)
    inside = (u > 0.002) & (u < 0.998) & (v > 0.002) & (v < 0.998) & (th < math.radians(c.get('maxth', 80)))
    # ego body: rays that hit our own car within 3.5 m
    fw, rt, dn = basis(c)
    ray = X[..., None] * rt + Y[..., None] * dn + fw; ray /= np.linalg.norm(ray, axis=-1, keepdims=True)
    pos = np.array(c['pos']); ego = np.zeros_like(inside)
    if cam in ('left_pillar', 'right_pillar', 'left_repeater', 'right_repeater'):   # body visible at the image edge
        for s in np.linspace(0.05, 3.5, 70):
            p = pos + ray * s
            ego |= (np.abs(p[..., 0]) < 0.88) & (np.abs(p[..., 2]) < 2.42) & (p[..., 1] > 0.15) & (p[..., 1] < 1.62)
    # ground-plane range along each pinhole ray (camera height / downward component), inf above the horizon
    down = -ray[..., 1]; rg = np.where(down > 0.01, pos[1] / np.maximum(down, 1e-6), np.inf)
    MAPS[cam] = dict(K=K, mx=mx, my=my, valid=inside & ~ego, fw=fw, rt=rt, dn=dn, pos=pos, rg=rg, zfac=1 / np.sqrt(1 + X * X + Y * Y))
    print(cam, 'valid', round(MAPS[cam]['valid'].mean(), 3))

import pandas as pd
cf = pd.read_parquet('out/fsd-data/data/camera_frames.parquet'); cf = cf[cf.clip_id == CLIP]
def frame_file(cam, t):
    g = cf[cf.camera == cam]; s = int(round(t * 36)); i = np.searchsorted(g.frame_seq_no.values, s).clip(0, len(g) - 1)
    ids = json.load(open(f'{D}/tmp/{cam}/idx.json')); return f'{D}/tmp/{cam}/{ids.index(int(g.frame_index.values[i])) + 1:04d}.jpg'

preds = np.load(f'{D}/tmp/preds.npz')
SC = json.load(open(f'{D}/scales.json')) if os.path.exists(f'{D}/scales.json') else {}
out = []; n = 0
for k in idx['kf']:
    yw = k['yaw']; Rcw_car = np.array([[math.cos(yw), 0, -math.sin(yw)], [0, 1, 0], [math.sin(yw), 0, math.cos(yw)]])
    for ci, cam in enumerate(CAMS):
        M = MAPS[cam]
        src = cv2.imread(frame_file(cam, k['t']))
        img = cv2.remap(src, M['mx'], M['my'], cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)
        # mask: valid lens area, not black (plate mask / vignette), not sky, not moving vehicles
        m = M['valid'].copy()
        m &= img.astype(int).sum(-1) > 45
        pr = preds[f"{k['i']}_{cam}"]
        prs = cv2.resize(pr, (W, H)); prr = cv2.remap(prs, M['mx'], M['my'], cv2.INTER_LINEAR)
        sky = prr < 0.035 * prr.max()                             # relative inverse depth ~0: sky (rendered as background)
        m &= ~sky
        for x1, y1, x2, y2 in cars['masks'].get(str(k['i']), {}).get(cam, []):
            # box corners in source image -> mask in the pinhole image
            box = (M['mx'] >= x1 * W) & (M['mx'] <= x2 * W) & (M['my'] >= y1 * H) & (M['my'] <= y2 * H)
            m &= ~box
        # inverse z-depth target (0 = no target): road pixels from the calibrated plane, the rest from scaled monocular depth
        key = f"{k['i']}_{cam}"
        if key in SC:
            a, b = SC[key]; r_mono = 1 / np.maximum(a * prr + b, 1e-3)
            rg = M['rg']; road = np.isfinite(rg) & (rg < 40) & (r_mono > 0.85 * rg)
            r = np.where(road, rg, np.where(r_mono < 45, r_mono, np.inf))
            zdep = r * M['zfac']
            inv = np.where(np.isfinite(zdep) & m, 1 / zdep, 0).astype(np.float32)
            conf = np.where(road, 1.0, 0.25).astype(np.float32) * (inv > 0)
            np.save(f'{O}/depth/{n:04d}.npy', np.stack([cv2.resize(inv, (OW // 2, OH // 2), interpolation=cv2.INTER_NEAREST),
                                                        cv2.resize(conf, (OW // 2, OH // 2), interpolation=cv2.INTER_NEAREST)]).astype(np.float16))
        cv2.imwrite(f'{O}/images/{n:04d}.jpg', img, [cv2.IMWRITE_JPEG_QUALITY, 92])
        cv2.imwrite(f'{O}/masks/{n:04d}.png', (m * 255).astype(np.uint8))
        Rc = np.stack([M['rt'], M['dn'], M['fw']], 1)               # camera axes in car frame (OpenCV)
        Rwc = Rcw_car @ Rc; twc = Rcw_car @ M['pos'] + np.array([k['x'], 0, k['z']])
        w2c = np.eye(4); w2c[:3, :3] = Rwc.T; w2c[:3, 3] = -Rwc.T @ twc
        out.append(dict(i=n, file=f'images/{n:04d}.jpg', mask=f'masks/{n:04d}.png', cam=cam, cam_id=ci, kf=k['i'], t=k['t'],
                        K=M['K'].tolist(), w2c=w2c.tolist(), width=OW, height=OH, depth=f'depth/{n:04d}.npy' if f"{k['i']}_{cam}" in SC else None))
        n += 1
    if k['i'] % 30 == 0: print('kf', k['i'], flush=True)
json.dump(dict(images=out, cams=CAMS), open(f'{O}/cameras.json', 'w'))
# initial points from the fused world
dt = np.dtype([('p', '<f4', 3), ('c', 'u1', 3), ('k', 'u1'), ('n', 'i1', 3), ('s', 'u1')])
w = np.fromfile(f'{D}/world.bin', dtype=dt)
pts = np.concatenate([w['p'], w['c'].astype(np.float32) / 255, (0.01 * 1.04 ** w['s'].astype(np.float32))[:, None], (w['k'] & 1).astype(np.float32)[:, None]], 1)
np.save(f'{O}/points.npy', pts.astype(np.float32))
print('images', n, 'points', len(pts))
