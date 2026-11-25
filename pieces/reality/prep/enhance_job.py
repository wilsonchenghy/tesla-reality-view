"""Diffusion enhancement of the splat-world plates (the 'last 10%'): NVIDIA Difix3D+ (nvidia/difix_ref, single step),
each chase-view plate cleaned with the real front-camera frame of the same instant as reference.
Runs on an HF GPU job: python enhance_job.py IN_DIR OUT_DIR  (IN_DIR has plate/NNNN.jpg and ref/NNNN.jpg)
"""
import os, sys, time, glob
import torch
from PIL import Image
sys.path.insert(0, '/tmp/Difix3D/src')
from pipeline_difix import DifixPipeline
IN, OUT = sys.argv[1], sys.argv[2]; os.makedirs(OUT, exist_ok=True)
pipe = DifixPipeline.from_pretrained('nvidia/difix_ref', trust_remote_code=True).to('cuda')
pipe.set_progress_bar_config(disable=True)
fs = sorted(glob.glob(f'{IN}/plate/*.jpg'))
W, H = 1024, 728              # multiple of 8, the pane's aspect (1408 x 1000)
t0 = time.time()
for k, f in enumerate(fs):
    name = os.path.basename(f)
    img = Image.open(f).convert('RGB'); size = img.size
    ref = Image.open(f'{IN}/ref/{name}').convert('RGB').resize((W, H), Image.LANCZOS)
    with torch.no_grad():
        out = pipe(prompt='remove degradation', image=img.resize((W, H), Image.LANCZOS), ref_image=ref,
                   num_inference_steps=1, timesteps=[199], guidance_scale=0.0).images[0]
    out.resize(size, Image.LANCZOS).save(f'{OUT}/{name}', quality=94)
    if k % 50 == 0: print(k, len(fs), f'{time.time() - t0:.0f}s', flush=True)
print('done', len(fs), f'{time.time() - t0:.0f}s')
