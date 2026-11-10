#!/usr/bin/env python3
"""Post-Bali video spec as HARD gates (Marvin t201u/t202u, 10 Nov 2026).

Input: an EDL json (build/edl-<unit>.json written by tools/title_runner.py) plus the
licence log. Every gate is pass/fail; any fail = the video fails. A fallback, an
illustration-only scene or a missing licence field FAILS the video; nothing here
can be waived by a plan flag.

    python tools/spec_gates.py --edl build/edl-long.json --licence licence-log.csv \
        [--output out/long-v4.mp4 --freeze] --write out/spec-gates.json
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import statistics
import subprocess
from collections import defaultdict
from pathlib import Path

SPEC = {
    "footage_ratio_min": 0.80,
    "map_ratio_max": 0.10,
    "shot_median_min": 3.0,
    "shot_median_max": 6.0,
    "shot_max_s": 8.0,           # maps excepted
    "creator_share_max": 0.30,
    "engagement_gap_max": 90.0,
    "engagement_gap_min": 45.0,  # natural, not spammy
    "no_fullscreen_text_before_s": 45.0,
    "hook_max_s": 15.0,
    "hook_promise_by_s": 12.0,   # "by ~0:10"
    "chapter_min_s": 60.0,
    "chapter_max_s": 120.0,
    "disclosure_by_s": 30.0,
    "lufs": -14.0,
    "lufs_tol": 1.0,
    "true_peak_max": -1.0,
    "freeze_max_s": 1.0,
    "reuse_overlap_tol_s": 0.10,
    # v5 additions (independent review of Aruba long-v4, 10 Nov 2026: 3/10 despite all v4 gates passing)
    "motion_median_min": 1.2,    # mean |frame diff| x100/255 at 96x54, 6 fps; near-static drone sea ~0.6-1.1
    "motion_second_min": 0.8,    # no second of a shot below this
    "luma_mean_min": 70.0,       # shot mean luma (0-255); "nearly black" fails
    "luma_frame_min": 60.0,      # darkest sampled frame in a shot (fades from black, night)
    "dup_hash_max_dist": 12,     # v6: was 6; 12 flags the v5 replays (39 of 7021 non-adjacent pairs)
    "dup_sig_max_diff": 10.0,    # 16x9 RGB mid-frame signature, mean |diff| (0-255): catches same-looking static sea reused (dHash misses it)      # 64-bit dHash: two non-adjacent shots this close = same-looking shot reused
    # v6 additions (independent review of Aruba v5 animatic, 10 Nov 2026: 4/10, heavy repetition + near-still drones)
    "scene_uses_max": 1,         # a continuous source scene (same place + camera move) may appear once per video
    "scene_cut_hash": 20,        # per-second dHash jump that starts a new scene inside one source
    "scene_cut_luma": 18.0,      # or a per-second mean-luma jump
    "parent_uses_max": 3,
    "video_uses_max": 5,         # shots from one source video per long cut (v5: one beach-walk POV video gave 23 shots)        # uses of one source clip (footage.json parent range) per video
    "cam_shift_min": 0.75,       # px/s at 96x54 (phase correlation), median over the shot; calibrated on the v5 animatic
    "cam_gmot_min": 0.8,         # block-mean change; both below = still drone / static tripod ocean
    "src_height_min": 1080,      # effective source height after crop
    "src_fps_min": 23.9,
    "sharp_lap_min": 35.0,       # Laplacian variance at 1280x720 gray, median of 5 frames (v5 library: soft clips 3-33, sharp 50-400)
    "lift_min_count": 3,         # voice-free natural-sound lifts in a long video
    "lift_min_s": 1.0,
    "lift_rms_min_dbfs": -32.0,  # measured in the final mix inside each lift
    "ambient_under_voice_db": [-26.0, -10.0],  # ducked ambient vs voice, over audio-licensed shots
}
FOOTAGE_KINDS = {"clip"}
MAP_KINDS = {"map"}
PREVIEW_MAX_S = 180.0  # longest program that may use the preview scope (see chapter gate)
BANNED_KINDS = {"illustration", "text", "fallback", "placeholder", "still", "sea", "desert", "town", "calendar", "checklist"}
CC_BY = re.compile(r"creative commons attribution", re.I)
STRESS = re.compile(r"\b(landed|landing|arriv\w*|airport|hotel|not sure|stress|first hour)\b", re.I)
THREE_WAYS = (re.compile(r"transfer", re.I), re.compile(r"taxi", re.I), re.compile(r"rental|rent a car|hire car", re.I))
NUMBERED = re.compile(r"^\s*\d+\s*[.)]\s+\S")
LICENCE_FIELDS = ("url", "creator", "licence", "date", "evidence", "in_s", "out_s")


def load_qc(root):
    """clipqc.json -> {file: {second: rec}}, plus per-clip quality records keyed by clip id."""
    import math as _m
    from collections import defaultdict as _dd
    qx, qual = _dd(dict), {}
    p = Path(root) / "build" / "clipqc.json" if root else None
    if not p or not p.exists():
        return qx, qual
    for cid, v in json.loads(p.read_text()).items():
        for x in v.get("secs", []):
            qx[v["file"]][int(_m.floor(x["t"] + 1e-6))] = x
        qual[cid] = {k: v.get(k) for k in ("src_h", "eff_h", "src_fps", "lap_med", "lap_min")}
    return qx, qual


def scene_index(qx):
    """Split every source file's measured seconds into continuous scenes: a new scene starts at a gap in the
    measured seconds, a dHash jump over scene_cut_hash bits or a mean-luma jump over scene_cut_luma."""
    out = {}
    for f, secs in qx.items():
        ks = sorted(secs); sc = 0; m = {}
        for a, b in zip([None] + ks, ks):
            if a is not None:
                pa, pb = secs[a], secs[b]
                if b - a > 1 or bin(int(pa["dh"]) ^ int(pb["dh"])).count("1") > SPEC["scene_cut_hash"] or abs(pa["y"] - pb["y"]) > SPEC["scene_cut_luma"]:
                    sc += 1
            m[b] = sc
        out[f] = m
    return out


def read_rows(path: Path) -> list[dict]:
    if not path or not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _overlap(a, b):
    return min(a[1], b[1]) - max(a[0], b[0])


def evaluate(edl: dict, rows: list[dict], output: dict | None = None, root: Path | None = None) -> dict:
    g: dict[str, dict] = {}

    def add(name, ok, detail):
        g[name] = {"pass": bool(ok), "detail": detail}

    shots = sorted(edl.get("shots", []), key=lambda s: s["t0"])
    ovs = edl.get("overlays", [])
    program = float(edl.get("program_end_s") or edl.get("duration_s") or 0)
    dur = lambda x: max(0.0, min(float(x["t1"]), program) - max(0.0, float(x["t0"])))

    # 1 footage ratio
    foot = sum(dur(s) for s in shots if s.get("kind") in FOOTAGE_KINDS)
    ratio = foot / program if program else 0
    add("footage_ratio_ge_80", ratio >= SPEC["footage_ratio_min"], {"ratio": round(ratio, 4), "footage_s": round(foot, 2), "program_s": round(program, 2)})
    # 2 map ratio (full-screen maps + map insets)
    map_s = sum(dur(s) for s in shots if s.get("kind") in MAP_KINDS) + sum(dur(o) for o in ovs if o.get("kind") == "mapinset")
    add("map_ratio_le_10", (map_s / program if program else 1) <= SPEC["map_ratio_max"], {"ratio": round(map_s / program, 4) if program else None, "map_s": round(map_s, 2)})
    # 3 illustration / fallback / placeholder scenes = fail
    banned = [{"t0": s["t0"], "kind": s.get("kind")} for s in shots if s.get("kind") in BANNED_KINDS or s.get("fallback_for") or s.get("fallback")]
    add("no_illustration_or_fallback_scenes", not banned, banned or "none")
    # coverage holes (picture must never be empty)
    holes, cur = [], 0.0
    for s in shots:
        if s["t0"] - cur > 1 / 30 + 1e-6:
            holes.append([round(cur, 3), round(s["t0"], 3)])
        cur = max(cur, s["t1"])
    if program - cur > 1 / 30 + 1e-6:
        holes.append([round(cur, 3), round(program, 3)])
    add("no_picture_gaps", not holes, holes or "none")
    # 4 shot lengths
    lens = [s["t1"] - s["t0"] for s in shots if s.get("kind") in FOOTAGE_KINDS and s["t0"] < program]
    med = statistics.median(lens) if lens else 0
    longest = [round(l, 2) for l in lens if l > SPEC["shot_max_s"] + 1e-6]
    add("shot_median_3_6s", SPEC["shot_median_min"] <= med <= SPEC["shot_median_max"], {"median_s": round(med, 3), "n": len(lens), "min_s": round(min(lens), 2) if lens else None, "max_s": round(max(lens), 2) if lens else None})
    add("no_shot_over_8s", not longest, longest or "none")
    # 5 no clip reuse (overlapping source range of the same source video)
    ranges = defaultdict(list)
    for s in shots:
        if s.get("kind") in FOOTAGE_KINDS:
            ranges[s["video_id"]].append((float(s["src_in"]), float(s["src_out"]), s["t0"]))
    reused = []
    for vid, rs in ranges.items():
        rs.sort()
        for i in range(len(rs)):
            for j in range(i + 1, len(rs)):
                if rs[j][0] >= rs[i][1]:
                    break
                ov = _overlap(rs[i], rs[j])
                if ov > SPEC["reuse_overlap_tol_s"]:
                    reused.append({"video_id": vid, "overlap_s": round(ov, 2), "at": [rs[i][2], rs[j][2]]})
    add("no_clip_reuse", not reused, reused or "none")
    # 6 creator share
    by = defaultdict(float)
    for s in shots:
        if s.get("kind") in FOOTAGE_KINDS:
            by[s.get("creator") or "?"] += dur(s)
    shares = {k: round(v / foot, 4) for k, v in sorted(by.items(), key=lambda kv: -kv[1])} if foot else {}
    add("creator_share_le_30", bool(shares) and max(shares.values()) <= SPEC["creator_share_max"], shares)
    # 7 footage from frame 1
    first = shots[0] if shots else {}
    add("footage_from_frame_1", bool(first) and first.get("kind") in FOOTAGE_KINDS and float(first["t0"]) == 0.0, {"first": first.get("kind"), "t0": first.get("t0")})
    # 8 no full-screen text card before 0:45
    early = [s["t0"] for s in shots if s.get("kind") in {"text", "endcard", "card"} and s["t0"] < SPEC["no_fullscreen_text_before_s"]]
    early += [o["t0"] for o in ovs if o.get("fullscreen") and o["t0"] < SPEC["no_fullscreen_text_before_s"]]
    add("no_fullscreen_text_before_45s", not early, early or "none")
    # 9 hook
    sents = edl.get("sentences", [])
    hook_end = float(edl.get("hook_end_s") or 99)
    hook_txt = " ".join(s["text"] for s in sents if s["t1"] <= hook_end + 0.05)
    ways_t = None
    acc = ""
    for s in sents:
        acc += " " + s["text"]
        if all(p.search(acc) for p in THREE_WAYS):
            ways_t = s["t1"]
            break
    add("hook_le_15s", hook_end <= SPEC["hook_max_s"], {"hook_end_s": hook_end})
    add("hook_stress_and_three_ways", bool(STRESS.search(hook_txt)) and all(p.search(hook_txt) for p in THREE_WAYS),
        {"text": hook_txt[:300]})
    add("hook_promise_by_10s", ways_t is not None and ways_t <= SPEC["hook_promise_by_s"], {"three_ways_spoken_by_s": ways_t})
    # 10 disclosure spoken + overlay < 30 s
    disc_sp = next((s["t0"] for s in sents if s.get("disclosure")), None)
    disc_ov = next((o["t0"] for o in ovs if o.get("kind") == "disclosure"), None)
    add("disclosure_spoken_and_overlay_lt30s", disc_sp is not None and disc_ov is not None and disc_sp < 30 and disc_ov < 30,
        {"spoken_s": disc_sp, "overlay_s": disc_ov})
    # 11 numbered chapters 60-120 s
    chs = sorted([o for o in ovs if o.get("kind") == "chapter"], key=lambda o: o["t0"])
    spans = []
    for i, c in enumerate(chs):
        end = chs[i + 1]["t0"] if i + 1 < len(chs) else program
        spans.append({"title": c.get("text"), "span_s": round(end - c["t0"], 1), "numbered": bool(NUMBERED.search(c.get("text") or ""))})
    first_ch = chs[0]["t0"] if chs else None
    ok = len(chs) >= 3 and all(sp["numbered"] for sp in spans) and all(SPEC["chapter_min_s"] <= sp["span_s"] <= SPEC["chapter_max_s"] for sp in spans[:-1]) \
        and spans[-1]["span_s"] <= SPEC["chapter_max_s"] and (first_ch is not None and first_ch <= SPEC["chapter_max_s"])
    # Preview scope (spec.json "scope": "preview"): a <=180 s review preview cannot hold three 60-120 s chapters.
    # Only the 60 s minimum and the 3-chapter count are skipped; every chapter must still be numbered, start by 120 s,
    # and no span may exceed 120 s. A program over 180 s is always gated as a full cut, whatever the scope says.
    # No other gate reads scope.
    preview = str(edl.get("scope") or "full") == "preview" and 0 < program <= PREVIEW_MAX_S
    if preview:
        ok = len(chs) >= 1 and all(sp["numbered"] for sp in spans) and all(sp["span_s"] <= SPEC["chapter_max_s"] for sp in spans) \
            and first_ch is not None and first_ch <= SPEC["chapter_max_s"]
    add("numbered_chapters_60_120s", ok, {"first_at_s": first_ch, "spans": spans, "scope": "preview" if preview else "full"})
    # 12 engagement prompts every 60-90 s (natural: not closer than 45 s)
    pts = sorted(o["t0"] for o in ovs if o.get("kind") == "prompt")
    marks = [hook_end] + pts + [program]
    gaps = [round(b - a, 1) for a, b in zip(marks, marks[1:])]
    close = [round(b - a, 1) for a, b in zip(pts, pts[1:]) if b - a < SPEC["engagement_gap_min"]]
    spoken = sum(1 for o in ovs if o.get("kind") == "prompt" and o.get("spoken"))
    add("engagement_prompts_every_60_90s", bool(pts) and max(gaps) <= SPEC["engagement_gap_max"] and not close,
        {"times_s": [round(p, 1) for p in pts], "gaps_s": gaps, "too_close": close, "spoken": spoken})
    # 13 landing + airport arrival present
    tags = [s.get("tag", "") for s in shots]
    add("landing_and_airport_arrival", any("landing" in t for t in tags) and any(("airport" in t or "arrival" in t) for t in tags),
        {"landing_shots": sum("landing" in t for t in tags), "airport_shots": sum(("airport" in t or "arrival" in t) for t in tags)})
    # 14 licence completeness for every used source video
    byvid = {}
    for r in rows:
        byvid.setdefault(r.get("video_id") or r.get("asset_id"), []).append(r)
    missing = []
    for vid in ranges:
        rr = byvid.get(vid) or []
        if not rr:
            missing.append({"video_id": vid, "missing": "no row"})
            continue
        r = rr[0]
        lack = [f for f in LICENCE_FIELDS if not str(r.get(f) or "").strip()]
        if not CC_BY.search(r.get("licence") or ""):
            lack.append("licence not CC BY")
        ev = r.get("evidence") or ""
        if root is not None and ev and not (root / ev).exists() and not Path(ev).exists():
            lack.append("evidence file missing")
        if lack:
            missing.append({"video_id": vid, "missing": lack})
    add("licence_rows_complete", bool(ranges) and not missing, missing or f"{len(ranges)} source videos complete")
    # 15 audio: music YTAL or none; ambient only from allowed sources
    au = edl.get("audio", {})
    music = (au.get("music") or "none").lower()
    add("music_ytal_or_none", music in {"none", "youtube audio library"}, music)
    bad_amb = [a for a in au.get("ambient", []) if not a.get("licence_ok")]
    add("ambient_only_from_allowed_sources", not bad_amb, {"splices": len(au.get("ambient", [])), "disallowed": bad_amb})
    # 16 output measurements (only when an output was probed)
    if output is not None:
        lufs, tp = output.get("lufs"), output.get("true_peak")
        add("loudness_-14_tp_le_-1", lufs is not None and abs(lufs - SPEC["lufs"]) <= SPEC["lufs_tol"] and tp <= SPEC["true_peak_max"],
            {"lufs": lufs, "true_peak": tp})
        if "freeze" in output:
            fz = output["freeze"]
            add("no_freeze_over_1s", fz.get("max_s", 0) <= SPEC["freeze_max_s"], fz)
        if "duration_s" in output:
            add("av_duration_match", abs(output["duration_s"] - output.get("audio_duration_s", output["duration_s"])) <= 0.2,
                {"video_s": output.get("duration_s"), "audio_s": output.get("audio_duration_s")})
    # ---- v5 gates (1)-(5) -------------------------------------------------------------------------
    clip_shots = [s for s in shots if s.get("kind") in FOOTAGE_KINDS and s["t0"] < program]
    meas = (output or {}).get("shots") or {}
    def q(s, k):
        m = meas.get(str(round(s["t0"], 3)))
        if m and k in m:
            return m[k]
        return (s.get("qc") or {}).get(k)
    # (1a) motion: near-static shots fail
    static = [{"t0": s["t0"], "clip": s.get("clip_id"), "mot_med": q(s, "mot_med"), "mot_min": q(s, "mot_min")} for s in clip_shots
              if q(s, "mot_med") is None or q(s, "mot_med") < SPEC["motion_median_min"] or (q(s, "mot_min") or 0) < SPEC["motion_second_min"]]
    add("no_near_static_shots", not static, static or {"src": "output" if meas else "edl-qc", "n": len(clip_shots)})
    # (1b) no same-looking shot twice (different ranges of a near-identical source count as reuse)
    def hd(a, b):
        return bin(int(a) ^ int(b)).count("1")
    dups = []
    for i in range(len(clip_shots)):
        for j in range(i + 2, len(clip_shots)):
            ha, hb = q(clip_shots[i], "dh") or [], q(clip_shots[j], "dh") or []
            dmin = min((hd(x, y) for x in ha for y in hb), default=99)
            sa, sb = q(clip_shots[i], "sig"), q(clip_shots[j], "sig")
            sd = (sum(abs(x - y) for x, y in zip(sa, sb)) / len(sa)) if sa and sb and len(sa) == len(sb) else 999
            if dmin <= SPEC["dup_hash_max_dist"] or sd <= SPEC["dup_sig_max_diff"]:
                dups.append({"a": clip_shots[i]["t0"], "b": clip_shots[j]["t0"], "clips": [clip_shots[i].get("clip_id"), clip_shots[j].get("clip_id")],
                             "dist": dmin, "sig_diff": round(sd, 1)})
    missing_dh = [s["t0"] for s in clip_shots if not q(s, "dh")]
    add("no_visual_duplicate_shots", not dups and not missing_dh, (dups[:30] + ([{"missing_hash": missing_dh[:10]}] if missing_dh else [])) or "none")
    # (1c) v6: one use per continuous source scene, <= parent_uses_max uses per source clip
    qx, qual = load_qc(root)
    scenes = scene_index(qx)
    import math as _m
    from collections import defaultdict as _dd
    sc_use = _dd(list); par_use = _dd(list); no_scene = []
    for s in clip_shots:
        f = s.get("file"); a = int(_m.floor(float(s.get("file_in", 0)) + 1e-6))
        b = int(_m.ceil(float(s.get("file_in", 0)) + (s["t1"] - s["t0"]) * float(s.get("play_speed", 1)) - 1e-6))
        ids = {scenes.get(f, {}).get(k) for k in range(a, max(a + 1, b))} - {None}
        if not ids:
            no_scene.append(s["t0"])
        for i_ in ids:
            sc_use[(s.get("video_id"), f, i_)].append(s["t0"])
        par_use[s.get("parent") or s.get("clip_id")].append(s["t0"])
    sc_bad = [{"video_id": k[0], "scene": k[2], "uses_t0": v} for k, v in sc_use.items() if len(v) > SPEC["scene_uses_max"]]
    add("source_scene_used_once", not sc_bad and not no_scene, (sc_bad[:40] + ([{"no_scene_qc": no_scene[:10]}] if no_scene else [])) or {"scenes": len(sc_use)})
    vid_use = _dd(list)
    for s in clip_shots:
        vid_use[s.get("video_id")].append(s["t0"])
    vid_bad = [{"video_id": k, "uses": len(v), "t0": v} for k, v in vid_use.items() if len(v) > SPEC["video_uses_max"]]
    add("source_video_uses_le_cap", not vid_bad, vid_bad or {"max": max((len(v) for v in vid_use.values()), default=0)})
    par_bad = [{"clip": k, "uses": len(v), "t0": v} for k, v in par_use.items() if len(v) > SPEC["parent_uses_max"]]
    add("source_clip_uses_le_cap", not par_bad, par_bad or {"max": max((len(v) for v in par_use.values()), default=0)})
    # (1d) v6: camera actually moves. Water shimmer inflates pixel-difference motion, so a shot is "still" when the
    # per-second phase-correlation shift (96x54) has median < cam_shift_min AND block-level change (gmot) < cam_gmot_min.
    # Forward-travel shots (dash/window: shows driving, plane-taxi or window-seat) have no translation and are exempt.
    # window-seat = forward-facing window view of a landing approach; it still has to pass the motion and luma floors.
    def seg(s):
        f = s.get("file"); a = int(_m.floor(float(s.get("file_in", 0)) + 1e-6))
        b = int(_m.ceil(float(s.get("file_in", 0)) + (s["t1"] - s["t0"]) * float(s.get("play_speed", 1)) - 1e-6))
        return [x for x in (qx.get(f, {}).get(k) for k in range(a, max(a + 1, b))) if x and "shift" in x]
    still = []
    for s in clip_shots:
        v = seg(s)
        if set(s.get("shows") or []) & {"driving", "plane-taxi", "window-seat"}:
            continue
        if not v:
            still.append({"t0": s["t0"], "clip": s.get("clip_id"), "why": "no v3 qc"}); continue
        sh_, gm_ = statistics.median(x["shift"] for x in v), statistics.median(x["gmot"] for x in v)
        if sh_ < SPEC["cam_shift_min"] and gm_ < SPEC["cam_gmot_min"]:
            still.append({"t0": s["t0"], "clip": s.get("clip_id"), "shift": round(sh_, 2), "gmot": round(gm_, 2)})
    add("camera_moves_no_still_drone", not still, still[:40] or "none")
    # (1e) v6: source quality: >=1080p effective, >=24 fps, sharp
    lowq = []
    for s in clip_shots:
        qq = qual.get(s.get("clip_id")) or qual.get(s.get("parent")) or {}
        why = []
        if (qq.get("eff_h") or 0) < SPEC["src_height_min"]: why.append(f"eff_h {qq.get('eff_h')}")
        if (qq.get("src_fps") or 0) < SPEC["src_fps_min"]: why.append(f"fps {qq.get('src_fps')}")
        if qq.get("lap_med") is None or qq["lap_med"] < SPEC["sharp_lap_min"]: why.append(f"lap {qq.get('lap_med')}")
        if why:
            lowq.append({"t0": s["t0"], "clip": s.get("clip_id"), "why": why})
    add("source_quality_1080p_24fps_sharp", not lowq, lowq[:40] or "none")
    # (2) brightness floor
    dark = [{"t0": s["t0"], "clip": s.get("clip_id"), "y_mean": q(s, "y_mean"), "y_min": q(s, "y_min")} for s in clip_shots
            if q(s, "y_mean") is None or q(s, "y_mean") < SPEC["luma_mean_min"] or (q(s, "y_min") or 0) < SPEC["luma_frame_min"]]
    add("no_dark_shots", not dark, dark or "none")
    # (3) banned clips / ranges (reversed, selfie, logo, dark, ... recorded in footage.json "banned")
    bans = edl.get("banned") or []
    hit = []
    for s in clip_shots:
        for b in bans:
            if (b.get("clip_id") and b["clip_id"] in (s.get("clip_id"), s.get("parent"))) or (b.get("video_id") == s.get("video_id") and b.get("src_in") is not None
                    and _overlap((float(s["src_in"]), float(s["src_out"])), (float(b["src_in"]), float(b["src_out"]))) > 0):
                hit.append({"t0": s["t0"], "clip": s.get("clip_id"), "ban": b.get("reason")})
    add("no_banned_clips", "banned" in edl and not hit, hit or {"bans": len(bans)} if "banned" in edl else "EDL has no ban list")
    # (4) every shot shows what its sentence is about
    sents_all = edl.get("sentences", [])
    mism = []
    for s in clip_shots:
        li = s.get("line")
        need = set((sents_all[li].get("need") or []) if li is not None and li < len(sents_all) else [])
        shows = set(s.get("shows") or [])
        if not need or not (need & shows):
            mism.append({"t0": s["t0"], "line": li, "need": sorted(need), "shows": sorted(shows), "clip": s.get("clip_id")})
    add("footage_matches_sentence", not mism, mism[:40] or "none")
    # (5) natural sound clearly audible: voice-free lifts on audio-licensed shots + ducked ambient under voice
    lifts = edl.get("lifts") or []
    good_l = []
    for L in lifts:
        cov = [s for s in shots if s["t1"] > L["t0"] and s["t0"] < L["t1"]]
        if L["t1"] - L["t0"] >= SPEC["lift_min_s"] - 1e-6 and cov and all(s.get("audio_ok") for s in cov):
            good_l.append(L)
    need_n = int(edl.get("lift_min_count", SPEC["lift_min_count"]))
    det = {"planned": len(lifts), "valid": len(good_l), "need": need_n}
    ok5 = len(good_l) >= need_n
    if output is not None and "lifts" in output:
        lr = output["lifts"]
        det["measured_rms_dbfs"] = lr
        ok5 = ok5 and len(lr) >= need_n and all(x is not None and x >= SPEC["lift_rms_min_dbfs"] for x in lr)
    if output is not None and "ambient_under_voice_db" in output:
        a = output["ambient_under_voice_db"]
        det["ambient_under_voice_db"] = a
        ok5 = ok5 and a is not None and SPEC["ambient_under_voice_db"][0] <= a <= SPEC["ambient_under_voice_db"][1]
    add("natural_sound_audible", ok5, det)
    failed = [k for k, v in g.items() if not v["pass"]]
    return {"pass": not failed, "failed": failed, "gates": g, "spec": SPEC}


def measure_shots(path: Path, edl: dict, fps: int = 6, w: int = 96, h: int = 54) -> dict:
    """Per-shot motion / luma / dHash measured on the RENDERED file (gates 1-2), keyed by shot t0."""
    import numpy as np
    b = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", str(path), "-an", "-vf", f"fps={fps},scale={w}:{h},format=gray", "-f", "rawvideo", "-"],
                       capture_output=True).stdout
    a = np.frombuffer(b, np.uint8).reshape(-1, h, w).astype(np.float32)
    bc = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", str(path), "-an", "-vf", "fps=2,scale=16:9,format=rgb24", "-f", "rawvideo", "-"],
                        capture_output=True).stdout
    col = np.frombuffer(bc, np.uint8).reshape(-1, 9, 16, 3).astype(np.float32)
    res = {}
    for s in edl.get("shots", []):
        if s.get("kind") not in FOOTAGE_KINDS:
            continue
        i0, i1 = int(np.ceil(s["t0"] * fps)) + 1, int(np.floor(s["t1"] * fps)) - 1  # skip cut frames
        blk = a[i0:i1]
        if len(blk) < 3:
            continue
        d = np.abs(np.diff(blk, axis=0)).mean(axis=(1, 2)) * 100 / 255
        per = [float(d[k:k + fps].mean()) for k in range(0, max(1, len(d) - fps + 1), fps)] or [float(d.mean())]
        ys = blk.mean(axis=(1, 2))
        def dh(fr):
            bh, bw = h // 8, w // 9
            m = fr[:bh * 8, :bw * 9].reshape(8, bh, 9, bw).mean(axis=(1, 3))
            return int("".join("1" if x else "0" for x in (m[:, 1:] > m[:, :-1]).flatten()), 2)
        res[str(round(s["t0"], 3))] = {"mot_med": round(float(np.median(per)), 3), "mot_min": round(min(per), 3), "y_mean": round(float(ys.mean()), 1),
                                       "y_min": round(float(ys.min()), 1), "dh": [dh(blk[len(blk) // 2])],
                                       "sig": [round(float(v), 1) for v in col[min(int((s["t0"] + s["t1"])), len(col) - 1)].flatten()]}
    return res


def measure_audio(path: Path, edl: dict, ambient_wav: Path | None = None, narration_wav: Path | None = None) -> dict:
    """RMS (dBFS) of the final mix inside each planned lift; ducked-ambient vs voice level over audio-licensed shots."""
    import numpy as np
    def load(f):
        b = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", str(f), "-vn", "-ac", "1", "-ar", "8000", "-f", "f32le", "-"], capture_output=True).stdout
        return np.frombuffer(b, np.float32)
    def db(x):
        return round(float(20 * np.log10(np.sqrt((x ** 2).mean()) + 1e-9)), 1) if len(x) else None
    mix = load(path); sr = 8000
    out = {"lifts": [db(mix[int(L["t0"] * sr):int(L["t1"] * sr)]) for L in edl.get("lifts") or []]}
    if ambient_wav and narration_wav and Path(ambient_wav).exists() and Path(narration_wav).exists():
        amb, nar = load(ambient_wav), load(narration_wav)
        n = min(len(amb), len(nar)); amb, nar = amb[:n], nar[:n]
        idx = []
        for s in edl.get("shots", []):
            if s.get("audio_ok"):
                idx.append((int(s["t0"] * sr), min(n, int(s["t1"] * sr))))
        # only where the voice is actually speaking
        fr = int(0.05 * sr)
        A, N = [], []
        for a0, a1 in idx:
            for k in range(a0, a1 - fr, fr):
                nv = nar[k:k + fr]
                if np.sqrt((nv ** 2).mean()) > 0.02:
                    A.append(amb[k:k + fr]); N.append(nv)
        if A:
            out["ambient_under_voice_db"] = round(db(np.concatenate(A)) - db(np.concatenate(N)), 1)
        else:
            out["ambient_under_voice_db"] = None
    return out


def measure_output(path: Path, freeze: bool, edl: dict | None = None, ambient_wav: Path | None = None, narration_wav: Path | None = None) -> dict:
    out = {}
    if edl is not None:
        out["shots"] = measure_shots(path, edl)
        out.update(measure_audio(path, edl, ambient_wav, narration_wav))
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-vn", "-af",
                        "loudnorm=I=-14:TP=-1:LRA=11:print_format=json", "-f", "null", "-"], capture_output=True, text=True)
    m = re.findall(r"\{[^{}]*\"input_i\"[^{}]*\}", r.stderr, re.S)
    if m:
        st = json.loads(m[-1])
        out["lufs"], out["true_peak"] = float(st["input_i"]), float(st["input_tp"])
    pr = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,duration", "-of", "json", str(path)],
                                   capture_output=True, text=True).stdout or "{}")
    for s in pr.get("streams", []):
        if s.get("codec_type") == "video":
            out["duration_s"] = float(s.get("duration") or 0)
        if s.get("codec_type") == "audio":
            out["audio_duration_s"] = float(s.get("duration") or 0)
    if freeze:
        r = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(path), "-vf", "freezedetect=n=0.003:d=1", "-an", "-f", "null", "-"],
                           capture_output=True, text=True)
        durs = [float(x) for x in re.findall(r"freeze_duration: ([\d.]+)", r.stderr)]
        starts = [float(x) for x in re.findall(r"freeze_start: ([\d.]+)", r.stderr)]
        out["freeze"] = {"count": len(durs), "max_s": max(durs) if durs else 0.0, "starts_s": starts[:20]}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--edl", type=Path, required=True)
    ap.add_argument("--licence", type=Path, required=True)
    ap.add_argument("--output", type=Path)
    ap.add_argument("--freeze", action="store_true")
    ap.add_argument("--write", type=Path, required=True)
    a = ap.parse_args()
    edl = json.loads(a.edl.read_text())
    edl_d = json.loads(a.edl.read_text())
    out = measure_output(a.output, a.freeze, edl_d) if a.output else None
    res = evaluate(edl, read_rows(a.licence), out, root=a.licence.parent)
    res.update({"edl": str(a.edl), "output": str(a.output) if a.output else None})
    a.write.parent.mkdir(parents=True, exist_ok=True)
    a.write.write_text(json.dumps(res, indent=2) + "\n")
    print(json.dumps({"pass": res["pass"], "failed": res["failed"]}))
    raise SystemExit(0 if res["pass"] else 1)


if __name__ == "__main__":
    main()
