"""3D Gaussian Splatting training for the drive (GPU, gsplat). The loop vogel describes: render the splats from each
real camera, compare with the photo, nudge them, repeat; densify where the error stays high, prune what is transparent.

Inputs (gs_package.py): images/, masks/, cameras.json, points.npy in --data. Outputs to --out:
  world_gs.bin   N x 32 bytes: f32 x,y,z | u8 r,g,b,a | f16 cov xx,xy,xz,yy,yz,zz | f16 pad (the piece's splat format v2)
  splats.ply     standard 3DGS ply (for any viewer)
  log.txt, previews/*.jpg (held-out renders next to the photos)
usage (GPU): python gs_train.py --data /data --out /out --iters 15000
"""
import argparse, json, math, os, random, time
import numpy as np, torch, torch.nn.functional as F
from PIL import Image

ap = argparse.ArgumentParser()
ap.add_argument('--data', default='/data'); ap.add_argument('--out', default='/out')
ap.add_argument('--iters', type=int, default=15000); ap.add_argument('--sh', type=int, default=1)
ap.add_argument('--scale', type=float, default=0.5, help='image downscale for training')
ap.add_argument('--max-init', type=int, default=900000)
ap.add_argument('--bg', default='0.62,0.67,0.66')
ap.add_argument('--depth-w', type=float, default=0.1)
ap.add_argument('--aniso-w', type=float, default=0.01)
ap.add_argument('--pose-opt', type=int, default=1)
ap.add_argument('--ego-prune', type=int, default=1)
ap.add_argument('--cams', default='cameras.json'); ap.add_argument('--points', default='points.npy')
ap.add_argument('--extra-points', default='', help='more initial points, e.g. points_sfm.npy (appended)')
ap.add_argument('--pose-lr', type=float, default=1.0, help='multiplier on the pose-refinement learning rates')
ap.add_argument('--opac-w', type=float, default=0.0); ap.add_argument('--max-scale', type=float, default=0.0)
A = ap.parse_args()
os.makedirs(A.out, exist_ok=True); os.makedirs(f'{A.out}/previews', exist_ok=True)
LOG = open(f'{A.out}/log.txt', 'a')
def log(*a):
    s = ' '.join(str(x) for x in a); print(s, flush=True); LOG.write(s + '\n'); LOG.flush()

from gsplat import rasterization
from gsplat.strategy import DefaultStrategy
dev = 'cuda'
torch.manual_seed(0); random.seed(0); np.random.seed(0)

meta = json.load(open(f'{A.data}/{A.cams}'))
IM = meta['images']
held = set(range(7, len(IM), 53))                                # held-out views for an honest score
train_ids = [i for i in range(len(IM)) if i not in held]
w0, h0 = IM[0]['width'], IM[0]['height']
TW, TH = int(w0 * A.scale), int(h0 * A.scale)

def load(i):
    e = IM[i]
    img = Image.open(f"{A.data}/{e['file']}").convert('RGB').resize((TW, TH), Image.BILINEAR)
    m = Image.open(f"{A.data}/{e['mask']}").convert('L').resize((TW, TH), Image.NEAREST)
    return torch.from_numpy(np.asarray(img).copy()), torch.from_numpy(np.asarray(m) > 127)
log('loading', len(IM), 'images at', TW, 'x', TH)
t0 = time.time()
GT = [load(i) for i in range(len(IM))]
GT_img = torch.stack([g[0] for g in GT]).to(dev); GT_mask = torch.stack([g[1] for g in GT]).to(dev)   # uint8 / bool on the GPU
del GT
log('loaded in', round(time.time() - t0, 1), 's')
Ks = torch.tensor([e['K'] for e in IM], dtype=torch.float32, device=dev); Ks[:, :2] *= A.scale
# inverse-depth targets (half res) when packaged: [inv, conf]
DEP = None
if A.depth_w > 0 and IM[0].get('depth'):
    DEP = torch.stack([torch.from_numpy(np.load(f"{A.data}/{e['depth']}").astype(np.float16)) if e.get('depth') else torch.zeros(2, h0 // 2, w0 // 2, dtype=torch.float16) for e in IM]).to(dev)
    log('depth targets', tuple(DEP.shape))
VM = torch.tensor([e['w2c'] for e in IM], dtype=torch.float32, device=dev)
CAMID = torch.tensor([e['cam_id'] for e in IM], device=dev)
KFID = torch.tensor([e['kf'] for e in IM], device=dev); NKF = int(KFID.max()) + 1
# ---- joint pose refinement: a rig correction per camera (calibration) and a world correction per keyframe (trajectory)
def skew(v):
    z = torch.zeros_like(v[0]); return torch.stack([torch.stack([z, -v[2], v[1]]), torch.stack([v[2], z, -v[0]]), torch.stack([-v[1], v[0], z])])
def se3(v):
    w, t = v[:3], v[3:]; th = w.norm().clamp(min=1e-9); K = skew(w / th)
    R = torch.eye(3, device=dev) + torch.sin(th) * K + (1 - torch.cos(th)) * (K @ K)
    T = torch.eye(4, device=dev); T[:3, :3] = R; T[:3, 3] = t; return T
cam_d = torch.nn.Parameter(torch.zeros(6, 6, device=dev)); kf_d = torch.nn.Parameter(torch.zeros(NKF, 6, device=dev))
pose_opt = torch.optim.Adam([{'params': [cam_d], 'lr': 1e-4 * A.pose_lr}, {'params': [kf_d], 'lr': 3e-4 * A.pose_lr}])
def viewmat(i):
    if not A.pose_opt: return VM[i]
    return se3(cam_d[CAMID[i]]) @ VM[i] @ se3(kf_d[KFID[i]])
# ego volume per keyframe: our own car fills it, so nothing may live there (kills near-camera floaters)
C2W = torch.linalg.inv(VM)
KFPOSE = {}
for e, c2w in zip(IM, C2W):
    if e['cam'] == 'front': KFPOSE[e['kf']] = e
def ego_prune_mask(means):
    bad = torch.zeros(len(means), dtype=torch.bool, device=dev)
    for k, e in KFPOSE.items():
        c2w = torch.linalg.inv(torch.tensor(e['w2c'], device=dev))
        # front camera sits at car (0, 1.48, -0.45); car axes from the camera axes (x right, -y up, z forward)
        right, up, fwd = c2w[:3, 0], -c2w[:3, 1], c2w[:3, 2]
        o = c2w[:3, 3] - up * 1.48 + fwd * 0.45
        d = means - o
        x, y, z = d @ right, d @ up, d @ fwd
        bad |= (x.abs() < 1.15) & (z > -5.0) & (z < 4.5) & (y > 0.25) & (y < 2.1)
    return bad

pts = np.load(f'{A.data}/{A.points}')
if pts.shape[1] < 8: pts = np.concatenate([pts, np.zeros((len(pts), 8 - pts.shape[1]), np.float32)], 1)
if len(pts) > A.max_init:
    # keep every non-road point, subsample the (dense) road sheet
    road_i = np.where(pts[:, 7] > 0.5)[0]; obj_i = np.where(pts[:, 7] <= 0.5)[0]
    keep_r = np.random.choice(road_i, max(0, min(len(road_i), A.max_init - len(obj_i))), replace=False)
    pts = pts[np.concatenate([obj_i, keep_r])]
if A.extra_points and os.path.exists(f'{A.data}/{A.extra_points}'):
    ex = np.load(f'{A.data}/{A.extra_points}'); log('extra points', len(ex)); pts = np.concatenate([pts, ex.astype(np.float32)], 0)
N = len(pts)
centres = torch.linalg.inv(VM)[:, :3, 3]
scene_scale = float((centres - centres.mean(0)).norm(dim=1).max()) * 0.1 + 10
log('init points', N, 'scene_scale', round(scene_scale, 2))
means = torch.tensor(pts[:, :3], device=dev)
rgb = torch.tensor(pts[:, 3:6], device=dev).clamp(0.02, 0.98)
size = torch.tensor(pts[:, 6], device=dev).clamp(0.02, 0.6)
C0 = 0.28209479177387814
params = torch.nn.ParameterDict({
    'means': torch.nn.Parameter(means),
    'scales': torch.nn.Parameter(torch.log(size)[:, None].repeat(1, 3)),  # road y-scale is pinned in the loop
    'quats': torch.nn.Parameter(torch.cat([torch.ones(N, 1), torch.zeros(N, 3)], 1).to(dev)),
    'opacities': torch.nn.Parameter(torch.logit(torch.full((N,), 0.6, device=dev))),
    'sh0': torch.nn.Parameter(((rgb - 0.5) / C0)[:, None, :]),
    'shN': torch.nn.Parameter(torch.zeros(N, (A.sh + 1) ** 2 - 1, 3, device=dev)),
    # road flag (frozen): densification copies/splits/prunes it with everything else
    'road': torch.nn.Parameter(torch.tensor(pts[:, 7] if pts.shape[1] > 7 else np.zeros(N), device=dev, dtype=torch.float32)),   # trainable for the strategy's bookkeeping, lr 0, never in the loss
})
lrs = {'road': 0.0, 'means': 1.6e-4 * scene_scale, 'scales': 5e-3, 'quats': 1e-3, 'opacities': 5e-2, 'sh0': 2.5e-3, 'shN': 2.5e-3 / 20}
optim = {k: torch.optim.Adam([{'params': params[k], 'lr': lrs[k], 'name': k}], eps=1e-15) for k in params}
# per-image exposure / white balance (the six cameras disagree): 3x3 + bias, starts at identity
app = torch.nn.Parameter(torch.zeros(len(IM), 12, device=dev))
app_opt = torch.optim.Adam([app], lr=1e-3)
strategy = DefaultStrategy(refine_start_iter=500, refine_stop_iter=int(A.iters * 0.75), refine_every=100, reset_every=3000,
                           grow_grad2d=0.0002, absgrad=False, verbose=False)
strategy.check_sanity(params, optim)
log('road gaussians', int((params['road'] > 0.5).sum()))
state = strategy.initialize_state(scene_scale=scene_scale)
bg = torch.tensor([float(v) for v in A.bg.split(',')], device=dev)
mean_decay = 0.01 ** (1 / A.iters)

def ssim(x, y, m):
    # x,y: (1,3,H,W); simple gaussian SSIM, masked mean
    g = torch.exp(-((torch.arange(11, device=dev) - 5) ** 2) / (2 * 1.5 ** 2)); g = (g / g.sum())
    win = (g[:, None] * g[None, :])[None, None].repeat(3, 1, 1, 1)
    f = lambda z: F.conv2d(z, win, padding=5, groups=3)
    mx, my = f(x), f(y); sxx = f(x * x) - mx ** 2; syy = f(y * y) - my ** 2; sxy = f(x * y) - mx * my
    s = ((2 * mx * my + 1e-4) * (2 * sxy + 9e-4)) / ((mx ** 2 + my ** 2 + 1e-4) * (sxx + syy + 9e-4))
    return (s.mean(1) * m).sum() / m.sum().clamp(min=1)

def render(i, sh_deg):
    p = params
    out, alpha, info = rasterization(p['means'], F.normalize(p['quats'], dim=-1), torch.exp(p['scales']), torch.sigmoid(p['opacities']),
                                     torch.cat([p['sh0'], p['shN']], 1), viewmat(i)[None], Ks[i:i + 1], TW, TH, sh_degree=sh_deg,
                                     near_plane=0.3, far_plane=300.0, backgrounds=bg[None], packed=False, render_mode='RGB+ED')
    return out[0, ..., :3], info, out[0, ..., 3]

def apply_app(img, i):
    a = app[i]; M = torch.eye(3, device=dev) + a[:9].view(3, 3); return (img @ M.T + a[9:]).clamp(0, 1)

t0 = time.time()
for step in range(A.iters):
    i = random.choice(train_ids)
    sh_deg = min(A.sh, step // 1000)
    img, info, dep = render(i, sh_deg)
    pred = apply_app(img, i)
    gt, m = GT_img[i].float() / 255, GT_mask[i].float()
    l1 = ((pred - gt).abs().mean(-1) * m).sum() / m.sum().clamp(min=1)
    s = ssim(pred.permute(2, 0, 1)[None], gt.permute(2, 0, 1)[None], m[None])
    loss = 0.8 * l1 + 0.2 * (1 - s) + 1e-3 * app.pow(2).mean()
    if DEP is not None:
        tgt = DEP[i].float(); dh, dw = tgt.shape[1:]
        d_small = F.interpolate(dep[None, None], size=(dh, dw), mode='bilinear', align_corners=False)[0, 0]
        inv_pred = 1 / d_small.clamp(min=0.3)
        w = tgt[1] * (tgt[0] > 0)
        dl = ((inv_pred - tgt[0]).abs() / tgt[0].clamp(min=1e-3) * w).sum() / w.sum().clamp(min=1)   # relative inverse-depth error
        loss = loss + A.depth_w * dl * max(0.2, 1 - step / A.iters)
    if A.opac_w > 0: loss = loss + A.opac_w * torch.sigmoid(params['opacities']).mean()          # sparse: no fog
    if A.max_scale > 0: loss = loss + 0.1 * F.relu(torch.exp(params['scales']).max(1).values - A.max_scale).mean()
    if A.aniso_w > 0:
        sc = torch.exp(params['scales']); ratio = sc.max(1).values / sc.min(1).values.clamp(min=1e-6)
        loss = loss + A.aniso_w * F.relu(ratio - 8).mean()
    strategy.step_pre_backward(params, optim, state, step, info)
    loss.backward()
    strategy.step_post_backward(params, optim, state, step, info, packed=False)
    for o in optim.values(): o.step(); o.zero_grad(set_to_none=True)
    app_opt.step(); app_opt.zero_grad(set_to_none=True)
    with torch.no_grad():     # the road is a flat sheet on the ground (vogel: "rebuilding the road")
        r = params['road'] > 0.5
        if r.any():
            params['means'].data[r, 1] = params['means'].data[r, 1].clamp(-0.05, 0.05)
            params['scales'].data[r, 1] = math.log(0.004)
            params['quats'].data[r] = torch.tensor([1.0, 0, 0, 0], device=dev)
    if A.pose_opt and step > 500: pose_opt.step()
    pose_opt.zero_grad(set_to_none=True)
    if A.ego_prune and step % 500 == 250 and step < A.iters * 0.9:
        with torch.no_grad():
            bad = ego_prune_mask(params['means'])
            if bad.any(): params['opacities'].data[bad] = torch.logit(torch.tensor(0.005, device=dev))   # transparent -> pruned by the strategy
    for g in optim['means'].param_groups: g['lr'] *= mean_decay
    if step % 500 == 0 or step == A.iters - 1:
        log(f'step {step} loss {loss.item():.4f} l1 {l1.item():.4f} n {len(params["means"])} {time.time() - t0:.0f}s')

# held-out score + previews
with torch.no_grad():
    ps = []
    for j, i in enumerate(sorted(held)):
        img, _, _ = render(i, A.sh); gt, m = GT_img[i].float() / 255, GT_mask[i].float()
        mse = (((img - gt) ** 2).mean(-1) * m).sum() / m.sum(); ps.append(float(-10 * torch.log10(mse)))
        if j < 12:
            both = torch.cat([img, gt], 1).clamp(0, 1).mul(255).byte().cpu().numpy()
            Image.fromarray(both).save(f'{A.out}/previews/{i:04d}_{IM[i]["cam"]}.jpg', quality=88)
    log('held-out PSNR (masked)', round(float(np.mean(ps)), 2), 'over', len(ps), 'views')

    # export: drop the nearly transparent, write the piece format + a standard ply
    op = torch.sigmoid(params['opacities']); keep = (op > 0.04) & (~ego_prune_mask(params['means']) if A.ego_prune else torch.ones_like(op, dtype=torch.bool))
    json.dump(dict(cam=cam_d.detach().cpu().tolist(), kf=kf_d.detach().cpu().tolist()), open(f'{A.out}/pose_corrections.json', 'w'))
    log('pose corrections: cam rot(deg)', [round(float(v[:3].norm()) * 57.3, 2) for v in cam_d], 'kf trans max', round(float(kf_d[:, 3:].norm(dim=1).max()), 3))
    mu = params['means'][keep]; sc = torch.exp(params['scales'][keep]); q = F.normalize(params['quats'][keep], dim=-1)
    w, x, y, z = q.unbind(-1)
    R = torch.stack([1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y),
                     2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x),
                     2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)], -1).view(-1, 3, 3)
    Sg = R @ torch.diag_embed(sc ** 2) @ R.transpose(1, 2)
    col = (params['sh0'][keep][:, 0] * C0 + 0.5).clamp(0, 1)
    n = int(keep.sum())
    rec = np.zeros(n, dtype=[('p', '<f4', 3), ('c', 'u1', 4), ('cov', '<f2', 6), ('pad', '<f2', 2)])
    rec['p'] = mu.cpu().numpy()
    rec['c'][:, :3] = (col * 255).round().byte().cpu().numpy(); rec['c'][:, 3] = (op[keep] * 255).round().byte().cpu().numpy()
    rec['cov'] = torch.stack([Sg[:, 0, 0], Sg[:, 0, 1], Sg[:, 0, 2], Sg[:, 1, 1], Sg[:, 1, 2], Sg[:, 2, 2]], 1).clamp(-6e4, 6e4).cpu().numpy().astype(np.float16)
    rec.tofile(f'{A.out}/world_gs.bin')
    # ply
    from io import BytesIO
    P = params
    cols = [mu, torch.zeros_like(mu), P['sh0'][keep][:, 0], P['shN'][keep].transpose(1, 2).reshape(n, -1),
            P['opacities'][keep][:, None], P['scales'][keep], q]
    arr = torch.cat(cols, 1).cpu().numpy().astype(np.float32)
    names = ['x', 'y', 'z', 'nx', 'ny', 'nz', 'f_dc_0', 'f_dc_1', 'f_dc_2'] + [f'f_rest_{k}' for k in range(arr.shape[1] - 9 - 8)] + ['opacity', 'scale_0', 'scale_1', 'scale_2', 'rot_0', 'rot_1', 'rot_2', 'rot_3']
    with open(f'{A.out}/splats.ply', 'wb') as fh:
        fh.write(('ply\nformat binary_little_endian 1.0\nelement vertex %d\n' % n + ''.join(f'property float {nm}\n' for nm in names) + 'end_header\n').encode())
        fh.write(arr.tobytes())
    log('exported', n, 'gaussians')
log('done', round(time.time() - t0), 's')
