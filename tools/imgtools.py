#!/usr/bin/env python3
"""Image + chart helpers for the rv harness (numpy + PIL only).

  imgtools.py sheet  out.png --cols 4 --width 360 img1.png:label1 img2.png:label2 ...
  imgtools.py onion  out.png img1.png img2.png ...            (time-coloured onion skin)
  imgtools.py energy out.png out.json --fps 60 --bpm 120 --offset 0 img0.png img1.png ...
  imgtools.py chart  out.png series.json                     (probe traces, beat grid)
  imgtools.py diff   a.png b.png                              (prints mean abs diff 0..255)
"""
import sys, json, math, argparse
import numpy as np
from PIL import Image, ImageDraw, ImageFont

def font(size):
    for p in ['/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf', '/System/Library/Fonts/Menlo.ttc', 'C:/Windows/Fonts/consola.ttf']:
        try: return ImageFont.truetype(p, size)
        except Exception: pass
    return ImageFont.load_default()

def load(p):
    return np.asarray(Image.open(p).convert('RGB')).astype(np.float32)

def cmd_sheet(a):
    items = []
    for s in a.items:
        p, _, label = s.partition(':')
        items.append((p, label))
    ims = [Image.open(p).convert('RGB') for p, _ in items]
    w = a.width; h = round(ims[0].height * w / ims[0].width)
    cols = min(a.cols, len(ims)); rows = math.ceil(len(ims) / cols)
    pad, lab = 8, 22
    sheet = Image.new('RGB', (cols * (w + pad) + pad, rows * (h + lab + pad) + pad), (24, 24, 24))
    d = ImageDraw.Draw(sheet); f = font(13)
    for i, (im, (_, label)) in enumerate(zip(ims, items)):
        x = pad + (i % cols) * (w + pad); y = pad + (i // cols) * (h + lab + pad)
        sheet.paste(im.resize((w, h), Image.LANCZOS), (x, y + lab))
        d.text((x + 2, y + 4), label, fill=(230, 230, 230), font=f)
    sheet.save(a.out)
    print(a.out)

def cmd_onion(a):
    frames = [load(p) for p in a.items]
    if a.crop:
        x, y, w, h = (int(v) for v in a.crop.split(','))
        frames = [f[y:y + h, x:x + w] for f in frames]
    stack = np.stack(frames)
    bg = np.median(stack, axis=0)
    out = bg.copy() * 0.55 + 255 * 0.45  # washed background so the trail reads
    n = len(frames)
    for k, f in enumerate(frames):
        u = k / max(1, n - 1)
        col = np.array([40 + 215 * u, 90 + 40 * (1 - abs(2 * u - 1)), 255 - 215 * u], np.float32)  # blue -> red
        m = np.clip(np.abs(f - bg).sum(-1, keepdims=True) / 90.0, 0, 1)
        alpha = m * (0.35 if k not in (0, n - 1) else 0.8)
        out = out * (1 - alpha) + col * alpha
    Image.fromarray(np.clip(out, 0, 255).astype(np.uint8)).save(a.out)
    print(a.out)

def cmd_diff(a):
    x, y = load(a.items[0]), load(a.items[1])
    print(f'{np.abs(x - y).mean():.4f}')

def draw_axes(d, box, f, title):
    x0, y0, x1, y1 = box
    d.rectangle(box, outline=(70, 70, 70))
    d.text((x0 + 6, y0 + 4), title, fill=(230, 230, 230), font=f)

def beat_lines(d, box, dur, bpm, offset, beats_per_bar=4):
    if not bpm: return
    x0, y0, x1, y1 = box
    spb = 60 / bpm; k = 0
    while offset + k * spb <= dur + 1e-9:
        t = offset + k * spb
        if t >= 0:
            x = x0 + (x1 - x0) * t / dur
            d.line([(x, y0), (x, y1)], fill=(90, 70, 40) if k % beats_per_bar == 0 else (50, 50, 50), width=2 if k % beats_per_bar == 0 else 1)
        k += 1

def cmd_energy(a):
    """Motion energy per frame: mean abs diff to the previous frame. Flags dead time and the loop seam."""
    frames = [load(p) for p in a.items]
    n = len(frames)
    e = np.array([np.abs(frames[i] - frames[i - 1]).mean() for i in range(1, n)])
    seam = float(np.abs(frames[0] - frames[-1]).mean()) if a.loop else None
    fps, bpm, off = a.fps, a.bpm, a.offset
    dur = n / fps
    # dead = below a small absolute floor, or tiny next to the typical frame; capped so one big move
    # (a page slide) cannot make small meaningful moves (ink writing, a checkbox) look dead
    thresh = max(0.015, min(0.12, 0.04 * float(np.percentile(e, 90)))) if len(e) else 0.015
    holds = json.loads(a.holds) if a.holds else []
    # dead spans: consecutive frames below threshold
    dead, start = [], None
    for i, v in enumerate(list(e) + [1e9]):
        if v < thresh and start is None: start = i
        if v >= thresh and start is not None:
            s0, s1 = (start + 1) / fps, (i + 1) / fps
            # declared holds (end cards, intentional stillness) are not dead time
            for h0, h1 in holds:
                if s0 >= h0 - 1e-6 and s1 <= h1 + 1 / fps: s1 = s0
            if s1 - s0 >= (60 / bpm if bpm else 0.5): dead.append([round(s0, 3), round(s1, 3)])
            start = None
    per_beat = []
    if bpm:
        spb = 60 / bpm; k = 0
        while off + k * spb < dur:
            a0, a1 = int((off + k * spb) * fps), int((off + (k + 1) * spb) * fps)
            seg = e[max(0, a0 - 1):max(0, a1 - 1)]
            per_beat.append(round(float(seg.max()) if len(seg) else 0.0, 3)); k += 1
    med = float(np.median(e)) if len(e) else 0
    rep = {'frames': n, 'median': round(med, 3), 'p90': round(float(np.percentile(e, 90)), 3) if len(e) else 0,
           'seam_diff': round(seam, 3) if seam is not None else None, 'seam_vs_median': round(seam / med, 2) if (seam is not None and med > 0) else None, 'holds': holds,
           'dead_spans_s': dead, 'quiet_beats': [i for i, v in enumerate(per_beat) if v < thresh], 'per_beat_peak': per_beat,
           'max_jump_frame': int(np.argmax(e)) + 1 if len(e) else None, 'max_jump': round(float(e.max()), 3) if len(e) else 0}
    W, H = 1600, 420
    im = Image.new('RGB', (W, H), (16, 16, 16)); d = ImageDraw.Draw(im); f = font(14)
    box = (50, 30, W - 20, H - 40)
    draw_axes(d, box, f, f'motion energy (mean |frame - prev|)  ' + (f'seam {seam:.2f}  ' if seam is not None else '') + f'median {med:.2f}  dead spans {dead}  holds {holds}')
    beat_lines(d, box, dur, bpm, off)
    top = max(1e-6, float(e.max()) * 1.1) if len(e) else 1
    pts = [(box[0] + (box[2] - box[0]) * (i + 1) / n, box[3] - (box[3] - box[1] - 20) * v / top) for i, v in enumerate(e)]
    if len(pts) > 1: d.line(pts, fill=(120, 200, 255), width=2)
    ty = box[3] - (box[3] - box[1] - 20) * thresh / top
    d.line([(box[0], ty), (box[2], ty)], fill=(200, 80, 80))
    for h0, h1 in holds:
        d.rectangle([box[0] + (box[2] - box[0]) * h0 / dur, box[3] - 8, box[0] + (box[2] - box[0]) * h1 / dur, box[3]], fill=(80, 160, 90))
    for s0, s1 in dead:
        d.rectangle([box[0] + (box[2] - box[0]) * s0 / dur, box[3] - 8, box[0] + (box[2] - box[0]) * s1 / dur, box[3]], fill=(200, 80, 80))
    for sec in range(int(dur) + 1):
        x = box[0] + (box[2] - box[0]) * sec / dur; d.text((x - 4, box[3] + 6), f'{sec}s', fill=(150, 150, 150), font=f)
    im.save(a.out)
    with open(a.json, 'w') as fh: json.dump(rep, fh, indent=1)
    print(json.dumps({k: v for k, v in rep.items() if k != 'per_beat_peak'}))

def cmd_chart(a):
    """series.json: {fps, bpm, offset, duration, t:[...], series:{name:[...]}} -> one panel per series + speed."""
    S = json.load(open(a.items[0]))
    t = np.array(S['t']); names = list(S['series'].keys())
    W, ph = 1600, 260
    H = 30 + ph * len(names)
    im = Image.new('RGB', (W, H), (16, 16, 16)); d = ImageDraw.Draw(im); f = font(14)
    report = {}
    for k, nm in enumerate(names):
        y = np.array([np.nan if v is None else v for v in S['series'][nm]], float)
        box = (60, 20 + k * ph, W - 20, 20 + (k + 1) * ph - 30)
        v = np.gradient(y, t) if len(y) > 2 else np.zeros_like(y)
        v[~np.isfinite(y)] = np.nan
        acc = np.gradient(v, t) if len(y) > 2 else np.zeros_like(y)
        # linear motion: non-zero speed that stays constant (within 2%) for > 8 frames
        lin = []
        moving = np.abs(v) > (np.nanmax(np.abs(v)) * 0.05 + 1e-9)
        const = np.abs(acc) < (np.nanmax(np.abs(acc)) * 0.01 + 1e-9)
        run = 0
        for i in range(len(y)):
            run = run + 1 if (moving[i] and const[i]) else 0
            if run == 9: lin.append(round(float(t[i - 8]), 3))
        # dead stops: speed falls from >30% of max to ~0 within one frame
        vmax = np.nanmax(np.abs(v)) + 1e-9
        stops = [round(float(t[i]), 3) for i in range(1, len(v)) if abs(v[i - 1]) > 0.3 * vmax and abs(v[i]) < 0.02 * vmax]
        jumps = [round(float(t[i]), 3) for i in range(1, len(y)) if abs(y[i] - y[i - 1]) > 0.25 * (np.nanmax(y) - np.nanmin(y) + 1e-9) and abs(v[i]) < 1e9]
        report[nm] = {'min': float(np.nanmin(y)), 'max': float(np.nanmax(y)), 'linear_runs_at': lin[:20], 'dead_stops_at': stops[:20], 'jumps_at': jumps[:20]}
        draw_axes(d, box, f, f'{nm}   range {np.nanmin(y):.3g}..{np.nanmax(y):.3g}   (white value, orange signed velocity: mid-line = 0)')
        beat_lines(d, box, S['duration'], S.get('bpm'), S.get('offset', 0))
        def plot(vals, col):
            lo, hi = np.nanmin(vals), np.nanmax(vals)
            if not np.isfinite(lo) or hi - lo < 1e-12: hi = lo + 1
            # null / NaN = absent: break the line there instead of drawing a straight bridge
            run = []
            for ti, vi in list(zip(t, vals)) + [(None, np.nan)]:
                if ti is not None and np.isfinite(vi):
                    run.append((box[0] + (box[2] - box[0]) * ti / S['duration'], box[3] - 6 - (box[3] - box[1] - 30) * (vi - lo) / (hi - lo)))
                else:
                    if len(run) > 1: d.line(run, fill=col, width=2)
                    run = []
        plot(v, (230, 140, 50)); plot(y, (240, 240, 240))
        for sec in range(int(S['duration']) + 1):
            x = box[0] + (box[2] - box[0]) * sec / S['duration']; d.text((x - 4, box[3] + 4), f'{sec}s', fill=(150, 150, 150), font=f)
    im.save(a.out)
    print(json.dumps(report, indent=1))

if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('cmd'); ap.add_argument('out', nargs='?'); ap.add_argument('json', nargs='?')
    ap.add_argument('--cols', type=int, default=4); ap.add_argument('--width', type=int, default=360)
    ap.add_argument('--crop', default=''); ap.add_argument('--loop', action='store_true'); ap.add_argument('--holds', default='');
    ap.add_argument('--fps', type=float, default=60); ap.add_argument('--bpm', type=float, default=0); ap.add_argument('--offset', type=float, default=0)
    ap.add_argument('items', nargs='*')
    a, extra = ap.parse_known_args()
    a.items = (a.items or []) + extra
    if a.cmd == 'diff':
        a.items = [a.out, a.json] + a.items
    if a.cmd == 'chart':
        a.items = [a.json] + a.items
    if a.cmd in ('sheet', 'onion') and a.json:
        a.items = [a.json] + a.items
    {'sheet': cmd_sheet, 'onion': cmd_onion, 'energy': cmd_energy, 'chart': cmd_chart, 'diff': cmd_diff}[a.cmd](a)
