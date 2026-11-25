"""Drop duplicate vehicle tracks: two tracks that sit within 3.5 m of each other for most of their shared time are one
vehicle seen as two (e.g. a box truck also detected as a pickup); keep the one with more observations.
usage: python3 dedupe_cars.py index.json"""
import json, sys, numpy as np
p = sys.argv[1]; d = json.load(open(p)); C = d['cars']
def at(tr, t): return np.interp(t, tr['t'], tr['x']), np.interp(t, tr['t'], tr['z'])
drop = set()
for i in range(len(C)):
    for j in range(i + 1, len(C)):
        a, b = C[i], C[j]
        t0, t1 = max(a['t'][0], b['t'][0]), min(a['t'][-1], b['t'][-1])
        if t1 - t0 < 0.5: continue
        ts = np.linspace(t0, t1, 20)
        xa, za = at(a, ts); xb, zb = at(b, ts)
        if np.mean(np.hypot(xa - xb, za - zb) < 3.5) > 0.6:
            lose = j if a['n'] >= b['n'] else i; drop.add(lose)
            print('duplicate', a['id'], a['model'], '<->', b['id'], b['model'], '-> drop', C[lose]['id'])
d['cars'] = [c for k, c in enumerate(C) if k not in drop]
json.dump(d, open(p, 'w')); print('cars', len(C), '->', len(d['cars']))
