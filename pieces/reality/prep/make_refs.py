"""Difix reference frames: the real front-camera frame at every output frame time of the piece (30 fps), at 1448x938.
usage: CLIP=clip_00 make_refs.py --t0 6 --dur 20 --out DIR   (then motion_masks.py --frames DIR --inpaint for moving-only removal)"""
import argparse, os
import cv2, numpy as np, pandas as pd
CLIP = os.environ.get('CLIP', 'clip_00')
ap = argparse.ArgumentParser(); ap.add_argument('--data', default='out/fsd-data'); ap.add_argument('--t0', type=float, required=True)
ap.add_argument('--dur', type=float, default=20.0); ap.add_argument('--fps', type=int, default=30); ap.add_argument('--out', required=True)
A = ap.parse_args(); os.makedirs(A.out, exist_ok=True)
cf = pd.read_parquet(f'{A.data}/data/camera_frames.parquet'); g = cf[(cf.clip_id == CLIP) & (cf.camera == 'front')].sort_values('frame_seq_no')
seqs, fidx = g.frame_seq_no.values, g.frame_index.values
want = []
for n in range(int(A.dur * A.fps)):
    s = int(round((A.t0 + n / A.fps) * 36)); i = int(np.clip(np.searchsorted(seqs, s), 0, len(seqs) - 1)); want.append(int(fidx[i]))
cap = cv2.VideoCapture(f'{A.data}/videos/{CLIP}/front.mp4'); k = -1; cur = None; got = {}
need = set(want); last = max(want)
while k < last:
    ok, fr = cap.read(); k += 1
    if not ok: raise SystemExit(f'video ended at frame {k}, need {last}')
    if k in need: got[k] = cv2.resize(fr, (1448, 938), interpolation=cv2.INTER_AREA)
for n, f in enumerate(want): cv2.imwrite(f'{A.out}/{n + 1:04d}.jpg', got[f], [cv2.IMWRITE_JPEG_QUALITY, 92])
print('refs', len(want), 'frames', want[0], '-', want[-1])
