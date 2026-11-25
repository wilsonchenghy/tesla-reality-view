# DESIGN SPEC: BOXTRUCK - a generic medium-duty box truck for background traffic (no badges, no livery).
# L 7200, W 2450 (box), H 3300, wheelbase 4300; a short-nose cab (W 2300) and a tall white cargo box with broken
# (R 45) edges on a dark frame; 22.5" wheels (tire 900), dual rear wheels, dark rear bumper with small lamps.
# World (harness, mm): x forward, y left, z up, ground z = 0, origin under the footprint centre.
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(globals().get("__file__", "/home/user/rv/pieces/reality/cad/boxtruck.py"))))
from build123d import Compound
import vlib as V

L, W, H, WB = 7200.0, 2450.0, 3300.0, 4300.0
XF, XR = L / 2, -L / 2
AX_F = XF - 1250.0
AX_R = AX_F - WB
TR, TW, RIM = 450.0, 250.0, 290.0
CAB_R = 1500.0                     # cab back
BOX_F, BOX_Z0 = 1420.0, 1080.0     # cargo box front, floor
CW = 2300.0                        # cab width

CAB = V.BodySpec(
    stations=[XF, 3480, 3300, 3050, 2850, 2600, 2200, 1800, CAB_R],
    zb=[(XF, 520), (3200, 470), (CAB_R, 470)],
    zs=[(XF, 1300), (3300, 1420), (2900, 1500), (CAB_R, 1520)],
    zt=[(XF, 1380), (3400, 1460), (3150, 1540), (3020, 1620), (2750, 2450), (2550, 2620), (2200, 2660),
        (CAB_R, 2660)],
    hw=[(XF, 1060), (3400, 1130), (3100, CW / 2), (CAB_R, CW / 2)],
    rw=[(XF, 1000), (3200, 1080), (2950, 1060), (2600, 1040), (CAB_R, 1040)],
    shape={"side": 0.95, "crown": 0.9, "sill": 0.35},
    nose_r=110.0, tail_r=50.0,
)
CAB.fillet_tail = True


def dlo():
    bot = [(x, CAB.zs(x) + 40) for x in (1800, 2400, 2950)]
    top = [(2900, CAB.zs(2900) + 60), (2720, 2400), (2600, 2520), (1800, 2520)]
    return bot + top


def build():
    ws = V.mirror_plan([(3100, 1060), (2900, 1045), (2700, 1030), (2580, 1020)])
    glass_cut = V.prism_y(dlo(), r=60) + V.prism_z(ws, z0=1520)
    head_h = [V.box(XF - 300, XF + 200, 640, 1300, 1050, 1250), V.box(XF - 300, XF + 200, -1300, -640, 1050, 1250)]
    head = [V.box(XF - 300, XF + 200, 660, 1300, 1150, 1180), V.box(XF - 300, XF + 200, -1300, -660, 1150, 1180)]
    grille = V.box(XF - 150, XF + 200, -620, 620, 760, 1270)
    bumper = V.box(XF - 150, XF + 200, -1200, 1200, 520, 680)
    p = V.build_vehicle(CAB, glass_cut, dark=[grille, bumper] + head_h, lamps_f=head, axles=(AX_F,), y_out=CW / 2 - 25, tire=(TR, TW, RIM), gap=55,
                        extra_body=V.mirrors(2950, CW / 2 + 40, 2050, 70, 40, 160, 120), spokes=8,
                        style="spoke")
    # rear duals sit out at the box width
    tires, rims = [], []
    for s in (1, -1):
        for yo in (W / 2 - 30, W / 2 - 30 - TW - 22):
            t, r = V.wheel(AX_R, yo, s, R=TR, w=TW, rim_r=RIM, spokes=8, style="spoke")
            tires.append(t)
            if yo == W / 2 - 30:
                rims.append(r)
    front_t = list(p["tire"])                               # liners + front tires
    front_r = list(p["rim"])
    # the cargo box: broken edges (one radius), white
    cargo = V.box(XR, BOX_F, -W / 2, W / 2, BOX_Z0, H)
    cargo = cargo.fillet(45.0, cargo.edges())
    seam = V.box(XR - 5, XR + 6, -6, 6, BOX_Z0 + 120, H - 120)                      # rear door split line
    frame = V.box(XR + 150, BOX_F + 400, -480, 480, 640, BOX_Z0)
    rbump = V.box(XR + 10, XR + 160, -1150, 1150, 520, 660)
    sill = V.box(XR + 30, BOX_F - 30, -W / 2 + 40, W / 2 - 40, BOX_Z0 - 60, BOX_Z0)
    lamps = [V.box(XR + 2, XR + 12, 760, 1060, 545, 635), V.box(XR + 2, XR + 12, -1060, -760, 545, 635)]
    p["tire"] = Compound(front_t + tires + [frame, rbump, sill, seam])
    p["rim"] = Compound(front_r + rims)
    p["cargo"] = cargo
    p["light_rear"] = Compound(lamps)
    return p


parts = build() if __name__ != "__nobuild__" else {}
COLORS = {k: V.COLORS[k] for k in parts}
