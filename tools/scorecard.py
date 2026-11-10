#!/usr/bin/env python3
"""Aurum long-cut scorecard (pre-render plan + optional output).

Standard: post-Bali spec (brand/visual-style.md v2). With --edl the spec HARD gates from
tools/spec_gates.py decide pass/fail; a fallback/illustration scene always fails. The script never starts a render.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLACEHOLDER_RE = re.compile(r"in this cut|no verified|placeholder|map only;|no store listing", re.I)
GRAPHIC_TYPES = {"map", "text", "checklist", "calendar", "sea", "desert", "town", "callout", "overlay", "kinetic", "route"}

# Thresholds: formulas.md + visual-style.md + t196u (formulas win where they differ).
GATES = {
    "avg_shot_s_max": 6.0,
    "visual_change_s_max": 5.0,
    "max_hold_s": 1.0,
    "hook_s_max": 15.0,
    "graphic_beats_per_chapter_min": 2,
    "clip_uses_max": 1,  # spec: no clip reused
    "map_only_scenes_max": 0,
    "placeholder_hits_max": 0,
    "ambient_coverage_min": 0.02,
    "engagement_gap_s_max": 90.0,
    "engagement_gap_s_target_min": 60.0,
    "chapter_s_min": 60.0,
    "chapter_s_max": 120.0,
    "title_max_chars": 60,
}
THREE_WAY = ("transfer", "taxi", "rental")
TITLE_YEAR_RE = re.compile(r"\b20\d{2}\b")
NUMBERED_CHAPTER_RE = re.compile(r"^\s*\d+\s*[.)]")
SEARCH_PHRASE_RE = re.compile(
    r"airport|hotel|transfer|ed-?card|beach|oranjestad|arrival|when to|best time|getting around|entry",
    re.I,
)


def _load(path: Path, default=None):
    if path is None or not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def placeholder_hits(obj) -> list[str]:
    hits = []

    def walk(x, path="$"):
        if isinstance(x, dict):
            for k, v in x.items():
                if k in {"text", "sub", "title", "items", "lines"} or "caption" in k.lower():
                    blob = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)
                    if PLACEHOLDER_RE.search(blob or ""):
                        hits.append(f"{path}.{k}: {blob[:160]}")
                walk(v, f"{path}.{k}")
        elif isinstance(x, list):
            for i, v in enumerate(x):
                walk(v, f"{path}[{i}]")
        elif isinstance(x, str) and PLACEHOLDER_RE.search(x):
            hits.append(f"{path}: {x[:160]}")

    walk(obj)
    return hits


def chapter_for(frame: int, chapters: list[dict], fps: int) -> str:
    title = "intro"
    for c in chapters or []:
        if frame >= int(c.get("from") or 0):
            title = c.get("title") or title
    return title


def score_timeline(tl: dict) -> dict:
    fps = float(tl.get("fps") or 30)
    shots = list(tl.get("shots") or [])
    chapters = list(tl.get("chapters") or [])
    durs = [s["dur"] / fps for s in shots] or [0.0]
    types = Counter(s.get("type") for s in shots)
    paras: dict[str, list] = defaultdict(list)
    for s in shots:
        paras[str(s.get("key", "x")).split("-")[0]].append(s)
    map_only = []
    for pid, ss in paras.items():
        kinds = {s.get("type") for s in ss}
        if kinds and kinds <= {"map", "text"}:
            map_only.append({"id": pid, "types": sorted(kinds), "dur_s": sum(s["dur"] for s in ss) / fps})

    reuse = Counter()
    ranges = defaultdict(list)
    holds = []
    for s in shots:
        if s.get("type") != "clip":
            continue
        cid = s.get("source_clip_id") or s.get("src") or "?"
        reuse[cid] += 1
        start_s = float(s.get("start_s") or (s.get("startFrom") or 0) / fps)
        dur_s = s["dur"] / fps
        ranges[cid].append((start_s, start_s + dur_s))
        usable = max(1, int(s.get("clipFrames") or s["dur"]) - int(s.get("startFrom") or 0))
        hold = (s["dur"] - usable) / fps
        if hold > 0.02:
            holds.append({"key": s.get("key"), "hold_s": round(hold, 3), "dur_s": round(dur_s, 3)})

    over_reuse = {k: v for k, v in reuse.items() if v > GATES["clip_uses_max"]}
    overlap_reuse = []
    for cid, rs in ranges.items():
        rs = sorted(rs)
        for (a0, a1), (b0, b1) in zip(rs, rs[1:]):
            ov = min(a1, b1) - max(a0, b0)
            if ov > 0.5:
                overlap_reuse.append({"clip": cid, "overlap_s": round(ov, 2)})

    beats = defaultdict(int)
    for s in shots:
        if s.get("type") in GRAPHIC_TYPES or s.get("callout") or s.get("overlay") or s.get("graphic"):
            beats[chapter_for(int(s.get("from") or 0), chapters, int(fps))] += 1
    # also count explicit graphic_beats on the timeline if present
    for g in tl.get("graphicBeats") or tl.get("overlays") or []:
        beats[chapter_for(int(g.get("from") or 0), chapters, int(fps))] += 1

    hook = next((s for s in shots if s.get("hook") or str(s.get("key", "")).startswith("hook")), None)
    hook_s = (hook["dur"] / fps) if hook else 0.0
    # hook window: shots before first disclosure frame
    disc = tl.get("disclosure") or {}
    disc_from = int(disc.get("from") or 0)
    pre = [s for s in shots if int(s.get("from") or 0) < disc_from]
    pre_s = sum(s["dur"] for s in pre) / fps if pre else 0.0

    gaps = []
    for a, b in zip(shots, shots[1:]):
        gaps.append((b["from"] - a["from"]) / fps)
    max_gap = max(gaps) if gaps else (durs[0] if durs else 0)

    hits = placeholder_hits(tl)
    return {
        "shot_count": len(shots),
        "avg_shot_s": round(sum(durs) / len(durs), 3),
        "max_shot_s": round(max(durs), 3),
        "min_shot_s": round(min(durs), 3),
        "max_visual_gap_s": round(max_gap, 3),
        "shot_types": dict(types),
        "map_only_scenes": map_only,
        "map_only_count": len(map_only),
        "max_hold_s": round(max((h["hold_s"] for h in holds), default=0.0), 3),
        "holds_over_1s": [h for h in holds if h["hold_s"] > GATES["max_hold_s"]],
        "clip_reuse": dict(reuse),
        "clips_used_over_twice": over_reuse,
        "overlapping_reuse": overlap_reuse,
        "graphic_beats_per_chapter": dict(beats),
        "chapters_short_on_graphics": [k for k, v in beats.items() if v < GATES["graphic_beats_per_chapter_min"]],
        "hook_flag_s": round(hook_s, 3),
        "pre_disclosure_s": round(pre_s, 3),
        "placeholder_hits": hits,
        "has_music_plan": bool(tl.get("music") or tl.get("audioMix", {}).get("music")),
        "has_ambient_plan": bool(tl.get("ambient") or tl.get("audioMix", {}).get("ambient")),
        "ambient_coverage": float((tl.get("audioMix") or {}).get("ambient_coverage") or 0),
        "has_comment_prompt": bool(tl.get("commentPrompt") or any(s.get("prompt") for s in shots)),
        "has_end_cta": bool(tl.get("endCard") or any(s.get("cta") for s in shots)),
    }


def probe_output(path: Path) -> dict:
    if not path.exists():
        return {"exists": False}
    def ff(*args):
        return subprocess.run(["ffprobe", "-v", "error", *args, str(path)], capture_output=True, text=True).stdout.strip()
    dur = float(ff("-show_entries", "format=duration", "-of", "csv=p=0") or 0)
    streams = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,codec_name,width,height,sample_rate",
         "-of", "json", str(path)], capture_output=True, text=True
    )
    info = {"exists": True, "path": str(path), "bytes": path.stat().st_size, "duration_s": dur}
    try:
        info["streams"] = json.loads(streams.stdout).get("streams", [])
    except json.JSONDecodeError:
        info["streams"] = []
    return info


def freezedetect(path: Path, threshold: float = 1.0) -> dict:
    if not path.exists():
        return {"ran": False}
    cmd = [
        "ffmpeg", "-hide_banner", "-i", str(path),
        "-vf", f"freezedetect=n=0.003:d={threshold}",
        "-an", "-f", "null", "-",
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    starts, durs = [], []
    for line in (r.stderr or "").splitlines():
        if "freeze_start:" in line:
            try:
                starts.append(float(line.rsplit("freeze_start:", 1)[1]))
            except ValueError:
                pass
        if "freeze_duration:" in line:
            try:
                durs.append(float(line.rsplit("freeze_duration:", 1)[1]))
            except ValueError:
                pass
    return {"ran": True, "threshold_s": threshold, "count": len(durs), "max_s": max(durs) if durs else 0.0, "events": list(zip(starts, durs))[:20]}



def chapter_spans(tl: dict) -> list[dict]:
    fps = float(tl.get("fps") or 30)
    total = (tl.get("endCard") or {}).get("from")
    if total is None:
        total = tl.get("durationInFrames") or 0
    chapters = list(tl.get("chapters") or [])
    spans = []
    # implicit opening chapter from 0 if the first card is later
    starts = []
    if not chapters or int(chapters[0].get("from") or 0) > fps:
        starts.append({"title": "Opening", "from": 0, "numbered": False})
    for c in chapters:
        starts.append({"title": c.get("title") or "", "from": int(c.get("from") or 0), "index": c.get("index")})
    for i, c in enumerate(starts):
        end = starts[i + 1]["from"] if i + 1 < len(starts) else int(total)
        dur = (end - c["from"]) / fps
        title = c["title"]
        spans.append({
            "title": title,
            "from_s": round(c["from"] / fps, 2),
            "dur_s": round(dur, 2),
            "numbered": bool(NUMBERED_CHAPTER_RE.search(title) or c.get("index") not in (None, 0) and NUMBERED_CHAPTER_RE.search(str(c.get("index")) + ". " + title)),
            "search_phrase": bool(SEARCH_PHRASE_RE.search(title)),
            "in_band": GATES["chapter_s_min"] <= dur <= GATES["chapter_s_max"],
        })
    # treat a chapter as numbered if the stored title starts with a number
    for s in spans:
        s["numbered"] = bool(NUMBERED_CHAPTER_RE.search(s["title"]))
    return spans


def hook_text_from(tl: dict, script_text: str, title: str) -> str:
    parts = []
    for s in tl.get("shots") or []:
        if s.get("hook") or str(s.get("key", "")).startswith("hook") or str(s.get("id", "")).startswith("hook"):
            parts.append(" ".join(str(s.get(k) or "") for k in ("text", "sub", "hook_text", "narration")))
    if tl.get("hookText"):
        parts.append(str(tl["hookText"]))
    if script_text:
        # first non-empty, non-comment, non-heading paragraph
        paras = []
        for line in script_text.splitlines():
            st = line.strip()
            if not st or st.startswith("#") or st.startswith(">" ) or st.startswith("<!--"):
                continue
            paras.append(st)
            if len(" ".join(paras).split()) >= 40:
                break
        parts.append(" ".join(paras[:2]))
    return " ".join(parts).lower()


def engagement_prompts(tl: dict, total_s: float) -> dict:
    prompts = list(tl.get("engagementPrompts") or [])
    for s in tl.get("shots") or []:
        if s.get("type") in {"prompt", "engagement"} or s.get("prompt") or s.get("engagement"):
            prompts.append({"from": s.get("from") or 0, "text": s.get("text") or s.get("prompt") or ""})
    fps = float(tl.get("fps") or 30)
    times = sorted({round(int(p.get("from") or 0) / fps, 2) if not isinstance(p.get("from_s"), (int, float)) else float(p["from_s"]) for p in prompts})
    # gaps from 15 s (after hook) to end-card
    end = total_s
    marks = [15.0] + times + [end]
    gaps = [round(b - a, 2) for a, b in zip(marks, marks[1:])]
    over = [g for g in gaps if g > GATES["engagement_gap_s_max"]]
    return {"count": len(times), "times_s": times, "gaps_s": gaps, "gaps_over_90s": over}


def title_score(title: str) -> dict:
    title = (title or "").strip()
    return {
        "title": title,
        "chars": len(title),
        "has_year": bool(TITLE_YEAR_RE.search(title)),
        "keyword_first": title.lower().startswith("aruba"),
        "has_promise": any(w in title.lower() for w in ("arrival", "transfer", "taxi", "rental", "guide", "hotel", "airport")),
        "within_60": len(title) <= GATES["title_max_chars"],
    }

def gates_from(plan: dict, output: dict | None = None) -> dict[str, dict]:
    g = {}
    def add(name, ok, detail):
        g[name] = {"pass": bool(ok), "detail": detail}
    add("avg_shot_s", plan["avg_shot_s"] <= GATES["avg_shot_s_max"], plan["avg_shot_s"])
    add("visual_change", plan["max_visual_gap_s"] <= GATES["visual_change_s_max"], plan["max_visual_gap_s"])
    add("max_hold_s", plan["max_hold_s"] <= GATES["max_hold_s"] and not plan["holds_over_1s"], plan["max_hold_s"])
    hook = plan.get("hook_flag_s") or plan.get("pre_disclosure_s") or 0
    add("hook_le_15s", 0 < hook <= GATES["hook_s_max"], hook)
    add("hook_stress_and_3_ways", plan.get("hook_has_stress") and plan.get("hook_has_3_ways"), {
        "stress": plan.get("hook_has_stress"), "three_ways": plan.get("hook_has_3_ways"), "text": plan.get("hook_text_excerpt")
    })
    add("no_map_only", plan["map_only_count"] <= GATES["map_only_scenes_max"], plan["map_only_count"])
    add("no_illustration_only_fallback", plan["map_only_count"] == 0, "visual-style.md: no illustration-only fallback")
    ch = plan.get("chapter_spans") or []
    add("chapter_lengths_60_120s", bool(ch) and all(c["in_band"] for c in ch), ch)
    add("numbered_search_phrase_chapters", bool(ch) and all(c["numbered"] and c["search_phrase"] for c in ch), ch)
    eng = plan.get("engagement") or {}
    add("engagement_every_60_90s", eng.get("count", 0) >= 1 and not eng.get("gaps_over_90s"), eng)
    add("airport_to_hotel_cta", plan.get("has_airport_hotel_cta"), plan.get("has_airport_hotel_cta"))
    add("end_screen_next_video", plan.get("has_next_video_end"), plan.get("end_card"))
    add("title_keyword_promise_year", plan.get("title_ok"), plan.get("title"))
    mix = (plan.get("music_source") or "none")
    add("music_ytal_or_none", mix in {"none", "youtube_audio_library", "YouTube Audio Library"}, mix)
    add("no_placeholders", len(plan["placeholder_hits"]) <= GATES["placeholder_hits_max"], plan["placeholder_hits"])
    add("no_clip_reuse", not plan["clips_used_over_twice"] and not plan["overlapping_reuse"], plan["clips_used_over_twice"])
    add("graphics_per_chapter", not plan["chapters_short_on_graphics"], plan["graphic_beats_per_chapter"])
    add("ambient_plan", plan["has_ambient_plan"] or plan["ambient_coverage"] >= GATES["ambient_coverage_min"], plan["ambient_coverage"])
    add("end_cta", plan["has_end_cta"], plan["has_end_cta"])
    if output and output.get("freeze"):
        fr = output["freeze"]
        add("output_freeze_le_1s", fr.get("max_s", 0) <= GATES["max_hold_s"], fr)
    return g


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--timeline", type=Path, default=ROOT / "videos/aruba-travel-guide/build/timeline-long.json")
    ap.add_argument("--shotlist", type=Path, default=ROOT / "videos/aruba-travel-guide/shotlist.json")
    ap.add_argument("--output", type=Path, default=None, help="Rendered mp4 for freeze/probe (optional)")
    ap.add_argument("--freeze", action="store_true", help="Run ffmpeg freezedetect (heavy; do not overlap a live render)")
    ap.add_argument("--write", type=Path, required=True)
    ap.add_argument("--edl", type=Path, default=None, help="EDL from tools/title_runner.py: adds the post-Bali spec HARD gates (tools/spec_gates.py)")
    ap.add_argument("--licence", type=Path, default=None)
    ap.add_argument("--script", type=Path, default=ROOT / "videos/aruba-travel-guide/script.md")
    ap.add_argument("--video-json", type=Path, default=ROOT / "videos/aruba-travel-guide/video.json")
    args = ap.parse_args()

    tl = _load(args.timeline, {})
    sl = _load(args.shotlist, {})
    plan = score_timeline(tl) if tl else {"error": "no timeline"}
    if "error" in plan:
        plan.update({"avg_shot_s": 0, "max_visual_gap_s": 0, "max_hold_s": 0, "holds_over_1s": [], "map_only_count": 0, "placeholder_hits": [], "clips_used_over_twice": {}, "overlapping_reuse": [], "chapters_short_on_graphics": [], "graphic_beats_per_chapter": {}, "has_ambient_plan": False, "ambient_coverage": 0, "has_end_cta": False})
    sl_hits = placeholder_hits(sl)
    plan["shotlist_placeholder_hits"] = sl_hits
    script_text = args.script.read_text(encoding="utf-8") if args.script and args.script.exists() else ""
    video = _load(args.video_json, {}) or {}
    title = (video.get("long") or {}).get("title") or ""
    ts = title_score(title)
    plan["title"] = ts
    plan["title_ok"] = ts["has_year"] and ts["keyword_first"] and ts["has_promise"] and ts["within_60"]
    hook_blob = hook_text_from(tl or {}, script_text, title)
    plan["hook_text_excerpt"] = hook_blob[:280]
    plan["hook_has_3_ways"] = all(w in hook_blob for w in THREE_WAY)
    plan["hook_has_stress"] = any(w in hook_blob for w in ("hotel", "airport", "landing", "arrived", "arrival", "beatrix"))
    fps = float((tl or {}).get("fps") or 30)
    total_s = ((tl or {}).get("endCard") or {}).get("from", (tl or {}).get("durationInFrames") or 0) / fps
    plan["engagement"] = engagement_prompts(tl or {}, total_s)
    plan["chapter_spans"] = chapter_spans(tl or {}) if tl else []
    end = (tl or {}).get("endCard") or video.get("end_card") or {}
    end_blob = " ".join(str(x) for x in [end.get("title"), end.get("lines"), end.get("next")]).lower()
    plan["end_card"] = end
    plan["has_next_video_end"] = "next video" in end_blob or "watch next" in end_blob or bool(end.get("next_video"))
    body = (script_text + " " + json.dumps(sl or {})).lower()
    plan["has_airport_hotel_cta"] = ("aurum-transfers.com" in body or "pre-booked transfer" in body) and ("taxi" in hook_blob or "transfer" in body)
    mix = ((tl or {}).get("audioMix") or {}).get("music_source") or ((tl or {}).get("music") or {}).get("source")
    if not mix:
        # credits_line often records "Music: none"
        credits = (video.get("credits_line") or "").lower()
        if "youtube audio library" in credits:
            mix = "youtube_audio_library"
        elif "music: none" in credits or "music none" in credits:
            mix = "none"
        else:
            mix = "none" if not (tl or {}).get("music") else "unknown"
    plan["music_source"] = mix
    out_info = None
    if args.output:
        out_info = probe_output(args.output)
        if args.freeze:
            out_info["freeze"] = freezedetect(args.output, 1.0)
    gates = gates_from(plan, out_info) if "avg_shot_s" in plan else {}
    # also fail if shotlist itself has editor notes
    if sl_hits:
        gates["shotlist_placeholders"] = {"pass": False, "detail": sl_hits}
    spec = None
    if args.edl:
        import sys as _sys
        _sys.path.insert(0, str(Path(__file__).resolve().parent))
        import spec_gates
        edl = json.loads(args.edl.read_text())
        mo = spec_gates.measure_output(args.output, args.freeze) if args.output else None
        lic = args.licence or (args.edl.parent.parent / "licence-log.csv")
        spec = spec_gates.evaluate(edl, spec_gates.read_rows(lic), mo, root=lic.parent)
        gates = {f"spec:{k}": v for k, v in spec["gates"].items()}  # spec gates are the standard; legacy plan gates do not apply to EDL builds
    failed = [k for k, v in gates.items() if not v["pass"]]
    doc = {
        "schema": "aurum-long-scorecard-v1",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "timeline": str(args.timeline) if args.timeline.exists() else None,
        "output": str(args.output) if args.output else None,
        "plan": plan,
        "output_probe": out_info,
        "gates": gates,
        "pass": not failed,
        "failed_gates": failed,
        "thresholds": GATES,
        "spec": spec["spec"] if spec else None,
    }
    args.write.parent.mkdir(parents=True, exist_ok=True)
    args.write.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({"write": str(args.write), "pass": doc["pass"], "failed": failed, "avg_shot_s": plan.get("avg_shot_s"), "map_only": plan.get("map_only_count")}, indent=2))


if __name__ == "__main__":
    main()
