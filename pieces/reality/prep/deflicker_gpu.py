"""Temporal deflicker of the diffusion-enhanced frames (GPU). Difix cleans every frame on its own, so details flicker.
The raw splat plates are temporally stable: RAFT optical flow (torchvision raft_large) between consecutive plates carries
the previous cleaned frame onto the current one; blended where forward/backward flow agree (occlusions keep the current
frame). Run forward and backward and average, so the result does not lag. A final per-frame colour match to a smoothed
mean removes low-frequency brightness pumping.
usage: python deflicker_gpu.py PLATES_DIR ENH_DIR OUT_DIR [--alpha 0.8]
"""
import argparse, glob, os, time
import numpy as np, torch, torch.nn.functional as F
from PIL import Image
from torchvision.models.optical_flow import raft_large, Raft_Large_Weights
ap = argparse.ArgumentParser(); ap.add_argument('plates'); ap.add_argument('enh'); ap.add_argument('out')
ap.add_argument('--alpha', type=float, default=0.8); A = ap.parse_args(); os.makedirs(A.out, exist_ok=True)
dev = 'cuda'; t0 = time.time()
names = sorted(os.path.basename(f) for f in glob.glob(f'{A.enh}/*.jpg'))
load = lambda p: torch.from_numpy(np.asarray(Image.open(p).convert('RGB'))).permute(2, 0, 1).float().div(255)
P = torch.stack([load(f'{A.plates}/{n}') for n in names]).half().to(dev)   # (T,3,H,W), half to fit 600 frames
E = torch.stack([load(f'{A.enh}/{n}') for n in names]).half().to(dev)
T, _, H, W = P.shape; print('frames', T, H, W, f'{time.time() - t0:.0f}s', flush=True)
model = raft_large(weights=Raft_Large_Weights.DEFAULT).to(dev).eval()
H8, W8 = (H // 8) * 8, (W // 8) * 8
def flow(a, b):   # flow from a to b, (2,H,W) in pixels
    with torch.no_grad():
        x = F.interpolate(torch.stack([a, b]).float() * 2 - 1, size=(H8, W8), mode='bilinear', align_corners=False)
        f = model(x[:1], x[1:], num_flow_updates=12)[-1][0]
        f = F.interpolate(f[None], size=(H, W), mode='bilinear', align_corners=False)[0]
        f[0] *= W / W8; f[1] *= H / H8
    return f.half()
gy, gx = torch.meshgrid(torch.arange(H, device=dev), torch.arange(W, device=dev), indexing='ij')
def warp(img, f):   # sample img at (x + f): brings img (frame b) onto frame a when f is the flow a->b
    img, f = img.float(), f.float()
    gxn = (gx + f[0]) / (W - 1) * 2 - 1; gyn = (gy + f[1]) / (H - 1) * 2 - 1
    return F.grid_sample(img[None], torch.stack([gxn, gyn], -1)[None], mode='bilinear', padding_mode='border', align_corners=True)[0]
def consistent(fab, fba):   # forward-backward check -> weight in [0,1]
    back = warp(fba, fab); err = (fab.float() + back).norm(dim=0)
    return torch.clamp(1.5 - err, 0, 1)
FW, BW = [None] * T, [None] * T       # FW[t] = flow t -> t-1 ; BW[t] = flow t -> t+1
for t in range(T):
    if t > 0: FW[t] = flow(P[t], P[t - 1])
    if t < T - 1: BW[t] = flow(P[t], P[t + 1])
    if t % 100 == 0: print('flow', t, f'{time.time() - t0:.0f}s', flush=True)
def recursive(order):
    out = E.clone()
    for k in range(1, T):
        t = order[k]; s = order[k - 1]
        f_ts = FW[t] if s == t - 1 else BW[t]          # flow current -> previous-in-order
        f_st = BW[s] if s == t - 1 else FW[s]
        w = consistent(f_ts, f_st) * A.alpha
        out[t] = (w * warp(out[s], f_ts) + (1 - w) * E[t].float()).half()
    return out
fwd = recursive(list(range(T))); bwd = recursive(list(range(T - 1, -1, -1)))
R = 0.5 * (fwd.float() + bwd.float()); del fwd, bwd
# low-frequency colour stability: match each frame's mean to a temporally smoothed mean
m = R.mean(dim=(2, 3)); k = torch.ones(1, 1, 15, device=dev) / 15
ms = F.conv1d(F.pad(m.T[:, None], (7, 7), mode='replicate'), k)[:, 0].T
R = (R * (ms / m.clamp(min=1e-3))[:, :, None, None]).clamp(0, 1)
for n, img in zip(names, R):
    Image.fromarray((img.permute(1, 2, 0).cpu().numpy() * 255).round().astype(np.uint8)).save(f'{A.out}/{n}', quality=94)
print('done', T, f'{time.time() - t0:.0f}s')
