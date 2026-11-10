#!/usr/bin/env python3
"""Screen CC BY YouTube candidates: watch-page metadata (licence) evidence, 360p proxy, contact sheet.
usage: footage_screen.py OUTDIR ID [ID ...]   (no login, no cookies; documented public pages only)"""
import json, subprocess, sys, os, datetime, pathlib
out = pathlib.Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)
YT = os.path.expanduser("~/.local/bin/yt-dlp")
now = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
summary = []
for vid in sys.argv[2:]:
    d = out / vid; d.mkdir(exist_ok=True)
    url = f"https://www.youtube.com/watch?v={vid}"
    r = subprocess.run([YT, "-J", "--no-warnings", url], capture_output=True, text=True)
    if r.returncode:
        summary.append({"id": vid, "error": r.stderr[-300:]}); continue
    j = json.loads(r.stdout)
    ev = {k: j.get(k) for k in ("id", "title", "channel", "channel_url", "uploader", "license", "duration", "upload_date", "width", "height", "description")}
    ev["description"] = (ev.get("description") or "")[:1500]
    ev["checked_at"] = now; ev["url"] = url; ev["method"] = "yt-dlp watch-page metadata, cookie-less"
    (d / "watchpage-licence.json").write_text(json.dumps(ev, indent=1))
    ok = (j.get("license") or "").startswith("Creative Commons Attribution")
    row = {"id": vid, "title": j.get("title"), "channel": j.get("channel"), "license": j.get("license"), "duration": j.get("duration"), "cc_by": ok}
    if ok and not (d / "proxy.mp4").exists():
        subprocess.run([YT, "-q", "--no-warnings", "-f", "bv*[height<=360][ext=mp4]+ba[ext=m4a]/b[height<=360]", "--merge-output-format", "mp4", "-o", str(d / "proxy.mp4"), url])
    if (d / "proxy.mp4").exists() and not (d / "sheet.jpg").exists():
        dur = j.get("duration") or 60
        step = max(2, dur / 40)
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(d / "proxy.mp4"), "-vf",
                        f"fps=1/{step:.2f},scale=320:-2,drawtext=text='%{{pts\\:hms}}':x=4:y=4:fontsize=18:fontcolor=yellow:box=1:boxcolor=black@0.6,tile=5x8",
                        "-frames:v", "1", str(d / "sheet.jpg")])
        row["sheet_step_s"] = round(step, 2)
    row["sheet"] = str(d / "sheet.jpg") if (d / "sheet.jpg").exists() else None
    summary.append(row); print(json.dumps(row), flush=True)
(out / "screen-summary.json").write_text(json.dumps(summary, indent=1))
