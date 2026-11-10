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
out = wd / "build" / "clipqc.json"; out.parent.mkdir(exist_ok=True)
cache = json.load(open(out)) if out.exists() else {}
cache = {k: v for k, v in cache.items() if v.get("ver") == 3}  # older measurements lack the v3 camera-move fields
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

res = dict(cache)
covered = {}
for v in cache.values():
    for x in v.get("secs", []):
        covered.setdefault(v["file"], set()).add(int(x["t"] + 1e-6))
for c in lib["clips"]:
    need = set(range(int(c["f0"]), int(c["f1"]) - 1))
    if need and need <= covered.get(c["file"], set()):
        continue  # sub-range of an already measured clip (planner indexes QC by file + second)
    crop = c.get("crop", "")
    key = hashlib.md5(f"v3|{c['file']}|{c['f0']}|{c['f1']}|{crop}".encode()).hexdigest()[:12]
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
        bm = blk[:, :48, :].reshape(len(blk), 8, 6, 8, 12).mean(axis=(2, 4)) if False else blk.reshape(len(blk), 6, 9, 8, 12).mean(axis=(2, 4))
        gd = np.abs(np.diff(bm, axis=0))
        # v3 (post v5-animatic review): camera-move proxies that water shimmer does not inflate
        g6 = blk.reshape(len(blk), 6, 9, 12, 8).mean(axis=(2, 4))      # 6x12 grid of block means
        lmot = float(np.abs(g6[-1] - g6[0]).mean()) * 100 / 255           # first vs last frame of the second
        f0_, f1_ = blk[0] - blk[0].mean(), blk[-1] - blk[-1].mean()
        r = np.abs(np.fft.ifft2(np.fft.fft2(f0_) * np.conj(np.fft.fft2(f1_))))
        iy, ix = np.unravel_index(int(r.argmax()), r.shape)
        iy = iy - H if iy > H // 2 else iy; ix = ix - W if ix > W // 2 else ix
        pk = float(r.max() / (r.mean() + 1e-6))
        secs.append({"t": round(c["f0"] + s, 2), "lmot": round(lmot, 3), "shift": round(float((ix * ix + iy * iy) ** 0.5), 2), "pk": round(pk, 1), "y": round(float(blk.mean()), 1), "ymin": round(float(blk.mean(axis=(1, 2)).min()), 1), "mot": round(float(d.mean()) * 100 / 255, 3),
                     "gmot": round(float(gd.mean()) * 100 / 255, 3), "dh": dhash(blk[len(blk) // 2])})
    res[c["id"]] = {"key": key, "ver": 3, "file": c["file"], "secs": secs, **quality(c)}
    print(c["id"], len(secs), file=sys.stderr)
json.dump(res, open(out, "w"))
print(json.dumps({"clips": len(res), "out": str(out)}))
