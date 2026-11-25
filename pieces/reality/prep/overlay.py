import sys, json, numpy as np
from PIL import Image, ImageDraw
sys.argv += [] 
exec(open('cal/bev.py').read().split('res = 0.08')[0].replace("CAMS = json.load(open(sys.argv[1]))\nS = sys.argv[2]; out = sys.argv[3]", ""))
CAMS = json.load(open(sys.argv[1])); S = sys.argv[2]; out = sys.argv[3]
lanes = [float(v) for v in (sys.argv[4] if len(sys.argv) > 4 else '-1.75,1.75,5.25,8.75').split(',')]
cols = [(255,60,60),(60,255,60),(80,160,255),(255,0,255),(255,255,0)]
tiles = []
for name, c in CAMS.items():
    im = Image.open(f'cal/{name}_{S}.png').convert('RGB'); W, H = im.size
    dr = ImageDraw.Draw(im)
    zs = np.concatenate([np.linspace(-200, 60, 2000)])
    for li, x in enumerate(lanes):
        P = np.stack([np.full_like(zs, x), np.zeros_like(zs), zs], -1)
        u, v, ok, th = project(c, P)
        pts = [(a*W, b*H) for a, b, k in zip(u, v, ok) if k]
        for i in range(len(pts)-1):
            if abs(pts[i][0]-pts[i+1][0]) < 50: dr.line([pts[i], pts[i+1]], fill=cols[li % 5], width=3)
    # horizon: points at 2km in all directions, y = cam height
    ang = np.linspace(0, 2*np.pi, 3000)
    P = np.stack([2000*np.sin(ang), np.full_like(ang, c['pos'][1]), -2000*np.cos(ang)], -1)
    u, v, ok, th = project(c, P)
    for a, b, k in zip(u, v, ok):
        if k: dr.point((a*W, b*H), fill=(255,255,255))
    # 10 m ticks on the x=lanes[1] line
    for z in range(-60, 40, 10):
        u, v, ok, _ = project(c, np.array([[lanes[1], 0, z], [lanes[1]+1, 0, z]]))
        if ok.all(): dr.line([(u[0]*W, v[0]*H), (u[1]*W, v[1]*H)], fill=(255,255,255), width=3)
    dr.text((10, 10), name, fill=(255,255,0))
    tiles.append(im.resize((724, 469)))
g = Image.new('RGB', (724*3, 469*2))
for i, t in enumerate(tiles): g.paste(t, ((i % 3)*724, (i//3)*469))
g.save(out)
