"""Training masks from the 3D traffic tracks (traffic3d.py), so the world and the drawn models agree: every vehicle
instance is lifted to the ground and matched to a track at that moment; parked -> visible in every view (the world
learns it from all angles), moving -> hidden in every view (drawn as a model). Unmatched instances keep the current mask.
  usage: track_masks.py --pack DIR --cams cameras_rig3.json --tracks tracks.json --masks DIR/masks_fused --out DIR/masks_tracks"""
import argparse, json, math, os
import cv2, numpy as np
from ultralytics import YOLO

ap = argparse.ArgumentParser()
ap.add_argument('--pack', required=True); ap.add_argument('--cams', default='cameras_rig3.json'); ap.add_argument('--tracks', required=True)
ap.add_argument('--masks', required=True); ap.add_argument('--out', required=True); ap.add_argument('--seg', default='out/fsd-data/models/yolo11s-seg.pt')
A = ap.parse_args(); os.makedirs(A.out, exist_ok=True)
meta = json.load(open(f'{A.pack}/{A.cams}'))['images']; T = json.load(open(A.tracks))
cams = sorted({e['cam'] for e in meta})
never = {}
for c in cams:    # ego body / vignette: hidden in (almost) every frame of that camera
    ms = [cv2.imread(f"{A.pack}/{e['mask']}", 0) < 128 for e in meta if e['cam'] == c][::8]
    never[c] = np.mean(ms, 0) > 0.95

def at(tr, t):
    ts = tr['t']
    if tr['static']: return (tr['x'][0], tr['z'][0]) if ts[0] - 1.0 <= t <= ts[-1] + 1.0 else None
    if t < ts[0] - 0.2 or t > ts[-1] + 0.2: return None
    return np.interp(t, ts, tr['x']), np.interp(t, ts, tr['z'])

yolo = YOLO(A.seg); st = dict(parked=0, moving=0, unmatched=0)
for e in meta:
    img = cv2.imread(f"{A.pack}/{e['file']}"); base = cv2.imread(f"{A.pack}/{e['mask']}", 0)
    cur = cv2.imread(f"{A.masks}/{os.path.basename(e['mask'])}", 0); out = cur.copy()
    r = yolo.predict(img[..., ::-1], imgsz=1024, classes=[2, 3, 5, 7], conf=0.3, verbose=False, retina_masks=True)[0]
    if r.masks is not None:
        K = np.array(e['K']); c2w = np.linalg.inv(np.array(e['w2c'])); o = c2w[:3, 3]
        for box, m in zip(r.boxes.xyxy.cpu().numpy(), r.masks.data.cpu().numpy() > 0.5):
            ys, xs = np.nonzero(m)
            if len(ys) < 40 or box[3] > e['height'] - 4: st['unmatched'] += 1; continue
            sel = ys >= np.percentile(ys, 97); u, v = float(np.median(xs[sel])), float(ys.max())
            ray = c2w[:3, :3] @ np.linalg.solve(K, [u, v, 1.0])
            if ray[1] > -1e-3: st['unmatched'] += 1; continue
            p = o + ray * (-o[1] / ray[1]); rng = math.hypot(p[0] - o[0], p[2] - o[2])
            hr = np.array([ray[0], ray[2]]) / math.hypot(ray[0], ray[2]); c = np.array([p[0], p[2]]) + hr * 1.3
            best, bd, gate = None, 1e9, 2.5 + 0.12 * rng   # ground lifts are metres off at range: gate grows with it
            for tr in T:
                q = at(tr, e['t'])
                if q is None: continue
                d = math.hypot(c[0] - q[0], c[1] - q[1])
                if d < gate and not tr['static']: best, bd = tr, 0.0; break   # any moving vehicle in reach: hide (a ghost is worse than a gap)
                if d < min(bd, gate): best, bd = tr, d
            if best is None: st['unmatched'] += 1; continue
            if best['static']:
                out[m & ~never[e['cam']]] = 255; st['parked'] += 1
            else:
                mm = cv2.dilate(m.astype(np.uint8), np.ones((9, 9), np.uint8)) > 0
                out[mm & (base < 128)] = 0; out[mm & (base >= 128) & ~never[e['cam']]] = 0; st['moving'] += 1
    cv2.imwrite(f"{A.out}/{os.path.basename(e['mask'])}", out)
    if e['i'] % 400 == 0: print(e['i'], st, flush=True)
print('done', st)
