#!/usr/bin/env python3
"""Download licensed source spans (<=1080p) with yt-dlp --download-sections; writes <id>.mp4 + span.json.
usage: dl_sections.py OUTDIR ID:START-END ...   (cookie-less, public pages only)"""
import json, subprocess, sys, os, pathlib, shutil
out = pathlib.Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)
YT = os.path.expanduser("~/.local/bin/yt-dlp")
for arg in sys.argv[2:]:
    vid, span = arg.split(":", 1)
    a, b = [float(x) for x in span.split("-")]
    f = out / f"{vid}.mp4"
    if f.exists():
        continue
    free = shutil.disk_usage(str(out)).free / 2**30
    if free < 6:
        print(json.dumps({"id": vid, "skipped": f"free {free:.1f} GiB < 6"})); break
    r = subprocess.run([YT, "-q", "--no-warnings", "-f", "bv*[height<=1080][ext=mp4]+ba[ext=m4a]/b[height<=1080]", "--merge-output-format", "mp4",
                        "--download-sections", f"*{a}-{b}", "--force-keyframes-at-cuts", "-o", str(f), f"https://www.youtube.com/watch?v={vid}"],
                       capture_output=True, text=True)
    (out / f"{vid}.span.json").write_text(json.dumps({"id": vid, "src_base": a, "src_end": b, "rc": r.returncode, "err": r.stderr[-400:]}))
    print(json.dumps({"id": vid, "rc": r.returncode, "exists": f.exists()}), flush=True)
