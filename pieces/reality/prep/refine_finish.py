"""Finish refine_job.py after its fine-tune (e.g. when a Difix pass ran out of GPU memory): Difix on plates1 -> clean1
(resumes), deflicker -> frames, export the refined world.  usage: refine_finish.py OUT_DIR DATA_DIR"""
import subprocess, sys
import numpy as np, torch, torch.nn.functional as F
import sys as _s; o = _s.argv[1]; dd = _s.argv[2]
subprocess.run([sys.executable, "-u", f"{dd}/difix_worker.py", f"{o}/plates1", f"{o}/clean1", f"{dd}/ref", "0", "1"], check=True)
subprocess.run([sys.executable, "-u", f"{dd}/deflicker_gpu.py", f"{o}/plates1", f"{o}/clean1", f"{o}/frames"], check=True)
dt = np.dtype([('p', '<f4', 3), ('c', 'u1', 4), ('cov', '<f2', 6), ('pad', '<f2', 2)]); C0 = 0.28209479177387814
with torch.no_grad():
    p = torch.load(f"{o}/params.pt"); op = torch.sigmoid(p['opacities']); k = op > 0.04
    q = F.normalize(p['quats'][k], dim=-1); w, x, y, z = q.unbind(-1)
    R = torch.stack([1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y), 2 * (x * y + w * z), 1 - 2 * (x * x + z * z),
                     2 * (y * z - w * x), 2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)], -1).view(-1, 3, 3)
    S = R @ torch.diag_embed(torch.exp(p['scales'][k]) ** 2) @ R.transpose(1, 2)
    rec = np.zeros(int(k.sum()), dtype=dt); rec['p'] = p['means'][k].numpy()
    rec['c'][:, :3] = ((p['sh0'][k][:, 0] * C0 + 0.5).clamp(0, 1) * 255).round().byte().numpy(); rec['c'][:, 3] = (op[k] * 255).round().byte().numpy()
    rec['cov'] = torch.stack([S[:, 0, 0], S[:, 0, 1], S[:, 0, 2], S[:, 1, 1], S[:, 1, 2], S[:, 2, 2]], 1).clamp(-6e4, 6e4).numpy().astype(np.float16)
    rec.tofile(f"{o}/world_gs.bin")
print("finished", int(k.sum()), "gaussians")
