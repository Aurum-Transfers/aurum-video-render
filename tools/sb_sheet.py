#!/usr/bin/env python3
"""Contact sheet from downloaded YouTube storyboard jpgs (pool_screen.py). Picks ~N evenly spaced tiles, labels each
with its source time. usage: sb_sheet.py POOLDIR ID [ID...] [--n 24] -> POOLDIR/screen/ID/sheet-sb.jpg"""
import json, sys, pathlib, subprocess
from PIL import Image, ImageDraw
pool = pathlib.Path(sys.argv[1]); a = sys.argv[2:]
N = int(a[a.index("--n") + 1]) if "--n" in a else 24
ids = [x for x in a if not x.startswith("--") and not x.isdigit()]
rows = {r["id"]: r for r in json.load(open(pool / "screen.json"))}
for vid in ids:
    r = rows[vid]; sb = r.get("sb") or {}
    d = pool / "screen" / vid
    fr = sorted(d.glob("sb*.jpg"))
    if not fr or not sb.get("cols"):
        print(vid, "no storyboard"); continue
    cols, rws = sb["cols"], sb["rows"]
    tiles = []
    dur = r["duration"] or 1
    per = cols * rws
    total = min(len(fr) * per, int(dur * (sb.get("fps") or 0.5)) + 1) if sb.get("fps") else len(fr) * per
    step_t = dur / max(1, total)
    for k in range(N):
        i = int(k * total / N)
        f, j = divmod(i, per)
        if f >= len(fr): break
        im = Image.open(fr[f]); tw, th = im.width // cols, im.height // rws
        y, x = divmod(j, cols)
        t = im.crop((x * tw, y * th, x * tw + tw, y * th + th)).resize((240, 135))
        ImageDraw.Draw(t).text((3, 3), f"{int(i * step_t)//60}:{int(i * step_t)%60:02d}", fill=(255, 255, 0))
        tiles.append(t)
    W = 6; H = (len(tiles) + W - 1) // W
    sh = Image.new("RGB", (240 * W, 135 * H + 18))
    ImageDraw.Draw(sh).text((4, 2), f"{vid} {r['max_height']}p{r['fps']} {r['channel']} | {r['title'][:80]}", fill=(255, 255, 255))
    for k, t in enumerate(tiles):
        sh.paste(t, ((k % W) * 240, 18 + (k // W) * 135))
    sh.save(d / "sheet-sb.jpg", quality=80); print(d / "sheet-sb.jpg")
