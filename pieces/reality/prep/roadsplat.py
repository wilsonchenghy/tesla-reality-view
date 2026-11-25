"""Sharp, smooth road as Gaussian splats.
Every road pixel of every view is cast onto the levelled ground (solved metric rig) and fused into CELL-sized cells.
Two passes: (1) fuse, (2) per view, a colour gain (3 channels) that maps the view onto the fused road, smoothed over time
per camera (exposure / white balance differ between the six cameras and drift over the drive), then fuse again with the
gains. Nearest views dominate (w = 1/r^3) so paint stays crisp; the gains remove the quilt between views.
Output: flat gaussians (32-byte piece format) <out>/road_gs.bin, and the trained world without its own road layer.
usage: python3 pieces/reality/prep/roadsplat.py --gs out/reality-gs --cams cameras_rig3.json --world out/reality-gs-out/v7/world_gs.bin
"""
import argparse, json, math, numpy as np, cv2
from PIL import Image
ap = argparse.ArgumentParser()
ap.add_argument('--gs', default='out/reality-gs'); ap.add_argument('--cams', default='cameras_rig3.json')
ap.add_argument('--world', default='out/reality-gs-out/v7/world_gs.bin'); ap.add_argument('--out', default='out/reality-data')
ap.add_argument('--cell', type=float, default=0.05); ap.add_argument('--maxr', type=float, default=22.0)
ap.add_argument('--wpow', type=float, default=3.0)
ap.add_argument('--align', type=int, default=2, help='lane-line registration rounds (0 = off)')
A = ap.parse_args()
M = json.load(open(f'{A.gs}/{A.cams}'))['images']; G = json.load(open(f'{A.gs}/ground.json'))['ground']
C2W = {e['i']: np.linalg.inv(np.array(e['w2c'])) for e in M}
BIG = 20000003

CORR = {}     # view id -> 2x3 affine on world (x, z): lane-line registration result
def observe(e, fine=True, keys=True):
    """road observations of one view: cell keys (or xz), rgb (float), range, ground y"""
    if not e.get('depth'): return None
    d = np.load(f"{A.gs}/{e['depth']}").astype(np.float32)
    vs, us = np.nonzero(d[1] >= 0.99)
    if len(us) == 0: return None
    img = np.asarray(Image.open(f"{A.gs}/{e['file']}").convert('RGB'))
    H, W = img.shape[:2]
    if fine: U = np.concatenate([us * 2 + 0.5, us * 2 + 1.5, us * 2 + 0.5, us * 2 + 1.5]); V = np.concatenate([vs * 2 + 0.5, vs * 2 + 0.5, vs * 2 + 1.5, vs * 2 + 1.5])
    else: U = us * 2 + 1.0; V = vs * 2 + 1.0
    K = np.array(e['K']); c2w = C2W[e['i']]; o = c2w[:3, 3]
    ray = np.stack([(U - K[0, 2]) / K[0, 0], (V - K[1, 2]) / K[1, 1], np.ones_like(U)], 1) @ c2w[:3, :3].T
    gy = G.get(str(e['kf']), 0.0)
    t = (gy - o[1]) / np.where(ray[:, 1] > -1e-6, -1e-6, ray[:, 1])
    rr = t * np.linalg.norm(ray, axis=1)
    ok = (t > 0) & (rr < A.maxr)
    P = o + ray[ok] * t[ok, None]
    c = img[np.clip(V[ok].astype(int), 0, H - 1), np.clip(U[ok].astype(int), 0, W - 1)].astype(np.float32)
    XZ = P[:, [0, 2]]
    if e['i'] in CORR: XZ = XZ @ CORR[e['i']][:, :2].T + CORR[e['i']][:, 2]
    if not keys: return XZ, c, rr[ok].astype(np.float32), P[:, 1].astype(np.float32)
    k = np.floor(XZ / A.cell).astype(np.int64)
    return k[:, 0] * BIG + k[:, 1], c, rr[ok].astype(np.float32), P[:, 1].astype(np.float32)

def fuse(gains):
    PART = []; buf = []
    def flush():
        if not buf: return
        K_ = np.concatenate([b[0] for b in buf]); C_ = np.concatenate([b[1] for b in buf])
        R_ = np.concatenate([b[2] for b in buf]); Y_ = np.concatenate([b[3] for b in buf])
        w = 1.0 / np.maximum(R_, 2.0) ** A.wpow
        uk, inv = np.unique(K_, return_inverse=True)
        PART.append((uk, np.bincount(inv, weights=w), np.stack([np.bincount(inv, weights=C_[:, i] * w) for i in range(3)], 1),
                     np.bincount(inv, weights=Y_ * w), np.bincount(inv).astype(np.float64)))
        buf.clear()
    for ei, e in enumerate(M):
        o = observe(e)
        if o is None: continue
        k, c, r, y = o
        buf.append((k, c * gains[e['i']], r, y))
        if len(buf) >= 50: flush()
    flush()
    AK = np.concatenate([p[0] for p in PART]); uk, inv = np.unique(AK, return_inverse=True)
    ws = np.bincount(inv, weights=np.concatenate([p[1] for p in PART]))
    WC = np.concatenate([p[2] for p in PART]); col = np.stack([np.bincount(inv, weights=WC[:, i]) for i in range(3)], 1) / ws[:, None]
    y = np.bincount(inv, weights=np.concatenate([p[3] for p in PART])) / ws
    cnt = np.bincount(inv, weights=np.concatenate([p[4] for p in PART]))
    return uk, col, y, cnt

ones = {e['i']: np.ones(3, np.float32) for e in M}
uk, col, y, cnt = fuse(ones)
print('pass 1 cells', len(uk))

def edges(img):
    g = cv2.GaussianBlur(img, (0, 0), 1.0)
    return cv2.magnitude(cv2.Sobel(g, cv2.CV_32F, 1, 0), cv2.Sobel(g, cv2.CV_32F, 0, 1))
for rnd in range(A.align):
    # fused mosaic raster (grey) from the cells
    cx = np.floor_divide(uk + BIG // 2, BIG); cz = uk - cx * BIG
    x0, z0 = cx.min(), cz.min(); Wm, Hm = int(cx.max() - x0 + 1), int(cz.max() - z0 + 1)
    mos = np.zeros((Hm, Wm), np.float32); mos[(cz - z0).astype(int), (cx - x0).astype(int)] = col.mean(1)
    mm = np.zeros((Hm, Wm), np.uint8); mm[(cz - z0).astype(int), (cx - x0).astype(int)] = 1
    moved = []
    for e in M:
        o = observe(e, fine=False, keys=False)
        if o is None: continue
        XZ, c, r, _ = o; sel = r < 16
        if sel.sum() < 2000: continue
        g = np.floor(XZ[sel] / A.cell).astype(np.int64)
        gx, gz = g[:, 0] - x0, g[:, 1] - z0
        bx0, bx1, bz0, bz1 = max(gx.min(), 0), min(gx.max() + 1, Wm), max(gz.min(), 0), min(gz.max() + 1, Hm)
        if bx1 - bx0 < 64 or bz1 - bz0 < 64: continue
        vi = np.zeros((bz1 - bz0, bx1 - bx0), np.float32); vm = np.zeros_like(vi)
        inb = (gx >= bx0) & (gx < bx1) & (gz >= bz0) & (gz < bz1)
        np.add.at(vi, (gz[inb] - bz0, gx[inb] - bx0), c[sel][inb].mean(1)); np.add.at(vm, (gz[inb] - bz0, gx[inb] - bx0), 1)
        vi = np.where(vm > 0, vi / np.maximum(vm, 1), 0); vmask = cv2.dilate((vm > 0).astype(np.uint8), np.ones((3, 3), np.uint8))
        tmpl = mos[bz0:bz1, bx0:bx1]; tm = mm[bz0:bz1, bx0:bx1]
        mask = (vmask & tm).astype(np.uint8)
        if mask.sum() < 3000: continue
        warp = np.eye(2, 3, dtype=np.float32)
        try:
            _, warp = cv2.findTransformECC(edges(tmpl), edges(vi.astype(np.float32)), warp, cv2.MOTION_EUCLIDEAN,
                                           (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 60, 1e-5), mask, 5)
        except cv2.error:
            continue
        # warp maps mosaic (template) pixels -> view pixels; view point p -> mosaic: inverse
        Wi = cv2.invertAffineTransform(warp)
        ang = math.degrees(math.atan2(Wi[1, 0], Wi[0, 0])); sh = np.hypot(Wi[0, 2], Wi[1, 2]) * A.cell
        if abs(ang) > 3 or sh > 1.5 + abs(ang) * 0.3: continue
        # to world xz: view-local pixel (u, v) = (x/cell - bx0 - x0, z/cell - bz0 - z0)
        S = np.array([[1 / A.cell, 0, -(bx0 + x0)], [0, 1 / A.cell, -(bz0 + z0)], [0, 0, 1]])
        Wf = np.vstack([Wi, [0, 0, 1]]); Si = np.linalg.inv(S)
        T = Si @ Wf @ S                                                   # world xz -> corrected world xz (on top of the old one)
        old = np.vstack([CORR.get(e['i'], np.array([[1, 0, 0], [0, 1, 0.0]])), [0, 0, 1]])
        CORR[e['i']] = (T @ old)[:2]; moved.append(sh)
    print(f'align round {rnd}: views registered {len(moved)}, median shift {np.median(moved) if moved else 0:.3f} m, p90 {np.percentile(moved, 90) if moved else 0:.3f} m', flush=True)
    uk, col, y, cnt = fuse(ones)
# per-view gains: median of fused / observed over the view's road cells (near range only: well-resolved paint)
raw = {}
for e in M:
    o = observe(e)
    if o is None: continue
    k, c, r, _ = o
    sel = r < 14
    if sel.sum() < 500: continue
    j = np.searchsorted(uk, k[sel]); j = np.clip(j, 0, len(uk) - 1); hit = uk[j] == k[sel]
    if hit.sum() < 500: continue
    ratio = col[j[hit]] / np.maximum(c[sel][hit], 8)
    raw[e['i']] = np.median(ratio, 0)
# smooth over time per camera (a camera's exposure drifts slowly)
gains = dict(ones)
for cam in sorted({e['cam'] for e in M}):
    es = sorted([e for e in M if e['cam'] == cam], key=lambda e: e['kf'])
    g = np.array([raw.get(e['i'], np.full(3, np.nan)) for e in es])
    for ch in range(3):
        v = g[:, ch]; ok = np.isfinite(v)
        if ok.sum() == 0: g[:, ch] = 1; continue
        v = np.interp(np.arange(len(v)), np.where(ok)[0], v[ok])
        g[:, ch] = np.convolve(np.pad(v, 5, mode='edge'), np.ones(11) / 11, mode='valid')
    for e, gg in zip(es, g): gains[e['i']] = np.clip(gg, 0.6, 1.6).astype(np.float32)
    print(cam, 'gain median', np.round(np.median(g, 0), 3))
uk, col, y, cnt = fuse(gains)
keep = cnt >= 3
uk, col, y = uk[keep], col[keep], y[keep]
cx = np.floor_divide(uk + BIG // 2, BIG); cz = uk - cx * BIG
X = (cx + 0.5) * A.cell; Z = (cz + 0.5) * A.cell
n = len(X); print('road splats', n)
dt = np.dtype([('p', '<f4', 3), ('c', 'u1', 4), ('cov', '<f2', 6), ('pad', '<f2', 2)])
r = np.zeros(n, dtype=dt)
r['p'] = np.stack([X, y + 0.01, Z], 1)
r['c'][:, :3] = np.clip(np.round(col), 0, 255); r['c'][:, 3] = 255
s = (A.cell * 0.62) ** 2; th = (A.cell * 0.03) ** 2
r['cov'] = np.array([s, 0, 0, th, 0, s], np.float16)
r.tofile(f'{A.out}/road_gs.bin')
# trained world minus its road layer (gaussians low over a road cell)
wd = np.fromfile(A.world, dtype=dt); P = wd['p'].astype(np.float64)
kk = np.floor(P[:, [0, 2]] / A.cell).astype(np.int64); kk = kk[:, 0] * BIG + kk[:, 1]
onroad = np.isin(kk, uk) & (P[:, 1] < 0.35)
cov = wd['cov'].astype(float); big = np.sqrt(np.maximum.reduce([cov[:, 0], cov[:, 3], cov[:, 5]])) > 2.5
w2 = wd[~(onroad | big | (P[:, 1] < -0.6))]
w2.tofile(f'{A.out}/world_gs.bin')
print('world', len(wd), '-> without road layer', len(w2))
