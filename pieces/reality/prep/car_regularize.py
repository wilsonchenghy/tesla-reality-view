"""Make traffic follow the road. Far vehicles lifted from one camera are metres off and their headings noisy, so:
 - moving: express each sample in road coordinates (distance along our path s, lateral offset l), keep s, smooth l hard
   (median for a vehicle that keeps its lane; ~1.5 s window if its lateral motion is a real lane change), heading = road
   heading at s (+180 deg for oncoming traffic)
 - static: drop if only seen beyond MAXR metres; heading snapped to the road (0 / 90 / 180 / 270 deg)
usage: car_regularize.py index.json [maxr]"""
import json, sys, math, numpy as np
p = sys.argv[1]; MAXR = float(sys.argv[2]) if len(sys.argv) > 2 else 28.0
d = json.load(open(p)); P = np.array(d['path']); P[:, 3] = np.unwrap(P[:, 3])
seg = np.diff(P[:, 1:3], axis=0); S = np.r_[0, np.cumsum(np.hypot(seg[:, 0], seg[:, 1]))]
def to_road(x, z):
    i = int(np.argmin((P[:, 1] - x) ** 2 + (P[:, 2] - z) ** 2)); yaw = P[i, 3]
    fw = np.array([math.sin(yaw), -math.cos(yaw)]); rt = np.array([math.cos(yaw), math.sin(yaw)])
    v = np.array([x - P[i, 1], z - P[i, 2]]); return S[i] + v @ fw, v @ rt
def from_road(s, l):
    yaw = np.interp(s, S, P[:, 3]); x0 = np.interp(s, S, P[:, 1]); z0 = np.interp(s, S, P[:, 2])
    return x0 + math.cos(yaw) * l, z0 + math.sin(yaw) * l, yaw
out = []
for c in d['cars']:
    rngs = [m[1] for o in c.get('obs', []) for m in o[3]]
    if c.get('static'):
        if rngs and min(rngs) > MAXR: print('drop far parked', c['id'], round(min(rngs), 1), 'm'); continue
        s, l = to_road(c['x'][0], c['z'][0]); ry = np.interp(s, S, P[:, 3])
        rel = (c['yaw'][0] - ry) % (2 * math.pi); q = round(rel / (math.pi / 2)) % 4
        c['yaw'] = [round(float(ry + q * math.pi / 2), 4)] * len(c['t']); out.append(c); continue
    sl = np.array([to_road(x, z) for x, z in zip(c['x'], c['z'])])
    s, l = sl[:, 0], sl[:, 1]
    oncoming = np.polyfit(c['t'], s, 1)[0] < 0
    if np.ptp(l) > 2.5 and abs(l[-1] - l[0]) > 2.0:      # a real lane change: keep the motion, remove the jitter
        k = max(3, int(1.5 / (c['t'][1] - c['t'][0]))) | 1
        l = np.convolve(np.pad(l, k // 2, mode='edge'), np.ones(k) / k, mode='valid')
    else:
        l = np.full_like(l, np.median(l))
    s = np.convolve(np.pad(s, 2, mode='edge'), np.ones(5) / 5, mode='valid')
    xs, zs, ys = zip(*[from_road(a, b) for a, b in zip(s, l)])
    c['x'] = [round(float(v), 3) for v in xs]; c['z'] = [round(float(v), 3) for v in zs]
    c['yaw'] = [round(float(y + (math.pi if oncoming else 0)), 4) for y in ys]
    out.append(c)
d['cars'] = out; json.dump(d, open(p, 'w')); print('cars', len(out))
