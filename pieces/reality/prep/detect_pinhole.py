"""Vehicle detections in every solved pinhole view (the views the world was trained on), cached for tracking and
evaluation: box, class, confidence, ground-contact pixel (lowest band of the instance mask) and body colour (upper part of
the mask, darkest/brightest pixels dropped).  usage: detect_pinhole.py --pack DIR --cams cameras_rig3.json --out dets.json"""
import argparse, json
import cv2, numpy as np
from ultralytics import YOLO

ap = argparse.ArgumentParser(); ap.add_argument('--pack', required=True); ap.add_argument('--cams', default='cameras_rig3.json')
ap.add_argument('--out', required=True); ap.add_argument('--seg', default='out/fsd-data/models/yolo11s-seg.pt')
A = ap.parse_args()
NAMES = {2: 'car', 3: 'moto', 5: 'bus', 7: 'truck'}
meta = json.load(open(f'{A.pack}/{A.cams}'))['images']
yolo = YOLO(A.seg); out = []
for e in meta:
    img = cv2.imread(f"{A.pack}/{e['file']}"); H, W = img.shape[:2]
    r = yolo.predict(img[..., ::-1], imgsz=1024, classes=list(NAMES), conf=0.3, verbose=False, retina_masks=True)[0]
    dets = []
    if r.masks is not None:
        for box, cls, conf, m in zip(r.boxes.xyxy.cpu().numpy(), r.boxes.cls.cpu().numpy(), r.boxes.conf.cpu().numpy(), r.masks.data.cpu().numpy() > 0.5):
            ys, xs = np.nonzero(m)
            if len(ys) < 40: continue
            yb = np.percentile(ys, 97); sel = ys >= yb
            contact = [float(np.median(xs[sel])), float(ys.max())]
            h0 = ys.max() - ys.min()                                           # body band: below the windows, above the wheels
            top = (ys > ys.min() + 0.40 * h0) & (ys < ys.min() + 0.75 * h0)
            px = img[ys[top], xs[top]].astype(np.float32); lum = px.mean(1)
            lo, hi = np.percentile(lum, 30), np.percentile(lum, 85)
            body = px[(lum >= lo) & (lum <= hi)]
            col = (body.mean(0)[::-1] if len(body) else px.mean(0)[::-1]).round().astype(int).tolist()   # RGB
            dets.append(dict(box=[round(float(v), 1) for v in box], cls=NAMES[int(cls)], conf=round(float(conf), 3),
                             contact=[round(v, 1) for v in contact], cut=bool(box[3] > H - 4), col=col, area=int(len(ys))))
    out.append(dict(i=e['i'], cam=e['cam'], kf=e['kf'], t=e['t'], dets=dets))
    if e['i'] % 400 == 0: print(e['i'], len(dets), flush=True)
json.dump(out, open(A.out, 'w')); print('views', len(out), 'detections', sum(len(o['dets']) for o in out))
