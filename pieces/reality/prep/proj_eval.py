"""How right is the traffic? Project every modelled vehicle (3D box at its tracked pose) into every solved camera view at
that moment and match it to the detections there (Hungarian on box IoU). Reports precision (drawn vehicles that are
really there), recall (real vehicles within range that are drawn) and the mean IoU of matches, overall and for moving
traffic only.  usage: proj_eval.py --dets dets.json --cams cameras_rig3.json --tracks tracks.json|index.json [--maxr 40]"""
import argparse, json, math
import numpy as np
from scipy.optimize import linear_sum_assignment

ap = argparse.ArgumentParser(); ap.add_argument('--dets', required=True); ap.add_argument('--cams', required=True)
ap.add_argument('--tracks', required=True); ap.add_argument('--maxr', type=float, default=40.0); ap.add_argument('--iou', type=float, default=0.3)
A = ap.parse_args()
meta = {e['i']: e for e in json.load(open(A.cams))['images']}
views = json.load(open(A.dets)); T = json.load(open(A.tracks)); T = T['cars'] if isinstance(T, dict) else T

def pose(tr, t):
    ts = tr['t']
    if t < ts[0] or t > ts[-1]: return None
    return np.interp(t, ts, tr['x']), np.interp(t, ts, tr['z']), np.interp(t, ts, np.unwrap(tr['yaw']))

def project(e, tr, p):
    K = np.array(e['K']); w2c = np.array(e['w2c']); x, z, yaw = p
    c, s = math.cos(yaw), math.sin(yaw); fw = np.array([s, 0, -c]); rt = np.array([c, 0, s])
    L, W, H = tr['len'], tr['wid'], tr['hgt']
    pts = np.array([[x, 0, z] + fw * a * L / 2 + rt * b * W / 2 + np.array([0, h, 0]) for a in (-1, 1) for b in (-1, 1) for h in (0, H)])
    cam = (w2c[:3, :3] @ pts.T + w2c[:3, 3:4]).T
    if (cam[:, 2] < 0.3).any(): return None, None
    uv = (K @ cam.T).T; uv = uv[:, :2] / uv[:, 2:3]
    b = [uv[:, 0].min(), uv[:, 1].min(), uv[:, 0].max(), uv[:, 1].max()]
    Wi, Hi = e['width'], e['height']
    cb = [max(0, b[0]), max(0, b[1]), min(Wi, b[2]), min(Hi, b[3])]
    if cb[2] - cb[0] < 4 or cb[3] - cb[1] < 4: return None, None
    return cb, float(np.median(cam[:, 2]))

def iou(a, b):
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0])); iy = max(0, min(a[3], b[3]) - max(a[1], b[1])); i = ix * iy
    return i / ((a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - i + 1e-9)

S = dict(proj=0, det=0, match=0, ious=[], proj_mv=0, match_mv=0, ious_mv=[])
for v in views:
    e = meta[v['i']]
    P = []
    for tr in T:
        p = pose(tr, v['t'])
        if p is None: continue
        b, depth = project(e, tr, p)
        if b is not None and depth < A.maxr and (b[3] - b[1]) > 0.04 * e['height']: P.append((b, tr))   # same size cut as the detections
    D = [d['box'] for d in v['dets'] if (d['box'][3] - d['box'][1]) > 0.04 * e['height']]
    S['proj'] += len(P); S['det'] += len(D); S['proj_mv'] += sum(not tr.get('static') for _, tr in P)
    if not P or not D: continue
    C = np.array([[1 - iou(b, d) for d in D] for b, _ in P]); ri, ci = linear_sum_assignment(C)
    for i, j in zip(ri, ci):
        if 1 - C[i, j] >= A.iou:
            S['match'] += 1; S['ious'].append(1 - C[i, j])
            if not P[i][1].get('static'): S['match_mv'] += 1; S['ious_mv'].append(1 - C[i, j])
pr = S['match'] / max(1, S['proj']); rc = S['match'] / max(1, S['det'])
print(json.dumps(dict(tracks=len(T), moving=sum(not t.get('static') for t in T), precision=round(pr, 3), recall=round(rc, 3),
                      mIoU=round(float(np.mean(S['ious'])) if S['ious'] else 0, 3),
                      precision_moving=round(S['match_mv'] / max(1, S['proj_mv']), 3),
                      mIoU_moving=round(float(np.mean(S['ious_mv'])) if S['ious_mv'] else 0, 3))))
