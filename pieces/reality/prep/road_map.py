"""Where is the road? Segment every solved pinhole view (SegFormer, Cityscapes classes), cast its road and not-road pixels
onto the ground plane (y = 0) through the solved camera pose, and vote them into a top-down grid. traffic3d.py uses the
grid to keep vehicles on the road.
usage: road_map.py --cams cameras_rig3.json --out road_map.npz [--res 0.5] [--maxr 50]"""
import argparse, json, os
import numpy as np, torch
from PIL import Image
from transformers import SegformerForSemanticSegmentation, SegformerImageProcessor

ap = argparse.ArgumentParser(); ap.add_argument('--cams', required=True); ap.add_argument('--out', required=True)
ap.add_argument('--res', type=float, default=0.5); ap.add_argument('--maxr', type=float, default=50.0)
ap.add_argument('--model', default='nvidia/segformer-b2-finetuned-cityscapes-1024-1024')
A = ap.parse_args()
C = json.load(open(A.cams)); root = os.path.dirname(os.path.abspath(A.cams))
proc = SegformerImageProcessor.from_pretrained(A.model); net = SegformerForSemanticSegmentation.from_pretrained(A.model).cuda().eval().half()
ROAD, NOT = [0], [1, 2, 3, 4, 8, 9]          # road | sidewalk, building, wall, fence, vegetation, terrain (cars and the rest abstain)
pts, votes = [], []
for n, e in enumerate(C['images']):
    im = Image.open(os.path.join(root, e['file'])).convert('RGB'); W, H = im.size
    with torch.no_grad():
        x = proc(images=im, return_tensors='pt')['pixel_values'].cuda().half()
        lab = torch.nn.functional.interpolate(net(pixel_values=x).logits.float(), size=(H // 4, W // 4), mode='bilinear').argmax(1)[0].cpu().numpy()
    v, u = np.mgrid[0:H // 4, 0:W // 4]; u = u.ravel() * 4 + 2.0; v = v.ravel() * 4 + 2.0; lab = lab.ravel()
    s = np.where(np.isin(lab, ROAD), 1, np.where(np.isin(lab, NOT), -1, 0))
    s[np.asarray(im)[v.astype(int), u.astype(int)].sum(1) < 30] = 0   # the black border of undistorted views abstains
    k = s != 0
    K = np.array(e['K'], float); w2c = np.array(e['w2c'], float); R, t = w2c[:3, :3], w2c[:3, 3]; c = -R.T @ t
    d = (R.T @ (np.linalg.inv(K) @ np.stack([u[k], v[k], np.ones(k.sum())]))).T
    g = d[:, 1] < -1e-3; lam = -c[1] / d[g, 1]; P = c + lam[:, None] * d[g]
    r = np.hypot(P[:, 0] - c[0], P[:, 2] - c[2]); m = r < A.maxr
    pts.append(P[m][:, [0, 2]]); votes.append(s[k][g][m] / (1 + r[m] / 15))   # near pixels are surer of their ground spot
    if n % 200 == 0: print(n, '/', len(C['images']), flush=True)
P = np.concatenate(pts); V = np.concatenate(votes)
lo = P.min(0) - 2; shape = np.ceil((P.max(0) + 2 - lo) / A.res).astype(int)
ij = ((P - lo) / A.res).astype(int)
road = np.zeros(shape); tot = np.zeros(shape)
np.add.at(road, (ij[:, 0], ij[:, 1]), np.clip(V, 0, None)); np.add.at(tot, (ij[:, 0], ij[:, 1]), np.abs(V))
np.savez_compressed(A.out, origin=lo, res=A.res, road=road, total=tot)
p = road / np.maximum(tot, 1e-6); seen = tot > 0.5
print('grid', shape, 'cells seen', int(seen.sum()), 'road share', round(float((p[seen] > 0.5).mean()), 3))
