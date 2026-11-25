import json, numpy as np
from scipy.optimize import least_squares
src = open('cal/bev.py').read().split('res = 0.08')[0]
src = src.replace("CAMS = json.load(open(sys.argv[1]))\nS = sys.argv[2]; out = sys.argv[3]", "")
exec(src)
W, H = 1448, 938
# marks: list of (line_x or None(unknown), [(px,py),...]); 'vp': vanishing point of +z/-z road direction
M = {
 'left_pillar':  {'lines': [(-1.75, [(0,775),(200,787),(500,775),(800,745),(1000,712),(1200,668),(1440,605)]),
                            (None, [(0,598),(400,585),(800,565),(1200,535),(1440,510)])],
                  'horizon': [(500, 415)]},
 'right_pillar': {'lines': [(None, [(90,567),(290,598),(480,628),(765,653),(1145,673),(1430,670)]),
                            (None, [(0,490),(300,512),(600,530),(900,543),(1200,550),(1440,553)])],
                  'horizon': [(700, 420)]},
 'left_repeater':{'lines': [(-1.75, [(100,440),(200,560),(300,670),(400,770),(500,865),(560,920)]),
                            (None, [(600,505),(900,545),(1200,590),(1440,612)])],
                  'vp': (75, 420)},
 'right_repeater':{'lines': [(1.75, [(1065,718),(1290,528)]),
                             (None, [(275,592),(730,535)]),
                             (None, [(0,540),(400,515),(800,495),(1200,470)])],
                  'vp': (1385, 425)},
 'back':         {'lines': [(-1.75, [(770,200),(900,300),(1000,385),(1100,495),(1200,610),(1265,725)])],
                  'vp': (700, 195)},
}
cams = json.load(open('cal/cams.json'))
zs = np.sinh(np.linspace(-6.4, 6.4, 1500))
def residual(p, name, spec, base):
    c = dict(base); c['yaw'], c['pitch'], c['roll'], c['f'], c['k1'] = p[:5]
    r = []; k = 5
    for lx, pts in spec['lines']:
        if lx is None: lx = p[k]; k += 1
        P = np.stack([np.full_like(zs, lx), np.zeros_like(zs), zs], -1)
        u, v, ok, _ = project(dict(c, maxth=89), P)
        q = np.stack([u[ok]*W, v[ok]*H], -1)
        for pt in pts:
            r.append(np.min(np.linalg.norm(q - pt, axis=1)) if len(q) else 1e3)
    if 'vp' in spec:
        for zz in (1e5, -1e5):
            u, v, ok, _ = project(dict(c, maxth=89), np.array([[0, c['pos'][1], zz]]))
            if ok[0]: r += [u[0]*W - spec['vp'][0], v[0]*H - spec['vp'][1]]
    if 'horizon' in spec:
        for hx, hy in spec['horizon']:
            ang = np.linspace(0, 2*np.pi, 3600)
            P = np.stack([1e5*np.sin(ang), np.full_like(ang, c['pos'][1]), -1e5*np.cos(ang)], -1)
            u, v, ok, _ = project(dict(c, maxth=89), P)
            sel = ok & (np.abs(u*W - hx) < 5)
            r.append((v[sel][0]*H - hy) * 0.5 if sel.any() else 100)
    r.append((p[2]) * 5)  # small roll prior
    return np.array(r, float)
for name, spec in M.items():
    base = cams[name]
    nunk = sum(1 for lx, _ in spec['lines'] if lx is None)
    best = None
    for y0 in np.linspace(base['yaw']-40, base['yaw']+40, 9):
        for f0 in (0.25, 0.35, 0.5):
            p0 = [y0, base['pitch'], 0, f0, 0.0] + [(-6 if base['pos'][0] < 0 else 6)]*nunk
            try:
                s = least_squares(residual, p0, args=(name, spec, base), bounds=([-360,-60,-15,0.12,-0.3]+[-40]*nunk, [360,40,15,1.5,0.5]+[40]*nunk))
            except Exception as e: continue
            if best is None or s.cost < best.cost: best = s
    p = best.x
    cams[name].update(yaw=round(p[0],2), pitch=round(p[1],2), roll=round(p[2],2), f=round(p[3],4), k1=round(p[4],4))
    print(name, np.round(p, 3), 'rms px', np.sqrt(np.mean(best.fun[:-1]**2)).round(1))
json.dump(cams, open('cal/cams_fit.json', 'w'), indent=1)
