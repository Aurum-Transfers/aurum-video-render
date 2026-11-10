"""render: build per-unit timelines (props) and render with Remotion, then mux narration with ffmpeg.

Video is rendered muted; the loudness-normalised narration is muxed in afterwards (AAC 48 kHz),
so loudness and sync are exactly what the tts phase produced. Music: none.
"""
from __future__ import annotations

import hashlib
import json
import os

from .assets import has_row, read_log
from .common import ROOT, PhaseError, load_json, log, media_duration, run, save_json, settings, tool
from .maps import map_for_slug
from .script import units

DISCLOSURE_DUR_S = 7.0
CHAPTER_DUR_S = 3.0
LOWER_DUR_S = 4.5


def _f(sec: float, fps: int) -> int:
    return int(round(sec * fps))


def disclosure_para(script, keyword: str):
    for p in script.paragraphs:
        if keyword.lower() in p.text.lower():
            return p
    return None


def build_timeline(unit: str, script, timing: dict, entries: list[dict], clips: dict, licence_rows: list[dict],
                   map_data: dict, meta: dict, cfg: dict, cues: list[dict] | None,
                   allow_fallback: bool = True) -> dict:
    fps = cfg["render"]["fps"]
    short = unit.startswith("short")
    w, h = (1080, 1920) if short else (1920, 1080)
    paras = timing["paragraphs"]
    end_extra = cfg["render"]["end_card_s"]
    total_s = timing["total"] + end_extra
    total = _f(total_s, fps)
    emap = {e["id"]: e for e in entries}
    missing = [p.id for p in script.paragraphs if p.id not in emap]
    if missing:
        raise PhaseError(f"{unit}: shotlist has no entry for {', '.join(missing)}")

    shots, lowers, chapters = [], [], []
    chapter_starts = {pid: i for i, (_, pid) in enumerate(script.chapters)}
    for i, t in enumerate(paras):
        start = 0.0 if i == 0 else t["start"]
        end = paras[i + 1]["start"] if i + 1 < len(paras) else total_s
        entry = emap[t["id"]]
        sl = entry["shots"]
        weights = [float(s.get("weight", 1)) for s in sl]
        cur = start
        for j, s in enumerate(sl):
            dur = (end - start) * weights[j] / sum(weights)
            shot = dict(s)
            if s["type"] == "clip":
                c = clips.get(f"{unit}/{t['id']}/{j}", {})
                if c.get("file"):
                    if not has_row(licence_rows, c["asset_id"]):
                        raise PhaseError(f"no licence row for {c['asset_id']}: refusing to use it")
                    shot = {**s, "src": c["file"]}
                elif allow_fallback and s.get("fallback"):
                    shot = {**s["fallback"], "fallback_for": "clip"}
                else:
                    raise PhaseError(f"{unit}/{t['id']}/{j}: clip has no asset and no fallback")
            shot.pop("queries", None)
            shot.pop("fallback", None)
            shot.update({"from": _f(cur, fps), "dur": max(1, _f(cur + dur, fps) - _f(cur, fps)), "key": f"{t['id']}-{j}"})
            shots.append(shot)
            cur += dur
        if t["id"] in chapter_starts and chapter_starts[t["id"]] > 0 and not short:
            idx = chapter_starts[t["id"]]
            chapters.append({"from": _f(t["start"], fps), "dur": _f(CHAPTER_DUR_S, fps), "index": idx,
                             "title": script.chapters[idx][0]})
        lt = entry.get("lower_third")
        if lt:
            delay = 0.6 + (CHAPTER_DUR_S if (t["id"] in chapter_starts and chapter_starts[t["id"]] > 0) else 0)
            lowers.append({"from": _f(t["start"] + delay, fps), "dur": _f(LOWER_DUR_S, fps), **lt})

    dp = disclosure_para(script, cfg["disclosure"]["keyword"])
    if not dp:
        raise PhaseError(f"{unit}: no spoken disclosure paragraph (keyword '{cfg['disclosure']['keyword']}')")
    dstart = next(t["start"] for t in paras if t["id"] == dp.id)
    disclosure = {"from": _f(dstart, fps), "dur": _f(DISCLOSURE_DUR_S, fps), "text": cfg["disclosure"]["onscreen"]}

    last = paras[-1]
    end_from = _f(last["end"] + 0.3, fps)
    tl = {
        "unit": unit, "width": w, "height": h, "fps": fps, "durationInFrames": total, "portrait": short,
        "title": script.title, "map": map_data, "shots": shots, "chapters": chapters, "lowerThirds": lowers,
        "disclosure": disclosure,
        "captions": [{"from": _f(c["start"], fps), "dur": max(1, _f(c["end"], fps) - _f(c["start"], fps)),
                      "text": c["text"]} for c in (cues or [])] if short else [],
        "endCard": {"from": min(end_from, total - _f(2, fps)), "dur": total - min(end_from, total - _f(2, fps)),
                    "title": meta["end_card"]["title"], "lines": meta["end_card"]["lines"]},
        "brand": cfg["brand"],
    }
    return tl


def timelines(ctx) -> dict[str, dict]:
    cfg = settings()
    meta = load_json(ctx.paths.video / "video.json")
    shotlist = load_json(ctx.paths.video / "shotlist.json")
    clips = load_json(ctx.paths.build / "assets.json")["clips"]
    rows = read_log(ctx.paths.licence_log)
    map_data = map_for_slug(ctx.paths.video)
    plan_path = ctx.paths.video / "used-sources.json"
    plan = load_json(plan_path) if plan_path.exists() else None
    allow_fallback = False  # post-Bali spec: graphics fallback always fails the build (was plan-controlled)
    wanted = set(getattr(ctx, "units", None) or [])
    out = {}
    for unit, script in units(ctx.paths.video).items():
        if wanted and unit not in wanted:
            continue
        timing = load_json(ctx.paths.tts / unit / "timing.json")
        cues = load_json(ctx.paths.build / f"cues-{unit}.json", default=[]) if unit.startswith("short") else None
        if unit.startswith("short") and not cues:
            raise PhaseError(f"{unit}: captions missing; run the captions phase first")
        tl = build_timeline(unit, script, timing, shotlist.get(unit, []), clips, rows, map_data, meta, cfg, cues,
                            allow_fallback=allow_fallback)
        fps = tl["fps"]
        max_hold = fps  # 1 second
        for s in tl["shots"]:
            if s.get("src"):
                s["clipFrames"] = max(30, int(media_duration(ctx.paths.public / s["src"]) * fps) - 2)
                start_from = int(round(float(s.get("start_s") or 0) * fps))
                if start_from < 0:
                    raise PhaseError(f"{unit}/{s.get('key')}: start_s must be >= 0")
                if start_from >= s["clipFrames"]:
                    raise PhaseError(f"{unit}/{s.get('key')}: start_s exceeds clip length")
                s["startFrom"] = start_from
                usable = max(1, s["clipFrames"] - start_from)
                if s["dur"] > usable + max_hold:
                    raise PhaseError(
                        f"{unit}/{s.get('key')}: shot {s['dur']}f exceeds usable clip "
                        f"{usable}f + 1s hold (start_s={s.get('start_s') or 0})"
                    )
        out[unit] = tl
    return out


def out_name(unit: str, stem: str | None = None) -> str:
    if unit == "long":
        return f"{stem or 'long'}.mp4"
    return f"{unit}.mp4"


def remotion_common(ctx) -> list[str]:
    args = [f"--public-dir={ctx.paths.public}"]
    browser = os.environ.get("REMOTION_BROWSER_EXECUTABLE")
    if browser:
        args.append(f"--browser-executable={browser}")
    # System Google Chrome crashed the page around the first large clip
    # (frame 384, start of drone_reef_b). Use Remotion's headless shell,
    # software GL, a small OffthreadVideo cache, and disk capture so the
    # compositor does not exhaust /dev/shm or RAM.
    args += [
        "--chrome-mode=headless-shell",
        "--gl=swangle",
        "--disable-shared-memory-capture",
        "--offthreadvideo-video-threads=1",
        "--offthreadvideo-cache-size-in-bytes=268435456",
        "--timeout=120000",
    ]
    return args


def concurrency(ctx) -> int:
    pre = load_json(ctx.paths.build / "prereqs.json", default={})
    ram = pre.get("free_ram_gb")
    c = settings()["render"]["concurrency"]
    return 1 if (ram is not None and ram < 4) else max(1, min(2, c))


def run_phase(ctx) -> dict:
    rdir = ROOT / "remotion"
    ff = tool("ffmpeg") or "ffmpeg"
    tls = timelines(ctx)
    only = set(ctx.units) if ctx.units else set(tls)
    summary = {}
    for unit, tl in tls.items():
        if unit not in only:
            continue
        props = ctx.paths.build / f"timeline-{unit}.json"
        save_json(props, tl)
        narration = ctx.paths.public / f"narration-{unit}.wav"
        digest = hashlib.sha1((json.dumps(tl, sort_keys=True) + str(narration.stat().st_mtime_ns)
                               + _remotion_src_digest()).encode()).hexdigest()
        final = ctx.paths.out / out_name(unit, getattr(ctx, 'output_stem', None))
        stamp = ctx.paths.build / f"render-{unit}.sha1"
        if final.exists() and stamp.exists() and stamp.read_text().strip() == digest and not ctx.force:
            log(f"{unit}: unchanged, skipping render")
            summary[unit] = str(final.relative_to(ROOT))
            continue
        silent = ctx.paths.build / f"video-{unit}.mp4"
        comp = "Short" if tl["portrait"] else "Long"
        run(["npx", "remotion", "render", "src/index.ts", comp, str(silent), f"--props={props}",
             f"--concurrency={concurrency(ctx)}", "--muted", "--codec=h264", "--crf=20",
             "--pixel-format=yuv420p", "--log=warn", *remotion_common(ctx)], cwd=rdir)
        run([ff, "-hide_banner", "-loglevel", "error", "-y", "-i", str(silent), "-i", str(narration),
             "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
             "-af", "apad", "-shortest", "-movflags", "+faststart", str(final)])
        stamp.write_text(digest)
        summary[unit] = str(final.relative_to(ROOT))
    return summary


def _remotion_src_digest() -> str:
    h = hashlib.sha1()
    for p in sorted((ROOT / "remotion" / "src").rglob("*")):
        if p.is_file():
            h.update(p.read_bytes())
    return h.hexdigest()
