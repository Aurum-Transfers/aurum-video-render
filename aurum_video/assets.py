"""assets: attach licensed clips to shotlist 'clip' shots and log a licence row per asset.

Preferred path: videos/<slug>/used-sources.json lists explicit CC BY (or other allowed)
clips with source in/out/speed. Those are cut from a local library and must already have
licence evidence. This path does not need Pexels/Pixabay keys.

Legacy path (no used-sources.json): search Pexels, Pixabay, then CC BY YouTube. A clip
that cannot be sourced may use a declared own-graphics fallback only when no explicit
plan is present. An explicit plan with allow_graphics_fallback=false is fail-closed:
missing real footage fails; zero sourced clips fails; fallback is not written.

No row, no use: render refuses any file without a licence row.
"""
from __future__ import annotations

import csv
import json
import os
import shutil
from pathlib import Path

from .common import ROOT, PhaseError, ffprobe_json, load_json, log, run, save_json, scrub, today, tool

LOG_FIELDS = ["asset_id", "file", "source", "creator", "url", "licence", "date", "used_in"]
UA = {"User-Agent": "aurum-videos/1.0 (+https://aurum-transfers.com)"}


# ---------- licence log ----------
def read_log(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_log(path: Path, rows: list[dict]) -> None:
    rows = sorted({r["asset_id"]: r for r in rows}.values(), key=lambda r: r["asset_id"])
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=LOG_FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in LOG_FIELDS})


def has_row(rows: list[dict], asset_id: str) -> bool:
    return any(r["asset_id"] == asset_id and r.get("licence") and r.get("url") for r in rows)


# ---------- sources ----------
def _get(url, **kw):
    import requests

    r = requests.get(url, timeout=60, **kw)
    r.raise_for_status()
    return r


def _download(url: str, dest: Path) -> None:
    import requests

    tmp = dest.with_suffix(".part")
    with requests.get(url, stream=True, timeout=120, headers=UA) as r:
        r.raise_for_status()
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
    os.replace(tmp, dest)


def search_pexels(query: str, orientation: str, min_w: int, used: set) -> dict | None:
    key = os.environ.get("PEXELS_API_KEY")
    if not key:
        return None
    data = _get("https://api.pexels.com/videos/search",
                params={"query": query, "orientation": orientation, "per_page": 20, "size": "medium"},
                headers={"Authorization": key, **UA}).json()
    for v in data.get("videos", []):
        aid = f"pexels-{v['id']}"
        if aid in used or v.get("duration", 0) < 6:
            continue
        files = [f for f in v.get("video_files", []) if f.get("file_type") == "video/mp4"
                 and min(f.get("width") or 0, f.get("height") or 0) >= 720]
        files.sort(key=lambda f: abs((f.get("width") or 0) - min_w))
        if not files:
            continue
        return {"asset_id": aid, "download": files[0]["link"], "source": "Pexels",
                "creator": v.get("user", {}).get("name", ""), "url": v["url"], "licence": "Pexels License"}
    return None


def search_pixabay(query: str, orientation: str, min_w: int, used: set) -> dict | None:
    key = os.environ.get("PIXABAY_API_KEY")
    if not key:
        return None
    data = _get("https://pixabay.com/api/videos/",
                params={"key": key, "q": query, "per_page": 20, "safesearch": "true"}, headers=UA).json()
    for h in data.get("hits", []):
        aid = f"pixabay-{h['id']}"
        if aid in used or h.get("duration", 0) < 6:
            continue
        vids = h.get("videos", {})
        pick = next((vids[s] for s in ("large", "medium") if vids.get(s, {}).get("url")), None)
        if not pick:
            continue
        portrait = (pick.get("height") or 0) > (pick.get("width") or 0)
        if (orientation == "portrait") != portrait and orientation != "any":
            continue
        return {"asset_id": aid, "download": pick["url"], "source": "Pixabay", "creator": h.get("user", ""),
                "url": h.get("pageURL", ""), "licence": "Pixabay Content License"}
    return None


def youtube_ccby(query: str, used: set, need_s: float) -> dict | None:
    """Search YouTube, keep only videos whose watch page states CC BY today."""
    ytdlp = tool("yt-dlp")
    if not ytdlp:
        return None
    res = run([ytdlp, "--flat-playlist", "-J", f"ytsearch15:{query}"], capture=True, check=False, timeout=180)
    if res.returncode != 0:
        return None
    for e in json.loads(res.stdout).get("entries", []):
        vid = e.get("id")
        aid = f"youtube-{vid}"
        if not vid or aid in used:
            continue
        info = run([ytdlp, "-J", "--skip-download", f"https://www.youtube.com/watch?v={vid}"],
                   capture=True, check=False, timeout=180)
        if info.returncode != 0:
            continue
        meta = json.loads(info.stdout)
        lic = (meta.get("license") or "")
        if "creative commons attribution" not in lic.lower():
            continue
        dur = float(meta.get("duration") or 0)
        if dur < need_s + 20:
            continue
        start = max(10.0, dur * 0.35)
        return {"asset_id": aid, "source": "YouTube (CC BY)", "creator": meta.get("uploader", ""),
                "url": f"https://www.youtube.com/watch?v={vid}", "licence": f"{lic} (checked on watch page {today()})",
                "yt": {"id": vid, "start": round(start, 1), "end": round(start + need_s + 2, 1)}}
    return None


def _download_youtube(hit: dict, dest: Path) -> None:
    y = hit["yt"]
    run([tool("yt-dlp"), "-q", "--no-playlist", "-f", "bv*[ext=mp4][height<=1080]/bv*[height<=1080]",
         "--download-sections", f"*{y['start']}-{y['end']}", "--force-keyframes-at-cuts",
         "-o", str(dest), f"https://www.youtube.com/watch?v={y['id']}"], timeout=600)



# ---------- explicit used-sources ingest ----------
def load_used_sources(video_dir: Path) -> dict | None:
    path = video_dir / "used-sources.json"
    if not path.exists():
        return None
    return load_json(path)


def flatten_plan_clips(plan: dict) -> dict[str, dict]:
    out = {}
    for src in plan.get("sources", []):
        for c in src.get("clips", []):
            out[c["clip_id"]] = {**c, "video_id": src["video_id"], "url": src["url"],
                                 "creator": src["creator"], "title": src.get("title", ""),
                                 "licence": src["licence"], "licence_checked_at": src.get("licence_checked_at", ""),
                                 "licence_evidence": src.get("licence_evidence", ""),
                                 "mute": src.get("mute", True)}
    return out


def library_roots(plan: dict) -> list[Path]:
    roots: list[Path] = []
    env = os.environ.get("AURUM_FOOTAGE_LIBRARY")
    if env:
        roots.append(Path(env))
    if plan.get("library_dir"):
        roots.append(Path(plan["library_dir"]))
    for h in plan.get("library_dir_hints", []):
        hp = Path(h)
        roots.append(hp if hp.is_absolute() else ROOT / hp)
    out, seen = [], set()
    for r in roots:
        r = r.resolve() if r.exists() else r
        if r in seen:
            continue
        seen.add(r)
        out.append(r)
    return out


def resolve_source_file(video_id: str, plan: dict) -> Path | None:
    names = [f"{video_id}.mp4", f"{video_id}.mkv", f"{video_id}.webm", f"{video_id}.MP4"]
    for r in library_roots(plan):
        for n in names:
            cand = r / n
            if cand.exists() and cand.stat().st_size > 0:
                return cand
    return None


def resolve_prepared_clip(clip_id: str, plan: dict) -> Path | None:
    """A pre-cut muted 1920x1080 segment, used so each transfer stays under 100 MiB."""
    names = [f"{clip_id}.mp4", f"clips/{clip_id}.mp4"]
    for r in library_roots(plan):
        for n in names:
            cand = r / n
            if cand.exists() and cand.stat().st_size > 0:
                return cand
    return None


def prepare_clip(src: Path, dest: Path, start: float, end: float, speed: float,
                 whole_file: bool = False) -> None:
    ff = tool("ffmpeg") or "ffmpeg"
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".part.mp4")
    filt = "scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080,fps=30"
    speed = float(speed or 1.0)
    if not whole_file and abs(speed - 1.0) > 1e-6:
        filt = f"setpts=PTS/{speed}," + filt
    cmd = [ff, "-hide_banner", "-loglevel", "error", "-y"]
    if not whole_file:
        # Input seek. -ss after -i plus setpts drops all frames on ffmpeg 8 / VP9.
        dur = max(0.001, float(end) - float(start))
        cmd += ["-ss", f"{float(start):.3f}", "-t", f"{dur:.3f}"]
    cmd += ["-i", str(src), "-an", "-vf", filt, "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-crf", "18", "-movflags", "+faststart", str(tmp)]
    run(cmd, timeout=600)
    if not tmp.exists() or tmp.stat().st_size < 10_000:
        raise PhaseError(f"ffmpeg wrote an empty cut: {tmp}")
    os.replace(tmp, dest)


def is_ready_mezzanine(path: Path) -> bool:
    """True when a pre-cut clip is already muted 1920x1080 30fps h264 and can be staged as-is."""
    if not path.exists() or path.stat().st_size < 10_000:
        return False
    info = ffprobe_json(path)
    videos = [s for s in info.get("streams", []) if s.get("codec_type") == "video"]
    audios = [s for s in info.get("streams", []) if s.get("codec_type") == "audio"]
    if len(videos) != 1 or audios:
        return False
    v = videos[0]
    rate = v.get("r_frame_rate") or "0/1"
    try:
        num, den = rate.split("/")
        fps = float(num) / float(den or 1)
    except ValueError:
        fps = 0.0
    return (v.get("codec_name") == "h264" and v.get("width") == 1920 and v.get("height") == 1080
            and v.get("pix_fmt") == "yuv420p" and abs(fps - 30.0) < 0.01)


def stage_clip(src: Path, dest: Path, start: float, end: float, speed: float,
               whole_file: bool = False) -> None:
    """Stage a clip into remotion public. Compliant pre-cuts are hardlinked or copied, not re-encoded."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if whole_file and is_ready_mezzanine(src):
        if dest.exists():
            try:
                if dest.samefile(src):
                    return
            except OSError:
                pass
            dest.unlink()
        try:
            os.link(src, dest)
        except OSError:
            shutil.copy2(src, dest)
        if not dest.exists() or dest.stat().st_size < 10_000:
            raise PhaseError(f"failed to stage pre-cut clip: {dest}")
        return
    prepare_clip(src, dest, start, end, speed, whole_file=whole_file)


# ---------- phase ----------
def clip_shots(shotlist: dict):
    for unit, entries in shotlist.items():
        if unit.startswith("_"):
            continue
        for e in entries:
            for i, s in enumerate(e.get("shots", [])):
                if s.get("type") == "clip":
                    yield unit, e["id"], i, s


def _log_static_registry(ctx, rows, manifest, failures):
    reg = load_json(ROOT / "assets" / "registry.json")
    for a in reg["assets"]:
        if not (ROOT / a["file"]).exists():
            failures.append(f"registry file missing: {a['file']}")
            continue
        rows[:] = [r for r in rows if r["asset_id"] != a["asset_id"]]
        rows.append({**{k: a.get(k, "") for k in LOG_FIELDS}, "date": today(), "used_in": ctx.slug})
        manifest["static"].append(a["asset_id"])
        if a.get("public"):
            dest = ctx.paths.public / a["public"]
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / a["file"], dest)
    return rows


def _ingest_explicit(ctx, shotlist, plan, rows, manifest, failures, warnings):
    """Cut explicit plan clips; fail closed when footage or licence evidence is missing."""
    if plan.get("allow_graphics_fallback", False):
        warnings.append("used-sources.json allows graphics fallback; unexpected for the improved cut")
    needed = {}
    units = set(getattr(ctx, "units", None) or [])
    for unit, pid, idx, shot in clip_shots(shotlist):
        if units and unit not in units:
            continue
        cid = shot.get("source_clip_id")
        key = f"{unit}/{pid}/{idx}"
        if not cid:
            failures.append(f"{key}: clip shot has no source_clip_id and used-sources.json is present")
            continue
        needed.setdefault(cid, []).append(key)
    catalog = flatten_plan_clips(plan)
    staged: dict[str, dict] = {}
    for cid, keys in needed.items():
        meta = catalog.get(cid)
        if not meta:
            failures.append(f"{cid}: not listed in used-sources.json (needed by {', '.join(keys)})")
            continue
        if not (meta.get("licence") and meta.get("url") and meta.get("creator") and meta.get("licence_checked_at")):
            failures.append(f"{cid}: incomplete licence evidence (need licence, url, creator, licence_checked_at)")
            continue
        pre_cut = resolve_prepared_clip(cid, plan)
        src = pre_cut or resolve_source_file(meta["video_id"], plan)
        if not src:
            failures.append(f"{cid}: source file for {meta['video_id']} not found in library_dir hints")
            continue
        asset_id = f"yt-{meta['video_id']}-{cid}"
        fname = f"assets/{asset_id}.mp4"
        dest = ctx.paths.public / fname
        if pre_cut:
            log(f"prepare {cid} from pre-cut {src.name}")
            stage_clip(src, dest, 0.0, 0.0, 1.0, whole_file=True)
        else:
            log(f"prepare {cid} from {src.name} {meta['source_in_s']}-{meta['source_out_s']}s @ {meta.get('speed', 1)}x")
            stage_clip(src, dest, float(meta["source_in_s"]), float(meta["source_out_s"]), float(meta.get("speed") or 1))
        rows[:] = [r for r in rows if r["asset_id"] != asset_id]
        rows.append({"asset_id": asset_id, "file": fname, "source": f"YouTube (CC BY) {meta['title']}".strip(),
                     "creator": meta["creator"], "url": meta["url"],
                     "licence": f"{meta['licence']} (checked on watch page {meta['licence_checked_at']})",
                     "date": today(), "used_in": ctx.slug})
        info = {"asset_id": asset_id, "file": fname, "clip_id": cid, "video_id": meta["video_id"],
                "source_in_s": meta["source_in_s"], "source_out_s": meta["source_out_s"],
                "speed": meta.get("speed", 1), "place": meta.get("place", "")}
        staged[cid] = info
        for key in keys:
            manifest["clips"][key] = dict(info)
    return rows


def run_phase(ctx) -> dict:
    shotlist = load_json(ctx.paths.video / "shotlist.json")
    rows = read_log(ctx.paths.licence_log)
    manifest = {"clips": {}, "static": []}
    used = {r["asset_id"] for r in rows}
    keys = {k: bool(os.environ.get(k)) for k in ("PEXELS_API_KEY", "PIXABAY_API_KEY")}
    warnings = [f"{k} not set: stock search on that source skipped" for k, v in keys.items() if not v]
    failures = []

    rows = _log_static_registry(ctx, rows, manifest, failures)
    plan = load_used_sources(ctx.paths.video)
    if plan:
        rows = _ingest_explicit(ctx, shotlist, plan, rows, manifest, failures, warnings)
    else:
        session_used: set[str] = set()
        units = set(getattr(ctx, "units", None) or [])
        for unit, pid, idx, shot in clip_shots(shotlist):
            if units and unit not in units:
                continue
            key = f"{unit}/{pid}/{idx}"
            orient = "portrait" if unit.startswith("short") else "landscape"
            min_w = 1080 if orient == "portrait" else 1920
            prior = next((m for m in load_json(ctx.paths.build / "assets.json", default={"clips": {}})["clips"].items()
                          if m[0] == key and m[1].get("asset_id")), None)
            if prior and (ctx.paths.public / prior[1]["file"]).exists() and has_row(rows, prior[1]["asset_id"]):
                manifest["clips"][key] = prior[1]
                session_used.add(prior[1]["asset_id"])
                continue
            hit = None
            for q in shot.get("queries", []):
                try:
                    hit = (search_pexels(q, orient, min_w, used | session_used)
                           or search_pixabay(q, orient, min_w, used | session_used)
                           or (youtube_ccby(q, used | session_used, float(shot.get("need_s", 8)))
                               if shot.get("allow_youtube") else None))
                except Exception as e:
                    warnings.append(scrub(f"{key}: search error for '{q}': {e}"))
                if hit:
                    break
            if not hit:
                if shot.get("fallback"):
                    manifest["clips"][key] = {"fallback": True}
                    continue
                failures.append(f"{key}: no licensed clip found and no fallback")
                continue
            fname = f"assets/{hit['asset_id']}.mp4"
            dest = ctx.paths.public / fname
            log(f"download {hit['asset_id']} for {key}")
            if "yt" in hit:
                _download_youtube(hit, dest)
            else:
                _download(hit["download"], dest)
            rows = [r for r in rows if r["asset_id"] != hit["asset_id"]]
            rows.append({"asset_id": hit["asset_id"], "file": fname, "source": hit["source"], "creator": hit["creator"],
                         "url": hit["url"], "licence": hit["licence"], "date": today(), "used_in": ctx.slug})
            manifest["clips"][key] = {"asset_id": hit["asset_id"], "file": fname}
            session_used.add(hit["asset_id"])

    write_log(ctx.paths.licence_log, rows)
    save_json(ctx.paths.build / "assets.json", manifest)
    n_clip = sum(1 for v in manifest["clips"].values() if v.get("asset_id"))
    n_fb = sum(1 for v in manifest["clips"].values() if v.get("fallback"))
    summary = {"clips_sourced": n_clip, "clips_fallback_graphics": n_fb, "static_assets": len(manifest["static"]),
               "licence_rows": len(read_log(ctx.paths.licence_log)), "warnings": warnings,
               "used_sources_plan": bool(plan)}
    for w in warnings:
        log("WARN " + w)
    if plan and not plan.get("allow_graphics_fallback", False):
        if n_fb:
            failures.append(f"unintended graphics fallback: {n_fb} clip slot(s) fell back")
        if n_clip == 0:
            failures.append("zero real footage cannot pass: clips_sourced=0")
    if failures:
        raise PhaseError("; ".join(failures))
    return summary
