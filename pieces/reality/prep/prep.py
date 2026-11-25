"""Reality View reconstruction: Tesla dashcam (6 cams + telemetry) -> per-keyframe 3D Gaussian splats.

Pipeline (CPU only, no training):
  1. ego trajectory from telemetry (speed + heading integrated at 36 Hz)
  2. frames per keyframe from all 6 cameras (synced on frame_seq_no)
  3. monocular depth per image (Depth Anything V2 small, ONNX)
  4. metric scale: relative inverse depth fitted to the calibrated ground plane (robust, per image),
     then smoothed over time per camera (the "loop": a scale that disagrees with its neighbours is pulled back)
  5. back-project to splats: road pixels snap to the ground as flat horizontal disks ("rebuilding the road"),
     everything else becomes a disk facing its source camera; sky and the ego car are dropped
  6. write out/reality-data/kf/NNN.bin (20 bytes/splat) + index.json + left-panel camera frames

usage: python3 pieces/reality/prep/prep.py [--data out/fsd-data] [--out out/reality-data] [--t0 6] [--dur 20]
needs: numpy, pillow, pandas, pyarrow, onnxruntime, ffmpeg; dataset clip_00 in --data (see fetch.sh)
"""
import argparse, json, os, subprocess, sys, math
import numpy as np
from PIL import Image
import os as _os; CLIP = _os.environ.get('CLIP', 'clip_00')    # which one-minute clip of the drive

HERE = os.path.dirname(os.path.abspath(__file__))
ap = argparse.ArgumentParser()
ap.add_argument('--data', default='out/fsd-data')
ap.add_argument('--out', default='out/reality-data')
ap.add_argument('--t0', type=float, default=6.0)     # drive time of piece t=0
ap.add_argument('--dur', type=float, default=20.0)
ap.add_argument('--pre', type=float, default=2.5)    # keyframes before t0 (history for the road)
ap.add_argument('--kfps', type=float, default=8.0)   # keyframes per second (36 / 4.5)
ap.add_argument('--fps', type=int, default=30)
ap.add_argument('--skip-frames', action='store_true')
ap.add_argument('--skip-depth', action='store_true')
ap.add_argument('--vox-road', type=float, default=0.10)
ap.add_argument('--vox-obj', type=float, default=0.15)
A = ap.parse_args()

CAMS = ['front', 'left_pillar', 'right_pillar', 'left_repeater', 'right_repeater', 'back']
RIG = json.load(open(os.path.join(HERE, 'rig.json')))
W, H = 1448, 938                         # all cams resampled to this
DW, DH = 616, 406                        # depth net input (multiples of 14)
STRIDE = {'front': 2}                    # sample stride on the depth grid; others 3
os.makedirs(f'{A.out}/kf', exist_ok=True); os.makedirs(f'{A.out}/cams', exist_ok=True)
tmp = f'{A.out}/tmp'; os.makedirs(tmp, exist_ok=True)

import pandas as pd
tel = pd.read_parquet(f'{A.data}/data/telemetry.parquet')
tel = tel[tel.clip_id == CLIP].sort_values('frame_seq_no')
meta = {}
for l in open(f'{A.data}/videos/metadata.jsonl'):
    m = json.loads(l)
    if m['clip_id'] == CLIP: meta[m['camera']] = m
cf = pd.read_parquet(f'{A.data}/data/camera_frames.parquet'); cf = cf[cf.clip_id == CLIP]

# ---------- 1. ego trajectory on the 36 Hz frame counter ----------
seq = np.arange(0, int(tel.frame_seq_no.max()) + 60)
ts = seq / 36.0
sp = np.interp(seq, tel.frame_seq_no, tel.vehicle_speed_mps)
hd = np.interp(seq, tel.frame_seq_no, tel.heading_change_deg)       # deg, negative = turned left
yaw = np.radians(hd)                                                # our yaw: + = right (clockwise from above)
x = np.cumsum(sp * np.sin(yaw)) / 36.0
z = np.cumsum(-sp * np.cos(yaw)) / 36.0
s0 = int(round(A.t0 * 36)); X0, Z0, Y0 = x[s0], z[s0], yaw[s0]
def pose(s):
    dx, dz = x[s] - X0, z[s] - Z0
    c, sn = math.cos(Y0), math.sin(Y0)
    # rotate world so the car faces -z at t0: inverse of yaw Y0 (clockwise) is a counter-clockwise turn
    wx = c * dx + sn * dz
    wz = -sn * dx + c * dz
    return wx, wz, yaw[s] - Y0

def col(name, s):
    return float(np.interp(s, tel.frame_seq_no, tel[name].astype(float)))

# per output frame telemetry for the piece (a little beyond the window for the path look-ahead)
frames = []
for k in range(int(A.dur * A.fps) + 1):
    td = A.t0 + k / A.fps
    s = td * 36
    si = int(round(s))
    wx, wz, wy = pose(si)
    frames.append(dict(t=round(td, 4), x=round(wx, 3), z=round(wz, 3), yaw=round(wy, 5),
                       v=round(col('vehicle_speed_mps', s), 3), steer=round(col('steering_wheel_angle_deg', s), 2),
                       bl=bool(col('blinker_on_left', s) > 0.5), br=bool(col('blinker_on_right', s) > 0.5),
                       ap=str(tel.iloc[np.searchsorted(tel.frame_seq_no.values, si).clip(0, len(tel) - 1)].autopilot_state)))
# dense path (every 1/12 s) far enough ahead for a 6 s look-ahead
path = []
for s in range(int((A.t0 - A.pre) * 36), min(len(seq) - 1, int((A.t0 + A.dur + 8) * 36)), 3):
    wx, wz, wy = pose(s); path.append([round(s / 36, 4), round(wx, 3), round(wz, 3), round(wy, 5)])

# ---------- camera model ----------
def basis(c):
    y, p, r = np.radians([c['yaw'], c['pitch'], c.get('roll', 0)])
    f = np.array([np.sin(y) * np.cos(p), np.sin(p), -np.cos(y) * np.cos(p)])
    rt = np.cross(f, [0, 1, 0]); rt /= np.linalg.norm(rt)
    d = np.cross(f, rt)
    cr, sr = np.cos(r), np.sin(r)
    return f, cr * rt + sr * d, -sr * rt + cr * d
def unproject(c, u, v):
    """u, v in [0,1] image coords -> unit ray in car frame, theta"""
    dx = u - 0.5 - c.get('cx', 0); dy = (v - 0.5 - c.get('cy', 0)) * (H / W)
    rp = np.hypot(dx, dy) + 1e-12
    k1, k2, f = c.get('k1', 0), c.get('k2', 0), c['f']
    th = rp / f
    for _ in range(8):
        g = f * (th + k1 * th ** 3 + k2 * th ** 5) - rp
        dg = f * (1 + 3 * k1 * th ** 2 + 5 * k2 * th ** 4)
        th = th - g / dg
    fw, rt, dn = basis(c)
    s = np.sin(th)
    d = (s * dx / rp)[..., None] * rt + (s * dy / rp)[..., None] * dn + np.cos(th)[..., None] * fw
    dpdth = f * (1 + 3 * k1 * th ** 2 + 5 * k2 * th ** 4)   # width-units per radian at this theta
    return d, th, dpdth

# ---------- 2. frames ----------
kf_t = np.round(np.arange(A.t0 - A.pre, A.t0 + A.dur + 1e-6, 1 / A.kfps), 4)
def frame_index(cam, s):
    g = cf[cf.camera == cam]
    i = np.searchsorted(g.frame_seq_no.values, s).clip(0, len(g) - 1)
    return int(g.frame_index.values[i])
if not A.skip_frames:
    procs = []
    for cam in CAMS:
        idx = sorted({frame_index(cam, int(round(t * 36))) for t in kf_t})
        expr = '+'.join(f'eq(n\\,{i})' for i in idx)
        os.makedirs(f'{tmp}/{cam}', exist_ok=True)
        with open(f'{tmp}/{cam}/idx.json', 'w') as fh: json.dump(idx, fh)
        procs.append(subprocess.Popen(['ffmpeg', '-v', 'error', '-y', '-i', f'{A.data}/videos/{CLIP}/{cam}.mp4', '-vf', f'select={expr},scale={W}:{H}',
                                       '-fps_mode', 'passthrough', '-q:v', '2', f'{tmp}/{cam}/%04d.jpg']))
        # left-panel feed: 30 fps across the piece window
        g = cf[cf.camera == cam]
        start = frame_index(cam, int(round(A.t0 * 36))) / 36.0
        os.makedirs(f'{A.out}/cams/{cam}', exist_ok=True)
        sz = '960:622' if cam in ('front', 'back') else '480:311'
        procs.append(subprocess.Popen(['ffmpeg', '-v', 'error', '-y', '-ss', f'{start:.4f}', '-i', f'{A.data}/videos/{CLIP}/{cam}.mp4', '-t', f'{A.dur + 0.2}',
                                       '-vf', f'fps={A.fps},scale={sz}', '-q:v', '4', f'{A.out}/cams/{cam}/%04d.jpg']))
    for p in procs: p.wait()
    print('frames done')

# ---------- 3-5. depth -> splats ----------
import onnxruntime as ort
sess = ort.InferenceSession(f'{A.data}/models/da2s.onnx', providers=['CPUExecutionProvider'])
def depth(img):
    a = np.asarray(img.resize((DW, DH), Image.BILINEAR), np.float32) / 255
    a = ((a - [0.485, 0.456, 0.406]) / [0.229, 0.224, 0.225]).transpose(2, 0, 1)[None].astype(np.float32)
    return sess.run(None, {'pixel_values': a})[0][0]

def load(cam, t):
    idx = json.load(open(f'{tmp}/{cam}/idx.json'))
    i = idx.index(frame_index(cam, int(round(t * 36))))
    return Image.open(f'{tmp}/{cam}/{i + 1:04d}.jpg').convert('RGB')

# precompute rays on each camera's sampling grid
GRID = {}
for cam in CAMS:
    st = STRIDE.get(cam, 3)
    gy, gx = np.mgrid[st // 2:DH:st, st // 2:DW:st]
    u, v = (gx + 0.5) / DW, (gy + 0.5) / DH
    c = RIG[cam]
    ray, th, dpdth = unproject(c, u, v)
    pitch = (st / DW) / dpdth                      # radians between samples
    GRID[cam] = dict(gx=gx, gy=gy, u=u, v=v, ray=ray, th=th, pitch=pitch, pos=np.array(c['pos']), maxth=np.radians(c.get('maxth', 80)))

def fit_scale(cam, pred):
    """inv_range = a * pred + b, fitted to ground-plane range on the lower image."""
    g = GRID[cam]; ray = g['ray']; h = g['pos'][1]
    pr = pred[g['gy'], g['gx']]
    down = -ray[..., 1]
    rg = np.where(down > 0.02, h / np.maximum(down, 1e-6), np.inf)
    # candidate ground: within 3..30 m, inside lens, not the ego car
    m = (rg > 3) & (rg < 30) & (g['th'] < g['maxth'] * 0.95)
    gp = g['pos'] + ray * np.where(np.isfinite(rg), rg, 0)[..., None]
    m &= ~((np.abs(gp[..., 0]) < 1.1) & (np.abs(gp[..., 2]) < 2.6))
    P, T = pr[m], 1 / rg[m]
    if len(P) < 50: return None
    w = np.ones_like(P)
    a, b = 0.03, 0.0
    for it in range(6):
        Am = np.stack([P, np.ones_like(P)], 1) * w[:, None]
        a, b = np.linalg.lstsq(Am, T * w, rcond=None)[0]
        res = (a * P + b - T) / T
        # objects stand above the road: they read nearer (res > 0); keep the road (|res| small)
        w = (np.abs(res) < (0.6 if it < 2 else 0.25)).astype(float)
    return float(a), float(b), float(w.mean())

if not A.skip_depth:
    preds = {}
    for ki, t in enumerate(kf_t):
        for cam in CAMS:
            preds[(ki, cam)] = depth(load(cam, t))
        if ki % 10 == 0: print('depth', ki, '/', len(kf_t), flush=True)
    np.savez_compressed(f'{tmp}/preds.npz', **{f'{k}_{c}': v for (k, c), v in preds.items()})
else:
    z_ = np.load(f'{tmp}/preds.npz'); preds = {}
    for key in z_.files:
        k, c = key.split('_', 1); preds[(int(k), c)] = z_[key]

# fit scale per image, then smooth over time per camera (median of neighbours, reject outliers)
scales = {}
for cam in CAMS:
    ab = [fit_scale(cam, preds[(ki, cam)]) for ki in range(len(kf_t))]
    a = np.array([s[0] if s else np.nan for s in ab]); b = np.array([s[1] if s else np.nan for s in ab])
    a2, b2 = a.copy(), b.copy()
    for i in range(len(a)):
        lo, hi = max(0, i - 4), min(len(a), i + 5)
        ma, mb = np.nanmedian(a[lo:hi]), np.nanmedian(b[lo:hi])
        if not np.isfinite(a[i]) or abs(a[i] - ma) > 0.25 * abs(ma): a2[i], b2[i] = ma, mb
        else: a2[i], b2[i] = 0.5 * a[i] + 0.5 * ma, 0.5 * b[i] + 0.5 * mb
    for i in range(len(a)): scales[(i, cam)] = (a2[i], b2[i])
    print(cam, 'scale a med', np.nanmedian(a).round(4), 'b med', np.nanmedian(b).round(4))

VIG = {}
for cam in CAMS:
    g = GRID[cam]; acc = None
    for t in kf_t[::4]:
        ia = np.asarray(load(cam, t), np.float32)
        px = (g['u'] * W).astype(int).clip(0, W - 1); py = (g['v'] * H).astype(int).clip(0, H - 1)
        v = ia[py, px].mean(-1); acc = v if acc is None else acc + v
    acc /= len(kf_t[::4])
    VIG[cam] = acc > 62
    print(cam, 'vignette masked', round(100 * (1 - VIG[cam].mean()), 1), '%')

# moving vehicles (cars.py): cut their pixels out; the piece draws them as tracked 3D models
CARS = json.load(open(f'{A.out}/cars.json')) if os.path.exists(f'{A.out}/cars.json') else None
def car_mask(ki, cam, u, v):
    m = np.zeros(u.shape, bool)
    if not CARS: return m
    for x1, y1, x2, y2 in CARS['masks'].get(str(ki), {}).get(cam, []):
        m |= (u >= x1) & (u <= x2) & (v >= y1) & (v <= y2)
    return m

json.dump({f'{k}_{c}': [float(v[0]), float(v[1])] for (k, c), v in scales.items()}, open(f'{A.out}/scales.json', 'w'))

index = dict(t0=A.t0, dur=A.dur, fps=A.fps, kfps=A.kfps, kf=[], frames=frames, path=path, cams=CAMS)
total = 0
for ki, t in enumerate(kf_t):
    s = int(round(t * 36)); wx, wz, wy = pose(s)
    cy, sy = math.cos(wy), math.sin(wy)
    out = []
    for ci, cam in enumerate(CAMS):
        g = GRID[cam]; img = load(cam, t); ia = np.asarray(img)
        pred = preds[(ki, cam)][g['gy'], g['gx']]
        a, b = scales[(ki, cam)]
        inv = a * pred + b
        ray, h = g['ray'], g['pos'][1]
        r = 1 / np.maximum(inv, 1e-4)
        ok = (inv > 1 / 90) & (g['th'] < g['maxth'])
        down = -ray[..., 1]
        rg = np.where(down > 0.01, h / np.maximum(down, 1e-6), np.inf)
        # side cameras: monocular depth on wide lenses is less reliable than the calibrated ground plane, trust geometry further
        near_rg, near_k = (11, 0.55) if cam == 'front' else (30, 0.35)
        road_max = {'front': 45, 'back': 11}.get(cam, 24)
        road = ok & np.isfinite(rg) & (rg < road_max) & ((r > 0.88 * rg) | ((rg < near_rg) & (r > near_k * rg)))
        ok &= road | ((r < 55) & ~((cam != 'front') & (ray[..., 1] > 0.0) & (r > 35)))
        if cam == 'back': ok &= road     # fisheye depth fit is unreliable above the road: its objects formed a fog dome behind the car                              # far 'cards' read as floating panels from the chase cam: drop
        r = np.where(road, rg, np.minimum(r, rg))       # nothing below the road
        p = g['pos'] + ray * r[..., None]
        ok &= ~((np.abs(p[..., 0]) < 1.1) & (np.abs(p[..., 2]) < 2.6) & (p[..., 1] < 1.8))
        px = (g['u'] * W).astype(int).clip(0, W - 1); py = (g['v'] * H).astype(int).clip(0, H - 1)
        colr = ia[py, px]
        ok &= (colr.sum(-1) > 30) & VIG[cam]               # back-camera plate mask, lens vignette
        ok &= ~car_mask(ki, cam, g['u'], g['v'])
        sz = r * g['pitch'] * 0.75
        # road splats: footprint across the ray = r*pitch, along it r*pitch/sin(grazing): stored as an elongation code
        graze = np.maximum(down, 0.03)
        el = np.clip(np.round(np.log(1 / graze) / np.log(1.25)), 0, 15 if cam == 'front' else 7).astype(np.uint8)   # side/back: long streaks read as shells
        sz = np.clip(sz, 0.012, np.where(road, 0.5, 0.7))
        hray = ray * np.array([1, 0, 1.0]); hray /= np.linalg.norm(hray, axis=-1, keepdims=True) + 1e-9
        nrm = np.where(road[..., None], hray, -ray)
        sel = ok
        P = p[sel]; N = nrm[sel]; C = colr[sel]; S = sz[sel]; R = road[sel]; E = el[sel]
        # car frame -> world
        Pw = np.stack([cy * P[:, 0] - sy * P[:, 2], P[:, 1], sy * P[:, 0] + cy * P[:, 2]], 1)
        Nw = np.stack([cy * N[:, 0] - sy * N[:, 2], N[:, 1], sy * N[:, 0] + cy * N[:, 2]], 1)
        Pw[:, 0] += wx; Pw[:, 2] += wz
        n = len(P)
        rec = np.zeros(n, dtype=[('p', '<f4', 3), ('c', 'u1', 3), ('k', 'u1'), ('n', 'i1', 3), ('s', 'u1')])
        rec['p'] = Pw; rec['c'] = C
        rec['k'] = (R.astype(np.uint8)) | (ci << 1) | np.where(R, E << 4, 0).astype(np.uint8)
        rec['n'] = np.clip(np.round(Nw * 127), -127, 127)
        rec['s'] = np.clip(np.round(np.log(S / 0.01) / np.log(1.04)), 0, 255)
        out.append(rec)
    allr = np.concatenate(out)
    allr.tofile(f'{A.out}/kf/{ki:03d}.bin')
    index['kf'].append(dict(i=ki, t=float(t), n=int(len(allr)), road=int((allr['k'] & 1).sum()), x=round(wx, 3), z=round(wz, 3), yaw=round(wy, 5)))
    total += len(allr)
print('splats total', total, 'per kf', total // len(kf_t))

# ---------- 6. one continuous world: fuse every keyframe, then carve floaters against the depth maps ----------
def project_pts(c, P):
    f, rt, d = basis(c); v = P - np.array(c['pos']); zc, xc, yc = v @ f, v @ rt, v @ d
    rho = np.hypot(xc, yc) + 1e-9; th = np.arctan2(rho, zc)
    rp = c['f'] * (th + c.get('k1', 0) * th ** 3 + c.get('k2', 0) * th ** 5)
    return 0.5 + rp * xc / rho, 0.5 + rp * yc / rho * (W / H), th, np.sqrt(zc * zc + rho * rho)

dt_ = np.dtype([('p', '<f4', 3), ('c', 'u1', 3), ('k', 'u1'), ('n', 'i1', 3), ('s', 'u1')])
ALL = []
for ki in range(len(kf_t)):
    r = np.fromfile(f'{A.out}/kf/{ki:03d}.bin', dtype=dt_)
    ALL.append((r, np.full(len(r), ki, np.int32)))
R = np.concatenate([a for a, _ in ALL]); KI = np.concatenate([b for _, b in ALL]); del ALL
road = (R['k'] & 1) == 1
P = R['p'].astype(np.float64); S = 0.01 * 1.04 ** R['s'].astype(np.float64)
camid = (R['k'] >> 1) & 7
kx = np.array([q['x'] for q in index['kf']])[KI]; kz = np.array([q['z'] for q in index['kf']])[KI]
dist = np.hypot(P[:, 0] - kx, P[:, 2] - kz)
okobs = road | (dist < np.where(camid == 0, 35, 22))       # monocular depth is only trustworthy near
R, KI, P, S, road, dist = R[okobs], KI[okobs], P[okobs], S[okobs], road[okobs], dist[okobs]
Wt = 1.0 / np.maximum(S, 0.01) ** 2                       # near observations (small footprints) dominate
VR, VO = A.vox_road, A.vox_obj
key = np.where(road[:, None], np.stack([np.floor(P[:, 0] / VR), np.zeros(len(P)), np.floor(P[:, 2] / VR)], 1),
               np.stack([np.floor(P[:, 0] / VO), np.floor(P[:, 1] / VO), np.floor(P[:, 2] / VO)], 1) + np.array([0, 1e6, 0])).astype(np.int64)
key = (key[:, 0] + 2 ** 20) * 2 ** 42 + (key[:, 1] % 2 ** 21) * 2 ** 21 + (key[:, 2] + 2 ** 20)
uk, inv = np.unique(key, return_inverse=True); NV = len(uk)
acc = lambda v: np.bincount(inv, weights=v, minlength=NV)
wsum = acc(Wt)
FP = np.stack([acc(P[:, i] * Wt) for i in range(3)], 1) / wsum[:, None]
FC = np.stack([acc(R['c'][:, i] * Wt) for i in range(3)], 1) / wsum[:, None]
FN = np.stack([acc(R['n'][:, i].astype(float) * Wt) for i in range(3)], 1)
FN /= np.linalg.norm(FN, axis=1, keepdims=True) + 1e-9
FR = acc(road.astype(float)) / np.bincount(inv, minlength=NV) > 0.5
FS = np.minimum(np.exp(acc(np.log(S) * Wt) / wsum), np.where(FR, VR, VO) * 1.4)
FS = np.maximum(FS, np.where(FR, VR, VO) * 0.75)          # cover the cell: no gaps between neighbours
# support: distinct keyframes that saw the 0.6 m neighbourhood (fine cells are too small to be hit twice by noisy depth)
ck = np.floor(FP / 0.6).astype(np.int64); ck = (ck[:, 0] + 2 ** 20) * 2 ** 42 + (ck[:, 1] + 2 ** 10) * 2 ** 21 + (ck[:, 2] + 2 ** 20)
cu, cinv = np.unique(ck, return_inverse=True)
obs_cell = cinv[inv]
csup = np.bincount(np.unique(obs_cell.astype(np.int64) * 4096 + KI) // 4096, minlength=len(cu))
support = csup[cinv]
print('fused', len(R), '->', NV, 'voxels (road', int(FR.sum()), ')')
keep = FR | (support >= 5)                                 # seen in fewer than 3 keyframes: noise
# free-space carving: a point a camera saw *through* (its depth there is clearly farther) is a floater
viol = np.zeros(NV, np.int32); seen = np.zeros(NV, np.int32)
obj = np.where(keep & ~FR)[0]
for ki in range(0, len(kf_t), 1):
    k = index['kf'][ki]; cy_, sy_ = math.cos(k['yaw']), math.sin(k['yaw'])
    dx, dz = FP[obj, 0] - k['x'], FP[obj, 2] - k['z']
    PC = np.stack([cy_ * dx + sy_ * dz, FP[obj, 1], -sy_ * dx + cy_ * dz], 1)   # world -> car frame
    for cam in CAMS:
        if cam == 'back': continue
        c = RIG[cam]; u, v, th, rr = project_pts(c, PC)
        m = (th < np.radians(c.get('maxth', 80)) * 0.95) & (u > 0) & (u < 1) & (v > 0) & (v < 1) & (rr < 50)
        if not m.any(): continue
        a, b = scales[(ki, cam)]; pr = preds[(ki, cam)]
        dobs = 1 / np.maximum(a * pr[(v[m] * DH).astype(int).clip(0, DH - 1), (u[m] * DW).astype(int).clip(0, DW - 1)] + b, 1e-4)
        ii = obj[m]; seen[ii] += 1
        viol[ii] += (rr[m] < 0.8 * dobs - 0.3)
carve = (viol > np.maximum(1, 0.3 * seen))
keep &= ~carve
# object cells lying on a road cell's surface are road misread as objects: the road owns the ground
rk = set(((np.floor(FP[FR, 0] / 0.5)).astype(np.int64) * 100003 + np.floor(FP[FR, 2] / 0.5).astype(np.int64)).tolist())
low = (~FR) & (FP[:, 1] < 0.35)
lk = (np.floor(FP[:, 0] / 0.5)).astype(np.int64) * 100003 + np.floor(FP[:, 2] / 0.5).astype(np.int64)
onroad = low & np.isin(lk, np.fromiter(rk, np.int64))
keep &= ~onroad
print('carved', int((carve & ~FR).sum()), 'floaters; kept', int(keep.sum()))
wr = np.zeros(int(keep.sum()), dtype=dt_)
wr['p'] = FP[keep]; wr['c'] = np.clip(np.round(FC[keep]), 0, 255)
wr['k'] = FR[keep].astype(np.uint8)
nn = np.where(FR[keep][:, None], np.array([0, 0, -1.0]), FN[keep])          # road: flat isotropic disk (axis unused)
wr['n'] = np.clip(np.round(nn * 127), -127, 127)
wr['s'] = np.clip(np.round(np.log(FS[keep] / 0.01) / np.log(1.04)), 0, 255)
wr.tofile(f'{A.out}/world.bin')
index['world'] = dict(n=int(len(wr)), road=int(FR[keep].sum()), vox_road=VR, vox_obj=VO)
print('wrote world.bin', len(wr))
if CARS: index['cars'] = CARS['tracks']
json.dump(index, open(f'{A.out}/index.json', 'w'))
print('wrote', f'{A.out}/index.json')
