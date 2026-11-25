#!/usr/bin/env python3
"""Measure a reference video (or any render, e.g. from Blender) so a style is learned from numbers.

  study.py <video> --out <dir>

Writes to <dir>: shots.png (one frame per shot, labelled), palette.png, energy.png, report.json and
bible.md (a style-bible skeleton pre-filled with the measurements). Prints a summary.
Measures: cuts and shot lengths, drawing rate (held frames: animated on 1s/2s/3s), motion energy
over time, palette (k-means) with shares, value and saturation ranges, tempo and loudness of the audio.
"""
import sys, os, json, argparse, subprocess
import numpy as np
from PIL import Image, ImageDraw
sys.path.insert(0, os.path.dirname(__file__))
from imgtools import font  # noqa: E402

def probe(path):
    r = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'stream=codec_type,width,height,r_frame_rate,duration:format=duration', '-of', 'json', path], capture_output=True, text=True)
    return json.loads(r.stdout)

def frames(path, fps, w):
    p = subprocess.Popen(['ffmpeg', '-v', 'error', '-i', path, '-vf', f'fps={fps},scale={w}:-2:flags=area', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'], stdout=subprocess.PIPE)
    return p

def kmeans(px, k=8, iters=12, seed=0):
    rng = np.random.default_rng(seed)
    c = px[rng.choice(len(px), k, replace=False)].astype(np.float32)
    for _ in range(iters):
        d = ((px[:, None, :] - c[None]) ** 2).sum(-1)
        lab = d.argmin(1)
        for j in range(k):
            m = px[lab == j]
            if len(m): c[j] = m.mean(0)
    d = ((px[:, None, :] - c[None]) ** 2).sum(-1); lab = d.argmin(1)
    share = np.bincount(lab, minlength=k) / len(px)
    o = np.argsort(-share)
    return c[o], share[o]

def main():
    ap = argparse.ArgumentParser(); ap.add_argument('video'); ap.add_argument('--out', required=True)
    ap.add_argument('--fps', type=float, default=0); ap.add_argument('--width', type=int, default=240)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    info = probe(a.video)
    vs = [s for s in info['streams'] if s['codec_type'] == 'video'][0]
    num, den = map(float, vs['r_frame_rate'].split('/'))
    src_fps = num / den if den else 24
    dur = float(info['format'].get('duration') or vs.get('duration') or 0)
    fps = a.fps or min(src_fps, 30)
    W = a.width
    H = int(round(int(vs['height']) * W / int(vs['width']) / 2) * 2)
    p = frames(a.video, fps, W)
    fsize = W * H * 3
    prev, diffs, held, thumbs, lums, sats, samples, corrs, pth = None, [], [], [], [], [], [], [], None
    rng = np.random.default_rng(1)
    i = 0
    while True:
        buf = p.stdout.read(fsize)
        if len(buf) < fsize: break
        f = np.frombuffer(buf, np.uint8).reshape(H, W, 3)
        ff = f.astype(np.float32)
        th = np.asarray(Image.fromarray(f).resize((24, 24), Image.BOX)).astype(np.float32).ravel(); th -= th.mean()
        if prev is not None:
            d = np.abs(ff - prev).mean()
            diffs.append(d); held.append(d < 0.35)
            corrs.append(float((th * pth).sum() / (np.sqrt((th * th).sum() * (pth * pth).sum()) + 1e-6)))
        prev, pth = ff, th
        mx, mn = ff.max(-1), ff.min(-1)
        lums.append(float((0.2126 * ff[..., 0] + 0.7152 * ff[..., 1] + 0.0722 * ff[..., 2]).mean() / 255))
        sats.append(float(np.where(mx > 0, (mx - mn) / np.maximum(mx, 1), 0).mean()))
        if i % max(1, int(fps / 4)) == 0:
            samples.append(f.reshape(-1, 3)[rng.choice(W * H, 400, replace=False)])
        thumbs.append(f)
        i += 1
    p.wait()
    n = len(thumbs)
    diffs = np.array(diffs) if diffs else np.zeros(1)
    # cuts: a spike well above the local median of frame differences
    cuts = []
    for k, d in enumerate(diffs):
        lo, hi = max(0, k - 6), min(len(diffs), k + 7)
        local = np.median(diffs[lo:k]) if k > lo else 0   # what came before: motion after a cut is normal
        # a cut jumps: big change right after a much smaller one (motion after a cut is fine). A wipe or
        # whip ramps up over several frames, so its change is never 4x the frame before.
        prev = diffs[k - 1] if k > 0 else 0
        # and the layout must be replaced (24x24 thumbnails decorrelate); motion keeps the layout.
        # Approximate by nature: springy type and full-frame wipes can still read as cuts. Check shots.png.
        if d > max(2.5, 4 * local + 1.5) and d > 4 * prev + 1.5 and corrs[k] < 0.7 and (not cuts or k + 1 - cuts[-1] > 2): cuts.append(k + 1)
    bounds = [0] + cuts + [n]
    shots = [(bounds[j] / fps, (bounds[j + 1] - bounds[j]) / fps) for j in range(len(bounds) - 1) if bounds[j + 1] > bounds[j]]
    lens = np.array([s[1] for s in shots])
    # drawing rate: fraction of frames identical to the previous one (only meaningful at source fps)
    hold_ratio = float(np.mean(held)) if held else 0
    # palette
    px = np.concatenate(samples).astype(np.float32) if samples else np.zeros((1, 3))
    cents, share = kmeans(px, k=min(8, len(px)))
    hexes = ['#%02X%02X%02X' % tuple(int(x) for x in c) for c in cents]
    # images: shots sheet
    cols = 6; tw = 240; th = int(tw * H / W)
    rows = (len(shots) + cols - 1) // cols
    sheet = Image.new('RGB', (cols * (tw + 6) + 6, max(1, rows) * (th + 26) + 6), (24, 24, 24)); dr = ImageDraw.Draw(sheet); fo = font(12)
    for j, (t0, ln) in enumerate(shots):
        mid = min(n - 1, int((t0 + ln / 2) * fps))
        x = 6 + (j % cols) * (tw + 6); y = 6 + (j // cols) * (th + 26)
        sheet.paste(Image.fromarray(thumbs[mid]).resize((tw, th)), (x, y + 20))
        dr.text((x + 2, y + 4), f'#{j + 1}  {t0:.2f}s  {ln:.2f}s', fill=(230, 230, 230), font=fo)
    sheet.save(os.path.join(a.out, 'shots.png'))
    pal = Image.new('RGB', (900, 140), (24, 24, 24)); dp = ImageDraw.Draw(pal); x = 0
    for h, s in zip(hexes, share):
        w = max(1, int(900 * s)); dp.rectangle([x, 0, x + w, 100], fill=h); dp.text((x + 4, 108), f'{h} {s * 100:.0f}%', fill=(220, 220, 220), font=fo); x += w
    pal.save(os.path.join(a.out, 'palette.png'))
    EW, EH = 1600, 300
    en = Image.new('RGB', (EW, EH), (16, 16, 16)); de = ImageDraw.Draw(en)
    top = max(1e-6, float(diffs.max()))
    de.line([(40 + (EW - 60) * (k + 1) / n, EH - 30 - (EH - 60) * d / top) for k, d in enumerate(diffs)], fill=(120, 200, 255), width=1)
    for c in cuts: de.line([(40 + (EW - 60) * c / n, 20), (40 + (EW - 60) * c / n, EH - 30)], fill=(230, 80, 60))
    de.text((44, 4), 'motion energy per analysed frame (red = detected cuts)', fill=(220, 220, 220), font=fo)
    en.save(os.path.join(a.out, 'energy.png'))
    # audio
    audio = None
    if any(s['codec_type'] == 'audio' for s in info['streams']):
        r = subprocess.run(['python3', os.path.join(os.path.dirname(__file__), 'audiotools.py'), 'song', a.video, '--json', os.path.join(a.out, 'beats.json')], capture_output=True, text=True)
        try: audio = json.load(open(os.path.join(a.out, 'beats.json'))); audio = {k: audio[k] for k in ('bpm', 'first_downbeat')}
        except Exception: audio = None
        l = subprocess.run(['ffmpeg', '-hide_banner', '-nostats', '-i', a.video, '-af', 'ebur128', '-f', 'null', '-'], capture_output=True, text=True).stderr
        import re
        m = re.findall(r'I:\s+(-?[\d.]+) LUFS', l)
        if audio is not None and m: audio['lufs'] = float(m[-1])
    rep = {
        'video': a.video, 'size': [int(vs['width']), int(vs['height'])], 'fps': round(src_fps, 3), 'duration': round(dur, 3), 'analysed_fps': fps,
        'shots': len(shots), 'cuts_at_s': [round(c / fps, 3) for c in cuts],
        'shot_length_s': {'median': round(float(np.median(lens)), 3), 'min': round(float(lens.min()), 3), 'max': round(float(lens.max()), 3)} if len(lens) else None,
        'held_frame_ratio': round(hold_ratio, 3),
        'motion_energy': {'median': round(float(np.median(diffs)), 3), 'p90': round(float(np.percentile(diffs, 90)), 3)},
        'luminance': {'mean': round(float(np.mean(lums)), 3), 'min': round(float(np.min(lums)), 3), 'max': round(float(np.max(lums)), 3)},
        'saturation_mean': round(float(np.mean(sats)), 3),
        'palette': [{'hex': h, 'share': round(float(s), 3)} for h, s in zip(hexes, share)],
        'audio': audio,
    }
    json.dump(rep, open(os.path.join(a.out, 'report.json'), 'w'), indent=1)
    bible = f"""# Style bible: {os.path.basename(a.video)}

Measured by `rv study`. Numbers are evidence: confirm each against the frames in shots.png.

## Format
- {rep['size'][0]}x{rep['size'][1]}, {rep['fps']} fps, {rep['duration']} s
- drawing rate: {rep['held_frame_ratio'] * 100:.0f}% of analysed frames are holds{' (looks animated on 2s or more)' if hold_ratio > 0.35 else ''}

## Edit
- {rep['shots']} shots, median {rep['shot_length_s']['median'] if rep['shot_length_s'] else '-'} s (min {rep['shot_length_s']['min'] if rep['shot_length_s'] else '-'}, max {rep['shot_length_s']['max'] if rep['shot_length_s'] else '-'})
- cuts at: {', '.join(f'{c:.2f}' for c in rep['cuts_at_s'][:40])}
- cut on the beat? compare cut times with the beat grid below

## Color and value
- palette (share): {', '.join(f"{p['hex']} {p['share'] * 100:.0f}%" for p in rep['palette'])}
- mean luminance {rep['luminance']['mean']} (range {rep['luminance']['min']}-{rep['luminance']['max']}), mean saturation {rep['saturation_mean']}

## Sound
- {('tempo ' + str(audio['bpm']) + ' BPM, first downbeat ' + str(audio['first_downbeat']) + ' s' + (', ' + str(audio.get('lufs')) + ' LUFS' if audio.get('lufs') is not None else '')) if audio else 'no audio stream'}

## By eye (fill these in from shots.png)
- rendering model:
- type (faces, sizes, tracking, how it moves):
- camera and lens:
- transitions:
- signature moves:
- what NOT to copy (surface), what to carry (DNA):
"""
    open(os.path.join(a.out, 'bible.md'), 'w').write(bible)
    print(json.dumps({k: v for k, v in rep.items() if k not in ('cuts_at_s',)}, indent=1))
    print('\n' + '\n'.join(os.path.join(a.out, f) for f in ('shots.png', 'palette.png', 'energy.png', 'report.json', 'bible.md')))

if __name__ == '__main__':
    main()
