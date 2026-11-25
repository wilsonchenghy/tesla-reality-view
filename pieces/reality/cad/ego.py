# DESIGN SPEC: EGO - a modern electric compact crossover (Model-Y-like silhouette, no badges), the hero car of the
# Reality View piece. L 4750, W 1920 (body), H 1620, wheelbase 2890, 20" wheels (tire 740), smooth fastback roof,
# short grille-less nose, full-width thin rear light bar, black glass roof + windows.
# World (harness, mm): x forward, y left, z up, ground z = 0, origin under the footprint centre.
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(globals().get("__file__", "/home/user/rv/pieces/reality/cad/ego.py"))))
from build123d import Compound, Location
import vlib as V

L, W, H, WB = 4750.0, 1920.0, 1620.0, 2890.0
XF, XR = L / 2, -L / 2
AX_F = XF - 890.0                     # front axle (front overhang 890)
AX_R = AX_F - WB                      # rear axle (rear overhang 970)
TR, TW, RIM = 370.0, 255.0, 250.0     # tire radius, width; rim radius (20")

SPEC = V.BodySpec(
    stations=[XF, 2290, 2100, 1800, 1300, 900, 400, -100, -600, -1100, -1600, -1950, -2220, XR],
    zb=[(XF, 430), (2200, 260), (1600, 190), (0, 172), (-1300, 185), (-2000, 290), (XR, 440)],
    zs=[(XF, 700), (2200, 800), (1800, 875), (1200, 965), (300, 1035), (-800, 1065), (-1600, 1085),
        (-2100, 1060), (XR, 980)],
    zt=[(XF, 790), (2250, 845), (1800, 910), (1250, 990), (1100, 1045), (700, 1280), (300, 1500), (0, 1597),
        (-350, H), (-800, 1597), (-1400, 1470), (-1900, 1240), (-2150, 1185), (XR, 1110)],
    hw=[(XF, 590), (2290, 780), (2100, 890), (1800, 945), (AX_F, 958), (0, W / 2), (AX_R, W / 2),
        (-2000, 925), (-2220, 845), (XR, 640)],
    rw=[(XF, 540), (2100, 820), (1800, 860), (1250, 850), (1000, 770), (600, 690), (0, 662), (-800, 650),
        (-1500, 640), (-2000, 680), (XR, 580)],
    shape={"side": 0.35, "crown": 0.62, "sill": 0.55},
    nose_r=200.0, tail_r=180.0,
)


def dlo():
    """side daylight opening (x, z): A-pillar parallel to the windshield, fastback quarter window"""
    bot = [(x, SPEC.zs(x) + 38) for x in (-1660, -1200, -600, 0, 600, 1050)]
    top = [(1000, SPEC.zs(1000) + 58), (420, 1400), (150, 1500), (-400, 1522), (-1000, 1452), (-1400, 1310),
           (-1700, 1180)]
    return bot + top


def top_glass():
    """windshield + glass roof + rear glass, plan half (x, y)"""
    half = [(1140, 700), (900, 662), (500, 628), (0, 622), (-1300, 602), (-1700, 612), (-1905, 622)]
    return V.mirror_plan(half)


def build():
    glass_cut = V.prism_y(dlo()) + V.prism_z(top_glass(), z0=900)
    rear_bar = V.box(XR - 200, XR + 260, -1100, 1100, 880, 906)
    front_bar = V.box(XF - 260, XF + 200, -1100, 1100, 706, 720)
    head_h = [V.box(XF - 300, XF + 200, 440, 1100, 612, 666), V.box(XF - 300, XF + 200, -1100, -440, 612, 666)]
    head = [V.box(XF - 300, XF + 200, 450, 1100, 634, 646), V.box(XF - 300, XF + 200, -1100, -450, 634, 646)]
    intake = V.box(XF - 150, XF + 200, -540, 540, 452, 512)
    diffuser = V.box(XR - 200, XR + 170, -680, 680, 478, 532)
    return V.build_vehicle(SPEC, glass_cut, dark=[intake, diffuser] + head_h, lamps_r=[rear_bar],
                           lamps_f=[front_bar] + head, axles=(AX_F, AX_R), y_out=W / 2 - 18, tire=(TR, TW, RIM),
                           gap=36, extra_body=V.mirrors(1120, 905, 1050))


parts = build() if __name__ != "__nobuild__" else {}
COLORS = {k: V.COLORS[k] for k in parts}
