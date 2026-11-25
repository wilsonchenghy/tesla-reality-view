#!/usr/bin/env python3
"""Heuristic checks for the default "AI look" on a set of frames. Hints, not verdicts.

  taste.py frames.json   (written by `rv taste`: {"frames": [png...], "texts": [[{x,y,w,h,color}...] per frame]})

Flags: purple/blue gradient backgrounds, glow halos, everything centred on every beat, text contrast under
4.5:1 against the pixels actually behind it, and a palette with no clear accent.
"""
import sys, json, colorsys
import numpy as np
from PIL import Image

def lin(c): c = c / 255.0; return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
def lum(rgb): l = lin(np.asarray(rgb, float)); return 0.2126 * l[..., 0] + 0.7152 * l[..., 1] + 0.0722 * l[..., 2]
def contrast(a, b): x, y = lum(a), lum(b); return (max(x, y) + 0.05) / (min(x, y) + 0.05)

def main():
    J = json.load(open(sys.argv[1]))
    frames = [np.asarray(Image.open(p).convert('RGB')) for p in J['frames']]
    out = []
    # 1. purple/blue gradient background: border pixels mostly in hue 215-290, saturated, and varying smoothly
    grad_hits = 0
    for f in frames:
        h, w, _ = f.shape
        border = np.concatenate([f[:h // 10].reshape(-1, 3), f[-h // 10:].reshape(-1, 3), f[:, :w // 10].reshape(-1, 3), f[:, -w // 10:].reshape(-1, 3)])[::37] / 255.0
        hsv = np.array([colorsys.rgb_to_hsv(*p) for p in border])
        purple = ((hsv[:, 0] * 360 > 215) & (hsv[:, 0] * 360 < 290) & (hsv[:, 1] > 0.25) & (hsv[:, 2] > 0.15)).mean()
        spread = np.ptp(lum(border * 255))
        if purple > 0.5 and spread > 0.05: grad_hits += 1
    if grad_hits > len(frames) / 3: out.append(['default look', f'purple/blue gradient background in {grad_hits}/{len(frames)} frames'])
    # 2. glow: bright cores with wide smooth halos (large area of mid-bright pixels around a bright blob)
    glow_hits = 0
    for f in frames:
        L = lum(f)
        core = L > 0.85
        if core.mean() < 0.0005 or core.mean() > 0.4: continue
        halo = (L > 0.25) & (L < 0.8)
        # halo must be mostly smooth: low local gradient
        gy, gx = np.gradient(L)
        smooth = (np.hypot(gx, gy) < 0.01) & halo
        if smooth.mean() > 4 * core.mean() and smooth.mean() > 0.05 and L.mean() < 0.35: glow_hits += 1
    if glow_hits > len(frames) / 3: out.append(['default look', f'glow halos (bright cores in wide smooth falloff on a dark field) in {glow_hits}/{len(frames)} frames'])
    # 3. centred everything: the "ink" (pixels far from the background) has its centroid at the centre and is
    #    left/right symmetric on nearly every frame
    centred = 0
    for f in frames:
        bg = np.median(np.concatenate([f[0], f[-1], f[:, 0], f[:, -1]]), axis=0)
        ink = np.abs(f.astype(float) - bg).sum(-1) > 60
        if ink.mean() < 0.002: continue
        ys, xs = np.nonzero(ink)
        cx, cy = xs.mean() / f.shape[1], ys.mean() / f.shape[0]
        sym = 1 - np.abs(ink.astype(float) - ink[:, ::-1]).mean() / max(ink.mean(), 1e-6) / 2
        if abs(cx - 0.5) < 0.04 and abs(cy - 0.5) < 0.06 and sym > 0.7: centred += 1
    if centred >= 0.8 * len(frames): out.append(['composition', f'centred and mirror-symmetric on {centred}/{len(frames)} frames: is that a decision? (docs/creativity.md 5)'])
    # 4. text contrast against the real pixels behind each DOM text box
    low = []
    for k, (f, texts) in enumerate(zip(frames, J.get('texts', []))):
        for tx in texts:
            x0, y0 = max(0, int(tx['x'])), max(0, int(tx['y'])); x1, y1 = min(f.shape[1], int(tx['x'] + tx['w'])), min(f.shape[0], int(tx['y'] + tx['h']))
            if x1 - x0 < 4 or y1 - y0 < 4 or tx.get('opacity', 1) < 0.95: continue
            reg = f[y0:y1, x0:x1].reshape(-1, 3).astype(float)
            col = np.array(tx['color'][:3], float)
            dist = np.abs(reg - col).sum(1)
            far = reg[dist > 90]
            if len(far) < 10: continue
            # background = the pixels farthest from the text colour (anti-aliased edges sit in between)
            bg = np.median(reg[dist >= np.percentile(dist, 70)], axis=0)
            c = contrast(col, bg)
            if c < 4.5 and tx['size'] < 40: low.append((k, tx['text'][:24], round(float(c), 2)))
            elif c < 3: low.append((k, tx['text'][:24], round(float(c), 2)))
    # ~1:1 = the text is not visible at all there (covered, clipped, or the label-through-a-pill trick)
    hidden = list(dict.fromkeys(t for k, t, c in low if c < 1.15))
    if hidden: out.append(['note', 'invisible text (covered, clipped or same colour as behind; fine if intended): ' + ', '.join(f'"{t}"' for t in hidden[:6])])
    low = [x for x in low if x[2] >= 1.15]
    by = {}
    for k, t, c in low: by.setdefault(c, []).append(t)
    for c, ts in sorted(by.items()):
        ts = list(dict.fromkeys(ts))
        out.append(['legibility', f'contrast {c}:1 for {len(ts)} text(s): ' + ', '.join(f'"{t}"' for t in ts[:5]) + (' ...' if len(ts) > 5 else '') + ' (need 4.5:1 under 40 px, 3:1 large)'])
    # 6. text under platform UI (captions, buttons, action rail): only reported when the piece is vertical
    zones = J.get('uiZones', [])
    if zones and frames and frames[0].shape[0] / frames[0].shape[1] >= 1.6:
        hit = []
        for texts in J.get('texts', []):
            for tx in texts:
                if tx.get('opacity', 1) < 0.5: continue
                for zx, zy, zw, zh in zones:
                    ox = min(tx['x'] + tx['w'], zx + zw) - max(tx['x'], zx); oy = min(tx['y'] + tx['h'], zy + zh) - max(tx['y'], zy)
                    if ox > 0 and oy > 0 and ox * oy > 0.3 * tx['w'] * tx['h']: hit.append(tx['text'][:24]); break
        hit = list(dict.fromkeys(hit))
        if hit: out.append(['safe area', 'text under platform UI on vertical (captions, buttons, action rail): ' + ', '.join(f'"{t}"' for t in hit[:6]) + '. Preview with C to see the zones.'])
    # 5. accent discipline: share of strongly saturated pixels by hue family
    fams = {}
    for f in frames[::max(1, len(frames) // 8)]:
        px = f.reshape(-1, 3)[::97] / 255.0
        for p in px:
            h, s, v = colorsys.rgb_to_hsv(*p)
            if s > 0.45 and v > 0.25: fams[int(h * 12) % 12] = fams.get(int(h * 12) % 12, 0) + 1
    tot = sum(fams.values())
    if tot:
        big = [k for k, v in fams.items() if v / tot > 0.15]
        if len(big) >= 4: out.append(['color', f'{len(big)} saturated hue families each over 15% of the color: no single accent leads'])
    print(json.dumps(out, indent=1))

if __name__ == '__main__':
    main()
