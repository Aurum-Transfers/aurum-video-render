#!/usr/bin/env python3
"""Watermark / face / burned-in text heuristics for every clip in a job's footage.json (complements clip_qc.py, which
already measures resolution, sharpness, motion, luma and source-audio tonality).

Per clip, 8 frames across [f0, f1] at 640x360 gray (OpenCV):
  faces      Haar frontal-face detections >= 4% of frame height (vlogger faces)      -> flag if >= 2 frames
  watermark  corner/edge band with persistent edges: per-pixel edge in >= 85% of frames while the
             rest of the frame moves (static logo / channel bug over moving footage)  -> flag if band edge share >= 0.6%
  text       MSER + stroke-like regions in a horizontal line cluster (burned-in titles) -> flag if >= 3 frames
Heuristics only: a flag means "look at it", never an automatic pass. Writes WORKDIR/build/autoqc.json and exits 1 when
any clip is flagged and not listed in footage.json "autoqc_ack" (ids a reviewer cleared).

usage: clip_autoqc.py WORKDIR [OUT.json]   (default WORKDIR/build/autoqc.json)
"""
import json, subprocess, sys
from pathlib import Path
import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import spec_gates  # noqa: E402

wd = Path(sys.argv[1]); lib = spec_gates.resolve_clip_files(json.load(open(wd / "footage.json")), wd)
FACE = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
W, H, N = 640, 360, 8


def frames(c):
    out = []
    for k in range(N):
        t = float(c["f0"]) + (float(c["f1"]) - float(c["f0"])) * (k + 0.5) / N
        b = subprocess.run(["ffmpeg", "-loglevel", "error", "-ss", f"{t:.3f}", "-i", c["file"], "-frames:v", "1", "-an", "-vf",
                            (f"crop={c['crop']}," if c.get("crop") else "") + f"scale={W}:{H},format=gray", "-f", "rawvideo", "-"],
                           capture_output=True).stdout
        if len(b) == W * H:
            out.append(np.frombuffer(b, np.uint8).reshape(H, W))
    return out


def check(c):
    fr = frames(c)
    if len(fr) < 4:
        return {"error": "could not read frames"}
    faces = sum(1 for f in fr if len(FACE.detectMultiScale(f, 1.1, 6, minSize=(int(H * 0.04), int(H * 0.04)))) > 0)
    edges = np.stack([cv2.Canny(f, 80, 200) > 0 for f in fr])
    persist = edges.mean(axis=0) >= 0.85
    band = np.zeros((H, W), bool); m = int(H * 0.16)
    band[:m, :] = band[-m:, :] = True; band[:, :int(W * 0.12)] = band[:, -int(W * 0.12):] = True
    moving = float(np.mean([np.abs(fr[i].astype(int) - fr[i - 1].astype(int)).mean() for i in range(1, len(fr))]))
    wm_share = float(persist[band].mean()) if moving > 3 else 0.0
    mser = cv2.MSER_create(delta=5, min_area=30, max_area=1500)
    txt = 0
    for f in fr:
        regs, boxes = mser.detectRegions(f)
        bx = [b for b in boxes if 0.2 < b[2] / max(1, b[3]) < 1.5 and 8 <= b[3] <= 60]
        rows = {}
        for x, y, w, h in bx:
            rows.setdefault(int(y // 12), []).append(x)
        if any(len(set(int(x // 10) for x in xs)) >= 8 for xs in rows.values()):
            txt += 1
    flags = []
    if faces >= 2: flags.append(f"faces in {faces}/{len(fr)} frames")
    if wm_share >= 0.006: flags.append(f"persistent edge band {wm_share:.3%} (watermark/logo?)")
    if txt >= 3: flags.append(f"text-like line clusters in {txt}/{len(fr)} frames")
    return {"faces": faces, "watermark_band": round(wm_share, 5), "text_frames": txt, "flags": flags}


res = {c["id"]: {"file": c["file"], **check(c)} for c in lib["clips"]}
ack = set(lib.get("autoqc_ack") or [])
flagged = {k: v["flags"] for k, v in res.items() if (v.get("flags") or v.get("error")) and k not in ack}
outp = Path(sys.argv[2]) if len(sys.argv) > 2 else wd / "build" / "autoqc.json"
outp.parent.mkdir(parents=True, exist_ok=True)
outp.write_text(json.dumps({"clips": res, "flagged_unacked": flagged}, indent=1))
print(json.dumps({"clips": len(res), "flagged_unacked": len(flagged)}))
sys.exit(1 if flagged else 0)
