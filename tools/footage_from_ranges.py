#!/usr/bin/env python3
"""ranges.json (the reviewed footage pick) -> download + footage.json, scripted.

ranges.json (jobs/<job>/ranges.json) is the only hand/visual input of the footage stage:
 {"slug": "...", "evidence_dir": "pool/<place>/licence", "ranges": [
   {"id": "kin_harbour", "video_id": "<yt id or pexels-123>", "a": 120, "b": 160, "tags": [...], "shows": [...],
    "subject": "kin-harbour", "place": "Kingston Harbour from the air", "play_speed": 1.0, "audio": false, "crop": ""}],
  "banned": [], "scarce": [], "autoqc_ack": []}
YouTube ranges are fetched with dl_ranges.py (cookie-less yt-dlp). Pexels/Pixabay ranges are cut from the stock file
in POOL/stock/ that stock_search.py downloaded. Creator/title/url come from the watch-page evidence
(pool_screen.py / stock_search.py), never typed by hand.

usage: footage_from_ranges.py JOBDIR [--no-download]
"""
import json, subprocess, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
job = Path(sys.argv[1]); nodl = "--no-download" in sys.argv
R = json.loads((job / "ranges.json").read_text())
evd = Path(R["evidence_dir"])
yt = [f"{r['video_id']}:{int(r['a'])}-{int(r['b'])}" for r in R["ranges"] if not str(r["video_id"]).startswith(("pexels-", "pixabay-"))]
if yt and not nodl:
    subprocess.run([sys.executable, str(HERE / "dl_ranges.py"), str(job), *yt], check=True)
clips, missing = [], []
for r in R["ranges"]:
    vid = str(r["video_id"]); a, b = int(r["a"]), int(r["b"])
    ev = json.loads((evd / vid / "watchpage-licence.json").read_text())
    name = f"{vid}_{a}-{b}.mp4"; f = job / "clips" / name
    if vid.startswith(("pexels-", "pixabay-")) and not f.exists() and not nodl:
        src = evd.parent / "stock" / f"{vid}.mp4"
        f.parent.mkdir(exist_ok=True)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", str(a), "-i", str(src), "-t", str(b - a), "-c:v", "libx264", "-crf", "14",
                        "-preset", "medium", "-pix_fmt", "yuv420p", "-an", str(f)], check=True)
    if not f.exists():
        missing.append(name)
    d = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(f)],
                             capture_output=True, text=True).stdout.strip() or 0) if f.exists() else float(b - a)
    clips.append({"id": r["id"], "parent": r.get("parent", r["id"]), "video_id": vid, "creator": ev.get("uploader") or ev.get("channel"),
                  "url": ev.get("url"), "title": ev.get("title") or ev.get("url"), "file": f"clips/{name}", "f0": 0.3, "f1": round(d - 0.3, 2),
                  "src_base": float(a), "src_speed": 1.0, "play_speed": float(r.get("play_speed", 1.0)), "tags": r["tags"],
                  "shows": r.get("shows", r["tags"]), "audio": bool(r.get("audio")), "licensedContent": bool(ev.get("licensedContent", False)),
                  "place": r["place"], "subject": r.get("subject", r["id"]), **({"crop": r["crop"]} if r.get("crop") else {})})
lib = {"schema": "v6", "slug": R["slug"], "job": job.name, "notes": "Built by tools/footage_from_ranges.py from ranges.json.",
       "clips": clips, "banned": R.get("banned", []), "scarce": R.get("scarce", []), "autoqc_ack": R.get("autoqc_ack", [])}
(job / "footage.json").write_text(json.dumps(lib, indent=1, ensure_ascii=False))
print(json.dumps({"clips": len(clips), "missing": missing}))
sys.exit(1 if missing else 0)
