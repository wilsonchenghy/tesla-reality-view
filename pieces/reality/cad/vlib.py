"""vlib: a small build123d library for clean road-vehicle models (the Prometheus CAD harness kernel).

CAD frame (harness convention, mm): X forward (front at +X), Y left, Z up, ground z = 0, origin under the centre of
the footprint. `export_glb` converts to the scene frame: metres, Y up, front toward -Z.

A body is one loft through cross-sections taken along X. Each section is a closed periodic spline built from a few
numbers that vary along the car (tables, interpolated with PCHIP so the loft stays fair):
    zb  underside height        hw  half width (the widest point of the lower body)
    zs  shoulder / belt height  rw  greenhouse half width near the roof (tumblehome)
    zt  top (roof / hood / deck at the centreline)
The end sections are capped flat and the caps rounded with one large fillet (the nose and tail radius).
Windows and lamps are inset: the body is cut back inside a cutter by a recess depth, and the glass / lamp is a thin
skin of the same body shrunk by a smaller depth, so it sits a few mm below the paint like a flush-glazed product.
"""
import math
import sys

import numpy as np
from scipy.interpolate import PchipInterpolator
from build123d import (Axis, Box, Cylinder, Edge, Face, Location, Plane, Polyline, Pos, Rot, Solid, Wire,
                       Compound, make_face, extrude, Vector, fillet)

sys.path.insert(0, "/home/user/prometheus/Backend/occ_services")
try:
    from pcad import edge_break, safe_fillet          # noqa: F401  (the harness's edge break / guarded fillet)
except Exception:                                    # pragma: no cover
    edge_break = None
    safe_fillet = None


def _gt(s):
    g = s.geom_type
    return getattr(g, "name", str(g)).upper()


# ----------------------------------------------------------------------------------------------------------- tables
class Table:
    """piecewise-smooth function of x from (x, value) pairs (PCHIP: monotone between knots, no overshoot)"""

    def __init__(self, pts):
        pts = sorted(pts)
        self.x = np.array([p[0] for p in pts], float)
        self.v = np.array([p[1] for p in pts], float)
        self.f = PchipInterpolator(self.x, self.v, extrapolate=True)

    def __call__(self, x):
        return float(self.f(x))


# --------------------------------------------------------------------------------------------------------- sections
def section_pts(zb, zs, hw, zt, rw, shape):
    """right half of a cross-section's CONTROL POLYGON, (y, z), bottom centre -> top centre. Every section has the
    same pole count and a periodic cubic B-spline through them (uniform knots), so the sections are compatible and
    the loft is fair (a B-spline stays inside its polygon: no wiggles). `shape`: side = slab-sidedness (0 soft ..
    1 boxy); crown = how far out the roof / hood stays high; sill = how far in the greenhouse starts."""
    side = shape.get("side", 0.5)
    crown = shape.get("crown", 0.62)
    sill = shape.get("sill", 0.55)
    hl = zs - zb
    gh = max(zt - zs, 1.0)
    rw = min(rw, hw * 0.97)
    ysh = hw * (0.955 + 0.03 * side)
    ysill = rw + (ysh - rw) * sill
    return [
        (0.0, zb),
        (0.45 * hw, zb),
        (hw * (0.80 + 0.12 * side), zb),
        (hw, zb + (0.16 - 0.08 * side) * hl),
        (hw, zb + 0.55 * hl),
        (hw * (0.995 + 0.005 * side), zs - 0.10 * hl),
        (ysh, zs),
        (ysill, zs + 0.16 * gh),
        (rw, zs + 0.58 * gh),
        (rw * (0.80 + 0.15 * crown), zt - 0.03 * gh),
        (rw * crown * 0.6, zt),
        (0.0, zt),
    ]


def section_ring(pts, d=0.0):
    """closed ring (y, z) from the right half; d > 0 shrinks it (approximate inward offset)"""
    half = []
    for y, z in pts:
        half.append((max(y - d, 0.0) if y > 0 else 0.0, z))
    zb, zt = half[0][1] + d, half[-1][1] - d
    half[0] = (0.0, zb)
    half[1] = (half[1][0], half[1][1] + d)
    half[-1] = (0.0, zt)
    half[-2] = (half[-2][0], half[-2][1] - d)
    half[-3] = (half[-3][0], half[-3][1] - d * 0.8)
    return half + [(-y, z) for (y, z) in reversed(half[1:-1])]


def chord_params(ring):
    p = np.array(ring + [ring[0]], float)
    c = np.concatenate([[0], np.cumsum(np.linalg.norm(np.diff(p, axis=0), axis=1))])
    return list(c / c[-1])


def section_wire(x, pts, d=0.0, params=None):
    """closed periodic cubic B-spline section at X = x on the ring of poles (uniform knots: compatible sections)"""
    from OCP.Geom import Geom_BSplineCurve
    from OCP.collections import Array1_gp_Pnt as TColgp_Array1OfPnt, Array1_double as TColStd_Array1OfReal
    from OCP.collections import Array1_int as TColStd_Array1OfInteger
    from OCP.gp import gp_Pnt
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge
    ring = section_ring(pts, d)
    n = len(ring)
    P = TColgp_Array1OfPnt(1, n)
    for i, (y, z) in enumerate(ring):
        P.SetValue(i + 1, gp_Pnt(x, y, z))
    K = TColStd_Array1OfReal(1, n + 1)
    M = TColStd_Array1OfInteger(1, n + 1)
    for i in range(n + 1):
        K.SetValue(i + 1, float(i))
        M.SetValue(i + 1, 1)
    c = Geom_BSplineCurve(P, K, M, 3, True)
    return Wire([Edge(BRepBuilderAPI_MakeEdge(c).Edge())])


class BodySpec:
    def __init__(self, stations, zb, zs, hw, zt, rw, shape=None, nose_r=120.0, tail_r=120.0, shape_tables=None):
        self.stations = sorted(stations, reverse=True)               # front -> rear
        self.zb, self.zs, self.hw, self.zt, self.rw = (Table(t) for t in (zb, zs, hw, zt, rw))
        self.shape = shape or {}
        self.shape_tables = {k: Table(v) for k, v in (shape_tables or {}).items()}
        self.nose_r, self.tail_r = nose_r, tail_r
        self.smooth = True
        self.fillet_tail = False          # True: flat tail cap rounded by a fillet (a cab back), not end stations

    def pts(self, x):
        sh = dict(self.shape)
        for k, t in self.shape_tables.items():
            sh[k] = t(x)
        return section_pts(self.zb(x), self.zs(x), self.hw(x), self.zt(x), self.rw(x), sh)

    def solid(self, d=0.0):
        """the loft; the nose and tail are rounded by extra end stations shrunk on a quarter ellipse (radius
        nose_r / tail_r), not by a fillet (cap fillets on lofts gave solids that later booleans could not cut)"""
        xf, xr = self.stations[0] - d, self.stations[-1] + d
        rf, rr = self.nose_r, self.tail_r
        mid = [x for x in self.stations[1:-1] if xr + rr + 25 < x < xf - rf - 25]
        th = [1.3, 0.95, 0.6, 0.28]                                  # radians, pi/2 = the end face
        front = [(xf - rf * (1 - math.sin(t)), d + rf * (1 - math.cos(t))) for t in th]
        rear = [(xr + rr * (1 - math.sin(t)), d + rr * (1 - math.cos(t))) for t in reversed(th)]
        if self.fillet_tail:
            mid = [x for x in self.stations[1:-1] if xr + 25 < x < xf - rf - 25]
            rear = [(xr, d)]
        plan = front + [(x, d) for x in mid] + rear
        wires = [section_wire(x, self.pts(x), dd) for x, dd in plan]
        s = _loft(wires, self.smooth)
        if self.fillet_tail:
            s = _round_caps(s, 1e9, xr, 0, rr - d)
        return s


def _loft(wires, smooth=True):
    """a closed loft; smooth=True approximates (fairer, no wiggle between stations) instead of interpolating"""
    if not smooth:
        return Solid.make_loft(wires, ruled=False)
    from OCP.BRepOffsetAPI import BRepOffsetAPI_ThruSections
    from OCP.Approx import Approx_ParametrizationType as PT
    for deg, par in ((6, PT.Approx_ChordLength), (4, PT.Approx_ChordLength), (8, PT.Approx_Centripetal),
                     (5, PT.Approx_IsoParametric), (10, PT.Approx_ChordLength)):
        ts = BRepOffsetAPI_ThruSections(True, False, 1e-4)
        ts.SetSmoothing(True)
        ts.SetMaxDegree(deg)
        ts.SetParType(par)
        ts.CheckCompatibility(False)
        for w in wires:
            ts.AddWire(w.wrapped)
        try:
            ts.Build()
            return Solid(ts.Shape())
        except Exception:
            pass
    print("vlib: smoothed loft failed; interpolating loft instead", file=sys.stderr)
    return Solid.make_loft(wires, ruled=False)


def _round_caps(s, x_front, x_rear, r_front, r_rear):
    for xc, r in ((x_front, r_front), (x_rear, r_rear)):
        cap_edges = [e for f in s.faces() if abs(f.center().X - xc) < 1.0 and _gt(f) == "PLANE" for e in f.edges()]
        if not cap_edges or r <= 0:
            continue
        done = False
        for rr in (r, r * 0.8, r * 0.6, r * 0.4):
            try:
                t = s.fillet(rr, cap_edges)
                if (t.is_valid() if callable(t.is_valid) else t.is_valid):
                    s, done = t, True
                    break
            except Exception:
                pass
        if not done:
            print(f"vlib: cap fillet at x={xc:.0f} failed", file=sys.stderr)
    return s


# ---------------------------------------------------------------------------------------------------------- cutters
def _rounded_wire(pts3, r):
    w = Wire.make_polygon([Vector(*p) for p in pts3], close=True)
    if r > 0:
        for rr in (r, r * 0.6, r * 0.3):
            try:
                return w.fillet_2d(rr, w.vertices())
            except Exception:
                pass
    return w


def prism_y(poly_xz, y0=-3000, y1=3000, r=60.0):
    """a side-view outline (x, z), corners rounded r, extruded across Y"""
    w = _rounded_wire([(x, y0, z) for x, z in poly_xz], r)
    return extrude(Face(w), amount=y1 - y0, dir=(0, 1, 0))


def prism_z(poly_xy, z0=-100, z1=4000, r=60.0):
    """a plan-view outline (x, y), corners rounded r, extruded along Z"""
    w = _rounded_wire([(x, y, z0) for x, y in poly_xy], r)
    return extrude(Face(w), amount=z1 - z0, dir=(0, 0, 1))


def mirror_plan(half_xy):
    """plan outline from its right... left half (y >= 0), front->rear, mirrored to a closed loop"""
    return list(half_xy) + [(x, -y) for x, y in reversed(half_xy)]


def smooth_poly(pts, r=40.0, n=4):
    """round the corners of a polygon (Chaikin) so cut outlines read as designed, not boxed"""
    p = np.array(pts, float)
    for _ in range(n):
        q = []
        for i in range(len(p)):
            a, b = p[i], p[(i + 1) % len(p)]
            q.append(0.75 * a + 0.25 * b)
            q.append(0.25 * a + 0.75 * b)
        p = np.array(q)
    return [tuple(v) for v in p]


def box(x0, x1, y0, y1, z0, z1):
    return Box(x1 - x0, y1 - y0, z1 - z0).moved(Location(((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2)))


def cut(a, b, what=""):
    """a - b, guarded: an OCC boolean that silently empties the body is retried with the cutter nudged a fraction of
    a mm (coincident / tangent faces), then reported and skipped"""
    for d in ((0, 0, 0), (0.31, 0.17, 0.23), (-0.47, 0.29, -0.13)):
        try:
            r = a - (b.moved(Location(d)) if any(d) else b)
            if r.volume > 0.5 * a.volume:
                return r
        except Exception as ex:
            print(f"vlib: cut {what} raised {ex}", file=sys.stderr)
    print(f"vlib: cut {what} failed (empty result); skipped", file=sys.stderr)
    return a


def join(a, b, what=""):
    """a + b, guarded: a fuse that loses the body is retried slightly moved, then skipped"""
    for dz in (0.0, 0.7, -1.3):
        try:
            r = a + (b.moved(Location((0, 0, dz))) if dz else b)
            if r.volume >= a.volume * 0.999:
                return r
        except Exception:
            pass
    print(f"vlib: join {what} failed; skipped", file=sys.stderr)
    return a


def fuse(shapes):
    shapes = [s for s in shapes if s is not None]
    out = shapes[0]
    for s in shapes[1:]:
        out = out + s
    return out


def skin(shrunk, cutter):
    """the part of the shrunk body's outer surface that lies inside the cutter: a surface (glass, a lamp lens)
    a few mm below the paint, covering the opening `cutter` leaves in the body"""
    inter = shrunk & cutter
    outer = Compound(shrunk.faces())
    keep = [f for f in inter.faces() if outer.distance_to(f.position_at(0.5, 0.5)) < 0.05]
    return Compound(keep)


# ----------------------------------------------------------------------------------------------------------- wheels
def wheel(x, y_out, side, R=370.0, w=255.0, rim_r=250.0, spokes=5, style="aero"):
    """tire + rim at axle x, outer face at |y| = y_out on `side` (+1 left, -1 right). Returns (tire, rim)."""
    # built along +Z (axis), outer face at z = 0, then turned so the axis is Y and the outer face looks outward
    tire = Cylinder(R, w).moved(Location((0, 0, -w / 2)))
    tire = tire - Cylinder(rim_r + 4, w + 2).moved(Location((0, 0, -w / 2)))
    try:
        tire = tire.fillet(min(55.0, w * 0.22), [e for e in tire.edges() if _gt(e) == "CIRCLE" and abs(e.radius - R) < 1])
        tire = tire.fillet(8.0, [e for e in tire.edges() if _gt(e) == "CIRCLE" and abs(e.radius - rim_r - 4) < 1])
    except Exception as ex:
        print("vlib: tire fillet", ex, file=sys.stderr)
    dish = Cylinder(rim_r + 6, 12).moved(Location((0, 0, -72)))        # the dark well behind the spokes
    tire = tire + dish
    # rim: a lip ring + a face with windows
    lip = Cylinder(rim_r + 6, 26).moved(Location((0, 0, -14))) - Cylinder(rim_r - 16, 30).moved(Location((0, 0, -14)))
    face_d = 24
    face = Cylinder(rim_r - 10, face_d).moved(Location((0, 0, -face_d / 2 - 16)))
    hub_r = 0.26 * rim_r
    win_in, win_out = hub_r + 18, rim_r - 30
    wins = []
    for k in range(spokes):
        a0 = 2 * math.pi * k / spokes
        span = (2 * math.pi / spokes) * (0.62 if style == "aero" else 0.70)
        if style == "aero":
            span_in = span * 0.55
        else:
            span_in = span * 0.75
        pts = []
        for i in range(7):
            t = a0 - span / 2 + span * i / 6
            pts.append((win_out * math.cos(t), win_out * math.sin(t)))
        for i in range(5):
            t = a0 + span_in / 2 - span_in * i / 4
            pts.append((win_in * math.cos(t), win_in * math.sin(t)))
        pts = smooth_poly(pts, n=2)
        wpoly = Wire.make_polygon([Vector(px, py, -80) for px, py in pts], close=True)
        wins.append(extrude(Face(wpoly), amount=100, dir=(0, 0, 1)))
    face = face - fuse(wins)
    cap = Cylinder(hub_r * 0.55, 10).moved(Location((0, 0, -9)))
    rim = lip + face + cap
    # turn: axis +Z -> outward along +/-Y, outer face at y_out
    rot = Rot(-90, 0, 0) if side > 0 else Rot(90, 0, 0)
    loc = Location((x, side * y_out, R)) * rot
    return tire.moved(loc), rim.moved(loc)


def arch_liner(x, R, y_in, y_out, z_min, gap=40.0, t=6.0):
    """a dark wheel-well liner (tire material): the well's roof and its inner wall, only above the body's underside"""
    r = R + gap
    out = []
    for s in (1, -1):
        ln = y_out - y_in + 40
        yc = s * (y_in + ln / 2 - 2)
        tube = Cylinder(r - 1.5, ln) - Cylinder(r - 1.5 - t, ln + 2)
        wall = Cylinder(r - 1.5, 4)
        wall = wall.moved(Location((0, 0, s * (ln / 2 - 4))))
        sol = (tube + wall).moved(Location((x, yc, R)) * Rot(90, 0, 0))
        out.append(sol & box(x - r - 10, x + r + 10, -(y_out - 25), y_out - 25, z_min + 50, R + r + 10))
    return out


def arch_cut(x, R, y_in, gap=45.0, z=None):
    """a wheel-well pocket on both sides: cylinder about Y through the axle, from |y| = y_in outward"""
    r = R + gap
    zc = R if z is None else z
    cuts = []
    for s in (1, -1):
        c = Cylinder(r, 1000).moved(Location((x, s * (y_in + 500), zc)) * Rot(90, 0, 0))
        cuts.append(c)
    return cuts[0] + cuts[1]


# ----------------------------------------------------------------------------------------------------------- export
COLORS = {"body": "#EDEDEA", "glass": "#0E1116", "tire": "#16171A", "rim": "#3A3D42",
          "light_rear": "#B3121F", "light_front": "#F5F5F0", "cargo": "#EDEDEA"}
PBR = {"body": (0.0, 0.42), "glass": (0.0, 0.35), "tire": (0.0, 0.9), "rim": (0.15, 0.45),
       "light_rear": (0.0, 0.3), "light_front": (0.0, 0.25), "cargo": (0.0, 0.55)}


PART_TOL = {"glass": (2.0, 0.12), "body": (3.0, 0.25), "tire": (5.0, 0.6), "rim": (5.0, 0.6), "light_rear": (2.0, 0.3), "light_front": (2.0, 0.3)}


def mesh_shape(shape, tol=3.0, ang=0.35):
    """OCC tessellation with surface normals (smooth inside faces; tangent faces meet with matching normals)"""
    from OCP.BRepMesh import BRepMesh_IncrementalMesh
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopAbs import TopAbs_FACE, TopAbs_REVERSED
    from OCP.BRep import BRep_Tool
    from OCP.TopLoc import TopLoc_Location
    from OCP.TopoDS import TopoDS
    from OCP.BRepLib import BRepLib_ToolTriangulatedShape

    w = shape.wrapped
    BRepMesh_IncrementalMesh(w, tol, False, ang, True)
    V, N, F = [], [], []
    off = 0
    for bf in shape.faces():
        f = bf.wrapped
        loc = TopLoc_Location()
        tri = BRep_Tool.Triangulation_s(f, loc)
        if tri is None:
            continue
        BRepLib_ToolTriangulatedShape.ComputeNormals_s(f, tri)
        tr = loc.Transformation()
        nn = tri.NbNodes()
        v = np.empty((nn, 3))
        n = np.empty((nn, 3))
        for i in range(1, nn + 1):
            p = tri.Node(i).Transformed(tr)
            v[i - 1] = (p.X(), p.Y(), p.Z())
            d = tri.Normal(i).Transformed(tr)
            n[i - 1] = (d.X(), d.Y(), d.Z())
        rev = f.Orientation() == TopAbs_REVERSED
        t = np.empty((tri.NbTriangles(), 3), int)
        for i in range(1, tri.NbTriangles() + 1):
            a, b, c = tri.Triangle(i).Get()
            t[i - 1] = (a - 1, c - 1, b - 1) if rev else (a - 1, b - 1, c - 1)
        # orient normals with the winding (majority vote per face)
        g = np.cross(v[t[:, 1]] - v[t[:, 0]], v[t[:, 2]] - v[t[:, 0]])
        if np.sum(np.einsum("ij,ij->i", g, n[t[:, 0]])) < 0:
            n = -n
        V.append(v)
        N.append(n)
        F.append(t + off)
        off += nn
    if not V:
        return None
    return np.vstack(V), np.vstack(N), np.vstack(F)


def to_scene(v):
    """CAD (mm, X fwd, Y left, Z up) -> scene (m, Y up, front -Z)"""
    return np.column_stack([-v[:, 1], v[:, 2], -v[:, 0]]) * 0.001


def export_glb(parts, path, tol=3.0, ang=0.35):
    """parts: {name: build123d shape}; one node + mesh + material per name. Returns {name: triangles}."""
    import trimesh
    sc = trimesh.Scene()
    counts = {}
    for name, shp in parts.items():
        if shp is None:
            continue
        pt = PART_TOL.get(name, (tol, ang))
        m = mesh_shape(shp, pt[0], pt[1]) if name in PART_TOL else mesh_shape(shp, tol, ang)
        if m is None:
            continue
        v, n, f = m
        vs, ns = to_scene(v), to_scene(n) / 0.001
        ns /= np.linalg.norm(ns, axis=1, keepdims=True) + 1e-12
        # the frame change is a proper rotation, so winding is preserved
        mesh = trimesh.Trimesh(vs, f, vertex_normals=ns, process=False)
        col = COLORS.get(name, "#808080")
        rgb = [int(col[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        lin = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]   # glTF factors are linear
        met, rough = PBR.get(name, (0.0, 0.5))
        mat = trimesh.visual.material.PBRMaterial(name=name, baseColorFactor=lin + [1.0], metallicFactor=met,
                                                  roughnessFactor=rough, doubleSided=False)
        mesh.visual = trimesh.visual.TextureVisuals(material=mat)
        sc.add_geometry(mesh, node_name=name, geom_name=name)
        counts[name] = int(len(f))
    data = sc.export(file_type="glb", include_normals=True)
    with open(path, "wb") as fh:
        fh.write(data)
    return counts


# ------------------------------------------------------------------------------------------------- whole vehicles
def mirrors(x, y, z, sx=100, sy=50, sz=58, stalk_in=130):
    """a pair of mirror pods on short stalks (separate solids, joined to the body mesh, not fused)"""
    from build123d import Sphere, scale
    out = []
    for s in (1, -1):
        m = scale(Sphere(1.0), by=(sx, sy, sz)).moved(Location((x, s * y, z)))
        y0, y1 = sorted((s * (y - stalk_in), s * (y - sy * 0.5)))
        out.append(m + box(x - 10, x + 50, y0, y1, z - 40, z - 10))
    return out


def build_vehicle(spec, glass_cut, dark=(), lamps_r=(), lamps_f=(), axles=(), y_out=900.0, tire=(370, 255, 250),
                  gap=36.0, extra_body=(), duals=(), arches=None, spokes=5, style="aero", bodies=None):
    """the standard car build: loft -> openings (glass / dark trim / lamps, each a skin a few mm under the paint)
    -> wheel wells with dark liners -> wheels. Returns the parts dict.
    bodies: optional list of (spec, cutter_or_None) extra lofted bodies (a pickup bed) that share the treatment."""
    R, TW, RIM = tire
    full = spec.solid()
    s_glass, s_lamp = spec.solid(5.0), spec.solid(3.0)
    dark_all = fuse([glass_cut] + list(dark)) if glass_cut is not None or dark else None
    lr = fuse(list(lamps_r)) if lamps_r else None
    lf = fuse(list(lamps_f)) if lamps_f else None
    cut_all = fuse([c for c in (dark_all, lr, lf) if c is not None])
    body = cut(full, cut_all, "openings") if cut_all is not None else full
    glass = skin(s_glass, dark_all) if dark_all is not None else None
    light_r = skin(s_lamp, lr) if lr is not None else None
    light_f = skin(s_lamp, lf) if lf is not None else None
    y_in = y_out - TW - 75
    arch_x = list(axles) if arches is None else list(arches)
    liners = []
    if arch_x:
        for x in arch_x:
            body = cut(body, arch_cut(x, R, y_in, gap=gap), f"arch x={x:.0f}")
        for x in arch_x:
            liners += arch_liner(x, R, y_in, y_out, spec.zb(x) + 8, gap=gap)
    tires, rims = list(liners), []
    for x in axles:
        for s in (1, -1):
            t, r = wheel(x, y_out, s, R=R, w=TW, rim_r=RIM, spokes=spokes, style=style)
            tires.append(t)
            rims.append(r)
            if x in duals:
                t, r = wheel(x, y_out - TW - 22, s, R=R, w=TW, rim_r=RIM, spokes=spokes, style=style)
                tires.append(t)
    return {"body": Compound([body] + list(extra_body)), "glass": glass, "tire": Compound(tires),
            "rim": Compound(rims), "light_rear": light_r, "light_front": light_f}
