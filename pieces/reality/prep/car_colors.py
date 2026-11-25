"""Re-measure each tracked vehicle's paint from its nearest observation: body-panel band of the box, drop the darkest
45% (windows, tyres, shadow) and the brightest 8% (glints), mean of the rest. usage: car_colors.py index.json data_dir"""
import json, sys, numpy as np, pandas as pd
from PIL import Image
import os as _os; CLIP = _os.environ.get('CLIP', 'clip_00')    # which one-minute clip of the drive
p, D = sys.argv[1], sys.argv[2]
idx = json.load(open(p)); KF = json.load(open(f'{D}/index.json'))['kf']
cf = pd.read_parquet('out/fsd-data/data/camera_frames.parquet'); cf = cf[cf.clip_id == CLIP]
def frame(cam, t):
    g = cf[cf.camera == cam]; s = int(round(t * 36)); i = np.searchsorted(g.frame_seq_no.values, s).clip(0, len(g) - 1)
    ids = json.load(open(f'{D}/tmp/{cam}/idx.json')); return np.asarray(Image.open(f'{D}/tmp/{cam}/{ids.index(int(g.frame_index.values[i])) + 1:04d}.jpg').convert('RGB')).astype(np.float32)
for c in idx['cars']:
    obs = [(m[1], o[0], m[0], m[2]) for o in c.get('obs', []) for m in o[3]]
    if not obs: continue
    obs.sort()
    cols = []
    for rng, kf, cam, b in obs[:4]:
        img = frame(cam, KF[kf]['t']); H, W = img.shape[:2]
        x1, y1, x2, y2 = b; w, h = x2 - x1, y2 - y1
        patch = img[int((y1 + 0.38 * h) * H):int((y1 + 0.78 * h) * H), int((x1 + 0.15 * w) * W):int((x2 - 0.15 * w) * W)].reshape(-1, 3)
        if len(patch) < 30: continue
        L = patch @ [0.299, 0.587, 0.114]; lo, hi = np.percentile(L, [45, 92])
        sel = patch[(L >= lo) & (L <= hi)]
        if len(sel): cols.append(sel.mean(0))
    if cols:
        old = c['color']; c['color'] = np.median(cols, 0).round().astype(int).tolist()
        print(c['id'], c['model'], old, '->', c['color'])
json.dump(idx, open(p, 'w'))
