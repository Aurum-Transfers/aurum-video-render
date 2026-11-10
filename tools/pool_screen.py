#!/usr/bin/env python3
"""Metadata + storyboard screening for a CC search pool (no video downloads).
usage: pool_screen.py POOLDIR [--place REGEX] [--exclude ID,ID]
For every hit in POOLDIR/cc-search.json: yt-dlp -J (cookie-less watch page) -> watchpage-licence.json evidence,
quality metadata (max height, fps, vcodec), hard pre-filter (CC BY, >=1080p, >=24 fps, title/desc names the place),
then the largest storyboard (sb0) sheets as tiny jpgs for visual screening. Output POOLDIR/screen.json"""
import json, subprocess, sys, os, re, datetime, pathlib, urllib.request, concurrent.futures as cf
pool = pathlib.Path(sys.argv[1]); args = sys.argv[2:]
place = re.compile(args[args.index("--place") + 1] if "--place" in args else "aruba", re.I)
excl = set((args[args.index("--exclude") + 1] if "--exclude" in args else "").split(","))
YT = os.path.expanduser("~/.local/bin/yt-dlp")
hits = json.load(open(pool / "cc-search.json"))["hits"]
now = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
prev = {}
if (pool / "screen.json").exists():
    prev = {r["id"]: r for r in json.load(open(pool / "screen.json"))}
def one(h):
    vid = h["id"]
    if vid in prev and "error" not in prev[vid]:
        return prev[vid]
    d = pool / "screen" / vid; d.mkdir(parents=True, exist_ok=True)
    r = subprocess.run([YT, "-J", "--no-warnings", f"https://www.youtube.com/watch?v={vid}"], capture_output=True, text=True, timeout=120)
    if r.returncode:
        return {"id": vid, "error": r.stderr[-200:]}
    j = json.loads(r.stdout)
    ev = {k: j.get(k) for k in ("id", "title", "channel", "channel_url", "uploader", "license", "duration", "upload_date", "width", "height")}
    ev["description"] = (j.get("description") or "")[:1500]; ev["checked_at"] = now
    ev["url"] = f"https://www.youtube.com/watch?v={vid}"; ev["method"] = "yt-dlp watch-page metadata, cookie-less"
    vf = [f for f in j.get("formats", []) if f.get("vcodec") not in (None, "none") and f.get("height") and not str(f.get("format_id", "")).startswith("sb")]
    mh = max((f["height"] for f in vf), default=0)
    fps = max((f.get("fps") or 0 for f in vf if f["height"] == mh), default=0)
    ev["max_height"] = mh; ev["fps_at_max"] = fps
    (d / "watchpage-licence.json").write_text(json.dumps(ev, indent=1))
    row = {"id": vid, "title": j.get("title"), "channel": j.get("channel"), "license": j.get("license"), "duration": j.get("duration"),
           "max_height": mh, "fps": fps, "queries": h.get("queries"), "evidence": str(d / "watchpage-licence.json")}
    txt = (j.get("title") or "") + " " + (j.get("description") or "")[:600]
    why = []
    if not (j.get("license") or "").startswith("Creative Commons Attribution"): why.append("not CC BY")
    if mh < 1080: why.append(f"{mh}p")
    if fps and fps < 24: why.append(f"{fps}fps")
    if not place.search(txt): why.append("place not named")
    if (j.get("duration") or 0) < 20: why.append("too short")
    if (j.get("duration") or 0) > 5400: why.append("over 90 min")
    row["reject"] = why
    if not why:
        sb = [f for f in j.get("formats", []) if str(f.get("format_id", "")).startswith("sb")]
        sb.sort(key=lambda f: -(f.get("width") or 0))
        if sb:
            f = sb[0]; frs = f.get("fragments") or []
            row["sb"] = {"w": f.get("width"), "h": f.get("height"), "rows": f.get("rows"), "cols": f.get("columns"), "fps": f.get("fps"), "n": len(frs)}
            for k, fr in enumerate(frs[:60]):
                p = d / f"sb{k:03d}.jpg"
                if not p.exists():
                    try:
                        urllib.request.urlretrieve(fr["url"], p)
                    except Exception as e:
                        row.setdefault("sb_err", str(e)[:100]); break
    return row
rows = []
with cf.ThreadPoolExecutor(6) as ex:
    for row in ex.map(one, [h for h in hits if h["id"] not in excl]):
        rows.append(row)
(pool / "screen.json").write_text(json.dumps(rows, indent=1))
ok = [r for r in rows if not r.get("reject") and "error" not in r]
print(json.dumps({"hits": len(rows), "pass_prefilter": len(ok), "errors": sum("error" in r for r in rows)}))
