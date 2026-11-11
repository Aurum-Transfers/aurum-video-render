#!/usr/bin/env python3
"""Per-second visual QC of every clip range in a footage.json (post-v4 review, 10 Nov 2026).
For each clip: samples 6 fps at 96x54 gray (after the clip's crop) and records per second:
  y/ymin mean / darkest-frame luma (0-255, tv-range source)          -> brightness floor gate
  mot  mean |frame diff| over 1/6 s, x100/255      -> near-static gate
  gmot mean |diff| of the 8x8 block means (global) -> distinguishes camera move from noise
  dh   64-bit dHash of the second's middle frame   -> near-duplicate / reused-look gate
usage: clip_qc.py WORKDIR   -> WORKDIR/build/clipqc.json (cached per clip key)"""
import json, subprocess, sys, hashlib, numpy as np
from pathlib import Path
wd = Path(sys.argv[1]); lib = json.load(open(wd / "footage.json"))
sys.path.insert(0, str(Path(__file__).resolve().parent)); import spec_gates  # noqa: E402
spec_gates.resolve_clip_files(lib, wd)  # job-relative clip paths -> repo-root paths
out = wd / "build" / "clipqc.json"; out.parent.mkdir(exist_ok=True)
cache = json.load(open(out)) if out.exists() else {}
cache = {k: v for k, v in cache.items() if v.get("ver") == 4}  # v4 adds per-second cut (hard-cut spike) and audio tonality (music/SFX)
W, H, FPS = 96, 54, 6
def dhash(fr):
    import numpy as np
    # 9x8 block means -> horizontal gradient bits
    h, w = fr.shape; bh, bw = h // 8, w // 9
    m = fr[:bh * 8, :bw * 9].reshape(8, bh, 9, bw).mean(axis=(1, 3))
    bits = (m[:, 1:] > m[:, :-1]).flatten()
    return int("".join("1" if b else "0" for b in bits), 2)
def quality(c):
    """Source resolution/fps (ffprobe) and sharpness: Laplacian variance of 5 frames across the range, after the clip's
    crop, scaled to 1280x720 gray so values compare across sources (Marvin 10 Nov: high-quality footage only)."""
    pr = json.loads(subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height,avg_frame_rate",
                                    "-of", "json", c["file"]], capture_output=True, text=True).stdout or "{}").get("streams", [{}])[0]
    num, _, den = (pr.get("avg_frame_rate") or "0/1").partition("/")
    fps = float(num) / float(den) if float(den or 0) else 0.0
    crop = c.get("crop", ""); laps = []
    for k in range(5):
        t = c["f0"] + (c["f1"] - c["f0"]) * (k + 0.5) / 5
        b = subprocess.run(["ffmpeg", "-loglevel", "error", "-ss", f"{t:.3f}", "-i", c["file"], "-frames:v", "1", "-an", "-vf",
                            (f"crop={crop}," if crop else "") + "scale=1280:720,format=gray", "-f", "rawvideo", "-"], capture_output=True).stdout
        if len(b) != 1280 * 720:
            continue
        a = np.frombuffer(b, np.uint8).reshape(720, 1280).astype(np.float32)
        lap = a[1:-1, :-2] + a[1:-1, 2:] + a[:-2, 1:-1] + a[2:, 1:-1] - 4 * a[1:-1, 1:-1]
        laps.append(float(lap.var()))
    eff_h = int(crop.split(":")[1]) if crop else pr.get("height", 0)
    return {"src_w": pr.get("width"), "src_h": pr.get("height"), "eff_h": eff_h, "src_fps": round(fps, 2),
            "lap_med": round(float(np.median(laps)), 1) if laps else None, "lap_min": round(min(laps), 1) if laps else None}

def audio_tonality(c):
    """v4 (Aruba v6 preview review, 10 Nov: 8-bit game jump/coin SFX in a creator's edit at 0:11): per source second,
    the share of spectral energy in narrow peaks >20x the local median (music notes, chiptune, beeps, sung voice).
    Wind/surf/crowd ambience measures ~0.00; the q9_rZmj1kSk SFX measured 0.82-0.88. Returns {second: tonality} or {}."""
    if not c.get("audio"):
        return {}
    b = subprocess.run(["ffmpeg", "-loglevel", "error", "-ss", f"{c['f0']:.3f}", "-t", f"{c['f1'] - c['f0']:.3f}", "-i", c["file"], "-vn", "-ac", "1",
                        "-ar", "16000", "-f", "f32le", "-"], capture_output=True).stdout
    a = np.frombuffer(b, np.float32); sr, N = 16000, 2048; out = {}
    from numpy.lib.stride_tricks import sliding_window_view
    for s_ in range(int(len(a) // sr)):
        seg = a[s_ * sr:(s_ + 1) * sr]
        P = np.array([np.abs(np.fft.rfft(seg[k:k + N] * np.hanning(N))) ** 2 for k in range(0, len(seg) - N, N // 2)])
        pm = P.mean(0)[10:]
        base = np.median(sliding_window_view(np.pad(pm, 15, mode="edge"), 31), axis=1)
        rms = float(np.sqrt((seg ** 2).mean()))
        ton = float(pm[pm / (base + 1e-12) > 20].sum() / (pm.sum() + 1e-12)) if rms > 1e-4 else 0.0
        out[round(c["f0"] + s_, 2)] = round(ton, 3)
    return out

res = dict(cache)
covered = {}
for v in cache.values():
    for x in v.get("secs", []):
        covered.setdefault(v["file"], set()).add(int(x["t"] + 1e-6))
for c in lib["clips"]:
    # v7: every clip is measured under its own id (the old "covered sub-range" skip read stale cache entries and left
    # a re-split clip with no QC record)
    crop = c.get("crop", "")
    # Sped-up clips (play_speed > 1, e.g. the 4x window-seat approach) are measured as they appear ON SCREEN:
    # each frame difference spans 1/6 s of screen time (lag = play_speed frames at 6 fps). Measuring them at 1x
    # under-reported their on-screen motion and rejected every second. 1x clips are measured exactly as before.
    ps = float(c.get("play_speed") or 1.0); lag = max(1, int(round(ps))) if ps > 1 else 1
    key = hashlib.md5((f"v4|{c['file']}|{c['f0']}|{c['f1']}|{crop}" + (f"|lag{lag}" if lag > 1 else "") + ("|aud" if c.get("audio") else "")).encode()).hexdigest()[:12]
    if cache.get(c["id"], {}).get("key") == key:
        res[c["id"]] = cache[c["id"]]; continue
    vf = (f"crop={crop}," if crop else "") + f"fps={FPS},scale={W}:{H},format=gray"
    b = subprocess.run(["ffmpeg", "-loglevel", "error", "-ss", f"{c['f0']:.3f}", "-t", f"{c['f1'] - c['f0']:.3f}", "-i", c["file"], "-an",
                        "-vf", vf, "-f", "rawvideo", "-"], capture_output=True).stdout
    a = np.frombuffer(b, np.uint8).reshape(-1, H, W).astype(np.float32)
    secs = []
    for s in range(int(len(a) // FPS)):
        blk = a[s * FPS:(s + 1) * FPS]
        d = np.abs(np.diff(blk, axis=0))
        if lag > 1:  # on-screen motion of a sped-up clip: pair each frame with the one lag frames later
            i0, i1 = s * FPS, min((s + 1) * FPS, len(a) - lag)
            pairs = (a[i0:i1], a[i0 + lag:i1 + lag]) if i1 > i0 else (blk[:1], blk[-1:])
            d = np.abs(pairs[1] - pairs[0])
        bm = blk[:, :48, :].reshape(len(blk), 8, 6, 8, 12).mean(axis=(2, 4)) if False else blk.reshape(len(blk), 6, 9, 8, 12).mean(axis=(2, 4))
        gd = np.abs(np.diff(bm, axis=0))
        if lag > 1:
            bm1 = pairs[0].reshape(len(pairs[0]), 6, 9, 8, 12).mean(axis=(2, 4)); bm2 = pairs[1].reshape(len(pairs[1]), 6, 9, 8, 12).mean(axis=(2, 4))
            gd = np.abs(bm2 - bm1)
            last = a[min(s * FPS + (FPS - 1) * lag, len(a) - 1)]  # end of one on-screen second
        else:
            last = blk[-1]
        # v3 (post v5-animatic review): camera-move proxies that water shimmer does not inflate
        g6 = blk.reshape(len(blk), 6, 9, 12, 8).mean(axis=(2, 4))      # 6x12 grid of block means
        g6l = last.reshape(6, 9, 12, 8).mean(axis=(1, 3))
        lmot = float(np.abs(g6l - g6[0]).mean()) * 100 / 255           # first vs last frame of the second
        f0_, f1_ = blk[0] - blk[0].mean(), last - last.mean()
        r = np.abs(np.fft.ifft2(np.fft.fft2(f0_) * np.conj(np.fft.fft2(f1_))))
        iy, ix = np.unravel_index(int(r.argmax()), r.shape)
        iy = iy - H if iy > H // 2 else iy; ix = ix - W if ix > W // 2 else ix
        pk = float(r.max() / (r.mean() + 1e-6))
        cut = float(np.abs(np.diff(blk, axis=0)).mean(axis=(1, 2)).max()) * 100 / 255 if len(blk) > 1 else 0.0  # hard-cut spike
        secs.append({"t": round(c["f0"] + s, 2), "cut": round(cut, 2), "lmot": round(lmot, 3), "shift": round(float((ix * ix + iy * iy) ** 0.5), 2), "pk": round(pk, 1), "y": round(float(blk.mean()), 1), "ymin": round(float(blk.mean(axis=(1, 2)).min()), 1), "mot": round(float(d.mean()) * 100 / 255, 3),
                     "gmot": round(float(gd.mean()) * 100 / 255, 3), "dh": dhash(blk[len(blk) // 2])})
    ton = audio_tonality(c)
    for x in secs:
        if ton:
            x["ton"] = ton.get(round(x["t"], 2), 1.0)  # missing audio second = not proven clean
    res[c["id"]] = {"key": key, "ver": 4, "file": c["file"], "secs": secs, "audio_measured": bool(ton), **quality(c)}
    print(c["id"], len(secs), file=sys.stderr)
json.dump(res, open(out, "w"))
print(json.dumps({"clips": len(res), "out": str(out)}))
