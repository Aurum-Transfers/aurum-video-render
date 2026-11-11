#!/usr/bin/env python3
"""make_banner.py - Aurum 'Bali standard' YouTube thumbnail (Marvin 11 Nov 3:45 PM: every video gets a banner on par with Bali).

Background: photoreal destination scene at sunset with a jetliner flying over (AI image, made with GenerateImage using the live
Bali thumbnail as style reference; real-place photo as likeness reference). Overlay: very bold condensed text stacked on the
left, white lines then yellow line(s), thick black outline (Anton). Output 1280x720 JPEG < 2 MB.

  make_banner.py --bg bg.jpg --out thumb/banner.jpg --lines "BEFORE|YOU LAND|ARUBA 2026" [--yellow 1] [--video-json video.json]
--yellow N: the last N lines are yellow. --video-json records {"thumbnail": {file, sha256, bytes, size, style, bg}} in video.json.
"""
import argparse, hashlib, json, os
from PIL import Image, ImageDraw, ImageFont, ImageFilter
FONT = "/usr/share/fonts/truetype/sand-box/google/Anton/Anton-Regular.ttf"
FALLBACK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets/fonts/BebasNeue-Regular.ttf")
W, H, MAX_BYTES = 1280, 720, 2 * 1024 * 1024
WHITE, YELLOW, BLACK = (255, 255, 255), (255, 214, 0), (0, 0, 0)
STYLE = "bali-banner-v1"

def font(sz):
    return ImageFont.truetype(FONT if os.path.exists(FONT) else FALLBACK, sz)

def render(bg, lines, yellow, col_w=600, x0=34, top=26, bottom=26, gap=4):
    im = Image.open(bg).convert("RGB")
    if im.size != (W, H):  # cover-crop to 16:9 then resize
        r = max(W / im.width, H / im.height); im = im.resize((round(im.width * r), round(im.height * r)), Image.LANCZOS)
        l, t = (im.width - W) // 2, (im.height - H) // 2; im = im.crop((l, t, l + W, t + H))
    d0 = ImageDraw.Draw(im)
    # size each line to fill the column width, then scale all down together if the stack is too tall
    sizes = []
    for ln in lines:
        s = 400
        while s > 20 and d0.textlength(ln, font=font(s)) > col_w: s -= 2
        sizes.append(s)
    def stack_h(sz): return sum(font(s).getbbox(ln)[3] - font(s).getbbox(ln)[1] for ln, s in zip(lines, sz)) + gap * (len(lines) - 1)
    k = 1.0
    while stack_h([int(s * k) for s in sizes]) > H - top - bottom and k > 0.3: k -= 0.01
    sizes = [int(s * k) for s in sizes]
    # cap so a short line (e.g. "2026") isn't gigantic compared with the rest
    cap = int(sorted(sizes)[len(sizes) // 2] * 1.15); sizes = [min(s, cap) for s in sizes]
    y = top + max(0, (H - top - bottom - stack_h(sizes)) // 2)
    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0)); ds = ImageDraw.Draw(shadow)
    txt = Image.new("RGBA", (W, H), (0, 0, 0, 0)); dt = ImageDraw.Draw(txt)
    for i, (ln, s) in enumerate(zip(lines, sizes)):
        f = font(s); bb = f.getbbox(ln); col = YELLOW if i >= len(lines) - yellow else WHITE
        sw = max(5, s // 22)
        ds.text((x0 + 6, y - bb[1] + 8), ln, font=f, fill=(0, 0, 0, 200), stroke_width=sw, stroke_fill=(0, 0, 0, 200))
        dt.text((x0, y - bb[1]), ln, font=f, fill=col, stroke_width=sw, stroke_fill=BLACK)
        y += (bb[3] - bb[1]) + gap
    im = Image.alpha_composite(im.convert("RGBA"), shadow.filter(ImageFilter.GaussianBlur(6)))
    return Image.alpha_composite(im, txt).convert("RGB")

def save(im, out):
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    for q in (92, 88, 84, 80, 75):
        im.save(out, "JPEG", quality=q, optimize=True, progressive=True)
        if os.path.getsize(out) < MAX_BYTES: return
    raise SystemExit("banner still >= 2 MB")

def sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--bg", required=True); ap.add_argument("--out", required=True)
    ap.add_argument("--lines", required=True); ap.add_argument("--yellow", type=int, default=1); ap.add_argument("--video-json")
    a = ap.parse_args(); lines = [x.strip().upper() for x in a.lines.split("|") if x.strip()]
    save(render(a.bg, lines, a.yellow), a.out)
    info = {"file": os.path.abspath(a.out), "sha256": sha(a.out), "bytes": os.path.getsize(a.out), "size": [W, H],
            "style": STYLE, "lines": lines, "bg": os.path.abspath(a.bg), "bg_sha256": sha(a.bg)}
    if a.video_json:
        vj = json.load(open(a.video_json)); old = vj.get("thumbnail") if isinstance(vj.get("thumbnail"), dict) else {}
        vj["thumbnail"] = {**info, "set": old.get("set") if old.get("sha256") == info["sha256"] else None}
        vj["thumb"] = os.path.relpath(os.path.abspath(a.out), os.path.dirname(os.path.abspath(a.video_json)))
        json.dump(vj, open(a.video_json, "w"), indent=1, ensure_ascii=False)
    print(json.dumps(info))

if __name__ == "__main__":
    main()
