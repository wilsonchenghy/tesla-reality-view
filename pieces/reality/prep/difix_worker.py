"""One Difix worker (one GPU): python difix_worker.py SRC DST REF_DIR START STEP   -> cleans frames START, START+STEP, ..."""
import os, sys, glob, torch
from PIL import Image
sys.path.insert(0, '/tmp/Difix3D/src')
from pipeline_difix import DifixPipeline
src, dst, ref, start, step = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4]), int(sys.argv[5])
os.makedirs(dst, exist_ok=True)
pipe = DifixPipeline.from_pretrained('nvidia/difix_ref', trust_remote_code=True).to('cuda'); pipe.set_progress_bar_config(disable=True)
for f in sorted(glob.glob(f'{src}/*.jpg'))[start::step]:
    n = os.path.basename(f); img = Image.open(f).convert('RGB'); size = img.size
    r = Image.open(f'{ref}/{n}').convert('RGB').resize((1024, 728), Image.LANCZOS)
    with torch.no_grad():
        out = pipe(prompt='remove degradation', image=img.resize((1024, 728), Image.LANCZOS), ref_image=r,
                   num_inference_steps=1, timesteps=[199], guidance_scale=0.0).images[0]
    out.resize(size, Image.LANCZOS).save(f'{dst}/{n}', quality=94)
