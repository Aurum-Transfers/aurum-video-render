#!/usr/bin/env python3
"""Cheap per-shot frame sheet from shotlist + TTS timing (no Remotion)."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VDIR = ROOT / "videos" / "aruba-travel-guide"
CLIPS = Path("/workspace/work/aruba-full-v2/sources/clips")
OUT = Path("/workspace/work/aruba-full-v2/v3-framesheet")


def windows(timing: dict, end_extra: float):
    paras = timing["paragraphs"]
    total_s = timing["total"] + end_extra
    out = []
    for i, t in enumerate(paras):
        start = 0.0 if i == 0 else t["start"]
        end = paras[i + 1]["start"] if i + 1 < len(paras) else total_s
        out.append((t["id"], start, end, end - start))
    return out


def grab(src: Path, t: float, dest: Path):
    dest.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-ss", f"{max(0, t):.3f}",
         "-i", str(src), "-frames:v", "1", "-vf", "scale=640:-2", "-q:v", "4", str(dest)],
        check=False,
    )


def label_card(text: str, sub: str, dest: Path, kind: str = "MAP"):
    dest.parent.mkdir(parents=True, exist_ok=True)
    caption = f"{kind}\\n{text}\\n{sub}".replace(":", "\\:")
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", "color=c=0x0d1b24:s=640x360:d=0.1",
         "-vf", f"drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf:text='{caption}':"
                "fontcolor=white:fontsize=28:x=(w-text_w)/2:y=(h-text_h)/2:line_spacing=12",
         "-frames:v", "1", str(dest)],
        check=False,
    )


def main():
    sl = json.loads((VDIR / "shotlist.json").read_text())
    timing = json.loads((VDIR / "build" / "tts" / "long" / "timing.json").read_text())
    end_extra = json.loads((ROOT / "config" / "settings.json").read_text())["render"]["end_card_s"]
    entries = {e["id"]: e for e in sl["long"]}
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    index = []
    for pid, start, end, window in windows(timing, end_extra):
        shots = entries[pid]["shots"]
        weights = [float(s.get("weight", 1)) for s in shots]
        wsum = sum(weights)
        cur = start
        for j, s in enumerate(shots):
            dur = window * weights[j] / wsum
            kind = s["type"]
            rec = {"pid": pid, "j": j, "type": kind, "t0": round(cur, 3), "t1": round(cur + dur, 3), "dur": round(dur, 3)}
            if kind == "clip":
                cid = s["source_clip_id"]
                start_s = float(s.get("start_s") or 0)
                rec["clip"] = cid
                rec["start_s"] = start_s
                src = CLIPS / f"{cid}.mp4"
                for label, off in (("in", 0.15), ("mid", dur / 2), ("out", max(0.05, dur - 0.25))):
                    dest = OUT / f"{pid}_{j}_{cid}_{label}_{cur+off:.1f}s.jpg"
                    grab(src, start_s + off, dest)
                    rec.setdefault("frames", {})[label] = str(dest)
            else:
                dest = OUT / f"{pid}_{j}_{kind}_{cur:.1f}s.jpg"
                label_card(s.get("text") or kind, s.get("sub") or "", dest, kind.upper())
                rec["text"] = s.get("text")
                rec["sub"] = s.get("sub")
                rec["frames"] = {"card": str(dest)}
            index.append(rec)
            rows.append(rec)
            cur += dur
    (OUT / "index.json").write_text(json.dumps(index, indent=2))
    # montage all in-frames in order
    ins = []
    for rec in index:
        fr = rec.get("frames") or {}
        path = fr.get("in") or fr.get("card")
        if path and Path(path).exists():
            ins.append(path)
    # also include mid/out for clip shots in a second sheet
    thumbs = OUT / "thumbs"
    thumbs.mkdir(exist_ok=True)
    files = []
    for rec in index:
        fr = rec.get("frames") or {}
        for key in ("in", "mid", "out", "card"):
            if key in fr and Path(fr[key]).exists():
                files.append(fr[key])
    n = len(files)
    cols = 6
    rows_n = (n + cols - 1) // cols
    # tile via ffmpeg montage-like: scale + tile
    lst = OUT / "files.txt"
    lst.write_text("\n".join(files))
    # use imagemagick if present else ffmpeg tile in chunks
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"]
    filt = []
    for i, f in enumerate(files):
        cmd += ["-i", f]
        filt.append(f"[{i}:v]scale=320:180,setsar=1,drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf:"
                    f"text='{Path(f).stem[:40]}':fontcolor=white:fontsize=12:x=6:y=6:box=1:boxcolor=black@0.55[v{i}]")
    ins_s = "".join(f"[v{i}]" for i in range(n))
    filt.append(f"{ins_s}tile={cols}x{rows_n}[out]")
    cmd += ["-filter_complex", ";".join(filt), "-map", "[out]", "-q:v", "3", str(OUT / "contact.jpg")]
    subprocess.run(cmd, check=False)
    print(f"shots={len(index)} frames={n} contact={(OUT / 'contact.jpg').exists()} out={OUT}")
    over = [r for r in index if r["type"] == "clip"]
    print("clip shots", len(over))


if __name__ == "__main__":
    main()
