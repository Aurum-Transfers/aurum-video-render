"""Download allowed YouTube sources and cut the explicit used-sources clips.

Cookie-less yt-dlp only. No login, cookies, or bot-block circumvention.
If a watch-page licence is no longer Creative Commons Attribution, skip that source.
Mute every clip. Prefer 1080p (good enough for a 1920x1080 render) over huge 4K files.

Usage:
    python tools/prepare_used_clips.py --slug aruba-travel-guide --library assets/cc-library/aruba-full-v2-sources
"""
from __future__ import annotations

import argparse
import os
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CC_MARKERS = ("creative commons attribution", "cc by", "creativecommon")


def which(name: str) -> str | None:
    found = shutil.which(name)
    if found:
        return found
    ext = ".exe" if os.name == "nt" else ""
    local = Path(sys.executable).parent / f"{name}{ext}"
    if local.exists():
        return str(local)
    return None


def run(cmd: list[str], timeout: int = 600) -> subprocess.CompletedProcess:
    print("+", " ".join(cmd), flush=True)
    return subprocess.run(cmd, check=True, timeout=timeout)


def licence_ok(video_id: str, ytdlp: str) -> tuple[bool, str]:
    url = f"https://www.youtube.com/watch?v={video_id}"
    # Default yt-dlp is cookie-less; do not pass --cookies or --cookies-from-browser.
    lic = subprocess.check_output(
        [ytdlp, "--no-warnings", "--skip-download", "--print", "%(license)s", url],
        text=True, timeout=120,
    ).strip()
    ok = any(m in lic.lower() for m in CC_MARKERS)
    return ok, lic


def download(video_id: str, dest: Path, ytdlp: str) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    # 1080p (or the best video at or under 1080). Mute happens at the cut step.
    fmt = (
        "bestvideo[height<=1080][ext=mp4]/"
        "bestvideo[height<=1080]/"
        "best[height<=1080][ext=mp4]/"
        "best[height<=1080]"
    )
    archive = dest.with_suffix(".download")
    run([
        ytdlp, "--no-warnings", "--no-playlist",
        "-f", fmt, "--merge-output-format", "mp4",
        "-o", str(archive.with_suffix(".%(ext)s")),
        f"https://www.youtube.com/watch?v={video_id}",
    ], timeout=1800)
    found = None
    for cand in dest.parent.glob(archive.stem + ".*"):
        if cand.suffix.lower() in {".mp4", ".mkv", ".webm", ".mov"}:
            found = cand
            break
    if not found:
        raise SystemExit(f"yt-dlp finished but no media file for {video_id}")
    if found != dest:
        if dest.exists():
            dest.unlink()
        found.replace(dest)
    return dest


def cut_clip(ffmpeg: str, src: Path, dest: Path, start: float, end: float, speed: float) -> None:
    """Seek on the input (-ss/-t before -i). Putting -ss after -i together with setpts
    drops every frame on ffmpeg 8 / VP9 (empty 261-byte MP4, exit 0)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".part.mp4")
    dur = max(0.001, end - start)
    speed = float(speed or 1.0)
    filt = "scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080,fps=30"
    if abs(speed - 1.0) > 1e-6:
        filt = f"setpts=PTS/{speed}," + filt
    run([
        ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
        "-ss", f"{start:.3f}", "-t", f"{dur:.3f}", "-i", str(src),
        "-an", "-vf", filt, "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-crf", "18", "-movflags", "+faststart", str(tmp),
    ], timeout=600)
    if not tmp.exists() or tmp.stat().st_size < 10_000:
        raise SystemExit(f"ffmpeg wrote an empty cut: {tmp}")
    tmp.replace(dest)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug", default="aruba-travel-guide")
    ap.add_argument("--library", default="assets/cc-library/aruba-full-v2-sources")
    ap.add_argument("--skip-download", action="store_true")
    args = ap.parse_args()
    ytdlp = which("yt-dlp")
    ffmpeg = which("ffmpeg")
    if not ytdlp or not ffmpeg:
        print("need yt-dlp and ffmpeg on PATH", file=sys.stderr)
        return 2
    plan_path = ROOT / "videos" / args.slug / "used-sources.json"
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    lib = Path(args.library)
    if not lib.is_absolute():
        lib = ROOT / lib
    clips_dir = lib / "clips"
    clips_dir.mkdir(parents=True, exist_ok=True)
    report = {"checked_at_local": None, "sources": [], "clips": [], "skipped": []}
    import datetime
    report["checked_at_local"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    for src in plan["sources"]:
        vid = src["video_id"]
        ok, lic = licence_ok(vid, ytdlp)
        entry = {"video_id": vid, "licence": lic, "cc_by": ok}
        report["sources"].append(entry)
        print(f"licence {vid}: {lic!r} cc_by={ok}", flush=True)
        if not ok:
            report["skipped"].append({"video_id": vid, "reason": f"licence not CC BY on watch page: {lic}"})
            continue
        master = lib / f"{vid}.mp4"
        if not args.skip_download and not master.exists():
            try:
                download(vid, master, ytdlp)
            except (subprocess.CalledProcessError, SystemExit) as e:
                report["skipped"].append({"video_id": vid, "reason": f"download failed: {e}"})
                print(f"SKIP download {vid}: {e}", flush=True)
                continue
        if not master.exists():
            report["skipped"].append({"video_id": vid, "reason": "master file missing"})
            continue
        for c in src["clips"]:
            dest = clips_dir / f"{c['clip_id']}.mp4"
            try:
                cut_clip(ffmpeg, master, dest, float(c["source_in_s"]), float(c["source_out_s"]),
                         float(c.get("speed") or 1))
                size = dest.stat().st_size
                report["clips"].append({"clip_id": c["clip_id"], "file": str(dest), "bytes": size})
                print(f"cut {c['clip_id']} -> {dest} ({size} bytes)", flush=True)
            except subprocess.CalledProcessError as e:
                report["skipped"].append({"clip_id": c["clip_id"], "reason": f"ffmpeg failed: {e}"})
    out = lib / "prepare-report.json"
    out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {out}: {len(report['clips'])} clips, {len(report['skipped'])} skipped")
    return 0 if report["clips"] and not report["skipped"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
