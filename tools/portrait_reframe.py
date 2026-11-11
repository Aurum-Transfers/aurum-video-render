#!/usr/bin/env python3
"""Subject-tracking 9:16 reframe for a portrait (Shorts) EDL: true crop + pan, never letterbox or blurred bars.

For every clip shot of a landscape source, 6 frames across the shot's source span are read at 320 px wide (gray);
per frame a column saliency profile = gradient energy + motion energy (|frame diff|), weighted toward the frame centre.
The 9:16 window (width = H*9/16) whose summed saliency is highest gives the subject centre cx for that frame; the
shot gets reframe {cx0, cx1} (start / end centre, 0..1 of source width, smoothed, pan speed capped) that
title_runner.segments turns into a panning crop. Portrait sources (w <= h) need no reframe.
Writes the EDL in place (or to OUT). Light: stills only, but run it through gate.py run --kind heavy like other ffmpeg work.

usage: portrait_reframe.py JOBDIR [EDL_IN] [EDL_OUT]   (default JOBDIR/build/edl-long.json in place)
"""
import json, subprocess, sys
from pathlib import Path
import numpy as np

job = Path(sys.argv[1]); ein = Path(sys.argv[2]) if len(sys.argv) > 2 else job / "build/edl-long.json"
eout = Path(sys.argv[3]) if len(sys.argv) > 3 else ein
ROOT = Path(__file__).resolve().parent.parent
edl = json.loads(ein.read_text())
SW = 320


def probe(f):
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "csv=p=0", str(f)],
                       capture_output=True, text=True).stdout.strip().split(",")
    return int(r[0]), int(r[1])


def frame(f, t, sh):
    b = subprocess.run(["ffmpeg", "-loglevel", "error", "-ss", f"{t:.3f}", "-i", str(f), "-frames:v", "1", "-an", "-vf", f"scale={SW}:{sh},format=gray",
                        "-f", "rawvideo", "-"], capture_output=True).stdout
    return np.frombuffer(b, np.uint8).reshape(sh, SW).astype(np.float32) if len(b) == SW * sh else None


def best_cx(fr, prev, win):
    gx = np.abs(np.diff(fr, axis=1, prepend=fr[:, :1])); gy = np.abs(np.diff(fr, axis=0, prepend=fr[:1]))
    sal = (gx + gy).mean(axis=0)
    if prev is not None:
        sal = sal + 2.0 * np.abs(fr - prev).mean(axis=0)
    x = np.arange(SW); sal = sal * (1.0 - 0.35 * np.abs(x / SW - 0.5) * 2)  # mild centre bias
    cs = np.convolve(sal, np.ones(win), "valid")
    return (int(np.argmax(cs)) + win / 2) / SW


n = 0
for s in edl["shots"]:
    if s.get("kind") != "clip":
        continue
    f = Path(s["file"]); f = f if f.exists() else ROOT / s["file"]
    w, h = probe(f)
    if w <= h:
        s.pop("reframe", None); continue
    sh = int(round(SW * h / w / 2) * 2); win = max(8, int(round(sh * 9 / 16)))
    span = (s["t1"] - s["t0"]) * float(s.get("play_speed", 1)); t0 = float(s["file_in"])
    cxs, prev = [], None
    for k in range(6):
        fr = frame(f, t0 + span * k / 5 * 0.98, sh)
        if fr is None:
            continue
        cxs.append(best_cx(fr, prev, win)); prev = fr
    if not cxs:
        continue
    half = len(cxs) // 2 or 1
    cx0, cx1 = float(np.median(cxs[:half])), float(np.median(cxs[half:] or cxs))
    lim = 0.5 * win / SW  # pan at most half a window width per shot (no whip pans)
    cx1 = cx0 + max(-lim, min(lim, cx1 - cx0))
    m = 0.5 * win / SW
    s["reframe"] = {"cx0": round(min(1 - m, max(m, cx0)), 4), "cx1": round(min(1 - m, max(m, cx1)), 4), "method": "saliency+motion v1"}
    n += 1
edl["reframe"] = {"tool": "tools/portrait_reframe.py", "shots": n}
eout.write_text(json.dumps(edl, indent=1, ensure_ascii=False))
print(json.dumps({"reframed": n, "out": str(eout)}))
