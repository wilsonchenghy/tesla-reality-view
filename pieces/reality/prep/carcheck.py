"""Project tracked vehicles back into all six cameras at drive time T (verification overlay). usage: carcheck.py T out.png"""
import sys, json, math, numpy as np
from PIL import Image, ImageDraw
T = float(sys.argv[1]); OUT = sys.argv[2]
D = 'out/reality-data'; idx = json.load(open(f'{D}/index.json')); RIG = json.load(open('pieces/reality/prep/rig.json'))
W, H = 1448, 938
exec('def basis' + open('pieces/reality/prep/cars.py').read().split('def basis', 1)[1].split('def unproject')[0])
def project(c, P):
    f, rt, d = basis(c); v = P - np.array(c['pos']); zc, xc, yc = v @ f, v @ rt, v @ d
    rho = np.hypot(xc, yc) + 1e-9; th = np.arctan2(rho, zc)
    rp = c['f'] * (th + c.get('k1', 0) * th ** 3 + c.get('k2', 0) * th ** 5)
    return 0.5 + rp * xc / rho, 0.5 + rp * yc / rho * (W / H), th
k = min(idx['kf'], key=lambda q: abs(q['t'] - T)); ki = k['i']
import pandas as pd
import os as _os; CLIP = _os.environ.get('CLIP', 'clip_00')    # which one-minute clip of the drive
cf = pd.read_parquet('out/fsd-data/data/camera_frames.parquet'); cf = cf[cf.clip_id == CLIP]
tiles = []
for cam in ['left_pillar', 'front', 'right_pillar', 'left_repeater', 'back', 'right_repeater']:
    g = cf[cf.camera == cam]; s = int(round(k['t'] * 36)); fi = int(g.frame_index.values[np.searchsorted(g.frame_seq_no.values, s).clip(0, len(g) - 1)])
    ids = json.load(open(f'{D}/tmp/{cam}/idx.json')); im = Image.open(f'{D}/tmp/{cam}/{ids.index(fi) + 1:04d}.jpg').convert('RGB'); dr = ImageDraw.Draw(im)
    c = RIG[cam]
    for tr in idx.get('cars', []):
        if not (tr['t'][0] <= k['t'] <= tr['t'][-1]): continue
        j = int(round((k['t'] - tr['t'][0]) / (tr['t'][1] - tr['t'][0])))
        wx, wz, wy = tr['x'][j], tr['z'][j], tr['yaw'][j]
        # world -> car frame
        dx, dz = wx - k['x'], wz - k['z']; cy, sy = math.cos(k['yaw']), math.sin(k['yaw'])
        cx, cz = cy * dx + sy * dz, -sy * dx + cy * dz; ry = wy - k['yaw']
        L, Wd, Hh = tr['len'], tr['wid'], tr['hgt']
        corners = []
        for a in (-1, 1):
            for b in (-1, 1):
                for h in (0, Hh):
                    lx, lz = a * Wd / 2, b * L / 2
                    corners.append([cx + math.cos(ry) * lx - math.sin(ry) * lz, h, cz + math.sin(ry) * lx + math.cos(ry) * lz])
        u, v, th = project(c, np.array(corners))
        if (th < math.radians(80)).all():
            dr.rectangle([u.min() * W, v.min() * H, u.max() * W, v.max() * H], outline=(255, 0, 255), width=4)
            dr.text((u.min() * W + 4, v.min() * H + 4), f"{tr['id']} {tr['cls']}", fill=(255, 0, 255))
    for x1, y1, x2, y2 in json.load(open(f'{D}/cars.json'))['masks'].get(str(ki), {}).get(cam, []):
        dr.rectangle([x1 * W, y1 * H, x2 * W, y2 * H], outline=(0, 255, 0), width=2)
    tiles.append(im.resize((724, 469)))
G = Image.new('RGB', (724 * 3, 469 * 2))
for i, t in enumerate(tiles): G.paste(t, ((i % 3) * 724, (i // 3) * 469))
G.save(OUT)
