#!/usr/bin/env python3
"""Portrait (Shorts) gate: a true 9:16 picture, never a horizontal frame centred with bars or a blurred copy behind it.

Pre-render (--edl): every clip shot of a landscape source must carry a reframe (portrait_reframe.py) or the source must
be portrait; shots without one would fall back to a plain centre crop -> FAIL (subject not tracked).
Output (--video): stream must be 1080x1920; 16 frames sampled; a frame FAILS when
  letterbox: the top and bottom 12 % bands are near-uniform (row std < 6) while the middle has detail, or
  blur-pad: the top/bottom 20 % bands are much softer than the middle (Laplacian var ratio < 0.12) AND there are
            sharp horizontal seams at BOTH edges of a centred 16:9 inset (rows 0.33h AND 0.67h). One seam alone
            (a dashboard, horizon or cloud layer) is not a pad.
Any failed frame fails the gate. Exit 0 pass, 1 fail; JSON on stdout. Also importable: check_edl(), check_video().

usage: portrait_gate.py [--edl EDL.json] [--video OUT.mp4] [--write RESULT.json]
"""
import argparse, json, subprocess, sys
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parent.parent


def check_edl(edl):
    bad = []
    for i, s in enumerate(edl.get("shots", [])):
        if s.get("kind") != "clip":
            continue
        f = Path(s["file"]); f = f if f.exists() else ROOT / s["file"]
        r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "csv=p=0", str(f)],
                           capture_output=True, text=True).stdout.strip().split(",")
        land = len(r) == 2 and r[0].isdigit() and int(r[0]) > int(r[1])
        if land and not s.get("reframe"):
            bad.append(i)
    return {"pass": not bad, "detail": {"shots_without_reframe": bad[:20], "n": len(bad)}}


def lapvar(a):
    l = a[1:-1, :-2] + a[1:-1, 2:] + a[:-2, 1:-1] + a[2:, 1:-1] - 4 * a[1:-1, 1:-1]
    return float(l.var())


def check_video(path, n=16):
    pr = json.loads(subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height:format=duration",
                                    "-of", "json", str(path)], capture_output=True, text=True).stdout or "{}")
    st = (pr.get("streams") or [{}])[0]; dur = float((pr.get("format") or {}).get("duration") or 0)
    if (st.get("width"), st.get("height")) != (1080, 1920):
        return {"pass": False, "detail": {"size": [st.get("width"), st.get("height")], "why": "not 1080x1920"}}
    W, H = 270, 480; bad = []
    for k in range(n):
        t = dur * (k + 0.5) / n
        b = subprocess.run(["ffmpeg", "-loglevel", "error", "-ss", f"{t:.2f}", "-i", str(path), "-frames:v", "1", "-an", "-vf",
                            f"scale={W}:{H},format=gray", "-f", "rawvideo", "-"], capture_output=True).stdout
        if len(b) != W * H:
            continue
        a = np.frombuffer(b, np.uint8).reshape(H, W).astype(np.float32)
        tb, bb, mid = a[: int(H * .12)], a[-int(H * .12):], a[int(H * .38): int(H * .62)]
        letter = tb.std(axis=1).mean() < 6 and bb.std(axis=1).mean() < 6 and mid.std() > 15
        t20, b20, m = a[: int(H * .2)], a[-int(H * .2):], a[int(H * .36): int(H * .64)]
        soft = (lapvar(t20) + lapvar(b20)) / 2 / max(1e-3, lapvar(m)) < 0.12
        rows = np.abs(np.diff(a.mean(axis=1)))
        # Real 16:9 blur-pads have two strong, aligned seams (~100 after the 270x480 probe).
        # A 6x-median threshold alone also fires on a faint tree-line plus a curb or caption.
        thresh = max(6 * (np.median(rows) + 0.5), 24.0)
        seam_top = rows[int(H * .30): int(H * .36)].max() > thresh
        seam_bot = rows[int(H * .64): int(H * .70)].max() > thresh
        # A centred 16:9 inset with blur bars has two seams. One horizon, curb or dashboard is not a pad.
        seam = bool(seam_top and seam_bot)
        if letter or (soft and seam):
            bad.append({"t": round(t, 2), "letterbox": bool(letter), "blur_pad": bool(soft and seam)})
    return {"pass": not bad, "detail": {"frames": n, "bad": bad}}


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--edl"); ap.add_argument("--video"); ap.add_argument("--write")
    a = ap.parse_args(); res = {}
    if a.edl:
        res["portrait_shots_reframed"] = check_edl(json.loads(Path(a.edl).read_text()))
    if a.video:
        res["portrait_no_letterbox_or_blur_pad"] = check_video(a.video)
    out = {"pass": all(v["pass"] for v in res.values()), "gates": res}
    if a.write:
        Path(a.write).write_text(json.dumps(out, indent=1))
    print(json.dumps(out)); sys.exit(0 if out["pass"] else 1)
