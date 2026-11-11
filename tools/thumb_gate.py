#!/usr/bin/env python3
"""thumb_gate.py <video.json> [--require-set] [--id VIDEO_ID]
Hard gate (Marvin 11 Nov: every video gets a banner on par with Bali). Exit 0 = pass, 2 = blocked (reason on stderr).
Checks: video.json "thumbnail" was made by make_banner.py (style bali-banner-*), file exists, sha256 matches the record,
1280x720, < 2 MB, and video.json "thumb" points at it (never the package frame grab thumb/thumb.jpg).
--require-set: also needs thumbnail.set.ok for this sha (and this video id when --id is given)."""
import hashlib, json, os, sys
from PIL import Image
MAX = 2 * 1024 * 1024

def check(vjp, require_set=False, vid=None):
    vj = json.load(open(vjp)); t = vj.get("thumbnail")
    if not isinstance(t, dict): return "no designed thumbnail recorded (run make_banner.py --video-json)"
    if not str(t.get("style", "")).startswith("bali-banner"): return f"thumbnail style {t.get('style')!r} is not the Bali banner"
    f = t.get("file") or ""
    if not os.path.isfile(f): return f"thumbnail file missing: {f}"
    if os.path.getsize(f) >= MAX: return f"thumbnail {os.path.getsize(f)} B >= 2 MB"
    if Image.open(f).size != (1280, 720): return f"thumbnail is {Image.open(f).size}, not 1280x720"
    h = hashlib.sha256(open(f, "rb").read()).hexdigest()
    if h != t.get("sha256"): return "thumbnail sha256 differs from the one recorded in video.json"
    rel = vj.get("thumb")
    if not rel or os.path.realpath(os.path.join(os.path.dirname(os.path.abspath(vjp)), rel)) != os.path.realpath(f):
        return f'video.json "thumb" ({rel}) is not the designed banner'
    if require_set:
        s = t.get("set") or {}
        if not (s.get("ok") and s.get("sha256") == h): return "designed thumbnail not yet set successfully on YouTube"
        if vid and s.get("video_id") != vid: return f"thumbnail was set on {s.get('video_id')}, not {vid}"
    return None

if __name__ == "__main__":
    args = sys.argv[1:]; vid = args[args.index("--id") + 1] if "--id" in args else None
    why = check(args[0], "--require-set" in args, vid)
    if why: print(f"THUMB GATE BLOCKED: {why}", file=sys.stderr); sys.exit(2)
    print("THUMB GATE OK"); sys.exit(0)
