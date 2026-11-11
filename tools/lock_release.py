"""Lock a box-planned EDL and cut short release windows around every used shot.

The public range-clip release must never carry full (or near-full) source videos. The cut is planned on the box from
longer range files; this tool cuts one short window per used clip (all of its shots + 1.5 s margin), rewrites the shots
to point at those windows, writes jobs/<job>/edl-lock.json (the plan stage then re-runs every gate on it instead of
re-planning) and a release footage.json that lists only the windows. The planning library is kept as
build/footage-plan.json.

Usage: python3 tools/lock_release.py jobs/<job>
"""
import json, math, subprocess, sys
from collections import defaultdict
from pathlib import Path

job = Path(sys.argv[1]); M = 1.5
edl = json.loads((job / "build/edl-long.json").read_text())
lib = json.loads((job / "footage.json").read_text())
assert not edl.get("needs_footage"), "plan has gaps; fix before locking"
(job / "build/footage-plan.json").write_text(json.dumps(lib, indent=1, ensure_ascii=False))
clips = {c["id"]: c for c in lib["clips"]}
use = defaultdict(list)
for s in edl["shots"]:
    if s.get("kind") == "clip":
        use[s["clip_id"]].append(s)

def dur(p):
    return float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(p)], capture_output=True, text=True).stdout.strip())

out, expo = [], defaultdict(list)
for cid, ss in use.items():
    c = clips[cid]; src = job / c["file"]; D = dur(src)
    a = min(float(s["file_in"]) for s in ss)
    b = max(float(s["file_in"]) + (s["t1"] - s["t0"]) * float(s.get("play_speed", 1)) for s in ss)
    c0 = max(0, math.floor(a - M)); c1 = min(math.floor(D), math.ceil(b + M))
    base = int(round(c["src_base"])) + c0
    name = f"{c['video_id']}_{base}-{base + c1 - c0}.mp4"; dst = job / "clips" / name
    if not dst.exists():
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", str(c0), "-i", str(src), "-t", str(c1 - c0), "-c:v", "libx264", "-crf", "14",
                        "-preset", "medium", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", str(dst)], check=True)
    n = dict(c); n["file"] = f"clips/{name}"; n["src_base"] = float(base); n["f0"] = 0.1; n["f1"] = round(dur(dst) - 0.1, 2)
    out.append(n); expo[c["video_id"]].append((base, base + c1 - c0))
    for s in ss:
        s["file"] = str(Path(s["file"]).parent / name) if "/" in s["file"] else name
        s["file_in"] = round(float(s["file_in"]) - c0, 4)
lib["clips"] = out
lib["notes"] = (lib.get("notes") or "") + " Release library: short windows around used shots only (tools/lock_release.py); planning library in build/footage-plan.json."
(job / "footage.json").write_text(json.dumps(lib, indent=1, ensure_ascii=False))
(job / "edl-lock.json").write_text(json.dumps(edl, indent=1, ensure_ascii=False))
rep = {}
for v, w in expo.items():
    w.sort(); tot, cur = 0, None
    for x0, x1 in w:
        if cur and x0 <= cur[1]: cur[1] = max(cur[1], x1)
        else:
            if cur: tot += cur[1] - cur[0]
            cur = [x0, x1]
    tot += cur[1] - cur[0]; rep[v] = tot
print(json.dumps({"clips": len(out), "files": sorted({c["file"] for c in out}), "exposed_s": rep}))
