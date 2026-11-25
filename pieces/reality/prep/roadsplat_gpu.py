"""GPU road builder (PyTorch): same method as roadsplat.py, minutes instead of the better part of an hour.
Road pixels of every view -> levelled ground -> dense 5 cm grid accumulated on the GPU (scatter_add), nearest views
weighted (1/r^3); lane-line registration rounds (ECC on paint edges against the fused road, OpenCV on CPU per view);
per-view exposure gains; output flat Gaussian splats (32-byte piece format) + the trained world minus its road layer.
usage: python roadsplat_gpu.py --gs DIR --cams cameras_rig3.json --world world_gs.bin --out OUTDIR
"""
import argparse, json, math, os, time
import numpy as np, cv2, torch
from PIL import Image
ap = argparse.ArgumentParser()
ap.add_argument('--gs', required=True); ap.add_argument('--cams', default='cameras_rig3.json')
ap.add_argument('--world', default=''); ap.add_argument('--out', required=True)
ap.add_argument('--cell', type=float, default=0.05); ap.add_argument('--maxr', type=float, default=22.0)
ap.add_argument('--wpow', type=float, default=2.5); ap.add_argument('--align', type=int, default=3)
A = ap.parse_args(); os.makedirs(A.out, exist_ok=True)
dev = 'cuda' if torch.cuda.is_available() else 'cpu'
t0 = time.time()
M = json.load(open(f'{A.gs}/{A.cams}'))['images']; GRD = json.load(open(f'{A.gs}/ground.json'))['ground']
C2W = {e['i']: np.linalg.inv(np.array(e['w2c'])) for e in M}
cen = np.array([c[:3, 3] for c in C2W.values()])
x0 = math.floor((cen[:, 0].min() - A.maxr - 2) / A.cell); z0 = math.floor((cen[:, 2].min() - A.maxr - 2) / A.cell)
GW = math.ceil((cen[:, 0].max() + A.maxr + 2) / A.cell) - x0; GH = math.ceil((cen[:, 2].max() + A.maxr + 2) / A.cell) - z0
NG = GW * GH; print('grid', GW, 'x', GH, f'({NG / 1e6:.1f} M cells) on', dev, flush=True)

# preload every view's road pixels (half-res mask -> full-res 2x2) and colours to the GPU once
V = []
for e in M:
    if not e.get('depth'): continue
    d = np.load(f"{A.gs}/{e['depth']}").astype(np.float32)
    vs, us = np.nonzero(d[1] >= 0.99)
    if len(us) == 0: continue
    img = np.asarray(Image.open(f"{A.gs}/{e['file']}").convert('RGB'))
    H, W = img.shape[:2]
    U = np.concatenate([us * 2 + 0.5, us * 2 + 1.5, us * 2 + 0.5, us * 2 + 1.5]).astype(np.float32)
    Vv = np.concatenate([vs * 2 + 0.5, vs * 2 + 0.5, vs * 2 + 1.5, vs * 2 + 1.5]).astype(np.float32)
    c = img[np.clip(Vv.astype(int), 0, H - 1), np.clip(U.astype(int), 0, W - 1)]
    K = np.array(e['K']); c2w = C2W[e['i']]
    V.append(dict(i=e['i'], cam=e['cam'], kf=e['kf'], U=torch.tensor(U).pin_memory(), V=torch.tensor(Vv).pin_memory(),   # host memory (16 GB cards), copied per view
                  c=torch.tensor(c, dtype=torch.float32).pin_memory(), K=K, R=torch.tensor(c2w[:3, :3], device=dev, dtype=torch.float32),
                  o=torch.tensor(c2w[:3, 3], device=dev, dtype=torch.float32), gy=float(GRD.get(str(e['kf']), 0.0))))
print('views', len(V), f'loaded in {time.time() - t0:.0f}s', flush=True)
CORR = {v['i']: torch.eye(3, device=dev) for v in V}       # per-view 2D (x, z) correction, homogeneous
GAIN = {v['i']: torch.ones(3, device=dev) for v in V}
SH = {}      # per camera: shading map (lens vignetting / sensor fall-off) on a 1/8-res pixel grid, 3 channels, multiplicative
SW, SHh = 181, 118

def cast(v, near=None):
    K = v['K']
    ray = torch.stack([(v['U'].to(dev, non_blocking=True) - K[0, 2]) / K[0, 0], (v['V'].to(dev, non_blocking=True) - K[1, 2]) / K[1, 1], torch.ones_like(v['U'].to(dev, non_blocking=True))], 1) @ v['R'].T
    t = (v['gy'] - v['o'][1]) / torch.where(ray[:, 1] > -1e-6, torch.full_like(ray[:, 1], -1e-6), ray[:, 1])
    rr = t * ray.norm(dim=1)
    ok = (t > 0) & (rr < (near or A.maxr))
    P = v['o'] + ray[ok] * t[ok, None]
    xz = torch.stack([P[:, 0], P[:, 2], torch.ones_like(P[:, 0])], 1) @ CORR[v['i']].T
    c = v['c'].to(dev, non_blocking=True)[ok] * GAIN[v['i']]
    if v['cam'] in SH:
        m = SH[v['cam']]; bi = (v['V'].to(dev, non_blocking=True)[ok] / 8).long().clamp(0, SHh - 1) * SW + (v['U'].to(dev, non_blocking=True)[ok] / 8).long().clamp(0, SW - 1)
        c = c * m[bi]
    return xz[:, :2], c, rr[ok], P[:, 1]

def fuse():
    acc = torch.zeros(NG, 6, device=dev)                  # w, w*r, w*g, w*b, w*y, count
    for v in V:
        xz, c, rr, y = cast(v)
        gx = torch.floor(xz[:, 0] / A.cell).long() - x0; gz = torch.floor(xz[:, 1] / A.cell).long() - z0
        inb = (gx >= 0) & (gx < GW) & (gz >= 0) & (gz < GH)
        idx = (gz[inb] * GW + gx[inb])
        w = 1.0 / rr[inb].clamp(min=2.0) ** A.wpow
        acc.index_add_(0, idx, torch.stack([w, w * c[inb, 0], w * c[inb, 1], w * c[inb, 2], w * y[inb], torch.ones_like(w)], 1))
    ws = acc[:, 0].clamp(min=1e-12)
    return acc[:, 1:4] / ws[:, None], acc[:, 4] / ws, acc[:, 5]

def edges(img):
    g = cv2.GaussianBlur(img, (0, 0), 1.0)
    return cv2.magnitude(cv2.Sobel(g, cv2.CV_32F, 1, 0), cv2.Sobel(g, cv2.CV_32F, 0, 1))

col, yy, cnt = fuse(); print(f'pass 1 {time.time() - t0:.0f}s', flush=True)
for rnd in range(A.align):
    mos = torch.where(cnt > 0, col.mean(1), torch.zeros_like(cnt)).view(GH, GW).cpu().numpy().astype(np.float32)
    mm = (cnt > 0).view(GH, GW).cpu().numpy().astype(np.uint8)
    shifts = []
    for v in V:
        xz, c, rr, _ = cast(v, near=16)
        if len(xz) < 2000: continue
        gx = (torch.floor(xz[:, 0] / A.cell).long() - x0).cpu().numpy(); gz = (torch.floor(xz[:, 1] / A.cell).long() - z0).cpu().numpy()
        g = c.mean(1).cpu().numpy()
        bx0, bx1, bz0, bz1 = max(gx.min(), 0), min(gx.max() + 1, GW), max(gz.min(), 0), min(gz.max() + 1, GH)
        if bx1 - bx0 < 64 or bz1 - bz0 < 64: continue
        vi = np.zeros((bz1 - bz0, bx1 - bx0), np.float32); vm = np.zeros_like(vi)
        inb = (gx >= bx0) & (gx < bx1) & (gz >= bz0) & (gz < bz1)
        np.add.at(vi, (gz[inb] - bz0, gx[inb] - bx0), g[inb]); np.add.at(vm, (gz[inb] - bz0, gx[inb] - bx0), 1)
        vi = np.where(vm > 0, vi / np.maximum(vm, 1), 0).astype(np.float32)
        mask = (cv2.dilate((vm > 0).astype(np.uint8), np.ones((3, 3), np.uint8)) & mm[bz0:bz1, bx0:bx1]).astype(np.uint8)
        if mask.sum() < 3000: continue
        warp = np.eye(2, 3, dtype=np.float32)
        try:
            _, warp = cv2.findTransformECC(edges(mos[bz0:bz1, bx0:bx1]), edges(vi), warp, cv2.MOTION_EUCLIDEAN,
                                           (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 60, 1e-5), mask, 5)
        except cv2.error:
            continue
        Wi = cv2.invertAffineTransform(warp)
        ang = math.degrees(math.atan2(Wi[1, 0], Wi[0, 0])); sh = float(np.hypot(Wi[0, 2], Wi[1, 2]) * A.cell)
        if abs(ang) > 3 or sh > 1.5 + abs(ang) * 0.3: continue
        S = np.array([[1 / A.cell, 0, -(bx0 + x0)], [0, 1 / A.cell, -(bz0 + z0)], [0, 0, 1]])
        T = np.linalg.inv(S) @ np.vstack([Wi, [0, 0, 1]]) @ S
        CORR[v['i']] = torch.tensor(T, device=dev, dtype=torch.float32) @ CORR[v['i']]; shifts.append(sh)
    col, yy, cnt = fuse()
    print(f'align {rnd}: registered {len(shifts)}/{len(V)} median shift {np.median(shifts):.3f} m p90 {np.percentile(shifts, 90):.3f} m  {time.time() - t0:.0f}s', flush=True)

# shading maps: per camera, mean log(fused / observed) by image position, smoothed; removes the seams between views
for _ in range(2):
    accs = {}
    for v in V:
        K = v['K']
        ray = torch.stack([(v['U'].to(dev, non_blocking=True) - K[0, 2]) / K[0, 0], (v['V'].to(dev, non_blocking=True) - K[1, 2]) / K[1, 1], torch.ones_like(v['U'].to(dev, non_blocking=True))], 1) @ v['R'].T
        xz, c, rr, _ = cast(v)
        t = (v['gy'] - v['o'][1]) / torch.where(ray[:, 1] > -1e-6, torch.full_like(ray[:, 1], -1e-6), ray[:, 1])
        ok = (t > 0) & ((t * ray.norm(dim=1)) < A.maxr)
        gx = torch.floor(xz[:, 0] / A.cell).long() - x0; gz = torch.floor(xz[:, 1] / A.cell).long() - z0
        inb = (gx >= 0) & (gx < GW) & (gz >= 0) & (gz < GH)
        idx = gz[inb] * GW + gx[inb]
        lr = torch.log(col[idx].clamp(min=4) / c[inb].clamp(min=4))
        bi = (v['V'].to(dev, non_blocking=True)[ok][inb] / 8).long().clamp(0, SHh - 1) * SW + (v['U'].to(dev, non_blocking=True)[ok][inb] / 8).long().clamp(0, SW - 1)
        a = accs.setdefault(v['cam'], torch.zeros(SW * SHh, 4, device=dev))
        a.index_add_(0, bi, torch.cat([lr, torch.ones_like(lr[:, :1])], 1))
    for cam, a in accs.items():
        m = (a[:, :3] / a[:, 3:].clamp(min=1)).view(SHh, SW, 3).cpu().numpy(); n = a[:, 3].view(SHh, SW).cpu().numpy()
        w = (n > 20).astype(np.float32)
        ms = cv2.GaussianBlur(m * w[..., None], (0, 0), 6); ws = cv2.GaussianBlur(w, (0, 0), 6)[..., None]
        m = np.where(ws > 1e-3, ms / np.maximum(ws, 1e-3), 0)
        m = np.clip(np.exp(m), 0.6, 1.7).astype(np.float32)
        prev = SH.get(cam); new = torch.tensor(m.reshape(-1, 3), device=dev)
        SH[cam] = new if prev is None else prev * new
        print(cam, 'shading map range', round(float(m.min()), 3), round(float(m.max()), 3), flush=True)
    col, yy, cnt = fuse()
# exposure gains per view (smoothed per camera over time), then the final fuse
raw = {}
for v in V:
    xz, c, rr, _ = cast(v, near=14)
    if len(xz) < 500: continue
    gx = torch.floor(xz[:, 0] / A.cell).long() - x0; gz = torch.floor(xz[:, 1] / A.cell).long() - z0
    inb = (gx >= 0) & (gx < GW) & (gz >= 0) & (gz < GH); idx = gz[inb] * GW + gx[inb]
    ratio = col[idx] / c[inb].clamp(min=8); raw[v['i']] = ratio.median(0).values.cpu().numpy()
for cam in sorted({v['cam'] for v in V}):
    vs_ = sorted([v for v in V if v['cam'] == cam], key=lambda v: v['kf'])
    g = np.array([raw.get(v['i'], np.full(3, np.nan)) for v in vs_])
    for ch in range(3):
        x = g[:, ch]; ok = np.isfinite(x)
        x = np.interp(np.arange(len(x)), np.where(ok)[0], x[ok]) if ok.any() else np.ones(len(x))
        g[:, ch] = np.convolve(np.pad(x, 5, mode='edge'), np.ones(11) / 11, mode='valid')
    for v, gg in zip(vs_, g): GAIN[v['i']] = torch.tensor(np.clip(gg, 0.6, 1.6), device=dev, dtype=torch.float32)
col, yy, cnt = fuse()
keep = (cnt >= 3).nonzero().squeeze(1)
gz, gx = keep // GW, keep % GW
X = (gx + x0 + 0.5) * A.cell; Z = (gz + z0 + 0.5) * A.cell
n = len(keep); print('road splats', n, f'{time.time() - t0:.0f}s', flush=True)
dt = np.dtype([('p', '<f4', 3), ('c', 'u1', 4), ('cov', '<f2', 6), ('pad', '<f2', 2)])
r = np.zeros(n, dtype=dt)
r['p'] = torch.stack([X, yy[keep] + 0.01, Z], 1).cpu().numpy()
r['c'][:, :3] = col[keep].round().clamp(0, 255).byte().cpu().numpy(); r['c'][:, 3] = 255
s = (A.cell * 0.62) ** 2; th = (A.cell * 0.03) ** 2
r['cov'] = np.array([s, 0, 0, th, 0, s], np.float16)
r.tofile(f'{A.out}/road_gs.bin')
json.dump({str(k): v.cpu().numpy().tolist() for k, v in CORR.items()}, open(f'{A.out}/road_corr.json', 'w'))
if A.world:
    wd = np.fromfile(A.world, dtype=dt); P = wd['p'].astype(np.float64)
    occ = (cnt >= 3).view(GH, GW).cpu().numpy()
    gxw = np.floor(P[:, 0] / A.cell).astype(int) - x0; gzw = np.floor(P[:, 2] / A.cell).astype(int) - z0
    inb = (gxw >= 0) & (gxw < GW) & (gzw >= 0) & (gzw < GH)
    onroad = np.zeros(len(P), bool); onroad[inb] = occ[gzw[inb], gxw[inb]]
    onroad &= P[:, 1] < 0.35
    cov = wd['cov'].astype(float); big = np.sqrt(np.maximum.reduce([cov[:, 0], cov[:, 3], cov[:, 5]])) > 2.5
    w2 = wd[~(onroad | big | (P[:, 1] < -0.6))]; w2.tofile(f'{A.out}/world_gs.bin')
    print('world', len(wd), '-> without road layer', len(w2))
print(f'done {time.time() - t0:.0f}s')
