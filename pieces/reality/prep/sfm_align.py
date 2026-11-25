"""Put the car, its path and the traffic into the solved (SfM rig) world the Gaussians were trained in.
Per keyframe the ego pose comes from the six solved cameras (rig centre, front-camera heading), interpolated to 30 fps;
every traffic track point is moved by the keyframe's telemetry->solved car transform. Ground height: --ground (metres).
usage: python3 pieces/reality/prep/sfm_align.py [--gs out/reality-gs] [--data out/reality-data] [--ground -0.0]
"""
import argparse, json, math
import numpy as np
ap = argparse.ArgumentParser(); ap.add_argument('--gs', default='out/reality-gs'); ap.add_argument('--data', default='out/reality-data')
ap.add_argument('--cams', default='cameras_rig.json'); ap.add_argument('--ground', type=float, default=None)
A = ap.parse_args()
M = json.load(open(f'{A.gs}/{A.cams}'))['images']; idx = json.load(open(f'{A.data}/index.json'))
import copy
if 'frames_tele' not in idx: idx['frames_tele'] = copy.deepcopy(idx['frames']); idx['path_tele'] = copy.deepcopy(idx['path']); idx['kf_tele'] = copy.deepcopy(idx['kf'])   # copies: kf is updated in place below
byk = {}
for e in M: byk.setdefault(e['kf'], {})[e['cam']] = np.linalg.inv(np.array(e['w2c']))
kt = np.array([k['t'] for k in idx['kf_tele']])
S = []      # solved car pose per keyframe: x, z, yaw, rig-centre height
for k in idx['kf_tele']:
    cs = byk[k['i']]; cen = np.mean([c[:3, 3] for c in cs.values()], 0); f = cs['front'][:3, 2]
    S.append([cen[0], cen[2], math.atan2(f[0], -f[2]), cen[1]])
S = np.array(S); S[:, 2] = np.unwrap(S[:, 2])
# light smoothing (keyframe noise), keep endpoints
ker = np.array([1, 2, 3, 2, 1.0]); ker /= ker.sum()
Ss = S.copy()
for c in range(4): Ss[2:-2, c] = np.convolve(S[:, c], ker, mode='valid')
T = np.array([[k['x'], k['z'], k['yaw']] for k in idx['kf_tele']]); T[:, 2] = np.unwrap(T[:, 2])
def interp(t, arr):
    return np.array([np.interp(t, kt, arr[:, c]) for c in range(arr.shape[1])])
def tele_to_solved(t, x, z):
    """world point at time t: telemetry world -> telemetry car frame -> solved world"""
    tx, tz, ty = interp(t, T); sx, sz, sy, _ = interp(t, Ss)
    dx, dz = x - tx, z - tz; c, s = math.cos(ty), math.sin(ty)
    cx, cz = c * dx + s * dz, -s * dx + c * dz                      # car frame (x right, z back)
    c2, s2 = math.cos(sy), math.sin(sy)
    return sx + c2 * cx - s2 * cz, sz + s2 * cx + c2 * cz, sy - ty
# 30 fps frames + dense path, solved
fr = []
for f in idx['frames_tele']:
    x, z, y, h = interp(min(max(f['t'], kt[0]), kt[-1]), Ss)
    fr.append(dict(f, x=round(float(x), 3), z=round(float(z), 3), yaw=round(float(y), 5)))
idx['frames'] = fr
pa = []
for p in idx['path_tele']:
    if kt[0] <= p[0] <= kt[-1]:
        x, z, y, h = interp(p[0], Ss); pa.append([p[0], round(float(x), 3), round(float(z), 3), round(float(y), 5)])
    else:          # outside the solved keyframes: carry the telemetry path with the end transform
        x, z, dy = tele_to_solved(p[0], p[1], p[2]); pa.append([p[0], round(x, 3), round(z, 3), round(p[3] + dy, 5)])
idx['path'] = pa
for k, s in zip(idx['kf'], Ss): k.update(x=round(float(s[0]), 3), z=round(float(s[1]), 3), yaw=round(float(s[2]), 5))
cars = idx.get('cars_tele', idx.get('cars', []))
idx['cars_tele'] = cars
out = []
for tr in cars:
    tr2 = dict(tr); xs, zs, ys = [], [], []
    for t, x, z, y in zip(tr['t'], tr['x'], tr['z'], tr['yaw']):
        a, b, dy = tele_to_solved(t, x, z); xs.append(round(a, 3)); zs.append(round(b, 3)); ys.append(round(y + dy, 4))
    tr2.update(x=xs, z=zs, yaw=ys); out.append(tr2)
idx['cars'] = out
if A.ground is not None: idx['ground_y'] = A.ground
idx['frame'] = 'sfm_rig'
json.dump(idx, open(f'{A.data}/index.json', 'w'))
print('aligned', len(fr), 'frames,', len(out), 'tracks; rig height median', round(float(np.median(Ss[:, 3])), 2))
