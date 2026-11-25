import sys, json, numpy as np
from PIL import Image
# car frame: X right, Y up, -Z forward. origin = ground under car centre.
CAMS = json.load(open(sys.argv[1]))
S = sys.argv[2]; out = sys.argv[3]
def basis(c):
    y, p, r = np.radians([c['yaw'], c['pitch'], c.get('roll', 0)])
    f = np.array([np.sin(y)*np.cos(p), np.sin(p), -np.cos(y)*np.cos(p)])
    rt = np.cross(f, [0,1,0]); rt /= np.linalg.norm(rt)
    d = np.cross(f, rt)
    cr, sr = np.cos(r), np.sin(r)
    return f, cr*rt + sr*d, -sr*rt + cr*d
def project(c, P):  # P: (...,3) -> u,v in [0,1], valid
    f, rt, d = basis(c)
    v = P - np.array(c['pos'])
    zc, xc, yc = v@f, v@rt, v@d
    rho = np.hypot(xc, yc) + 1e-9
    th = np.arctan2(rho, zc)
    rp = c['f'] * (th + c.get('k1', 0)*th**3 + c.get('k2', 0)*th**5)
    u = 0.5 + c.get('cx', 0) + rp*xc/rho            # f in units of image width
    w = 0.5 + c.get('cy', 0) + rp*yc/rho * c.get('aspect', 938/1448)**-1 * (938/1448) / (938/1448)
    vv = 0.5 + c.get('cy', 0) + rp*yc/rho * (1448/938)
    ok = (th < np.radians(c.get('maxth', 85))) & (u > 0) & (u < 1) & (vv > 0) & (vv < 1)
    return u, vv, ok, th
res = 0.08
xs = np.arange(-24, 24, res); zs = np.arange(-60, 20, res)
X, Z = np.meshgrid(xs, zs)
P = np.stack([X, np.zeros_like(X), Z], -1)
comp = np.zeros(X.shape + (3,)); wsum = np.zeros(X.shape)
tiles = []
for name, c in CAMS.items():
    img = np.asarray(Image.open(f'cal/{name}_{S}.png').convert('RGB')).astype(float)
    H, W = img.shape[:2]
    u, v, ok, th = project(c, P)
    ui = np.clip((u*W).astype(int), 0, W-1); vi = np.clip((v*H).astype(int), 0, H-1)
    col = img[vi, ui]
    ok &= col.sum(-1) > 25
    one = np.where(ok[..., None], col, 40)
    tiles.append(one)
    wt = ok * np.cos(th)**2 * c.get('w', 1)
    comp += col*wt[..., None]; wsum += wt
comp = comp/np.maximum(wsum, 1e-6)[..., None]
# grid lines every 3.6 m (x) and 10 m (z), car box
g = comp.copy()
for xv in np.arange(-21.6, 22, 3.6): g[:, int((xv+24)/res)] = [255, 0, 0]
for zv in range(-60, 20, 10): g[int((zv+60)/res), :] = [0, 255, 255]
g[int((-2.4+60)/res):int((2.4+60)/res), int((-0.95+24)/res):int((0.95+24)/res)] = [255,255,255]
Image.fromarray(np.clip(g, 0, 255).astype(np.uint8)).save(out)
row = np.concatenate([np.clip(t,0,255).astype(np.uint8) for t in tiles], 1)
Image.fromarray(row).resize((row.shape[1]//2, row.shape[0]//2)).save(out.replace('.png', '_each.png'))
