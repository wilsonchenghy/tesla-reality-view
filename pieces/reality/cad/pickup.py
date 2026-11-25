# DESIGN SPEC: PICKUP - a generic full-size crew-cab pickup with an open bed, for background traffic (no badges).
# L 5800, W 2000, H 1950, wheelbase 3600, 18" wheels on 800 tires, tall blunt nose with a dark grille, separate bed
# behind the cab (80 mm gap), bed walls 60 mm, floor at the rail height minus 520.
# World (harness, mm): x forward, y left, z up, ground z = 0, origin under the footprint centre.
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(globals().get("__file__", "/home/user/rv/pieces/reality/cad/pickup.py"))))
from build123d import Compound
import vlib as V

L, W, H, WB = 5800.0, 2000.0, 1950.0, 3600.0
XF, XR = L / 2, -L / 2
AX_F = XF - 1000.0
AX_R = AX_F - WB
TR, TW, RIM = 400.0, 275.0, 235.0
CAB_R = -1050.0                      # cab back (crew cab: two rows)
BED_F = CAB_R - 80.0                 # bed front (gap)
RAIL = 1330.0

ZB = [(XF, 480), (2500, 330), (2000, 280), (0, 270), (-2000, 290), (-2600, 360), (XR, 480)]
HW = [(XF, 860), (2700, 950), (2400, 990), (AX_F, W / 2), (0, W / 2), (AX_R, W / 2), (-2600, 990), (XR, 960)]

CAB = V.BodySpec(
    stations=[XF, 2750, 2450, 2050, 1700, 1400, 1100, 700, 200, -400, CAB_R],
    zb=ZB, hw=HW,
    zs=[(XF, 1180), (2400, 1250), (1500, 1300), (0, 1340), (CAB_R, 1350)],
    zt=[(XF, 1250), (2600, 1300), (1800, 1360), (1550, 1385), (1450, 1425), (1100, 1700), (900, 1870), (600, 1935),
        (0, H), (CAB_R, 1945)],
    rw=[(XF, 840), (2400, 950), (1600, 950), (1450, 900), (1100, 820), (700, 800), (CAB_R, 800)],
    shape={"side": 0.9, "crown": 0.85, "sill": 0.4},
    nose_r=90.0, tail_r=45.0,
)
CAB.fillet_tail = True


def bed_solid(d=0.0):
    """the bed: one constant section (the cab's lower body up to the rail) extruded, end edges rounded"""
    from build123d import Face, extrude
    xm = 0.5 * (BED_F + XR)
    pts = V.section_pts(CAB.zb(xm), RAIL - 60, CAB.hw(xm), RAIL, 960, {"side": 0.9, "crown": 0.95, "sill": 0.3})
    w = V.section_wire(BED_F - d, pts, d)
    s = extrude(Face(w), amount=(BED_F - XR) - 2 * d, dir=(-1, 0, 0))
    return V._round_caps(s, BED_F - d, XR + d, 45.0 - d, 60.0 - d)


def dlo_front():
    bot = [(x, CAB.zs(x) + 36) for x in (60, 700, 1350)]
    top = [(1300, CAB.zs(1300) + 50), (800, 1790), (550, 1850), (60, 1858)]
    return bot + top


def dlo_rear():
    bot = [(x, CAB.zs(x) + 36) for x in (CAB_R + 130, -500, -40)]
    top = [(-40, 1858), (CAB_R + 130, 1850)]
    return bot + top


def build():
    ws = V.mirror_plan([(1500, 860), (1200, 830), (920, 800), (800, 790)])
    glass_cut = V.prism_y(dlo_front(), r=40) + V.prism_y(dlo_rear(), r=40) + V.prism_z(ws, z0=1300) + V.box(CAB_R - 200, CAB_R + 120, -700, 700, 1500, 1840)
    head_h = [V.box(XF - 300, XF + 200, 520, 1100, 1020, 1160), V.box(XF - 300, XF + 200, -1100, -520, 1020, 1160)]
    head = [V.box(XF - 300, XF + 200, 540, 1100, 1120, 1140), V.box(XF - 300, XF + 200, -1100, -540, 1120, 1140)]
    grille = V.box(XF - 150, XF + 200, -520, 520, 640, 1160)
    bumper = V.box(XF - 150, XF + 200, -900, 900, 470, 560)
    p = V.build_vehicle(CAB, glass_cut, dark=[grille, bumper] + head_h, lamps_f=head, axles=(AX_F, AX_R),
                        arches=(AX_F,), y_out=W / 2 - 15, tire=(TR, TW, RIM), gap=45,
                        extra_body=V.mirrors(1350, 1000 - 48, 1450, 120, 48, 80, 170), spokes=6, style="spoke")
    # the bed: its own loft, the box cut out, a wheel well, tail lamps at the rear corners, a dark tailgate step
    bed = bed_solid()
    s_lamp = bed_solid(3.0)
    tub = V.box(XR + 70, BED_F - 70, -(W / 2 - 80), W / 2 - 80, RAIL - 520, RAIL + 400)
    lamps = [V.box(XR - 200, XR + 120, 760, 1100, 950, 1250), V.box(XR - 200, XR + 120, -1100, -760, 950, 1250)]
    bed = V.cut(bed, tub + V.fuse(lamps), "bed tub")
    light_r = V.skin(s_lamp, V.fuse(lamps))
    y_in = W / 2 - 15 - TW - 75
    bed = V.cut(bed, V.arch_cut(AX_R, TR, y_in, gap=45), "bed arch")
    liner = V.arch_liner(AX_R, TR, y_in, W / 2 - 15, CAB.zb(AX_R) + 8, gap=45)
    p["body"] = Compound(list(p["body"]) + [bed])
    p["tire"] = Compound(list(p["tire"]) + liner)
    p["glass"] = Compound(list(p["glass"]) + [V.box(XR + 10, BED_F - 10, -(W / 2 - 80), W / 2 - 80, RAIL - 525,
                                                     RAIL - 518)])         # dark bed floor liner
    p["light_rear"] = light_r
    return p


parts = build() if __name__ != "__nobuild__" else {}
COLORS = {k: V.COLORS[k] for k in parts}
