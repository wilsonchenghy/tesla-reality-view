"""Physical sanity check on vehicle tracks: nothing may occupy the space our own car drives through.
 - a parked (static) vehicle whose footprint touches our swept path at any time is impossible -> dropped
 - a moving vehicle that overlaps our car at the same moment (+-0.4 s) -> dropped
Footprints are oriented rectangles; our car 4.75 x 1.92 m plus a 0.3 m margin. usage: car_sanity.py index.json"""
import json, sys, math, numpy as np
p = sys.argv[1]; d = json.load(open(p))
P = np.array(d['path'])                      # t, x, z, yaw of our car (solved frame)
def corners(x, z, yaw, L, W):
    c, s = math.cos(yaw), math.sin(yaw); fw = np.array([s, -c]); rt = np.array([c, s])
    o = np.array([x, z]); return [o + fw * a * L / 2 + rt * b * W / 2 for a, b in ((1, 1), (1, -1), (-1, -1), (-1, 1))]
def overlap(A, B):                           # separating axis test for two convex quads
    for poly in (A, B):
        for i in range(4):
            e = poly[(i + 1) % 4] - poly[i]; n = np.array([-e[1], e[0]])
            pa = [q @ n for q in A]; pb = [q @ n for q in B]
            if max(pa) < min(pb) or max(pb) < min(pa): return False
    return True
EGO = (4.75 + 0.6, 1.92 + 0.6)
keep = []
for c in d['cars']:
    T = np.array(c['t']); bad = False
    if c.get('static'):
        x, z, y = c['x'][0], c['z'][0], c['yaw'][0]; B = corners(x, z, y, c['len'], c['wid'])
        for t, ex, ez, ey in P[::2]:
            if overlap(corners(ex, ez, ey, *EGO), B): bad = True; break
    else:
        X, Z = np.array(c['x']), np.array(c['z']); k = min(6, len(T) - 1); dtk = T[1] - T[0]
        v0 = ((X[k] - X[0]) / (k * dtk), (Z[k] - Z[0]) / (k * dtk)); v1 = ((X[-1] - X[-1 - k]) / (k * dtk), (Z[-1] - Z[-1 - k]) / (k * dtk))
        def pose(tt):
            if tt < T[0]: e = tt - T[0]; return X[0] + v0[0] * e, Z[0] + v0[1] * e, c['yaw'][0]
            if tt > T[-1]: e = tt - T[-1]; return X[-1] + v1[0] * e, Z[-1] + v1[1] * e, c['yaw'][-1]
            return np.interp(tt, T, X), np.interp(tt, T, Z), np.interp(tt, T, c['yaw'])
        def hits(tt):
            e = P[np.argmin(np.abs(P[:, 0] - tt))]; x, z, y = pose(tt)
            return overlap(corners(e[1], e[2], e[3], *EGO), corners(x, z, y, c['len'], c['wid']))
        # inside the observed span a collision means the track is wrong -> drop it
        bad = any(hits(tt) for tt in np.arange(T[0], T[-1] + 1e-6, 0.1))
        # outside it, coast only as far as is free (the piece reads c['ext'] = [back, forward] seconds)
        eb = 0.0
        while eb < 4 and not hits(T[0] - eb - 0.1): eb += 0.1
        ef = 0.0
        while ef < 4 and not hits(T[-1] + ef + 0.1): ef += 0.1
        c['ext'] = [round(eb, 1), round(ef, 1)]
    if bad: print('impossible (in our path):', c['id'], c['model'], 'static' if c.get('static') else 'moving')
    else: keep.append(c)
d['cars'] = keep; json.dump(d, open(p, 'w')); print('cars', len(keep))
