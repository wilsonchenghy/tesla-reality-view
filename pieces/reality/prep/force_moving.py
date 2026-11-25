"""Second pass over motion_masks.py output: a vehicle that the multi-camera tracker (cars.py, aligned by sfm_align.py)
saw moving at any time stays hidden in every view, even where one camera only saw it waiting at a light.
Each vehicle instance is lifted to the ground plane (y = 0 in the solved world) from its box bottom and matched to the
moving tracks at that moment.

  python force_moving.py --pack DIR --cams cameras_rig3.json --index out/reality-data/index.json --masks DIR/masks_static --out DIR/masks
"""
import argparse, json, os
import cv2, numpy as np
from ultralytics import YOLO

ap = argparse.ArgumentParser()
ap.add_argument('--pack', required=True); ap.add_argument('--cams', default='cameras_rig3.json')
ap.add_argument('--index', required=True); ap.add_argument('--masks', required=True); ap.add_argument('--out', required=True)
ap.add_argument('--seg', default='out/fsd-data/models/yolo11s-seg.pt')
A = ap.parse_args(); os.makedirs(A.out, exist_ok=True)
meta = json.load(open(f'{A.pack}/{A.cams}'))['images']
moving = [c for c in json.load(open(A.index))['cars'] if not c.get('static')]
print('moving tracks', len(moving))

def track_pos(tr, t):
    ts = np.array(tr['t'])
    if t < ts[0] - 0.3 or t > ts[-1] + 0.3: return None
    return np.interp(t, ts, tr['x']), np.interp(t, ts, tr['z'])

yolo = YOLO(A.seg); forced = kept = 0
for e in meta:
    img = cv2.imread(f"{A.pack}/{e['file']}"); base = cv2.imread(f"{A.pack}/{e['mask']}", 0); cur = cv2.imread(f"{A.masks}/{os.path.basename(e['mask'])}", 0)
    out = cur.copy()
    r = yolo.predict(img[..., ::-1], imgsz=1024, classes=[2, 3, 5, 7], conf=0.25, verbose=False, retina_masks=True)[0]
    if r.masks is not None:
        K = np.array(e['K']); c2w = np.linalg.inv(np.array(e['w2c'])); o = c2w[:3, 3]
        for box, m in zip(r.boxes.xyxy.cpu().numpy(), r.masks.data.cpu().numpy() > 0.5):
            if not (cur[m] > 127).any(): continue                       # already hidden: nothing to decide
            u, v = (box[0] + box[2]) / 2, box[3]
            ray = c2w[:3, :3] @ np.linalg.solve(K, [u, v, 1.0])
            if ray[1] > -1e-3: continue                                  # box bottom above the horizon: cannot lift
            p = o + ray * (-o[1] / ray[1]); rng = np.linalg.norm(p - o)
            hit = False
            for tr in moving:
                q = track_pos(tr, e['t'])
                if q is not None and np.hypot(p[0] - q[0], p[2] - q[1]) < 2.5 + 0.06 * rng: hit = True; break
            if hit:
                mm = cv2.dilate(m.astype(np.uint8), np.ones((9, 9), np.uint8)) > 0
                out[mm & (base < 128)] = 0; forced += 1
            else: kept += 1
    cv2.imwrite(f"{A.out}/{os.path.basename(e['mask'])}", out)
    if e['i'] % 300 == 0: print(e['i'], 'forced', forced, 'kept static', kept, flush=True)
print('done: forced hidden', forced, 'kept static', kept)
