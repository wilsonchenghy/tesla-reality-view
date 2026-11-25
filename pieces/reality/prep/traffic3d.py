"""Traffic in the solved world, measured rather than patched:
 1. every pinhole detection (detect_pinhole.py) is lifted to the ground plane (y = 0) through its solved camera pose,
    from the instance mask's lowest pixels, then pushed back along the view ray to the vehicle centre; each lift gets a
    covariance that grows with range (range error ~ r^2 / (camera height * focal) per pixel) along the ray
 2. per keyframe, lifts from different cameras of the same vehicle are fused (information weighting)
 3. constant-velocity Kalman filter per vehicle, Hungarian association on Mahalanobis distance, birth after 3 hits,
    death after 8 misses; then a Rauch-Tung-Striebel smoother over each track
 4. heading from the smoothed velocity (held when slow); parked = slow throughout
Writes tracks in the piece's format (solved frame), ready to replace index.json "cars" after sfm_align.py.
  usage: traffic3d.py --dets dets.json --cams DIR/cameras_rig3.json --index out/reality-data/index.json --out tracks.json
"""
import argparse, json, math
import numpy as np
from scipy.optimize import linear_sum_assignment

ap = argparse.ArgumentParser()
ap.add_argument('--dets', required=True); ap.add_argument('--cams', required=True); ap.add_argument('--index', required=True)
ap.add_argument('--out', required=True); ap.add_argument('--maxr', type=float, default=60.0)
ap.add_argument('--static-masks', help='masks where parked vehicles are visible (motion_masks.py + force_moving.py): flow-based parked/moving per detection')
A = ap.parse_args()
SIZE = {'car': (4.7, 1.85, 1.5), 'truck': (6.5, 2.3, 2.6), 'bus': (11.0, 2.55, 3.1), 'moto': (2.1, 0.8, 1.4)}
HGT = {'car': (1.55, 0.15), 'truck': (2.4, 0.3), 'bus': (3.1, 0.12), 'moto': (1.4, 0.15)}   # height (m), relative spread
import cv2, os
_MK = {}
def parked(e, d):
    """flow-based verdict for this detection: its pixels are visible (not hidden) in the static-vehicle masks"""
    if not A.static_masks: return None
    f = os.path.join(A.static_masks, os.path.basename(e['mask']))
    if f not in _MK: _MK.clear(); _MK[f] = cv2.imread(f, 0)
    b = [int(round(v)) for v in d['box']]; m = _MK[f][b[1]:b[3], b[0]:b[2]]
    return bool(m.size and (m > 127).mean() > 0.5)
meta = {e['i']: e for e in json.load(open(A.cams))['images']}
views = json.load(open(A.dets)); idx = json.load(open(A.index))
kfs = sorted({v['kf'] for v in views}); KT = {v['kf']: v['t'] for v in views}
dt = float(np.median(np.diff([KT[k] for k in kfs])))
P_EGO = np.array(idx['path'])          # t, x, z, yaw (solved)

# ---- 1. lift ----
def box_fit(e, K, d, o, hr, r0, dims):
    """1-D search over range along the bearing (and road-aligned or crossing heading) for the vehicle centre whose
    projected 3D box best overlaps the detected box. Returns (centre xz, IoU)."""
    if d['cut'] or d['box'][0] < 2 or d['box'][2] > e['width'] - 2: return None   # truncated boxes do not constrain size
    w2c = np.array(e['w2c']); L, W, H = dims
    j = np.argmin(np.abs(P_EGO[:, 0] - e['t'])); ry = P_EGO[j, 3]
    best = (None, 0.0)
    rs = r0 * np.linspace(0.6, 1.5, 37)
    for yaw in (ry, ry + math.pi / 2):
        cy, sy = math.cos(yaw), math.sin(yaw); fw = np.array([sy, 0, -cy]); rt = np.array([cy, 0, sy])
        corners = np.array([fw * a * L / 2 + rt * b * W / 2 + np.array([0, hh, 0]) for a in (-1, 1) for b in (-1, 1) for hh in (0, H)])
        for r in rs:
            cen = np.array([o[0] + hr[0] * (r + 0.5 * min(L, W)), 0.0, o[2] + hr[1] * (r + 0.5 * min(L, W))])
            cam = (w2c[:3, :3] @ (corners + cen).T + w2c[:3, 3:4]).T
            if (cam[:, 2] < 0.3).any(): continue
            uv = (K @ cam.T).T; uv = uv[:, :2] / uv[:, 2:3]
            b = [uv[:, 0].min(), uv[:, 1].min(), uv[:, 0].max(), uv[:, 1].max()]; db = d['box']
            ix = max(0, min(b[2], db[2]) - max(b[0], db[0])); iy = max(0, min(b[3], db[3]) - max(b[1], db[1])); i = ix * iy
            u = (b[2] - b[0]) * (b[3] - b[1]) + (db[2] - db[0]) * (db[3] - db[1]) - i
            if i / u > best[1]: best = (np.array([cen[0], cen[2]]), i / u)
    return best if best[0] is not None else None

def lift(e, d):
    K = np.array(e['K']); c2w = np.linalg.inv(np.array(e['w2c'])); o = c2w[:3, 3]
    if d['cut']: return None                                     # contact point below the image: no ground lift
    u, v = d['contact']; f = K[1, 1]; h = o[1]
    cam_ray = np.linalg.solve(K, [u, v, 1.0]); ray = c2w[:3, :3] @ cam_ray
    if ray[1] > -0.01: return None
    p = o + ray * (-o[1] / ray[1]); r = math.hypot(p[0] - o[0], p[2] - o[2])
    if r > A.maxr or r < 1.0: return None
    hr = np.array([ray[0], ray[2]]); hr /= np.linalg.norm(hr)
    sc = 0.35 + 0.004 * r * r                                          # flat-ground lift: ~0.3 deg of road slope / pitch
    # second range cue: apparent height of a vehicle of known class height (depth = f * H / h_px)
    b = d['box']; hpx = b[3] - b[1]
    if b[1] > 2 and hpx > 8:
        Hr, rel = HGT[d['cls']]
        ps = o + ray * (f * Hr / hpx)                                  # ray has unit camera depth
        rs = math.hypot(ps[0] - o[0], ps[2] - o[2]); ss = rel * rs
        r_f = (r / sc ** 2 + rs / ss ** 2) / (1 / sc ** 2 + 1 / ss ** 2); sr0 = (1 / sc ** 2 + 1 / ss ** 2) ** -0.5
    else:
        r_f, sr0 = r, sc
    p = np.array([o[0], o[2]]) + hr * r_f
    L, Wd, Hh = SIZE[d['cls']]
    c = p + hr * (0.5 * min(L, Wd) + 0.35)                             # contact = near face; centre is ~half a width behind
    sr = max(0.3, sr0)
    fit = box_fit(e, K, d, o, hr, r_f, (L, Wd, Hh))                    # slide a sized box along the bearing to fit the detection
    if fit is not None and fit[1] > 0.6:
        c = fit[0]; sr = max(0.3, min(sr, 0.06 * r_f + 0.3))
    st = max(0.25, 0.012 * r)                                          # across the ray: well constrained
    Rm = np.outer(hr, hr) * sr ** 2 + np.outer([-hr[1], hr[0]], [-hr[1], hr[0]]) * st ** 2
    return dict(z=c, R=Rm, r=r_f, cls=d['cls'], col=d['col'], cam=e['cam'], box=d['box'], conf=d['conf'], parked=parked(e, d), vi=e['i'],
                o=np.array([o[0], o[2]]), hr=hr, sr=sr)

meas = {k: [] for k in kfs}
for v in views:
    e = meta[v['i']]
    for d in v['dets']:
        m = lift(e, d)
        if m: meas[v['kf']].append(m)

# ---- 2. fuse per keyframe ----
def fuse(L):
    L = sorted(L, key=lambda m: m['r']); out = []
    for m in L:
        for f in out:
            dd = m['z'] - f['z']; S = m['R'] + f['R']
            if dd @ np.linalg.solve(S, dd) < 9.21 and np.linalg.norm(dd) < 4.0:
                Ii = np.linalg.inv(f['R']) + np.linalg.inv(m['R']); Rn = np.linalg.inv(Ii)
                f['z'] = Rn @ (np.linalg.solve(f['R'], f['z']) + np.linalg.solve(m['R'], m['z'])); f['R'] = Rn
                f['members'].append(m); f['r'] = min(f['r'], m['r']); break
        else:
            out.append(dict(z=m['z'].copy(), R=m['R'].copy(), r=m['r'], members=[m]))
    return out
F = {k: fuse(meas[k]) for k in kfs}

# ---- 3. Kalman tracking ----
Fm = np.array([[1, 0, dt, 0], [0, 1, 0, dt], [0, 0, 1, 0], [0, 0, 0, 1.0]]); Hm = np.array([[1, 0, 0, 0], [0, 1, 0, 0.0]])
qa = 2.5                                                            # acceleration noise (m/s^2)
G = np.array([[dt * dt / 2, 0], [0, dt * dt / 2], [dt, 0], [0, dt]]); Q = G @ G.T * qa ** 2
tracks, done = [], []
for k in kfs:
    for tr in tracks:                                              # predict
        tr['x'] = Fm @ tr['x']; tr['P'] = Fm @ tr['P'] @ Fm.T + Q
    M = F[k]
    if tracks and M:
        C = np.full((len(tracks), len(M)), 1e6)
        for i, tr in enumerate(tracks):
            for j, m in enumerate(M):
                S = Hm @ tr['P'] @ Hm.T + m['R']; dd = m['z'] - Hm @ tr['x']
                d2 = dd @ np.linalg.solve(S, dd)
                if d2 < 13.8 and np.linalg.norm(dd) < 6.0: C[i, j] = d2 + math.log(np.linalg.det(S))
        ri, ci = linear_sum_assignment(C)
        pairs = [(i, j) for i, j in zip(ri, ci) if C[i, j] < 1e5]
    else:
        pairs = []
    hit_t, hit_m = {i for i, _ in pairs}, {j for _, j in pairs}
    for i, j in pairs:                                             # update
        tr, m = tracks[i], M[j]
        S = Hm @ tr['P'] @ Hm.T + m['R']; Kg = tr['P'] @ Hm.T @ np.linalg.inv(S)
        tr['x'] = tr['x'] + Kg @ (m['z'] - Hm @ tr['x']); tr['P'] = (np.eye(4) - Kg @ Hm) @ tr['P']
        tr['hits'] += 1; tr['miss'] = 0; tr['obs'].append((k, m))
    for i, tr in enumerate(tracks):
        if i not in hit_t: tr['miss'] += 1
        tr['hist'].append((k, tr['x'].copy(), tr['P'].copy(), i in hit_t))
    keep = []
    for tr in tracks:
        if tr['miss'] > 8 or (tr['hits'] < 3 and tr['miss'] > 2): done.append(tr)
        else: keep.append(tr)
    tracks = keep
    for j, m in enumerate(M):                                      # birth
        if j in hit_m: continue
        P0 = np.diag([m['R'][0, 0], m['R'][1, 1], 15.0 ** 2, 15.0 ** 2]); P0[:2, :2] = m['R']
        tracks.append(dict(x=np.array([m['z'][0], m['z'][1], 0, 0.0]), P=P0, hits=1, miss=0, obs=[(k, m)], hist=[(k, np.array([m['z'][0], m['z'][1], 0, 0.0]), P0, True)]))
done += tracks

# ---- 4. smooth, classify, emit ----
def rts(hist):
    xs = [h[1] for h in hist]; Ps = [h[2] for h in hist]
    xs_s, Ps_s = [xs[-1]], [Ps[-1]]
    for i in range(len(xs) - 2, -1, -1):
        Pp = Fm @ Ps[i] @ Fm.T + Q; C = Ps[i] @ Fm.T @ np.linalg.inv(Pp)
        xs_s.insert(0, xs[i] + C @ (xs_s[0] - Fm @ xs[i])); Ps_s.insert(0, Ps[i] + C @ (Ps_s[0] - Pp) @ C.T)
    return np.array(xs_s)

def bearing_test(obs):
    """Triangulate the track's bearings (precise) as if it stood still. A parked vehicle's bearings from our moving car
    meet in one point; a moving one's do not, or meet far from where the range cues put it. Returns (rms bearing residual
    in degrees, median range mismatch in sigmas, baseline in metres)."""
    M = [m for _, f in obs for m in f['members']]
    O = np.array([m['o'] for m in M]); D = np.array([m['hr'] for m in M]); N = np.stack([-D[:, 1], D[:, 0]], 1)
    w = 1 / np.maximum(np.array([m['r'] for m in M]), 3) ** 2
    Aq = (N[:, :, None] * N[:, None, :] * w[:, None, None]).sum(0); bq = (N * (N * O).sum(1, keepdims=True) * w[:, None]).sum(0)
    base = float(np.linalg.norm(O.max(0) - O.min(0)))
    if base < 3 or np.linalg.cond(Aq) > 1e6: return None, None, base
    X = np.linalg.solve(Aq, bq)
    V = X - O; rt = np.linalg.norm(V, axis=1)
    ang = np.degrees(np.arcsin(np.clip((N * V).sum(1) / np.maximum(rt, 1e-6), -1, 1)))
    if ((D * V).sum(1) < 0).mean() > 0.2: return 99.0, 99.0, base          # point behind the cameras: not a fixed point
    mis = np.median(np.abs(rt - np.array([m['r'] for m in M])) / np.array([m['sr'] for m in M]))
    return float(np.sqrt(np.mean(ang ** 2))), float(mis), base

def motion_test(obs):
    """chi-square gain of a constant-velocity fit over a constant-position fit to the raw fused lifts (with their
    covariances), and the fitted speed"""
    t = np.array([KT[k] for k, _ in obs]); t = t - t.mean()
    Z = [f['z'] for _, f in obs]; Wi = [np.linalg.inv(f['R']) for _, f in obs]
    Ip = sum(Wi); mu = np.linalg.solve(Ip, sum(w @ z for w, z in zip(Wi, Z)))
    c0 = sum((z - mu) @ w @ (z - mu) for w, z in zip(Wi, Z))
    J = [np.hstack([np.eye(2), ti * np.eye(2)]) for ti in t]
    Ah = sum(j.T @ w @ j for j, w in zip(J, Wi)); bh = sum(j.T @ w @ z for j, w, z in zip(J, Wi, Z))
    th = np.linalg.solve(Ah + 1e-9 * np.eye(4), bh)
    c1 = sum((z - j @ th) @ w @ (z - j @ th) for j, w, z in zip(J, Wi, Z))
    return float(c0 - c1), float(np.hypot(th[2], th[3]))

def on_road(X, ts):
    """moving traffic must sit on the carriageways (lateral offset from our path -30..+12 m, as cars.py) and, away from the
    intersection we turn through, travel along the road (either direction)"""
    lats, das = [], []
    sp = np.hypot(X[:, 2], X[:, 3])
    for (x, z, vx, vz), t in zip(X, ts):
        j = np.argmin(np.hypot(P_EGO[:, 1] - x, P_EGO[:, 2] - z)); yaw = P_EGO[j, 3]
        lats.append((x - P_EGO[j, 1]) * math.cos(yaw) + (z - P_EGO[j, 2]) * math.sin(yaw))
        if math.hypot(vx, vz) > 2: das.append(abs((math.atan2(vx, -vz) - yaw + math.pi) % (2 * math.pi) - math.pi))
    lat = float(np.median(lats))
    if not (-30 < lat < 12): return False
    turning = abs(P_EGO[np.argmin(np.abs(P_EGO[:, 0] - ts.mean())), 3] - P_EGO[0, 3]) < 1.2 and ts.mean() < P_EGO[0, 0] + 7
    if das and not turning:
        da = float(np.median(das)); return min(da, math.pi - da) < math.radians(35)
    return True

def on_carriageway(x, z):
    j = np.argmin(np.hypot(P_EGO[:, 1] - x, P_EGO[:, 2] - z)); yaw = P_EGO[j, 3]
    lat = (x - P_EGO[j, 1]) * math.cos(yaw) + (z - P_EGO[j, 2]) * math.sin(yaw)
    return -22 < lat < 8

def footprint(tr, t):
    if t < tr['t'][0] or t > tr['t'][-1]: return None
    x, z, y = np.interp(t, tr['t'], tr['x']), np.interp(t, tr['t'], tr['z']), np.interp(t, tr['t'], np.unwrap(tr['yaw']))
    c, s_ = math.cos(y), math.sin(y); fw = np.array([s_, -c]); rt = np.array([c, s_])
    return np.array([[x, z] + fw * a * tr['len'] / 2 + rt * b * tr['wid'] / 2 for a, b in ((1, 1), (1, -1), (-1, -1), (-1, 1))])

def overlap(P, Q):
    """separating-axis test for two convex quads"""
    for poly in (P, Q):
        for i in range(4):
            e = poly[(i + 1) % 4] - poly[i]; ax = np.array([-e[1], e[0]])
            a, b = P @ ax, Q @ ax
            if a.max() < b.min() or b.max() < a.min(): return False
    return True

def resolve_overlaps(out):
    """vehicles cannot interpenetrate: a pair that overlaps for most of its shared time is one vehicle twice (or a bad
    fragment); keep the better supported one"""
    drop = set(); order = sorted(range(len(out)), key=lambda i: -out[i]['n'])
    for ii, i in enumerate(order):
        if i in drop or not out[i]['hidden']: continue
        for j in order[ii + 1:]:
            if j in drop or not out[j]['hidden']: continue
            a, b = out[i], out[j]
            t0, t1 = max(a['t'][0], b['t'][0]), min(a['t'][-1], b['t'][-1])
            if a['static']: t0, t1 = b['t'][0], b['t'][-1]
            if b['static'] and not a['static']: t0, t1 = a['t'][0], a['t'][-1]
            if t1 <= t0: continue
            ts = np.linspace(t0, t1, max(3, int((t1 - t0) * 8)))
            hits = tot = 0
            for t in ts:
                P, Q = (footprint(a, t) if not a['static'] else footprint(a, a['t'][0])), (footprint(b, t) if not b['static'] else footprint(b, b['t'][0]))
                if P is None or Q is None: continue
                tot += 1; hits += overlap(P, Q)
            if tot and hits / tot > 0.3: drop.add(j)
    return [o for k, o in enumerate(out) if k not in drop], len(drop)

def verify(out):
    """self-consistency: project each moving track's 3D box into the views of its own member detections at those moments;
    a real vehicle lines up with its own evidence (IoU >= 0.3) most of the time, a phantom (range error, duplicate) does not"""
    keep, nd = [], 0
    for tr in out:
        if tr['static'] or not tr.get('_members'): keep.append(tr); continue
        ok = tot = 0
        for (vi, t, box) in tr['_members']:
            e = meta[vi]; K = np.array(e['K']); w2c = np.array(e['w2c'])
            x, z, y = np.interp(t, tr['t'], tr['x']), np.interp(t, tr['t'], tr['z']), np.interp(t, tr['t'], np.unwrap(tr['yaw']))
            c, s_ = math.cos(y), math.sin(y); fw = np.array([s_, 0, -c]); rt = np.array([c, 0, s_])
            P = np.array([[x, 0, z] + fw * a * tr['len'] / 2 + rt * b * tr['wid'] / 2 + np.array([0, h, 0]) for a in (-1, 1) for b in (-1, 1) for h in (0, tr['hgt'])])
            cc = (w2c[:3, :3] @ P.T + w2c[:3, 3:4]).T
            if (cc[:, 2] < 0.3).any(): continue
            uv = (K @ cc.T).T; uv = uv[:, :2] / uv[:, 2:3]
            b = [max(0, uv[:, 0].min()), max(0, uv[:, 1].min()), min(e['width'], uv[:, 0].max()), min(e['height'], uv[:, 1].max())]
            ix = max(0, min(b[2], box[2]) - max(b[0], box[0])); iy = max(0, min(b[3], box[3]) - max(b[1], box[1])); i = ix * iy
            u = (b[2] - b[0]) * (b[3] - b[1]) + (box[2] - box[0]) * (box[3] - box[1]) - i
            tot += 1; ok += (i / max(u, 1e-6)) >= 0.3
        if tot and ok / tot < 0.25: nd += 1; continue
        keep.append(tr)
    return keep, nd

def ego_heading(t):
    j = np.argmin(np.abs(P_EGO[:, 0] - t)); return P_EGO[j, 3]

out = []
for tid, tr in enumerate(done):
    if tr['hits'] < 6: continue
    H_ = [h for h in tr['hist']]
    last = max(i for i, h in enumerate(H_) if h[3]); H_ = H_[:last + 1]     # drop the coasting tail
    X = rts(H_); ts = np.array([KT[h[0]] for h in H_])
    sp = np.hypot(X[:, 2], X[:, 3])
    disp = math.hypot(X[-1, 0] - X[0, 0], X[-1, 1] - X[0, 1])
    votes = [m['parked'] for _, f in tr['obs'] for m in f['members'] if m['parked'] is not None]
    brms, bmis, base = bearing_test(tr['obs'])
    pf = float(np.mean(votes)) if votes else None
    if brms is not None:
        static = bool(brms < 1.8 and bmis < 3.0)                       # the bearings meet where the ranges say (mask centres wander ~1 deg)
    else:
        dchi, vfit = motion_test(tr['obs']); static = bool(vfit < 1.0 or (pf is not None and pf > 0.7))
    hidden = (pf is None) or pf < 0.5                                  # not visible in the trained world: drawn as a model
    onroad = bool(static and on_carriageway(X[0, 0], X[0, 1]))      # standing in a lane (queued at a light): traffic, not scenery
    if static and not onroad and pf is not None and pf >= 0.2: hidden = False   # parked and seen in part of the views: the world has it
    if onroad: hidden = True
    if static and min(f['r'] for _, f in tr['obs']) > 28: hidden = False   # parked and only seen far away: too uncertain to place (as car_regularize.py)
    if not static and not on_road(X, ts):                              # road prior: traffic drives on the carriageway
        static = True
    obs = tr['obs']; cls = [m['cls'] for _, f in obs for m in f['members']]; cls = max(set(cls), key=cls.count)
    if static:
        X[:, 0] = np.median(X[:, 0]); X[:, 1] = np.median(X[:, 1]); X[:, 2:] = 0
        # parked: orientation from the nearest view's box shape (wide = seen side-on), snapped to the street grid
        mn = min((m for _, f in obs for m in f['members']), key=lambda m: m['r']); b = mn['box']
        az = math.atan2(mn['hr'][0], -mn['hr'][1])
        yaw0 = az + (math.pi / 2 if (b[2] - b[0]) / max(1e-6, b[3] - b[1]) > 1.75 else 0.0)
        ry = ego_heading(ts.mean()); q = round(((yaw0 - ry) % (2 * math.pi)) / (math.pi / 2)) % 4
        if on_carriageway(X[0, 0], X[0, 1]): q = 0 if q in (0, 1) else 2       # queued in a lane: along the road
        yaw = np.full(len(ts), ry + q * math.pi / 2)
    else:
        yaw = np.arctan2(X[:, 2], -X[:, 3])
        ok = sp > 2.0
        if ok.any():
            yi = np.interp(np.arange(len(ts)), np.flatnonzero(ok), np.unwrap(yaw[ok]))
            yaw = np.convolve(np.pad(yi, 3, mode='edge'), np.ones(7) / 7, mode='valid')
        else:
            yaw = np.full(len(ts), ego_heading(ts.mean()))
    near = [m for _, f in obs for m in f['members']]
    col = np.median(np.array([m['col'] for m in sorted(near, key=lambda m: m['r'])[:8]]), 0).astype(int).tolist()
    rear = [m['box'] for m in near if m['cam'] in ('front', 'back')]
    asp = float(np.median([(b[3] - b[1]) / max(1e-6, b[2] - b[0]) for b in rear])) if rear else 0.8
    model = ('boxtruck' if asp > 1.0 else 'pickup') if cls in ('truck', 'bus') else ('suv' if asp > 0.85 else 'sedan')
    SZ = {'boxtruck': (7.2, 2.45, 3.3), 'pickup': (5.8, 2.0, 1.95), 'suv': (4.9, 1.95, 1.78), 'sedan': (4.7, 1.85, 1.45)}
    Lm, Wm, Hm_ = SZ[model]
    out.append(dict(id=tid, cls=cls, static=static, model=model, aspect=round(asp, 2), color=col, speed=round(float(np.median(sp)), 2),
                    t=[round(float(v), 4) for v in ts], x=[round(float(v), 3) for v in X[:, 0]], z=[round(float(v), 3) for v in X[:, 1]],
                    yaw=[round(float(v), 4) for v in yaw], len=Lm, wid=Wm, hgt=Hm_, n=tr['hits'], minr=round(min(f['r'] for _, f in obs), 1),
                    hidden=bool(hidden), onroad=onroad, brms=None if brms is None else round(brms, 2),
                    _members=[(m['vi'], KT[k], m['box']) for k, f in obs for m in f['members']]))
out, nd = resolve_overlaps(out); print('dropped overlapping', nd)
out, nv = verify(out); print('dropped phantom (moving tracks that do not line up with their own detections)', nv)
for tr in out: tr.pop('_members', None)
json.dump(out, open(A.out, 'w'))
print('tracks', len(out), 'moving', sum(not t['static'] for t in out), 'static', sum(t['static'] for t in out))
