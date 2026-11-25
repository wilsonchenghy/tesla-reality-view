"""Per-camera depth meshes for projective texturing (the sharp path): for every keyframe and camera, the metric range
along each vertex ray of a GW x GH grid over the original image. The piece pushes each vertex out along its ray and
textures the mesh with that camera's live video frame, so the pixels on screen are the camera's own.
  rays.bin    f32 [6, GH, GW, 3]  unit rays in the car frame (calibrated lens model, SfM-corrected rig if present)
  ranges.bin  f16 [NKF, 6, GH, GW] range in metres, 0 = no surface (sky, outside the lens, own car)
  mesh.json   grid size, camera origins in the car frame, keyframe times
usage: python3 pieces/reality/prep/meshdepth.py [data_dir]
"""
import json, math, os, sys
import numpy as np, cv2
import os as _os; CLIP = _os.environ.get('CLIP', 'clip_00')    # which one-minute clip of the drive
HERE = os.path.dirname(os.path.abspath(__file__))
D = sys.argv[1] if len(sys.argv) > 1 else 'out/reality-data'
RIG = json.load(open(os.path.join(HERE, 'rig.json')))
SFMRIG = json.load(open(os.path.join(HERE, 'rig_sfm.json'))) if os.path.exists(os.path.join(HERE, 'rig_sfm.json')) else {}
idx = json.load(open(f'{D}/index.json')); SC = json.load(open(f'{D}/scales.json'))
preds = np.load(f'{D}/tmp/preds.npz')
CAMS = ['front', 'left_pillar', 'right_pillar', 'left_repeater', 'right_repeater', 'back']
W, H = 1448, 938; GW, GH = 129, 85; DW, DH = 616, 406

def basis(c):
    y, p, r = np.radians([c['yaw'], c['pitch'], c.get('roll', 0)])
    f = np.array([np.sin(y) * np.cos(p), np.sin(p), -np.cos(y) * np.cos(p)])
    rt = np.cross(f, [0, 1, 0]); rt /= np.linalg.norm(rt); d = np.cross(f, rt); cr, sr = np.cos(r), np.sin(r)
    return f, cr * rt + sr * d, -sr * rt + cr * d

gv, gu = np.mgrid[0:GH, 0:GW]
U, V = gu / (GW - 1), gv / (GH - 1)
RAYS = np.zeros((6, GH, GW, 3), np.float32); THETA = np.zeros((6, GH, GW)); POS = []
for ci, cam in enumerate(CAMS):
    c = dict(RIG[cam]); s = SFMRIG.get(cam, {})
    f_lens = c['f'] * s.get('f_scale', 1.0)
    dx = U - 0.5; dy = (V - 0.5) * (H / W); rp = np.hypot(dx, dy) + 1e-12
    k1, k2 = c.get('k1', 0), c.get('k2', 0); th = rp / f_lens
    for _ in range(10): th -= (f_lens * (th + k1 * th ** 3 + k2 * th ** 5) - rp) / (f_lens * (1 + 3 * k1 * th ** 2 + 5 * k2 * th ** 4))
    if 'R' in s: Rm = np.array(s['R']); rt, dn, fw = Rm[:, 0], Rm[:, 1], Rm[:, 2]
    else: fw, rt, dn = basis(c)
    sn = np.sin(th)
    ray = (sn * dx / rp)[..., None] * rt + (sn * dy / rp)[..., None] * dn + np.cos(th)[..., None] * fw
    RAYS[ci] = ray; THETA[ci] = th; POS.append(s.get('pos', c['pos']))

R = np.zeros((len(idx['kf']), 6, GH, GW), np.float16)
for ki, k in enumerate(idx['kf']):
    for ci, cam in enumerate(CAMS):
        key = f"{k['i']}_{cam}"
        if key not in SC: continue
        a, b = SC[key]; pr = preds[key]
        prg = cv2.remap(pr, (U * DW - 0.5).astype(np.float32), (V * DH - 0.5).astype(np.float32), cv2.INTER_LINEAR)
        prg = cv2.medianBlur(prg.astype(np.float32), 5)                 # foliage depth is noisy: smooth before meshing
        inv = a * prg + b; r = 1 / np.maximum(inv, 1e-4)
        ray = RAYS[ci]; h = POS[ci][1]; down = -ray[..., 1]
        rg = np.where(down > 0.01, h / np.maximum(down, 1e-6), np.inf)
        near_rg, near_k = (11, 0.55) if cam == 'front' else (30, 0.35)
        road_max = {'front': 60, 'back': 14}.get(cam, 30)
        road = np.isfinite(rg) & (rg < road_max) & ((r > 0.88 * rg) | ((rg < near_rg) & (r > near_k * rg)))
        rr = np.where(road, rg, np.minimum(r, rg))
        sky = (prg < 0.045 * float(pr.max())) & ~road                      # relative inverse depth ~0: sky, not a surface
        ok = (THETA[ci] < math.radians(RIG[cam].get('maxth', 80))) & (inv > 1 / 90) & (rr < 90) & ~sky
        if cam == 'back': ok &= road
        ok &= rr > 2.5                               # nothing real within 2.5 m of a lens but our own car
        # own car: points inside our footprint are the body / housing
        p = np.array(POS[ci]) + ray * rr[..., None]
        ok &= ~((np.abs(p[..., 0]) < 1.0) & (np.abs(p[..., 2]) < 2.45) & (p[..., 1] < 1.7))
        R[ki, ci] = np.where(ok, np.where(road, -rr, rr), 0)
    if ki % 40 == 0: print('kf', ki, flush=True)
import pandas as pd
cf = pd.read_parquet('out/fsd-data/data/camera_frames.parquet'); cf = cf[cf.clip_id == CLIP]
def frame_file(cam, t):
    g = cf[cf.camera == cam]; s_ = int(round(t * 36)); i = np.searchsorted(g.frame_seq_no.values, s_).clip(0, len(g) - 1)
    ids = json.load(open(f'{D}/tmp/{cam}/idx.json')); return f'{D}/tmp/{cam}/{ids.index(int(g.frame_index.values[i])) + 1:04d}.jpg'
road_mean = np.zeros((6, 3))
for ci, cam in enumerate(CAMS):
    acc = []
    for ki in range(0, len(idx['kf']), 8):
        m = R[ki, ci].astype(np.float32) < 0
        if m.sum() < 50: continue
        img = cv2.imread(frame_file(cam, idx['kf'][ki]['t']))[..., ::-1].astype(np.float32)
        px = (U * (W - 1)).astype(int); py = (V * (H - 1)).astype(int)
        acc.append(img[py[m], px[m]].mean(0))
    road_mean[ci] = np.mean(acc, 0) if acc else 128
target = np.median(road_mean, 0)
GAIN = (target / np.maximum(road_mean, 1)).round(4)
print('road mean per cam', road_mean.round(1).tolist(), 'gains', GAIN.tolist())
RAYS.tofile(f'{D}/rays.bin'); R.tofile(f'{D}/ranges.bin')
json.dump(dict(gw=GW, gh=GH, cams=CAMS, gain=GAIN.tolist(), pos=[list(map(float, p)) for p in POS], kf=[k['t'] for k in idx['kf']],
               sfm=bool(SFMRIG)), open(f'{D}/mesh.json', 'w'))
print('wrote rays/ranges', R.shape, 'valid', round(float((R > 0).mean()), 3), 'sfm rig' if SFMRIG else 'prior rig')
