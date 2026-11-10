#!/usr/bin/env python3
"""Cookie-less 1080p range download for the Actions smoke test.

No cookies, no account credentials, no bot-check circumvention.
Writes result.json and, on success, the mp4. Exit 0 success, 2 bot-blocked, 1 other.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

BOT_MARKERS = (
    "sign in to confirm you",
    "confirm you are not a bot",
    "confirm you're not a bot",
    "not a bot",
    "bot check",
    "bot detected",
    "please sign in",
    "sign in to confirm your age",
    "use --cookies",
    "cookies for the authentication",
    "http error 429",
    "too many requests",
    "403: forbidden",
    "http error 403",
    "requested format is not available",  # often accompanies a block; classified below only with other markers
)

# Strong markers: definite bot/IP block. Weak ones need a second marker.
STRONG_BOT = (
    "sign in to confirm you",
    "confirm you are not a bot",
    "confirm you're not a bot",
    "bot check",
    "bot detected",
    "use --cookies",
    "cookies for the authentication",
    "http error 429",
    "too many requests",
)


def which(name: str) -> str | None:
    return shutil.which(name)


def classify(stderr: str, rc: int) -> str:
    s = (stderr or "").lower()
    if any(m in s for m in STRONG_BOT):
        return "bot_blocked"
    if "http error 403" in s or "403: forbidden" in s:
        return "bot_blocked"
    if "video unavailable" in s or "private video" in s or "is not available" in s:
        return "unavailable"
    if rc != 0:
        return "download_failed"
    return "ok"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--video-id", required=True)
    ap.add_argument("--start", type=float, default=0)
    ap.add_argument("--end", type=float, default=20)
    ap.add_argument("--outdir", default="out/smoke")
    args = ap.parse_args()
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    ytdlp = which("yt-dlp")
    ffmpeg = which("ffmpeg")
    result = {
        "created": datetime.now(timezone.utc).isoformat(),
        "video_id": args.video_id,
        "url": f"https://www.youtube.com/watch?v={args.video_id}",
        "start": args.start,
        "end": args.end,
        "format_goal": "1080p or best at or under 1080p, with audio, merged to mp4",
        "cookies": False,
        "credentials": False,
        "ytdlp": ytdlp,
        "ffmpeg": ffmpeg,
    }
    out = outdir / f"{args.video_id}_{int(args.start)}-{int(args.end)}.mp4"
    result_path = outdir / "result.json"

    def write() -> None:
        result_path.write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps(result, indent=2), flush=True)

    if not ytdlp or not ffmpeg:
        result["status"] = "missing_tools"
        result["error"] = "yt-dlp and ffmpeg must be on PATH"
        write()
        return 1

    fmt = (
        "bv*[height<=1080][ext=mp4]+ba[ext=m4a]/"
        "bv*[height<=1080]+ba/"
        "b[height<=1080][ext=mp4]/"
        "b[height<=1080]"
    )
    cmd = [
        ytdlp,
        "--no-warnings",
        "--no-playlist",
        "--newline",
        "-f", fmt,
        "--merge-output-format", "mp4",
        "--download-sections", f"*{args.start}-{args.end}",
        "--force-keyframes-at-cuts",
        "-o", str(out),
        result["url"],
    ]
    # Deliberately no --cookies, --cookies-from-browser, --username, --password, or PO-token flags.
    result["cmd"] = " ".join(cmd)
    print("+", " ".join(cmd), flush=True)
    proc = subprocess.run(cmd, text=True, capture_output=True)
    result["returncode"] = proc.returncode
    result["stdout_tail"] = (proc.stdout or "")[-2000:]
    result["stderr_tail"] = (proc.stderr or "")[-2000:]
    result["exists"] = out.exists()
    result["bytes"] = out.stat().st_size if out.exists() else 0
    result["status"] = classify(proc.stderr + "\n" + proc.stdout, proc.returncode)
    if result["status"] == "ok" and (not out.exists() or result["bytes"] < 10_000):
        result["status"] = "download_failed"
        result["error"] = "yt-dlp exited 0 but the output file is missing or tiny"

    if result["status"] == "ok" and ffmpeg:
        probe = subprocess.run(
            [ffmpeg, "-hide_banner", "-i", str(out)],
            text=True, capture_output=True,
        )
        # ffmpeg probe info is on stderr
        result["ffprobe_tail"] = (probe.stderr or "")[-1500:]
        dur_proc = subprocess.run(
            [
                "ffprobe", "-v", "error", "-show_entries", "format=duration,size",
                "-show_entries", "stream=codec_type,codec_name,width,height",
                "-of", "json", str(out),
            ],
            text=True, capture_output=True,
        )
        try:
            result["probe"] = json.loads(dur_proc.stdout or "{}")
        except json.JSONDecodeError:
            result["probe_raw"] = dur_proc.stdout

    write()
    if result["status"] == "ok":
        return 0
    if result["status"] == "bot_blocked":
        return 2
    return 1


if __name__ == "__main__":
    sys.exit(main())
