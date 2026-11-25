"""Post-clean trained gaussians: drop any inside our own car's volume at a keyframe pose (near-camera floaters),
and the huge/faint ones. usage: gs_clean.py in.bin out.bin [index.json]"""
import sys, json, math, numpy as np
src, dst = sys.argv[1], sys.argv[2]; idx = json.load(open(sys.argv[3] if len(sys.argv) > 3 else 'out/reality-data/index.json'))
dt = np.dtype([('p', '<f4', 3), ('c', 'u1', 4), ('cov', '<f2', 6), ('pad', '<f2', 2)])
g = np.fromfile(src, dtype=dt); P = g['p'].astype(np.float64)
bad = np.zeros(len(g), bool)
for k in idx['kf']:
    dx, dz = P[:, 0] - k['x'], P[:, 2] - k['z']; c, s = math.cos(k['yaw']), math.sin(k['yaw'])
    x = c * dx + s * dz; z = -s * dx + c * dz           # car frame, +z = behind
    bad |= (np.abs(x) < 1.15) & (z > -4.5) & (z < 5.0) & (P[:, 1] > 0.25) & (P[:, 1] < 2.1)
cov = g['cov'].astype(np.float64); big = np.sqrt(np.maximum.reduce([cov[:, 0], cov[:, 3], cov[:, 5]])) > 3.0
faint = g['c'][:, 3] < 12
keep = ~(bad | big | faint)
print('in', len(g), 'ego-volume', int(bad.sum()), 'huge', int(big.sum()), 'faint', int(faint.sum()), 'kept', int(keep.sum()))
g[keep].tofile(dst)
