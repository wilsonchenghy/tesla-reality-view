# DESIGN SPEC: SUV - a generic boxy mid/full-size SUV for background traffic (no badges).
# L 4900, W 1950, H 1780, wheelbase 2900, 19" wheels (tire 780), upright two-box shape, near-vertical tailgate.
# World (harness, mm): x forward, y left, z up, ground z = 0, origin under the footprint centre.
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(globals().get("__file__", "/home/user/rv/pieces/reality/cad/suv.py"))))
import vlib as V

L, W, H, WB = 4900.0, 1950.0, 1780.0, 2900.0
XF, XR = L / 2, -L / 2
AX_F = XF - 920.0
AX_R = AX_F - WB
TR, TW, RIM = 390.0, 255.0, 245.0

SPEC = V.BodySpec(
    stations=[XF, 2300, 2100, 1800, 1400, 1100, 700, 200, -400, -1000, -1600, -2000, -2250, XR],
    zb=[(XF, 420), (2200, 290), (1700, 215), (0, 205), (-1300, 215), (-2050, 300), (XR, 440)],
    zs=[(XF, 860), (2200, 950), (1700, 1010), (1100, 1065), (0, 1100), (-1500, 1120), (-2150, 1115), (XR, 1080)],
    zt=[(XF, 930), (2250, 1000), (1700, 1080), (1250, 1130), (1150, 1170), (800, 1500), (500, 1720), (200, 1770),
        (-600, H), (-1500, 1775), (-2050, 1750), (-2300, 1690), (XR, 1600)],
    hw=[(XF, 760), (2300, 880), (2100, 940), (1800, 965), (AX_F, 975), (0, W / 2), (AX_R, W / 2),
        (-2100, 965), (-2300, 920), (XR, 820)],
    rw=[(XF, 700), (2100, 900), (1300, 900), (1100, 830), (700, 760), (300, 740), (-1000, 740), (-2000, 735),
        (-2300, 760), (XR, 720)],
    shape={"side": 0.85, "crown": 0.82, "sill": 0.45},
    nose_r=120.0, tail_r=110.0,
)


def dlo():
    bot = [(x, SPEC.zs(x) + 36) for x in (-2050, -1400, -600, 200, 800, 1120)]
    top = [(1070, SPEC.zs(1070) + 55), (520, 1610), (200, 1660), (-800, 1665), (-1800, 1655), (-2120, 1600)]
    return bot + top


def screens():
    ws = V.mirror_plan([(1160, 760), (900, 735), (560, 705), (440, 690)])
    return V.prism_z(ws, z0=1080)


def build():
    glass_cut = V.prism_y(dlo()) + screens()
    back = V.box(XR - 200, XR + 140, -690, 690, 1240, 1610)                  # tailgate window
    tail = [V.box(XR - 200, XR + 260, 690, 1100, 1060, 1380), V.box(XR - 200, XR + 260, -1100, -690, 1060, 1380)]
    head_h = [V.box(XF - 300, XF + 200, 380, 1100, 770, 860), V.box(XF - 300, XF + 200, -1100, -380, 770, 860)]
    head = [V.box(XF - 300, XF + 200, 395, 1100, 820, 836), V.box(XF - 300, XF + 200, -1100, -395, 820, 836)]
    grille = V.box(XF - 150, XF + 200, -370, 370, 560, 860)
    skid = V.box(XF - 150, XF + 200, -620, 620, 470, 520)
    rear_trim = V.box(XR - 200, XR + 160, -760, 760, 470, 540)
    return V.build_vehicle(SPEC, glass_cut, dark=[back, grille, skid, rear_trim] + head_h, lamps_r=tail,
                           lamps_f=head, axles=(AX_F, AX_R), y_out=W / 2 - 18, tire=(TR, TW, RIM), gap=40,
                           extra_body=V.mirrors(1080, 925, 1180, 105, 48, 66), spokes=6, style="spoke")


parts = build() if __name__ != "__nobuild__" else {}
COLORS = {k: V.COLORS[k] for k in parts}
