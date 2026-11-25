"""Quick CPU preview of the splat reconstruction from a chase camera (z-buffered points). usage: preview.py KF out.png [back up]"""
import sys, json, math, numpy as np
from PIL import Image
D = 'out/reality-data'; idx = json.load(open(f'{D}/index.json'))
ki = int(sys.argv[1]); out = sys.argv[2]; back = float(sys.argv[3]) if len(sys.argv) > 3 else 8; up = float(sys.argv[4]) if len(sys.argv) > 4 else 3.5
dt = np.dtype([('p', '<f4', 3), ('c', 'u1', 3), ('k', 'u1'), ('n', 'i1', 3), ('s', 'u1')])
recs = []
for j in range(max(0, ki - 6), ki + 1):
    r = np.fromfile(f'{D}/kf/{j:03d}.bin', dtype=dt)
    if j < ki: r = r[(r['k'] & 1) == 1]          # history: road only
    recs.append(r)
r = np.concatenate(recs)
k = idx['kf'][ki]; x0, z0, yw = k['x'], k['z'], k['yaw']
fw = np.array([math.sin(yw), 0, -math.cos(yw)])
eye = np.array([x0, up, z0]) - fw * back
tgt = np.array([x0, 0.5, z0]) + fw * 14
f = tgt - eye; f /= np.linalg.norm(f); rt = np.cross(f, [0, 1, 0]); rt /= np.linalg.norm(rt); u = np.cross(rt, f)
Wd, Hd = 960, 540; foc = Wd / 2 / math.tan(math.radians(30))
v = r['p'] - eye; zc = v @ f; xs = v @ rt; ys = v @ u
m = zc > 0.5
px = (Wd / 2 + foc * xs[m] / zc[m]).astype(int); py = (Hd / 2 - foc * ys[m] / zc[m]).astype(int)
sz = 0.01 * 1.04 ** r['s'][m].astype(float); rad = np.clip(foc * sz / zc[m], 1, 12).astype(int)
col = r['c'][m]; zz = zc[m]
img = np.zeros((Hd, Wd, 3), np.uint8) + np.array([150, 160, 160], np.uint8); zb = np.full((Hd, Wd), 1e9)
order = np.argsort(-zz)
for rr in range(1, 13):
    sel = order[rad[order] == rr]
    for dy in range(-rr // 2, rr // 2 + 1):
        for dx in range(-rr // 2, rr // 2 + 1):
            X = px[sel] + dx; Y = py[sel] + dy
            ok = (X >= 0) & (X < Wd) & (Y >= 0) & (Y < Hd)
            X, Y, s2 = X[ok], Y[ok], sel[ok]
            closer = zz[s2] < zb[Y, X]
            X, Y, s2 = X[closer], Y[closer], s2[closer]
            img[Y, X] = col[s2]; zb[Y, X] = zz[s2]
Image.fromarray(img).save(out); print(len(r), 'splats')
