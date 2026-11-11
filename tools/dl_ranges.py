#!/usr/bin/env python3
"""Download CC BY range clips straight into a job's clips/ folder as <id>_<a>-<b>.mp4 (cookie-less yt-dlp, public
watch pages only, <=1080p, keyframes forced at cuts). Skips existing files; stops if free disk < 6 GiB.
usage: dl_ranges.py JOBDIR ID:A-B [ID:A-B ...]"""
import json, subprocess, sys, os, pathlib, shutil
job = pathlib.Path(sys.argv[1]); out = job / "clips"; out.mkdir(parents=True, exist_ok=True)
YT = os.path.expanduser("~/.local/bin/yt-dlp")
def has_video(p):
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=height", "-of", "csv=p=0", str(p)], capture_output=True, text=True)
    return r.stdout.strip().isdigit() and int(r.stdout.strip()) >= 720
for arg in sys.argv[2:]:
    vid, span = arg.split(":", 1)
    a, b = span.split("-")
    f = out / f"{vid}_{a}-{b}.mp4"
    if f.exists() and f.stat().st_size > 10000 and has_video(f):
        continue
    if f.exists():  # audio-only or truncated result from an earlier run: keep it aside (no deletes), fetch again
        bad = job / "clips-rejected"; bad.mkdir(exist_ok=True); f.rename(bad / f.name)
    free = shutil.disk_usage(str(out)).free / 2**30
    if free < 6:
        print(json.dumps({"id": vid, "skipped": f"free {free:.1f} GiB < 6"}), flush=True); break
    r = subprocess.run([YT, "-q", "--no-warnings", "-f", "bv*[height<=1080][vcodec^=avc1]+ba[ext=m4a]/137+140/bv*[height<=1080]+ba",
                        "--merge-output-format", "mp4", "--download-sections", f"*{a}-{b}", "--force-keyframes-at-cuts",
                        "-o", str(f), f"https://www.youtube.com/watch?v={vid}"], capture_output=True, text=True)
    ok = f.exists() and has_video(f)
    print(json.dumps({"clip": f.name, "rc": r.returncode, "video": ok, "err": r.stderr[-200:] if r.returncode or not ok else ""}), flush=True)
