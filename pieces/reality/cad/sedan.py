# DESIGN SPEC: SEDAN - a generic mid-size three-box sedan for background traffic (no badges).
# L 4700, W 1850, H 1450, wheelbase 2830, 18" wheels (tire 660), body-colour roof, dark windows, notchback trunk.
# World (harness, mm): x forward, y left, z up, ground z = 0, origin under the footprint centre.
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(globals().get("__file__", "/home/user/rv/pieces/reality/cad/sedan.py"))))
import vlib as V

L, W, H, WB = 4700.0, 1850.0, 1450.0, 2830.0
XF, XR = L / 2, -L / 2
AX_F = XF - 930.0
AX_R = AX_F - WB
TR, TW, RIM = 330.0, 225.0, 222.0

SPEC = V.BodySpec(
    stations=[XF, 2270, 2080, 1750, 1300, 950, 500, 100, -300, -700, -1100, -1450, -1800, -2120, -2280, XR],
    zb=[(XF, 360), (2150, 230), (1500, 165), (0, 150), (-1400, 165), (-2050, 260), (XR, 400)],
    zs=[(XF, 650), (2150, 735), (1700, 815), (1000, 880), (0, 930), (-1200, 965), (-2000, 975), (XR, 930)],
    zt=[(XF, 720), (2200, 770), (1700, 850), (1050, 935), (950, 975), (600, 1180), (150, 1405), (-200, H),
        (-650, 1440), (-1100, 1330), (-1450, 1100), (-1600, 1055), (-2100, 1040), (XR, 1000)],
    hw=[(XF, 600), (2270, 760), (2080, 850), (1750, 905), (AX_F, 918), (0, W / 2), (AX_R, W / 2),
        (-2000, 900), (-2280, 830), (XR, 660)],
    rw=[(XF, 550), (2080, 790), (1750, 830), (1050, 810), (850, 720), (400, 640), (0, 620), (-700, 615),
        (-1150, 640), (-1450, 760), (-2000, 790), (XR, 600)],
    shape={"side": 0.45, "crown": 0.66, "sill": 0.5},
    nose_r=170.0, tail_r=150.0,
)


def dlo():
    """side windows (x, z): A-pillar, flat roof rail, C-pillar sloping into the deck"""
    bot = [(x, SPEC.zs(x) + 34) for x in (-1250, -700, 0, 600, 960)]
    top = [(900, SPEC.zs(900) + 52), (300, 1310), (0, 1362), (-500, 1365), (-900, 1300), (-1220, 1150)]
    return bot + top


def screens():
    """windshield and rear window, plan (x, y): the roof between them stays body colour"""
    ws = V.mirror_plan([(990, 690), (700, 650), (300, 600), (180, 585)])
    rw = V.mirror_plan([(-760, 575), (-1100, 600), (-1440, 640)])
    return V.prism_z(ws, z0=880) + V.prism_z(rw, z0=900)


def build():
    glass_cut = V.prism_y(dlo()) + screens()
    tail = [V.box(XR - 200, XR + 300, 430, 1100, 860, 930), V.box(XR - 200, XR + 300, -1100, -430, 860, 930)]
    tail_bar = V.box(XR - 200, XR + 120, -440, 440, 885, 900)
    head_h = [V.box(XF - 320, XF + 200, 430, 1100, 590, 650), V.box(XF - 320, XF + 200, -1100, -430, 590, 650)]
    head = [V.box(XF - 320, XF + 200, 445, 1100, 628, 640), V.box(XF - 320, XF + 200, -1100, -445, 628, 640)]
    grille = V.box(XF - 150, XF + 200, -420, 420, 430, 560)
    diffuser = V.box(XR - 200, XR + 160, -620, 620, 440, 490)
    return V.build_vehicle(SPEC, glass_cut, dark=[grille, diffuser] + head_h, lamps_r=tail + [tail_bar],
                           lamps_f=head, axles=(AX_F, AX_R), y_out=W / 2 - 16, tire=(TR, TW, RIM), gap=34,
                           extra_body=V.mirrors(1010, 880, 1010, 95, 46, 55), spokes=10, style="spoke")


parts = build() if __name__ != "__nobuild__" else {}
COLORS = {k: V.COLORS[k] for k in parts}
