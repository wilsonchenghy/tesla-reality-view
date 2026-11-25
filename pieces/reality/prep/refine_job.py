"""Difix3D+ style refinement, all on one GPU (the 'make the 3D world itself sharp' step).
 1. load the trained world (splats.ply) + the sharp road layer (road_gs.bin, fixed), drop the trained road under it
 2. render the chase-camera path (chase_cams.json from the piece) with gsplat -> plates
 3. Difix (nvidia/difix_ref) cleans the plates, real front-camera frame as reference
 4. fine-tune the world on the real photos (pack, cameras) + the cleaned chase views (distillation: sharp detail moves
    into the 3D gaussians, so it cannot flicker or seam)
 5. render the chase path again, light Difix pass, RAFT deflicker -> OUT/frames/NNNN.jpg + OUT/world_gs.bin
usage: python refine_job.py --data DIR (images masks cameras + chase_cams.json + ref/) --ply splats.ply --road road_gs.bin --out OUT
"""
import argparse, json, math, os, sys, time, glob
import numpy as np, torch, torch.nn.functional as F
from PIL import Image
ap = argparse.ArgumentParser()
ap.add_argument('--data', required=True); ap.add_argument('--cams', default='cameras_rig3.json')
ap.add_argument('--ply', required=True); ap.add_argument('--road', required=True); ap.add_argument('--out', required=True)
ap.add_argument('--iters', type=int, default=8000); ap.add_argument('--chase-w', type=float, default=0.5)
ap.add_argument('--bg', default='0.62,0.67,0.66'); ap.add_argument('--real-scale', type=float, default=0.5)
A = ap.parse_args(); os.makedirs(f'{A.out}/frames', exist_ok=True); os.makedirs(f'{A.out}/plates0', exist_ok=True)
dev = 'cuda'; t0 = time.time()
def log(*a): print(f'[{time.time() - t0:.0f}s]', *a, flush=True)
from gsplat import rasterization

# ---- 1. world + road
def read_ply(p):
    with open(p, 'rb') as f:
        hdr = b''
        while not hdr.endswith(b'end_header\n'): hdr += f.readline()
        names = [l.split()[-1].decode() for l in hdr.split(b'\n') if l.startswith(b'property')]
        n = int([l for l in hdr.split(b'\n') if l.startswith(b'element vertex')][0].split()[-1])
        a = np.frombuffer(f.read(n * 4 * len(names)), np.float32).reshape(n, len(names))
    return {k: a[:, i] for i, k in enumerate(names)}
P = read_ply(A.ply)
rest = sorted([k for k in P if k.startswith('f_rest_')], key=lambda k: int(k.split('_')[-1]))
nsh = len(rest) // 3; deg = int(round(math.sqrt(nsh + 1))) - 1
means = torch.tensor(np.stack([P['x'], P['y'], P['z']], 1), device=dev)
dt = np.dtype([('p', '<f4', 3), ('c', 'u1', 4), ('cov', '<f2', 6), ('pad', '<f2', 2)])
road = np.fromfile(A.road, dtype=dt); cell = 0.05
# drop trained gaussians low over road cells (the road layer owns the ground)
occ = set(map(tuple, np.floor(road['p'][:, [0, 2]] / cell).astype(np.int64).tolist()))
mk = np.floor(np.stack([P['x'], P['z']], 1) / cell).astype(np.int64)
onroad = np.array([tuple(k) in occ for k in mk.tolist()]) & (P['y'] < 0.35)
keep = torch.tensor(~onroad, device=dev)
log('world', len(P['x']), 'gaussians; under the road layer', int(onroad.sum()), '; road', len(road), 'sh degree', deg)
params = torch.nn.ParameterDict({
    'means': torch.nn.Parameter(means[keep]),
    'scales': torch.nn.Parameter(torch.tensor(np.stack([P['scale_0'], P['scale_1'], P['scale_2']], 1), device=dev)[keep]),
    'quats': torch.nn.Parameter(torch.tensor(np.stack([P['rot_0'], P['rot_1'], P['rot_2'], P['rot_3']], 1), device=dev)[keep]),
    'opacities': torch.nn.Parameter(torch.tensor(P['opacity'], device=dev)[keep]),
    'sh0': torch.nn.Parameter(torch.tensor(np.stack([P['f_dc_0'], P['f_dc_1'], P['f_dc_2']], 1), device=dev)[keep][:, None]),
    'shN': torch.nn.Parameter(torch.tensor(np.stack([P[k] for k in rest], 1), device=dev).view(-1, 3, nsh).transpose(1, 2)[keep]),
})
C0 = 0.28209479177387814
rm = torch.tensor(road['p'], device=dev)
rq = torch.tensor([1.0, 0, 0, 0], device=dev).repeat(len(road), 1)
rs = torch.tensor([cell * 0.62, cell * 0.03, cell * 0.62], device=dev).repeat(len(road), 1)
rcol = torch.tensor(road['c'][:, :3], device=dev).float() / 255
rsh0 = ((rcol - 0.5) / C0)[:, None]; rop = torch.full((len(road),), 0.999, device=dev)
bg = torch.tensor([float(v) for v in A.bg.split(',')], device=dev)

def render(viewmat, K, w, h, with_road=True):
    p = params
    m = torch.cat([p['means'], rm]) if with_road else p['means']
    q = torch.cat([F.normalize(p['quats'], dim=-1), rq]) if with_road else F.normalize(p['quats'], dim=-1)
    s = torch.cat([torch.exp(p['scales']), rs]) if with_road else torch.exp(p['scales'])
    o = torch.cat([torch.sigmoid(p['opacities']), rop]) if with_road else torch.sigmoid(p['opacities'])
    sh = torch.cat([p['sh0'], p['shN']], 1)
    if with_road: sh = torch.cat([sh, torch.cat([rsh0, torch.zeros(len(road), sh.shape[1] - 1, 3, device=dev)], 1)])
    img, _, info = rasterization(m, q, s, o, sh, viewmat[None], K[None], w, h, sh_degree=deg, near_plane=0.3, far_plane=400.0,
                                 backgrounds=bg[None], packed=False)
    return img[0].clamp(0, 1), info

# ---- chase cameras (three.js) -> OpenCV view matrices
CC = json.load(open(f'{A.data}/chase_cams.json'))
def chase_mats(c, scale=1.0):
    x, y, z, w = c['q']
    R = np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                  [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                  [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])
    Rcv = R @ np.diag([1, -1, -1]); c2w = np.eye(4); c2w[:3, :3] = Rcv; c2w[:3, 3] = c['p']
    W, H = int(c['w'] * scale), int(c['h'] * scale); fy = H / 2 / math.tan(math.radians(c['fov']) / 2)
    K = np.array([[fy, 0, W / 2], [0, fy, H / 2], [0, 0, 1]])
    return torch.tensor(np.linalg.inv(c2w), device=dev, dtype=torch.float32), torch.tensor(K, device=dev, dtype=torch.float32), W, H
def save(t, p): Image.fromarray((t.detach().cpu().numpy() * 255).round().astype(np.uint8)).save(p, quality=94)

def render_path(folder):
    os.makedirs(folder, exist_ok=True)
    with torch.no_grad():
        for i, c in enumerate(CC):
            V, K, W, H = chase_mats(c); img, _ = render(V, K, W, H); save(img, f'{folder}/{i + 1:04d}.jpg')
    log('rendered', len(CC), 'chase views ->', folder)
render_path(f'{A.out}/plates0')

# ---- 3. Difix
def difix_folder(src, dst):
    """Difix across every GPU in parallel (one worker process per GPU, frames interleaved)."""
    import subprocess
    n = torch.cuda.device_count(); os.makedirs(dst, exist_ok=True)
    procs = [subprocess.Popen([sys.executable, '-u', f'{A.data}/difix_worker.py', src, dst, f'{A.data}/ref', str(i), str(n)],
                              env=dict(os.environ, CUDA_VISIBLE_DEVICES=str(i))) for i in range(n)]
    for p in procs: p.wait()
    got = len(os.listdir(dst)); log('difix on', n, 'GPUs', src, '->', dst, got, 'frames')
    if got < len(os.listdir(src)): raise SystemExit(f'difix produced {got} frames, expected {len(os.listdir(src))}')
difix_folder(f'{A.out}/plates0', f'{A.out}/clean0')

# ---- 4. distillation fine-tune: real photos + cleaned chase views
meta = json.load(open(f'{A.data}/{A.cams}')); IM = meta['images']
s_ = A.real_scale; w0, h0 = IM[0]['width'], IM[0]['height']; TW, TH = int(w0 * s_), int(h0 * s_)
ld = lambda p, sz: torch.from_numpy(np.asarray(Image.open(p).convert('RGB').resize(sz, Image.BILINEAR)).copy())
RG = torch.stack([ld(f"{A.data}/{e['file']}", (TW, TH)) for e in IM]).to(dev)
RM = torch.stack([torch.from_numpy(np.asarray(Image.open(f"{A.data}/{e['mask']}").convert('L').resize((TW, TH), Image.NEAREST)) > 127) for e in IM]).to(dev)
RK = torch.tensor([e['K'] for e in IM], device=dev, dtype=torch.float32); RK[:, :2] *= s_
RV = torch.tensor([e['w2c'] for e in IM], device=dev, dtype=torch.float32)
cs = 0.5; CV = [chase_mats(c, cs) for c in CC]
CG = torch.stack([ld(f"{A.out}/clean0/{i + 1:04d}.jpg", (CV[0][2], CV[0][3])) for i in range(len(CC))]).to(dev)
log('training data: real', len(IM), 'chase', len(CC))
lrs = {'means': 2e-5, 'scales': 2e-3, 'quats': 5e-4, 'opacities': 1e-2, 'sh0': 1.5e-3, 'shN': 1e-4}
opt = torch.optim.Adam([{'params': [params[k]], 'lr': lrs[k]} for k in params], eps=1e-15)
for step in range(A.iters):
    if np.random.rand() < 0.35:
        i = np.random.randint(len(CC)); V, K, W, H = CV[i]
        img, _ = render(V, K, W, H); gt = CG[i].float() / 255
        loss = A.chase_w * (img - gt).abs().mean()
    else:
        i = np.random.randint(len(IM)); img, _ = render(RV[i], RK[i], TW, TH)
        gt = RG[i].float() / 255; m = RM[i].float()
        loss = ((img - gt).abs().mean(-1) * m).sum() / m.sum().clamp(min=1)
    opt.zero_grad(set_to_none=True); loss.backward(); opt.step()
    if step % 1000 == 0: log('step', step, 'loss', round(loss.item(), 4))

torch.save({k: v.detach().cpu() for k, v in params.items()}, f'{A.out}/params.pt'); log('checkpoint saved')
# ---- 5. final render, light Difix, deflicker
render_path(f'{A.out}/plates1')
difix_folder(f'{A.out}/plates1', f'{A.out}/clean1')
import subprocess
subprocess.run([sys.executable, '-u', f'{A.data}/deflicker_gpu.py', f'{A.out}/plates1', f'{A.out}/clean1', f'{A.out}/frames'], check=True)
# export refined world (covariance format for the piece)
with torch.no_grad():
    p = params; op = torch.sigmoid(p['opacities']); k = op > 0.04
    q = F.normalize(p['quats'][k], dim=-1); w, x, y, z = q.unbind(-1)
    R = torch.stack([1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y), 2 * (x * y + w * z), 1 - 2 * (x * x + z * z),
                     2 * (y * z - w * x), 2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)], -1).view(-1, 3, 3)
    S = R @ torch.diag_embed(torch.exp(p['scales'][k]) ** 2) @ R.transpose(1, 2)
    rec = np.zeros(int(k.sum()), dtype=dt); rec['p'] = p['means'][k].cpu().numpy()
    rec['c'][:, :3] = ((p['sh0'][k][:, 0] * C0 + 0.5).clamp(0, 1) * 255).round().byte().cpu().numpy(); rec['c'][:, 3] = (op[k] * 255).round().byte().cpu().numpy()
    rec['cov'] = torch.stack([S[:, 0, 0], S[:, 0, 1], S[:, 0, 2], S[:, 1, 1], S[:, 1, 2], S[:, 2, 2]], 1).clamp(-6e4, 6e4).cpu().numpy().astype(np.float16)
    rec.tofile(f'{A.out}/world_gs.bin')
log('done')
