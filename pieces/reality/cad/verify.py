"""Check the GLBs: loads, named nodes, bbox vs the brief (+-5 %), wheels on y = 0, front toward -Z, triangle budget.
python3 verify.py   (exit 1 on any failure)"""
import sys
from pathlib import Path

import numpy as np
import trimesh

MODELS = Path(__file__).resolve().parent.parent / "models"
SPEC = {"ego": (1.92, 1.62, 4.75), "sedan": (1.85, 1.45, 4.7), "suv": (1.95, 1.78, 4.9),
        "pickup": (2.0, 1.95, 5.8), "boxtruck": (2.45, 3.3, 7.2)}
NEED = ["body", "glass", "tire", "rim", "light_rear", "light_front"]
bad = 0
for name, (w, h, l) in SPEC.items():
    sc = trimesh.load(MODELS / f"{name}.glb")
    geo = {g: sc.geometry[g] for g in sc.geometry}
    nodes = set(sc.graph.nodes_geometry)
    lo, hi = sc.bounds
    size = hi - lo
    tris = sum(len(g.faces) for g in geo.values())
    errs = []
    need = NEED + (["cargo"] if name == "boxtruck" else [])
    missing = [n for n in need if n not in nodes]
    if missing:
        errs.append(f"missing nodes {missing}")
    for got, want, ax in zip(size, (w, h, l), "xyz"):
        if abs(got / want - 1) > 0.05:
            errs.append(f"size {ax} {got:.3f} vs {want}")
    if abs(lo[1]) > 0.01:
        errs.append(f"min y {lo[1]:.4f}")
    zf = geo["light_front"].bounds.mean(axis=0)[2]
    zr = geo["light_rear"].bounds.mean(axis=0)[2]
    if not zf < 0 < zr:
        errs.append(f"front not -Z (front lamp z {zf:.2f}, rear lamp z {zr:.2f})")
    if tris > 40000:
        errs.append(f"{tris} triangles")
    if abs((lo[0] + hi[0]) / 2) > 0.01 or abs((lo[2] + hi[2]) / 2) > 0.03:
        errs.append("not centred on the footprint")
    bad += bool(errs)
    print(f"{name:9s} {'OK  ' if not errs else 'FAIL'} tris={tris:6d} size(x,y,z)=({size[0]:.3f}, {size[1]:.3f}, "
          f"{size[2]:.3f}) min_y={lo[1]:+.4f} front_lamp_z={zf:+.2f} rear_lamp_z={zr:+.2f} {'; '.join(errs)}")
sys.exit(1 if bad else 0)
