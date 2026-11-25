#!/usr/bin/env python3
"""Subframe blending for the rv renderer (linear light), with motion analysis for adaptive blur.

  blend.py analyze manifest.json            -> JSON list: per frame, how many pixels change a lot
                                               between the first and last subframe (how far the shutter smears)
  blend.py stream manifest.json W H [cachedir start] -> raw rgb24 frames on stdout (ffmpeg -f rawvideo),
                                               optionally also saved as lossless PNGs for --patch
  blend.py pngs manifest.json outdir start [WxH]  -> blended PNGs

manifest.json: [[sub0.png, sub1.png, ...], ...] one list per output frame, in order.
"""
import sys, json, os
import numpy as np
from PIL import Image
from multiprocessing import Pool

LUT = np.array([(c / 255) / 12.92 if c / 255 <= 0.04045 else (((c / 255) + 0.055) / 1.055) ** 2.4 for c in range(256)], np.float32)

def to_srgb8(lin):
    lin = np.clip(lin, 0, 1)
    s = np.where(lin <= 0.0031308, 12.92 * lin, 1.055 * np.power(lin, 1 / 2.4) - 0.055)
    return np.clip(np.rint(s * 255), 0, 255).astype(np.uint8)

def load8(p):
    # the renderer may have written raw pixels (.rgb: 12-byte header W, H, flip + RGB) instead of an image
    if not os.path.exists(p):
        raw = os.path.splitext(p)[0] + '.rgb'
        if os.path.exists(raw): p = raw
    if p.endswith('.rgb'):
        with open(p, 'rb') as f:
            w, h, flip = np.frombuffer(f.read(12), '<u4')
            a = np.frombuffer(f.read(), np.uint8).reshape(int(h), int(w), 3)
        return a[::-1] if flip else a
    return np.asarray(Image.open(p).convert('RGB'))

SIZE = None  # (W, H) of the output; subframes may be supersampled

def blend(files):
    if len(files) == 1:
        x = load8(files[0])
        if SIZE is None or (x.shape[1], x.shape[0]) == SIZE: return x
    acc = None
    for f in files:
        x = LUT[load8(f)]
        acc = x if acc is None else acc + x
    acc /= len(files)
    if SIZE is not None and (acc.shape[1], acc.shape[0]) != SIZE:
        # downsample in linear light, per channel
        acc = np.stack([np.asarray(Image.fromarray(acc[..., c], 'F').resize(SIZE, Image.LANCZOS)) for c in range(3)], -1)
    return to_srgb8(acc)

def init(size):
    global SIZE
    SIZE = size

def spread(files):
    if len(files) < 2: return 0.0
    a = load8(files[0])[::2, ::2].astype(np.int16)
    b = load8(files[-1])[::2, ::2].astype(np.int16)
    d = np.abs(a - b).max(-1)
    return float((d > 48).sum() * 4)   # full-resolution pixels that change strongly across the shutter

def main():
    cmd, man = sys.argv[1], json.load(open(sys.argv[2]))
    procs = max(1, min(4, os.cpu_count() or 1))
    size = (int(sys.argv[3]), int(sys.argv[4])) if cmd == 'stream' else (tuple(int(x) for x in sys.argv[5].split('x')) if cmd == 'pngs' and len(sys.argv) > 5 else None)
    with Pool(procs, initializer=init, initargs=(size,)) as pool:
        if cmd == 'analyze':
            print(json.dumps([int(s) for s in pool.map(spread, man, chunksize=4)]))
        elif cmd == 'stream':
            # optional: also keep every final frame in a lossless cache (for --patch re-renders)
            cache = sys.argv[5] if len(sys.argv) > 5 else None
            start = int(sys.argv[6]) if len(sys.argv) > 6 else 0
            if cache: os.makedirs(cache, exist_ok=True)
            out = sys.stdout.buffer
            for i, fr in enumerate(pool.imap(blend, man, chunksize=2)):
                out.write(fr.tobytes())
                if cache: Image.fromarray(fr).save(os.path.join(cache, f'{start + i:05d}.png'), compress_level=1)
            out.flush()
        elif cmd == 'pngs':
            outdir, start = sys.argv[3], int(sys.argv[4])
            os.makedirs(outdir, exist_ok=True)
            for i, fr in enumerate(pool.imap(blend, man, chunksize=2)):
                Image.fromarray(fr).save(os.path.join(outdir, f'{start + i:05d}.png'), compress_level=3)

if __name__ == '__main__':
    main()
