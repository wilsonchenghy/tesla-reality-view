#!/usr/bin/env python3
"""Audio measurement for the rv harness. You cannot listen, so measure.

  audiotools.py report <audio|video> --hits hits.json --fps 60 --out report.png [--json r.json]
      per-hit peak timing vs intent, hit level over the bed, loudness trace chart with hit markers.
  audiotools.py song <audio> [--json out.json] [--min-bpm 70 --max-bpm 180]
      tempo, beat grid, first downbeat (to cut a piece to a supplied song).
"""
import sys, json, argparse, subprocess
import numpy as np
from PIL import Image, ImageDraw, ImageFont

def decode(path, sr=48000):
    raw = subprocess.run(['ffmpeg', '-v', 'error', '-i', path, '-f', 'f32le', '-ac', '1', '-ar', str(sr), '-'], capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.float32).copy(), sr

def font(size):
    for p in ['/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf', '/System/Library/Fonts/Menlo.ttc']:
        try: return ImageFont.truetype(p, size)
        except Exception: pass
    return ImageFont.load_default()

def db(x): return 20 * np.log10(np.maximum(x, 1e-9))

def cmd_report(a):
    x, sr = decode(a.input)
    hits = json.load(open(a.hits)) if a.hits else []
    # stems (rendered by the harness): hits-only for clean onsets, bed-only for "level over bed"
    sfx = decode(a.sfx)[0] if a.sfx else x
    bed = decode(a.bed)[0] if a.bed else None
    n = len(x)
    pad = int(0.1 * sr)
    def win(sig, i0, i1):                      # circular for loops, so hits near 0 or the end are measured
        idx = np.arange(i0, i1)
        if a.loop: return sig[idx % len(sig)]
        return sig[max(0, i0):min(len(sig), i1)]
    # high-passed envelope (first difference, 1 ms smoothing): sub tails and drones don't hide attacks
    hp = np.abs(np.concatenate([[0], np.diff(sfx)]))
    k = max(1, int(0.001 * sr)); env = np.convolve(hp, np.ones(k) / k, mode='same')
    out = []
    for h in hits:
        if h.get('bed'): continue
        t = h['t']; c = int(t * sr)
        i0, i1 = c - int(0.03 * sr), c + int(0.05 * sr)
        if not a.loop and (i0 < 0 or i1 >= n): continue
        e = win(env, i0, i1)
        pre = float(np.median(win(env, c - int(0.06 * sr), c - int(0.035 * sr)))) if True else 0
        pk = int(np.argmax(e)); top = float(e[pk])
        thr = pre + 0.5 * (top - pre)
        on = int(np.argmax(e >= thr)); onset_t = (i0 + on) / sr
        ambiguous = on <= int(0.001 * sr) or top < 3 * pre + 1e-6    # rising at the window edge or buried
        hit_rms = float(np.sqrt(np.mean(win(sfx, c, c + int(0.06 * sr)) ** 2)))
        if bed is not None:
            bed_rms = float(np.sqrt(np.mean(win(bed, c, c + int(0.06 * sr)) ** 2)))
        else:
            bed_rms = float(np.sqrt(np.mean(win(x, c - int(0.25 * sr), c - int(0.02 * sr)) ** 2)))
        early = h.get('early', 0)
        out.append({'name': h['name'], 'early': early, 't': round(t, 4), 'frame': round(t * a.fps, 2),
                    'onset_ms': round((onset_t - t) * 1000, 2), 'peak_ms': round(((i0 + pk) / sr - t) * 1000, 2),
                    'over_bed_db': round(float(db(hit_rms) - db(max(bed_rms, 1e-7))), 1), 'ambiguous': bool(ambiguous)})
    late = [o for o in out if not o['ambiguous'] and abs(o['onset_ms']) > 1000 / a.fps and not (o['early'] and -o['onset_ms'] <= o['early'] * 1000 + 1000 / a.fps)]
    weak = [o for o in out if o['over_bed_db'] < 3]
    amb = [o for o in out if o['ambiguous']]
    # loudness trace (RMS / 50 ms) + chart
    win = int(0.05 * sr); n = len(x) // win
    rms = db(np.sqrt(np.mean(x[:n * win].reshape(n, win) ** 2, axis=1)))
    dur = len(x) / sr
    W, H = 1600, 380
    im = Image.new('RGB', (W, H), (16, 16, 16)); d = ImageDraw.Draw(im); f = font(14)
    box = (50, 30, W - 20, H - 40)
    d.rectangle(box, outline=(70, 70, 70))
    d.text((56, 34), f'RMS dBFS per 50 ms (blue); hits: orange on time, red >1 frame off or <3 dB over bed, gray ambiguous; vertical gray/brown = beats/bars', fill=(230, 230, 230), font=f)
    def X(t): return box[0] + (box[2] - box[0]) * t / dur
    def Y(v): return box[3] - (box[3] - box[1] - 24) * (np.clip(v, -60, 0) + 60) / 60
    if a.bpm:
        k = 0
        while k * 60 / a.bpm <= dur:
            d.line([(X(k * 60 / a.bpm), box[1]), (X(k * 60 / a.bpm), box[3])], fill=(55, 55, 55) if k % 4 else (90, 70, 40)); k += 1
    for lv in (-12, -24, -36, -48):
        d.line([(box[0], Y(lv)), (box[2], Y(lv))], fill=(40, 40, 40)); d.text((8, Y(lv) - 8), f'{lv}', fill=(120, 120, 120), font=f)
    d.line([(X((i + 0.5) * 0.05), Y(v)) for i, v in enumerate(rms)], fill=(110, 180, 255), width=2)
    for o in out:
        bad = o in late or o in weak
        d.line([(X(o['t']), box[1] + 22), (X(o['t']), box[3])], fill=(230, 70, 60) if bad else (120, 120, 120) if o['ambiguous'] else (240, 150, 40))
    for sec in range(int(dur) + 1):
        d.text((X(sec) - 4, box[3] + 6), f'{sec}s', fill=(150, 150, 150), font=f)
    if a.out: im.save(a.out)
    rep = {'duration': round(dur, 3), 'hits': len(out), 'bed_marks': sum(1 for h in hits if h.get('bed')), 'off_by_more_than_a_frame': late, 'under_3db_over_bed': weak,
           'ambiguous_onsets': [{'name': o['name'], 't': o['t']} for o in amb], 'bed_measured_from': 'bed stem' if bed is not None else 'the 250 ms before each hit (approximate)',
           'median_onset_ms': round(float(np.median([o['onset_ms'] for o in out])), 2) if out else None,
           'silent_spans_s': silent_spans(rms, 0.05), 'detail': out}
    if a.json: json.dump(rep, open(a.json, 'w'), indent=1)
    print(json.dumps({k: v for k, v in rep.items() if k != 'detail'}, indent=1))

def silent_spans(rms, step, floor=-55, min_len=0.3):
    spans, s = [], None
    for i, v in enumerate(list(rms) + [0]):
        if v < floor and s is None: s = i
        if v >= floor and s is not None:
            if (i - s) * step >= min_len: spans.append([round(s * step, 2), round(i * step, 2)])
            s = None
    return spans

def cmd_song(a):
    x, sr = decode(a.input, 22050)
    hop, nfft = 256, 1024
    frames = 1 + (len(x) - nfft) // hop
    win = np.hanning(nfft).astype(np.float32)
    idx = np.arange(nfft)[None, :] + hop * np.arange(frames)[:, None]
    spec = np.abs(np.fft.rfft(x[idx] * win, axis=1))
    logs = np.log1p(100 * spec)
    flux = np.maximum(0, np.diff(logs, axis=0)).sum(1)
    flux = np.concatenate([[0], flux])
    flux -= np.convolve(flux, np.ones(16) / 16, mode='same')
    flux = np.maximum(flux, 0)
    # kick-band flux (40-160 Hz): beats sit on kicks far more reliably than on hats and foley (off-beats)
    lo0, lo1 = int(40 / (sr / nfft)), max(int(40 / (sr / nfft)) + 2, int(160 / (sr / nfft)))
    lflux = np.concatenate([[0], np.maximum(0, np.diff(logs[:, lo0:lo1], axis=0)).sum(1)])
    lflux -= np.convolve(lflux, np.ones(16) / 16, mode='same'); lflux = np.maximum(lflux, 0)
    lflux /= lflux.max() + 1e-9; nflux = flux / (flux.max() + 1e-9)
    beatflux = 2.0 * lflux + 0.5 * nflux
    fr = sr / hop
    # tempo by autocorrelation of onset strength, weighted toward 120 BPM
    ac = np.correlate(flux, flux, mode='full')[len(flux) - 1:]
    best, best_bpm = -1, 120
    for bpm in np.arange(a.min_bpm, a.max_bpm + 0.01, 0.1):
        lag = 60 / bpm * fr
        l0 = int(lag); fracl = lag - l0
        if l0 + 1 >= len(ac): continue
        v = (1 - fracl) * ac[l0] + fracl * ac[l0 + 1]
        v2 = 0
        for m in (2, 4):
            lm = lag * m; lm0 = int(lm)
            if lm0 + 1 < len(ac): v2 += (1 - (lm - lm0)) * ac[lm0] + (lm - lm0) * ac[lm0 + 1]
        score = (v + 0.5 * v2) * np.exp(-0.5 * (np.log2(bpm / 120) / 1.0) ** 2)
        if score > best: best, best_bpm = score, bpm
    spb = 60 / best_bpm
    # phase: maximize onset strength sampled on the grid
    def grid_score(ph, spb_):
        ts = np.arange(ph, len(x) / sr, spb_)
        ii = np.clip(np.rint(ts * fr).astype(int), 0, len(beatflux) - 1)
        # tolerate +-1 analysis frame
        return np.maximum(beatflux[ii], np.maximum(beatflux[np.clip(ii - 1, 0, None)], beatflux[np.clip(ii + 1, None, len(beatflux) - 1)])).sum()
    # joint refine: tempo within +-1.5% and phase, maximizing kick-weighted onset strength on the grid
    best_s, ph, bpm_r = -1, 0, best_bpm
    for bpm_c in np.linspace(best_bpm * 0.985, best_bpm * 1.015, 31):
        s_ = 60 / bpm_c
        for ph_c in np.linspace(0, s_, 160, endpoint=False):
            v = grid_score(ph_c, s_)
            if v > best_s: best_s, ph, bpm_r = v, ph_c, bpm_c
    best_bpm, spb = bpm_r, 60 / bpm_r
    if ph > spb - 0.03: ph -= spb                      # a beat at -1 ms is the beat at 0, not the next one
    beats = np.arange(ph, len(x) / sr, spb)
    beats = np.maximum(beats[beats > -0.03], 0.0)
    # downbeat: which of the 4 positions carries the most low-frequency energy
    low = spec[:, : int(150 / (sr / nfft))].sum(1)
    acc = []
    for k in range(4):
        # onsets in the kick/bass band, not level: a note held from the downbeat would make beat 2 look heavier
        ts = beats[k::4]; ii = np.clip(np.rint(ts * fr).astype(int), 0, len(lflux) - 1)
        acc.append(np.maximum(lflux[ii], lflux[np.clip(ii + 1, None, len(lflux) - 1)]).mean())
    k0 = int(np.argmax(acc))
    srt = sorted(acc, reverse=True)
    dconf = round(float((srt[0] - srt[1]) / (srt[0] + 1e-9)), 3)   # 0 = two candidates tie (e.g. kicks on 1 and 3)
    downbeats = beats[k0::4]
    rep = {'bpm': round(float(best_bpm), 2), 'first_beat': round(float(beats[0]), 4), 'first_downbeat': round(float(downbeats[0]), 4),
           'downbeat_confidence': dconf, 'downbeat_note': 'beats are reliable; which beat is "1" is an estimate. Below ~0.15 confidence, check the bar structure (where the arrangement changes) in shots/energy, or ask the user.',
           'beats': [round(float(b), 4) for b in beats], 'downbeats': [round(float(b), 4) for b in downbeats], 'duration': round(len(x) / sr, 3)}
    if a.json: json.dump(rep, open(a.json, 'w'), indent=1)
    print(json.dumps({k: v for k, v in rep.items() if k not in ('beats', 'downbeats')}, indent=1))
    print('first 8 beats:', rep['beats'][:8])

if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('cmd'); ap.add_argument('input')
    ap.add_argument('--hits'); ap.add_argument('--fps', type=float, default=60); ap.add_argument('--bpm', type=float, default=0)
    ap.add_argument('--out'); ap.add_argument('--json')
    ap.add_argument('--sfx'); ap.add_argument('--bed'); ap.add_argument('--loop', action='store_true')
    ap.add_argument('--min-bpm', type=float, default=70); ap.add_argument('--max-bpm', type=float, default=180)
    a = ap.parse_args()
    {'report': cmd_report, 'song': cmd_song}[a.cmd](a)
