"""Difix reference frames without vehicles: detect cars/trucks in each front-camera frame and inpaint them away, so the
diffusion cleanup cannot copy real cars into the background (vehicles are drawn as models). usage: ref_nocars.py IN OUT"""
import os, sys, glob, cv2, numpy as np
from ultralytics import YOLO
src, dst = sys.argv[1], sys.argv[2]; os.makedirs(dst, exist_ok=True)
m = YOLO('out/fsd-data/models/yolo11s.pt'); fs = sorted(glob.glob(f'{src}/*.jpg'))
for k in range(0, len(fs), 16):
    batch = fs[k:k + 16]
    for f, r in zip(batch, m.predict(batch, imgsz=960, classes=[2, 3, 5, 7], conf=0.25, verbose=False)):
        img = cv2.imread(f); mask = np.zeros(img.shape[:2], np.uint8)
        for x1, y1, x2, y2 in r.boxes.xyxy.cpu().numpy().astype(int):
            pw, ph = int(0.08 * (x2 - x1)), int(0.08 * (y2 - y1))
            mask[max(0, y1 - ph):y2 + ph, max(0, x1 - pw):x2 + pw] = 255
        out = cv2.inpaint(img, mask, 9, cv2.INPAINT_TELEA) if mask.any() else img
        cv2.imwrite(f'{dst}/{os.path.basename(f)}', out, [cv2.IMWRITE_JPEG_QUALITY, 92])
print('refs', len(fs))
