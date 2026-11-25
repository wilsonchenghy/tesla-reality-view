"""360° environment panoramas stitched from the six calibrated cameras (one per second of the drive), world-aligned
equirectangular JPEGs: the cars in the piece reflect, and are lit by, the street they are actually in.
usage: python3 pieces/reality/prep/pano.py   -> out/reality-data/pano/NN.jpg + pano.json
"""
import json, math, os
import numpy as np, cv2
HERE = os.path.dirname(os.path.abspath(__file__))
D = 'out/reality-data'; os.makedirs(f'{D}/pano', exist_ok=True)
RIG = json.load(open(os.path.join(HERE, 'rig.json'))); idx = json.load(open(f'{D}/index.json'))
CAMS = ['front', 'left_pillar', 'right_pillar', 'left_repeater', 'right_repeater', 'back']
W, H = 1448, 938; PW, PH = 1024, 512
def basis(c):
    y, p, r = np.radians([c['yaw'], c['pitch'], c.get('roll', 0)])
    f = np.array([np.sin(y) * np.cos(p), np.sin(p), -np.cos(y) * np.cos(p)])
    rt = np.cross(f, [0, 1, 0]); rt /= np.linalg.norm(rt); d = np.cross(f, rt); cr, sr = np.cos(r), np.sin(r)
    return f, cr * rt + sr * d, -sr * rt + cr * d
import pandas as pd
import os as _os; CLIP = _os.environ.get('CLIP', 'clip_00')    # which one-minute clip of the drive
cf = pd.read_parquet('out/fsd-data/data/camera_frames.parquet'); cf = cf[cf.clip_id == CLIP]
def frame_file(cam, t):
    g = cf[cf.camera == cam]; s = int(round(t * 36)); i = np.searchsorted(g.frame_seq_no.values, s).clip(0, len(g) - 1)
    ids = json.load(open(f'{D}/tmp/{cam}/idx.json')); return f'{D}/tmp/{cam}/{ids.index(int(g.frame_index.values[i])) + 1:04d}.jpg'
# world directions of every panorama pixel (three.js equirect: u=0.5 looks down -z... use its convention: dir = (-sin(lon)... )
v, u = np.mgrid[0:PH, 0:PW].astype(np.float64)
lon = (u + 0.5) / PW * 2 * np.pi - np.pi           # three.js: u -> atan2(dir.z, dir.x)
lat = np.pi / 2 - (v + 0.5) / PH * np.pi
dirw = np.stack([np.cos(lat) * np.cos(lon), np.sin(lat), np.cos(lat) * np.sin(lon)], -1)
times = [k for k in idx['kf'] if abs((k['t'] - idx['t0']) - round(k['t'] - idx['t0'])) < 1e-6 and idx['t0'] - 0.01 <= k['t'] <= idx['t0'] + idx['dur'] + 0.01]
meta = []
for n, k in enumerate(times):
    yw = k['yaw']; c_, s_ = math.cos(yw), math.sin(yw)
    # world -> car frame (inverse of car->world rotation used in prep)
    dc = np.stack([c_ * dirw[..., 0] + s_ * dirw[..., 2], dirw[..., 1], -s_ * dirw[..., 0] + c_ * dirw[..., 2]], -1)
    best = np.full((PH, PW), 9.0); out = np.zeros((PH, PW, 3), np.float32)
    for cam in CAMS:
        c = RIG[cam]; f, rt, d = basis(c)
        zc, xc, yc = dc @ f, dc @ rt, dc @ d
        rho = np.hypot(xc, yc) + 1e-9; th = np.arctan2(rho, zc)
        rp = c['f'] * (th + c.get('k1', 0) * th ** 3 + c.get('k2', 0) * th ** 5)
        pu = 0.5 + rp * xc / rho; pv = 0.5 + rp * yc / rho * (W / H)
        ok = (th < np.radians(c.get('maxth', 80)) * 0.92) & (pu > 0.01) & (pu < 0.99) & (pv > 0.01) & (pv < 0.99)
        img = cv2.imread(frame_file(cam, k['t'])).astype(np.float32)
        smp = cv2.remap(img, (pu * W).astype(np.float32), (pv * H).astype(np.float32), cv2.INTER_LINEAR)
        ok &= smp.sum(-1) > 60
        score = th / np.radians(c.get('maxth', 80)) + (0.15 if cam == 'back' else 0)
        take = ok & (score < best)
        out[take] = smp[take]; best[take] = score[take]
    hole = best > 8
    # sky above the cameras: the mean of the top covered band; below the car: asphalt
    sky = np.median(out[(~hole) & (lat > np.radians(20))], 0) if ((~hole) & (lat > np.radians(20))).any() else np.array([170, 168, 160.0])
    road = np.median(out[(~hole) & (lat < np.radians(-25))], 0)
    fill = np.where((lat > 0)[..., None], sky, road * 0.8)
    out = np.where(hole[..., None], fill, out)
    # soften the seams between cameras
    out = cv2.GaussianBlur(out, (0, 0), 1.2)
    cv2.imwrite(f'{D}/pano/{n:02d}.jpg', np.clip(out, 0, 255).astype(np.uint8), [cv2.IMWRITE_JPEG_QUALITY, 90])
    meta.append(dict(n=n, t=k['t'], sky=[round(float(x) / 255, 4) for x in sky[::-1]]))
json.dump(meta, open(f'{D}/pano.json', 'w'))
print('panoramas', len(meta))
