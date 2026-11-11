#!/usr/bin/env python3
"""set_thumb.py - set a designed (Bali banner) thumbnail on YouTube and record it.

  set_thumb.py --video-json V.json --id VID [--before-after out.png]   # pipeline videos (gated by thumb_gate.py)
  set_thumb.py --queue research/thumbs/queue.jsonl [--max N]           # run pending rows {id, file, sha256, video_json?}
thumbnails.set costs 50 units; stops at the first quotaExceeded (row stays pending). Runs gate.py publish first.
Records set {ok, at, video_id, sha256} in video.json and appends research/thumbs/set-log.jsonl."""
import argparse, hashlib, json, os, subprocess, sys, time, urllib.request
from datetime import datetime
HERE = os.path.dirname(os.path.abspath(__file__))
YT = "/workspace/handoff/aurum-youtube/tools/yt.py"
GATE = "/workspace/ops/scripts/gate.py"
LOG = "/workspace/handoff/aurum-youtube/research/thumbs/set-log.jsonl"
sys.path.insert(0, HERE); from thumb_gate import check  # noqa: E402

def now(): return datetime.now().astimezone().isoformat(timespec="seconds")
def sha(p): return hashlib.sha256(open(p, "rb").read()).hexdigest()
def log(r):
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    with open(LOG, "a") as f: f.write(json.dumps(r) + "\n")

def fetch_live(vid, out):
    for q in ("maxresdefault", "hqdefault"):
        try:
            b = urllib.request.urlopen(f"https://i.ytimg.com/vi/{vid}/{q}.jpg?t={int(time.time())}", timeout=20).read()
            open(out, "wb").write(b); return out
        except Exception: pass

def before_after(before, after, out):
    from PIL import Image, ImageDraw, ImageFont
    F = ImageFont.truetype("/usr/share/fonts/truetype/sand-box/google/Anton/Anton-Regular.ttf", 44)
    a, b = Image.open(before).convert("RGB").resize((960, 540)), Image.open(after).convert("RGB").resize((960, 540))
    im = Image.new("RGB", (1940, 620), "white"); im.paste(a, (0, 80)); im.paste(b, (980, 80)); d = ImageDraw.Draw(im)
    d.text((10, 10), "BEFORE (live frame grab)", font=F, fill="black"); d.text((990, 10), "AFTER (live on YouTube)", font=F, fill="black")
    os.makedirs(os.path.dirname(out), exist_ok=True); im.save(out); return out

def set_one(vid, f, h, vjp=None, before_after_out=None):
    if vjp:
        why = check(vjp)
        if why: return {"ok": False, "why": f"thumb gate: {why}"}
    from PIL import Image
    if Image.open(f).size != (1280, 720) or os.path.getsize(f) >= 2 * 1024 * 1024 or sha(f) != h:
        return {"ok": False, "why": "file not 1280x720/<2MB or sha changed"}
    g = subprocess.run(["python3", GATE, "publish", "--bot", "aurum-reels", "--what", f"YouTube thumbnail (Bali banner) on {vid}"], capture_output=True, text=True)
    if g.returncode: return {"ok": False, "why": f"gate.py publish exit {g.returncode}: {(g.stderr or g.stdout)[-200:]}"}
    before = None
    if before_after_out:
        before = before_after_out + ".before.jpg"
        if not os.path.exists(before): fetch_live(vid, before)
    p = subprocess.run([sys.executable, YT, "thumb", "--id", vid, "--thumb", f], capture_output=True, text=True)
    if p.returncode or "thumb ok" not in p.stdout:
        err = (p.stderr or p.stdout)[-300:]
        return {"ok": False, "why": "quotaExceeded" if "quota" in err.lower() else err}
    rec = {"ok": True, "at": now(), "video_id": vid, "sha256": h}
    if vjp:
        vj = json.load(open(vjp)); vj["thumbnail"]["set"] = rec; json.dump(vj, open(vjp, "w"), indent=1, ensure_ascii=False)
    if before_after_out and before:
        time.sleep(20); aft = fetch_live(vid, before_after_out + ".after.jpg")
        if aft: rec["before_after"] = before_after(before, aft, before_after_out)
    return rec

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--video-json"); ap.add_argument("--id"); ap.add_argument("--queue")
    ap.add_argument("--max", type=int, default=60); ap.add_argument("--before-after"); a = ap.parse_args()
    if a.video_json:
        vj = json.load(open(a.video_json)); t = vj.get("thumbnail") or {}
        r = set_one(a.id, t.get("file", ""), t.get("sha256", ""), a.video_json, a.before_after)
        log({"id": a.id, "file": t.get("file"), **r}); print(json.dumps(r)); sys.exit(0 if r.get("ok") else 2)
    rows = [json.loads(l) for l in open(a.queue) if l.strip()]
    done = {json.loads(l)["id"] for l in open(LOG) if l.strip() and json.loads(l).get("ok")} if os.path.exists(LOG) else set()
    n = 0; out = []
    for r in rows:
        if r["id"] in done or n >= a.max: continue
        res = set_one(r["id"], r["file"], r["sha256"], r.get("video_json"), r.get("before_after"))
        log({"id": r["id"], "file": r["file"], **res}); out.append({"id": r["id"], **res}); n += 1
        if res.get("why") == "quotaExceeded": break
    print(json.dumps({"attempted": len(out), "ok": sum(1 for x in out if x.get("ok")), "results": out}))

if __name__ == "__main__":
    main()
