#!/usr/bin/env python3
"""Compare two study reports (reference vs your render): where does the style drift?

  compare.py ref/report.json mine/report.json
"""
import sys, json, math

def lab(hexs):
    h = hexs.lstrip('#'); r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    lin = lambda c: c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = lin(r), lin(g), lin(b)
    l = (0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b) ** (1 / 3)
    m = (0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b) ** (1 / 3)
    s = (0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b) ** (1 / 3)
    return (0.2104542553 * l + 0.793617785 * m - 0.0040720468 * s, 1.9779984951 * l - 2.428592205 * m + 0.4505937099 * s, 0.0259040371 * l + 0.7827717662 * m - 0.808675766 * s)

def palette_distance(p, q):
    """share-weighted mean distance from each reference color to its nearest color in the other palette (OKLab)"""
    tot = 0; w = 0
    for c in p:
        a = lab(c['hex']); d = min(math.dist(a, lab(o['hex'])) for o in q)
        tot += d * c['share']; w += c['share']
    return tot / max(w, 1e-9)

def main():
    A, B = (json.load(open(f)) for f in sys.argv[1:3])
    rows = []
    def row(name, a, b, tol, unit='', hint=''):
        if a is None or b is None: return
        off = abs(a - b) > tol
        rows.append((name, a, b, off, unit, hint))
    sl = lambda r: (r.get('shot_length_s') or {}).get('median')
    row('median shot length', sl(A), sl(B), 0.3 * (sl(A) or 1), 's', 'cut more/less often')
    row('cuts per 10 s', len(A['cuts_at_s']) * 10 / A['duration'], len(B['cuts_at_s']) * 10 / B['duration'], 1.0, '', 'edit rhythm')
    row('held-frame ratio', A['held_frame_ratio'], B['held_frame_ratio'], 0.15, '', 'drawing rate: animate on 2s/3s or on 1s')
    row('motion energy (median)', A['motion_energy']['median'], B['motion_energy']['median'], 0.5 * max(A['motion_energy']['median'], 0.2), '', 'overall amount of movement')
    row('motion energy (p90)', A['motion_energy']['p90'], B['motion_energy']['p90'], 0.5 * max(A['motion_energy']['p90'], 0.5), '', 'size of the big moves')
    row('mean luminance', A['luminance']['mean'], B['luminance']['mean'], 0.08, '', 'overall value / exposure')
    row('mean saturation', A['saturation_mean'], B['saturation_mean'], 0.06, '', 'color intensity')
    pd = palette_distance(A['palette'], B['palette'])
    rows.append(('palette distance (OKLab)', 0, round(pd, 3), pd > 0.06, '', 'reference colors missing from yours'))
    if A.get('audio') and B.get('audio'):
        row('tempo', A['audio']['bpm'], B['audio']['bpm'], 2, ' BPM', 'match the tempo or a clean multiple')
    w = max(len(r[0]) for r in rows)
    print(f"{'':{w}}  {'reference':>10}  {'yours':>10}")
    for name, a, b, off, unit, hint in rows:
        print(f"{name:{w}}  {a:>10.3f}  {b:>10.3f}  {'<- ' + hint if off else 'ok'}")
    missing = [c['hex'] for c in A['palette'] if c['share'] > 0.04 and min(math.dist(lab(c['hex']), lab(o['hex'])) for o in B['palette']) > 0.08]
    if missing: print('reference colors (>4% of frame) with no close match in yours:', ', '.join(missing))

if __name__ == '__main__':
    main()
