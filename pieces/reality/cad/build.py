"""Build the vehicle GLBs: python3 build.py [ego sedan suv pickup boxtruck]  (all by default)

Each <name>.py is a build123d program (harness convention: mm, x forward, z up, a `parts` dict). This runs it,
tessellates every part (2-5 mm tolerance) and writes ../models/<name>.glb in the scene frame (m, Y up, front -Z),
one node / mesh / material per part name.
"""
import json
import runpy
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import vlib  # noqa: E402

OUT = HERE.parent / "models"
ALL = ["ego", "sedan", "suv", "pickup", "boxtruck"]
TOL = {"boxtruck": 4.0}


def build(name):
    t0 = time.time()
    g = runpy.run_path(str(HERE / f"{name}.py"), run_name="__vehicle__")
    t1 = time.time()
    OUT.mkdir(exist_ok=True)
    path = OUT / f"{name}.glb"
    counts = vlib.export_glb(g["parts"], path, tol=TOL.get(name, 3.0), ang=0.38)
    import trimesh
    sc = trimesh.load(path)
    lo, hi = sc.bounds
    rep = {"glb": str(path), "triangles": int(sum(counts.values())), "per_part": counts,
           "bbox_min": [round(float(v), 3) for v in lo], "bbox_max": [round(float(v), 3) for v in hi],
           "size_xyz": [round(float(v), 3) for v in (hi - lo)], "build_s": round(t1 - t0, 1),
           "export_s": round(time.time() - t1, 1), "kb": path.stat().st_size // 1024}
    print(json.dumps({name: rep}))
    return rep


if __name__ == "__main__":
    names = sys.argv[1:] or ALL
    reps = {n: build(n) for n in names}
    rp = HERE / "build_report.json"
    old = json.loads(rp.read_text()) if rp.exists() else {}
    old.update(reps)
    rp.write_text(json.dumps(old, indent=1))
