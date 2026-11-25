"""Other cars: detect -> lift to the ground -> track -> (moving ones) cut out of the splats and replaced by 3D models.

Runs after prep.py has extracted keyframe frames (out/reality-data/tmp). Writes out/reality-data/cars.json:
  tracks: [{id, cls, color, moving, t:[...], x:[...], z:[...], yaw:[...], len, wid, hgt}]
  masks:  {"<kf>": {"<cam>": [[x1,y1,x2,y2], ...]}}   image boxes (0..1) of moving vehicles, for prep.py to cut
then re-run: python3 pieces/reality/prep/prep.py --skip-frames --skip-depth

usage: python3 pieces/reality/prep/cars.py [--out out/reality-data] [--model out/fsd-data/models/yolo11s.pt]
needs: ultralytics (CPU torch is enough: ~0.4 s/image)
"""
import argparse, json, math, os, sys
import numpy as np
from PIL import Image
import os as _os; CLIP = _os.environ.get('CLIP', 'clip_00')    # which one-minute clip of the drive

HERE = os.path.dirname(os.path.abspath(__file__))
ap = argparse.ArgumentParser()
ap.add_argument('--out', default='out/reality-data')
ap.add_argument('--model', default='out/fsd-data/models/yolo11s.pt')
ap.add_argument('--conf', type=float, default=0.35)
ap.add_argument('--reuse', action='store_true', help='reuse detections.json')
A = ap.parse_args()

CAMS = ['front', 'left_pillar', 'right_pillar', 'left_repeater', 'right_repeater', 'back']
RIG = json.load(open(os.path.join(HERE, 'rig.json')))
W, H = 1448, 938
idx = json.load(open(f'{A.out}/index.json'))
KF = idx['kf']
tmp = f'{A.out}/tmp'
CLS = {2: 'car', 3: 'moto', 5: 'bus', 7: 'truck'}
SIZE = {'car': (4.7, 1.9, 1.55), 'moto': (2.1, 0.8, 1.4), 'bus': (11.0, 2.55, 3.2), 'truck': (7.2, 2.45, 3.3)}

# ---- camera model (same as prep.py) ----
def basis(c):
    y, p, r = np.radians([c['yaw'], c['pitch'], c.get('roll', 0)])
    f = np.array([np.sin(y) * np.cos(p), np.sin(p), -np.cos(y) * np.cos(p)])
    rt = np.cross(f, [0, 1, 0]); rt /= np.linalg.norm(rt)
    d = np.cross(f, rt); cr, sr = np.cos(r), np.sin(r)
    return f, cr * rt + sr * d, -sr * rt + cr * d
def unproject(c, u, v):
    dx = u - 0.5 - c.get('cx', 0); dy = (v - 0.5 - c.get('cy', 0)) * (H / W)
    rp = math.hypot(dx, dy) + 1e-12
    k1, k2, f = c.get('k1', 0), c.get('k2', 0), c['f']
    th = rp / f
    for _ in range(10):
        th -= (f * (th + k1 * th ** 3 + k2 * th ** 5) - rp) / (f * (1 + 3 * k1 * th ** 2 + 5 * k2 * th ** 4))
    fw, rt, dn = basis(c); s = math.sin(th)
    return (s * dx / rp) * rt + (s * dy / rp) * dn + math.cos(th) * fw, th


import pandas as pd
cf = None
def load_cf():
    global cf
    if cf is None:
        cf = pd.read_parquet('out/fsd-data/data/camera_frames.parquet'); cf = cf[cf.clip_id == CLIP]
    return cf
def frame_file(cam, t):
    g = load_cf(); g = g[g.camera == cam]
    s = int(round(t * 36)); i = np.searchsorted(g.frame_seq_no.values, s).clip(0, len(g) - 1)
    fi = int(g.frame_index.values[i]); ids = json.load(open(f'{tmp}/{cam}/idx.json'))
    return f'{tmp}/{cam}/{ids.index(fi) + 1:04d}.jpg'

# ---- 1. detect ----
det_path = f'{A.out}/detections.json'
if A.reuse and os.path.exists(det_path):
    dets = json.load(open(det_path))
else:
    from ultralytics import YOLO
    model = YOLO(A.model)
    dets = []
    for k in KF:
        files = [frame_file(cam, k['t']) for cam in CAMS]
        res = model.predict(files, imgsz=960, classes=list(CLS), conf=A.conf, verbose=False)
        for cam, f, r in zip(CAMS, files, res):
            if len(r.boxes) == 0: continue
            img = None
            for b, c, s in zip(r.boxes.xyxy.tolist(), r.boxes.cls.tolist(), r.boxes.conf.tolist()):
                x1, y1, x2, y2 = b
                if (x2 - x1) * (y2 - y1) < 18 * 18: continue
                if img is None: img = np.asarray(Image.open(f).convert('RGB'))
                cx0, cx1 = int(x1 + 0.3 * (x2 - x1)), int(x2 - 0.3 * (x2 - x1)); cy0, cy1 = int(y1 + 0.3 * (y2 - y1)), int(y2 - 0.35 * (y2 - y1))
                patch = img[max(0, cy0):max(cy0 + 1, cy1), max(0, cx0):max(cx0 + 1, cx1)].reshape(-1, 3)
                col = np.median(patch, 0).astype(int).tolist() if len(patch) else [128, 128, 128]
                dets.append(dict(kf=k['i'], cam=cam, cls=CLS[int(c)], conf=round(s, 3), box=[x1 / W, y1 / H, x2 / W, y2 / H], col=col))
        if k['i'] % 20 == 0: print('detect kf', k['i'], '/', len(KF), 'dets', len(dets), flush=True)
    json.dump(dets, open(det_path, 'w'))

# ---- 2. lift each box to a world position ----
def lift(d):
    c = RIG[d['cam']]; k = KF[d['kf']]
    x1, y1, x2, y2 = d['box']
    L, Wd, Hh = SIZE[d['cls']]
    pos = np.array(c['pos'])
    p = None
    if y2 < 0.975:                                      # bottom edge is the ground contact
        ray, th = unproject(c, (x1 + x2) / 2, y2)
        if ray[1] < -0.01:
            rg = pos[1] / -ray[1]
            if rg < 70: p = pos + ray * rg; rng = rg
    if p is None and y2 >= 0.975 and d['cls'] in ('car', 'moto') and y1 > 0.02 and Hh - pos[1] > 0.4:   # bottom cut off by the frame: roof edge on a roof-height plane
        ray, th = unproject(c, (x1 + x2) / 2, y1)
        if ray[1] > 0.01 and Hh > pos[1]:
            rr = (Hh - pos[1]) / ray[1]
            if rr < 40: p = pos + ray * rr; p[1] = 0; rng = rr
    if p is None: return None
    hr = np.array([ray[0], 0, ray[2]]); hr /= np.linalg.norm(hr) + 1e-9
    p = p + hr * (0.5 * min(L, Wd) + 0.35)              # contact point is the near face: push to the centre
    yw = k['yaw']; cy, sy = math.cos(yw), math.sin(yw)
    wx = cy * p[0] - sy * p[2] + k['x']; wz = sy * p[0] + cy * p[2] + k['z']
    return wx, wz, rng

obs = []
for d in dets:
    r = lift(d)
    if r is None: continue
    if r[2] > {'front': 60}.get(d['cam'], 40): continue      # near the horizon a pixel of error is metres of range
    obs.append(dict(d, x=r[0], z=r[1], rng=r[2]))
print('lifted', len(obs), 'of', len(dets))

# ---- 3. merge per keyframe (one vehicle seen by two cameras), then track ----
by_kf = {}
for o in obs: by_kf.setdefault(o['kf'], []).append(o)
merged = {}
for ki, L in by_kf.items():
    L = sorted(L, key=lambda o: o['rng'])
    out = []
    for o in L:
        for m in out:
            if math.hypot(m['x'] - o['x'], m['z'] - o['z']) < 3.0 + 0.06 * o['rng']:
                m['members'].append(o); break
        else:
            out.append(dict(o, members=[o]))
    for m in out:          # nearest view is most accurate: weight by 1/range
        w = np.array([1 / max(2, q['rng']) for q in m['members']])
        m['x'] = float(np.average([q['x'] for q in m['members']], weights=w)); m['z'] = float(np.average([q['z'] for q in m['members']], weights=w))
        cls = [q['cls'] for q in m['members']]; m['cls'] = max(set(cls), key=cls.count)
    merged[ki] = out

dt = 1 / idx['kfps']
tracks = []
for ki in range(len(KF)):
    cur = merged.get(ki, [])
    used = set()
    for tr in sorted([t for t in tracks if t['last'] >= ki - 3], key=lambda t: -len(t['obs'])):
        gap = ki - tr['last']
        vx, vz = tr.get('v', (0, 0))
        px, pz = tr['obs'][-1]['x'] + vx * dt * gap, tr['obs'][-1]['z'] + vz * dt * gap
        best, bd = None, 1e9
        for j, m in enumerate(cur):
            if j in used: continue
            dd = math.hypot(m['x'] - px, m['z'] - pz)
            if dd < bd: bd, best = dd, j
        if best is not None and bd < 3.0 + 0.05 * cur[best]['rng'] + 1.5 * gap:
            m = cur[best]; used.add(best)
            o0 = tr['obs'][-1]
            nv = ((m['x'] - o0['x']) / (dt * gap), (m['z'] - o0['z']) / (dt * gap))
            tr['v'] = (0.6 * vx + 0.4 * nv[0], 0.6 * vz + 0.4 * nv[1]) if len(tr['obs']) > 1 else nv
            tr['obs'].append(dict(m, kf=ki)); tr['last'] = ki
    for j, m in enumerate(cur):
        if j not in used: tracks.append(dict(obs=[dict(m, kf=ki)], last=ki))

# ---- 4. smooth, classify moving, emit ----
out_tracks, masks = [], {}
kft = np.array([k['t'] for k in KF])
for tid, tr in enumerate(tracks):
    O = tr['obs']
    if len(O) < 6: continue
    t = np.array([kft[o['kf']] for o in O]); x = np.array([o['x'] for o in O]); z = np.array([o['z'] for o in O])
    rng = np.array([o['rng'] for o in O])
    # robust line fit -> world speed
    A_ = np.stack([t - t.mean(), np.ones_like(t)], 1)
    w = 1 / np.maximum(rng, 3)
    sx = np.linalg.lstsq(A_ * w[:, None], x * w, rcond=None)[0]; sz = np.linalg.lstsq(A_ * w[:, None], z * w, rcond=None)[0]
    speed = math.hypot(sx[0], sz[0])
    moving = speed > 3.0 and len(O) >= 10
    static = (not moving) and len(O) >= 6 and np.median(rng) < 40
    if not (moving or static): continue
    # road traffic only: straight, parallel to the road (either direction), near the ego path
    if moving:
        disp = math.hypot(x[-1] - x[0], z[-1] - z[0]); plen = np.sum(np.hypot(np.diff(x), np.diff(z)))
        if disp < 4 or plen / disp > 1.6: continue
        hd = math.atan2(sx[0], -sz[0])
        tm = t.mean(); ep = min(idx['path'], key=lambda q: abs(q[0] - tm))
        da = abs((hd - ep[3] + math.pi) % (2 * math.pi) - math.pi)
        if min(da, math.pi - da) > math.radians(28): continue
    # signed lateral offset from our path (+ = right): our side has lanes to ~10 m right, the opposite carriageway is left
    lats = []
    for xi, zi in zip(x, z):
        q = min(idx['path'], key=lambda q: (q[1] - xi) ** 2 + (q[2] - zi) ** 2)
        lats.append((xi - q[1]) * math.cos(q[3]) + (zi - q[2]) * math.sin(q[3]))
    lat = float(np.median(lats))
    if lat > 12 or lat < -35: continue
    if np.median(rng) > 40: continue
    # dense smoothing: local weighted linear regression (window +-0.6 s); a stationary vehicle sits at its median
    ts = np.arange(t[0], t[-1] + 1e-6, dt)
    if static:
        # orientation from the box shape in the nearest view: wide box = seen side-on, narrow = end-on
        best = min(((q, o) for o in O for q in o['members']), key=lambda qo: qo[0]['rng'])
        q, o = best; b = q['box']; asp_w = (b[2] - b[0]) * W / max(1e-6, (b[3] - b[1]) * H)
        k = KF[o['kf']]; az = math.atan2(o['x'] - k['x'], -(o['z'] - k['z']))   # world bearing of the view ray
        yaw0 = az + (math.pi / 2 if asp_w > 1.75 else 0.0)
        mx, mz = float(np.median(x)), float(np.median(z))
        ts = np.array([t[0] - 0.3, t[-1] + 0.3]) if len(t) else ts
        ts = np.arange(ts[0], ts[1] + 1e-6, dt)
        x, z = np.full(len(ts), mx), np.full(len(ts), mz); t = ts
        w = np.ones(len(ts))
    xs, zs = [], []
    for tt in (ts if not static else []):
        ww = np.exp(-0.5 * ((t - tt) / 0.35) ** 2) * w
        Aw = np.stack([t - tt, np.ones_like(t)], 1) * ww[:, None]
        xs.append(np.linalg.lstsq(Aw, x * ww, rcond=None)[0][1]); zs.append(np.linalg.lstsq(Aw, z * ww, rcond=None)[0][1])
    if static:
        xs, zs, yaw = x, z, np.full(len(ts), yaw0)
    else:
        xs, zs = np.array(xs), np.array(zs)
        vx, vz = np.gradient(xs, dt), np.gradient(zs, dt)
        yaw = np.unwrap(np.arctan2(vx, -vz))
        yaw = np.convolve(np.pad(yaw, 3, mode='edge'), np.ones(7) / 7, mode='valid')
    cls = [o['cls'] for o in O]; cls = max(set(cls), key=cls.count)
    cols = np.array([q['col'] for o in O for q in o['members']]); col = np.median(cols, 0).astype(int).tolist()
    # which CAD model: box truck vs pickup from the rear-view box aspect; cars split sedan/suv by aspect too
    rear = [q['box'] for o in O for q in o['members'] if q['cam'] in ('front', 'back')]
    asp = float(np.median([(b[3] - b[1]) * H / max(1e-6, (b[2] - b[0]) * W) for b in rear])) if rear else 0.8
    model = ('boxtruck' if asp > 1.0 else 'pickup') if cls in ('truck', 'bus') else ('suv' if asp > 0.85 else 'sedan')
    SZ = {'boxtruck': (7.2, 2.45, 3.3), 'pickup': (5.8, 2.0, 1.95), 'suv': (4.9, 1.95, 1.78), 'sedan': (4.7, 1.85, 1.45)}
    Lm, Wm, Hm = SZ[model]
    out_tracks.append(dict(id=tid, cls=cls, static=bool(static), model=model, aspect=round(asp, 2), color=col, speed=round(speed, 2), t=[round(v, 4) for v in ts], x=[round(v, 3) for v in xs],
                           z=[round(v, 3) for v in zs], yaw=[round(v, 4) for v in yaw], len=Lm, wid=Wm, hgt=Hm, n=len(O),
                           obs=[[o['kf'], round(o['x'], 2), round(o['z'], 2), [[q['cam'], round(q['rng'], 1), [round(b, 3) for b in q['box']]] for q in o['members']]] for o in O],
                           cams={c: sum(1 for o in O for q in o['members'] if q['cam'] == c) for c in CAMS}))
    for o in O:
        for q in o['members']:
            b = q['box']; pw, ph = 0.06 * (b[2] - b[0]), 0.06 * (b[3] - b[1])
            masks.setdefault(str(o['kf']), {}).setdefault(q['cam'], []).append([b[0] - pw, b[1] - ph, b[2] + pw, b[3] + ph])
print('tracks', len(tracks), 'moving kept', len(out_tracks), [(t['cls'], t['speed'], t['n']) for t in out_tracks])
json.dump(dict(tracks=out_tracks, masks=masks), open(f'{A.out}/cars.json', 'w'))
print('wrote', f'{A.out}/cars.json')
