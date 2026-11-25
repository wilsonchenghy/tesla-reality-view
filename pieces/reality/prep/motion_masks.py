"""Static vs moving vehicles from optical flow, and training masks that hide only the moving ones.

A parked vehicle moves across the image exactly like the road it stands on; a moving one does not. For each vehicle
instance (YOLO11-seg) we compare its median optical flow (RAFT) to the flow of a ground strip just under its box.
Instances are linked across consecutive frames of the same camera, and a whole track counts as moving if enough of
its frames move (a car that stops at a light and then leaves is moving). The output masks take the existing masks
(every vehicle hidden) and give back the pixels of static vehicles, so parked cars stay photoreal in the world and only
moving traffic is left to the CAD models.

  python motion_masks.py --pack DIR --cams cameras_rig3.json --out DIR/masks_static   (pinhole training views)
  python motion_masks.py --frames REF_DIR --out OUT_DIR --inpaint                      (consecutive frames: inpaint moving only)
"""
import argparse, glob, json, os
import cv2, numpy as np, torch, torch.nn.functional as F
from torchvision.models.optical_flow import raft_large, Raft_Large_Weights
from ultralytics import YOLO

VEH = [2, 3, 5, 7]   # COCO car, motorcycle, bus, truck
STEP, THR = 2, 0.8   # flow baseline (frames) and the moving threshold on the relative flow difference
dev = 'cuda'


def load_models(seg_model):
    return YOLO(seg_model), raft_large(weights=Raft_Large_Weights.DEFAULT).to(dev).eval()


@torch.no_grad()
def flow(raft, a, b, scale=0.5):
    """optical flow a -> b in pixels of the full image, (H, W, 2)"""
    H, W = a.shape[:2]; h8, w8 = int(H * scale) // 8 * 8, int(W * scale) // 8 * 8
    t = lambda x: F.interpolate(torch.from_numpy(x).permute(2, 0, 1)[None].float().to(dev) / 127.5 - 1, size=(h8, w8), mode='bilinear', align_corners=False)
    f = raft(t(a), t(b), num_flow_updates=12)[-1]
    f = F.interpolate(f, size=(H, W), mode='bilinear', align_corners=False)[0]
    f[0] *= W / w8; f[1] *= H / h8
    return f.permute(1, 2, 0).cpu().numpy()


def detect(yolo, img):
    r = yolo.predict(img[..., ::-1], imgsz=1024, classes=VEH, conf=0.25, verbose=False, retina_masks=True)[0]
    if r.masks is None: return []
    out = []
    for box, m in zip(r.boxes.xyxy.cpu().numpy(), r.masks.data.cpu().numpy() > 0.5):
        out.append(dict(box=box, mask=m))
    return out


def motion_score(inst, fl, valid=None):
    """|median flow on the vehicle - median flow of the ground strip under it|, relative to the ground flow.
    None when the strip is outside the image or unusable."""
    H, W = fl.shape[:2]
    x1, y1, x2, y2 = inst['box']; bh = y2 - y1
    sy1, sy2 = int(y2 + 0.04 * bh), int(y2 + 0.04 * bh + max(4, 0.18 * bh))
    sx1, sx2 = int(max(0, x1 + 0.1 * (x2 - x1))), int(min(W, x2 - 0.1 * (x2 - x1)))
    if sy2 >= H or sx2 - sx1 < 3: return None
    strip = fl[sy1:sy2, sx1:sx2].reshape(-1, 2)
    if valid is not None:
        v = valid[sy1:sy2, sx1:sx2].reshape(-1)
        if v.mean() < 0.5: return None
        strip = strip[v]
    m = inst['mask']
    if m.sum() < 30: return None
    g = np.median(strip, 0); c = np.median(fl[m], 0)
    d = float(np.linalg.norm(c - g))
    return d / max(2.0, 0.3 * float(np.linalg.norm(g)))     # > 1: moving


def link(prev, cur, fl):
    """match instances of consecutive frames: warp previous masks' centroids by the flow, nearest box overlap"""
    pairs = []
    for j, c in enumerate(cur):
        best, bi = 0.0, None
        for i, p in enumerate(prev):
            ys, xs = np.nonzero(p['mask'])
            if len(xs) == 0: continue
            d = np.median(fl[ys, xs], 0)
            b = p['box'] + np.array([d[0], d[1], d[0], d[1]])
            ix = max(0, min(b[2], c['box'][2]) - max(b[0], c['box'][0])); iy = max(0, min(b[3], c['box'][3]) - max(b[1], c['box'][1]))
            inter = ix * iy; u = (b[2] - b[0]) * (b[3] - b[1]) + (c['box'][2] - c['box'][0]) * (c['box'][3] - c['box'][1]) - inter
            iou = inter / max(u, 1e-6)
            if iou > best: best, bi = iou, i
        if bi is not None and best > 0.2: pairs.append((bi, j))
    return pairs


def label_sequence(yolo, raft, imgs, valids=None):
    """imgs: consecutive frames of one camera. Returns per frame the list of instances with 'moving' set (track level)."""
    D = [detect(yolo, im) for im in imgs]
    tid = 0
    for k in range(len(imgs)):
        j = k + STEP if k + STEP < len(imgs) else max(0, k - STEP)          # two frames apart: twice the give-away motion
        fl = flow(raft, imgs[k], imgs[j])
        for inst in D[k]:
            inst['score'] = motion_score(inst, fl, None if valids is None else valids[k])
        if k == 0:
            for inst in D[k]: inst['track'] = tid; tid += 1
        else:
            fl_prev = flow(raft, imgs[k - 1], imgs[k])
            got = {j: i for i, j in link(D[k - 1], D[k], fl_prev)}
            for j, inst in enumerate(D[k]):
                if j in got: inst['track'] = D[k - 1][got[j]]['track']
                else: inst['track'] = tid; tid += 1
    tracks = {}
    for k in range(len(imgs)):
        for inst in D[k]: tracks.setdefault(inst['track'], []).append(inst['score'])
    verdict = {}
    for t, sc in tracks.items():
        s = [v for v in sc if v is not None]
        # moving if a third of the measurable frames move; unmeasurable tracks stay hidden (safe default)
        verdict[t] = (not s) or (np.mean([v > THR for v in s]) >= 0.25)
    for k in range(len(imgs)):
        for inst in D[k]: inst['moving'] = bool(verdict[inst['track']])
    return D


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--pack'); ap.add_argument('--cams', default='cameras_rig3.json')
    ap.add_argument('--frames'); ap.add_argument('--inpaint', action='store_true')
    ap.add_argument('--out', required=True); ap.add_argument('--seg', default='out/fsd-data/models/yolo11s-seg.pt')
    A = ap.parse_args(); os.makedirs(A.out, exist_ok=True)
    yolo, raft = load_models(A.seg)
    stats = dict(static=0, moving=0)
    if A.pack:
        meta = json.load(open(f'{A.pack}/{A.cams}'))['images']
        for cam in sorted({e['cam'] for e in meta}):
            es = sorted([e for e in meta if e['cam'] == cam], key=lambda e: e['kf'])
            imgs = [cv2.imread(f"{A.pack}/{e['file']}") for e in es]
            masks = [cv2.imread(f"{A.pack}/{e['mask']}", cv2.IMREAD_GRAYSCALE) for e in es]
            never = (np.mean([m < 128 for m in masks], 0) > 0.95)            # ego body / vignette: always hidden
            valids = [m > 127 for m in masks]
            D = label_sequence(yolo, raft, imgs, None)
            for e, m, insts in zip(es, masks, D):
                out = m.copy()
                for inst in insts:
                    if inst['moving']: stats['moving'] += 1; continue
                    stats['static'] += 1
                    out[inst['mask'] & ~never] = 255
                cv2.imwrite(f"{A.out}/{os.path.basename(e['mask'])}", out)
            print(cam, len(es), 'frames', stats, flush=True)
    else:
        fs = sorted(glob.glob(f'{A.frames}/*.jpg'))
        for k0 in range(0, len(fs), 120):                               # chunks keep memory bounded
            chunk = fs[max(0, k0 - 1):k0 + 121]
            imgs = [cv2.imread(f) for f in chunk]
            D = label_sequence(yolo, raft, imgs)
            for f, im, insts in list(zip(chunk, imgs, D))[(1 if k0 else 0):][:120]:
                hide = np.zeros(im.shape[:2], np.uint8)
                for inst in insts:
                    if inst['moving']:
                        stats['moving'] += 1
                        hide[inst['mask']] = 255
                    else: stats['static'] += 1
                hide = cv2.dilate(hide, np.ones((15, 15), np.uint8))
                out = cv2.inpaint(im, hide, 9, cv2.INPAINT_TELEA) if (A.inpaint and hide.any()) else im
                cv2.imwrite(f'{A.out}/{os.path.basename(f)}', out, [cv2.IMWRITE_JPEG_QUALITY, 92])
            print(k0, stats, flush=True)
    print('done', stats)


if __name__ == '__main__':
    main()
