"""checks: write out/checks.json; every check must pass.

When used-sources.json is present, also enforce computed real-footage coverage,
no unintended graphics fallback, and a non-zero sourced-clip count.
"""
from __future__ import annotations

import re
from pathlib import Path

from .assets import read_log
from .captions import parse_srt
from .common import ROOT, PhaseError, ffprobe_json, load_json, log, run, save_json, settings, tool, now_iso
from .description import URL_RE, chapters_from_timing
from .render import disclosure_para, out_name
from .script import OPERATOR_RE, PRICE_RE, selected_units, units
from .tts import measure_loudness

GRAB_POINTS = (0, 25, 50, 75, 100)
AFFILIATE_PATH_RE = re.compile(r"/(go|out)(/|$)", re.I)
BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/124.0 Safari/537.36")



def real_footage_coverage(tl: dict) -> dict:
    """Share of program (timeline minus end card) covered by real licensed clips.

    Computed from the timeline, never invented. Planned original maps/text do not
    count as footage. Graphics fallback shots are counted separately.
    """
    program = tl["endCard"]["from"] if tl.get("endCard") else tl.get("durationInFrames") or 0
    clip_frames = 0
    fallback = 0
    for s in tl.get("shots", []):
        start, dur = int(s.get("from", 0)), int(s.get("dur", 0))
        vis = max(0, min(start + dur, program) - start)
        if s.get("src") and not s.get("fallback_for"):
            clip_frames += vis
        if s.get("fallback_for"):
            fallback += 1
    return {
        "coverage": (clip_frames / program) if program else 0.0,
        "clip_frames": clip_frames,
        "program_frames": program,
        "fallback_shots": fallback,
    }


def check_link(url: str, session=None) -> tuple[bool, str]:
    """200 required. Affiliate /go and /out redirects are never followed (a 30x there passes)."""
    import requests

    s = session or requests.Session()
    hdr = {"User-Agent": BROWSER_UA, "Accept": "text/html,application/xhtml+xml,*/*"}
    affiliate = bool(AFFILIATE_PATH_RE.search(url))
    try:
        r = s.head(url, allow_redirects=not affiliate, timeout=30, headers=hdr)
        if r.status_code in (403, 405, 501) or (r.status_code >= 400 and not affiliate):
            r = s.get(url, allow_redirects=not affiliate, timeout=30, headers=hdr, stream=True)
            r.close()
    except Exception as e:
        return False, f"error: {type(e).__name__}"
    if affiliate and r.status_code in (200, 301, 302, 303, 307, 308):
        return True, f"{r.status_code} (affiliate redirect not followed)"
    return r.status_code == 200, str(r.status_code)


def frame_grabs(video: Path, qa: Path, stem: str) -> list[str]:
    ff = tool("ffmpeg") or "ffmpeg"
    dur = float(ffprobe_json(video)["format"]["duration"])
    out = []
    for pct in GRAB_POINTS:
        t = min(max(dur * pct / 100, 0), max(dur - 0.1, 0))
        dest = qa / f"{stem}-{pct:03d}.jpg"
        run([ff, "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{t:.3f}", "-i", str(video), "-frames:v", "1",
             "-q:v", "3", str(dest)])
        out.append(dest)
    return [str(p.relative_to(ROOT)) for p in out if p.exists() and p.stat().st_size > 0]


def run_phase(ctx) -> dict:
    cfg = settings()
    chk = cfg["checks"]
    results: list[dict] = []

    def add(name, ok, detail):
        results.append({"name": name, "pass": bool(ok), "detail": detail})

    us = selected_units(ctx)
    tls = {u: load_json(ctx.paths.build / f"timeline-{u}.json", default={}) for u in us}
    timings = {u: load_json(ctx.paths.tts / u / "timing.json", default={}) for u in us}

    # 1. licence row per asset (static + every clip used in any timeline)
    rows = read_log(ctx.paths.licence_log)
    have = {r["asset_id"] for r in rows if r.get("licence") and r.get("url") and r.get("source")}
    manifest = load_json(ctx.paths.build / "assets.json", default={"clips": {}, "static": []})
    needed = set(manifest["static"]) | {c["asset_id"] for c in manifest["clips"].values() if c.get("asset_id")}
    used_src = {s["src"] for tl in tls.values() for s in tl.get("shots", []) if s.get("src")}
    files_logged = {r["file"] for r in rows}
    missing = sorted((needed - have) | {f for f in used_src if f not in files_logged})
    add("licence_row_per_asset", not missing and needed,
        f"{len(rows)} rows; {len(needed)} assets needed" + (f"; missing: {missing}" if missing else ""))

    # 2/3. disclosure spoken and on screen within 30 s, every unit
    for u, script in us.items():
        dp = disclosure_para(script, cfg["disclosure"]["keyword"])
        t = next((p["start"] for p in timings[u].get("paragraphs", []) if dp and p["id"] == dp.id), None)
        add(f"disclosure_spoken_lt30s[{u}]", t is not None and t < 30, f"starts {t}s" if t is not None else "none")
        d = tls[u].get("disclosure") or {}
        fps = tls[u].get("fps", 30)
        ok = d and d["from"] / fps < 30 and d["dur"] / fps >= 3
        add(f"disclosure_onscreen_lt30s[{u}]", ok, f"card {d.get('from', 0) / fps:.1f}s for {d.get('dur', 0) / fps:.1f}s" if d else "none")

    # 4. loudness and clipping on the final files
    for u in us:
        f = ctx.paths.out / out_name(u, getattr(ctx, 'output_stem', None))
        if not f.exists():
            add(f"loudness[{u}]", False, "output missing")
            continue
        m = measure_loudness(f)
        ok = abs(m["lufs"] - chk["lufs_target"]) <= chk["lufs_tolerance"] and m["true_peak"] <= chk["max_true_peak"]
        add(f"loudness[{u}]", ok, f"{m['lufs']:.1f} LUFS, TP {m['true_peak']:.1f} dBTP (target -14 ±1, TP <= {chk['max_true_peak']})")

    # 5. captions present (SRT for all; burned into Shorts)
    for u in us:
        srt = ctx.paths.out / f"{u}.srt"
        cues = parse_srt(srt.read_text(encoding="utf-8")) if srt.exists() else []
        burned = (not u.startswith("short")) or bool(tls[u].get("captions"))
        tot = timings[u].get("total", 0)
        ok = bool(cues) and burned and cues[-1]["end"] <= tot + 0.01
        add(f"captions[{u}]", ok, f"{len(cues)} cues" + ("" if u == "long" else f", burned={burned}"))

    # 6. every link in every description returns 200
    import requests

    sess = requests.Session()
    urls = []
    for f in sorted(ctx.paths.out.glob("description*.txt")):
        urls += URL_RE.findall(f.read_text(encoding="utf-8"))
    urls = list(dict.fromkeys(u.rstrip(".,") for u in urls))
    bad = []
    for u in urls:
        ok, why = check_link(u, sess)
        if not ok:
            bad.append(f"{u} -> {why}")
    add("links_200", urls and not bad, f"{len(urls)} links" + (f"; failing: {bad}" if bad else " all 200"))

    # 7. frame grabs
    grabs = {}
    for u in us:
        f = ctx.paths.out / out_name(u, getattr(ctx, 'output_stem', None))
        grabs[u] = frame_grabs(f, ctx.paths.qa, u) if f.exists() else []
    add("frame_grabs", all(len(g) == len(GRAB_POINTS) for g in grabs.values()),
        f"{sum(len(g) for g in grabs.values())} grabs in out/qa/")

    # extra: output specs
    for u in us:
        f = ctx.paths.out / out_name(u, getattr(ctx, 'output_stem', None))
        if not f.exists():
            add(f"format[{u}]", False, "missing")
            continue
        info = ffprobe_json(f)
        v = next(s for s in info["streams"] if s["codec_type"] == "video")
        a = next((s for s in info["streams"] if s["codec_type"] == "audio"), {})
        want = (1080, 1920) if u.startswith("short") else (1920, 1080)
        fps = _fps(v.get("r_frame_rate", "0/1"))
        dur = float(info["format"]["duration"])
        ok = ((v["width"], v["height"]) == want and v["codec_name"] == "h264" and abs(fps - 30) < 0.01
              and a.get("codec_name") == "aac" and a.get("sample_rate") == "48000")
        if u.startswith("short"):
            ok = ok and dur <= 60
        add(f"format[{u}]", ok, f"{v['width']}x{v['height']} {v['codec_name']} {fps:g}fps, audio {a.get('codec_name')} {a.get('sample_rate')}Hz, {dur:.1f}s")

    # extra: script requirements
    long_s, long_t = us["long"], timings["long"]
    words = long_s.words
    add("script_words_1200_1700", 1200 <= words <= 1700, f"{words} words")
    total = long_t.get("total", 0) + cfg["render"]["end_card_s"]
    add("long_length_8_12min", 480 <= total <= 720, f"{total / 60:.2f} min")
    hook = long_t["paragraphs"][0]["end"] if long_t.get("paragraphs") else 99
    add("hook_le_15s", hook <= 15, f"hook ends {hook:.1f}s")
    chs = chapters_from_timing(long_s, long_t) if long_t else []
    spans = [round((chs[i + 1][0] if i + 1 < len(chs) else total) - chs[i][0], 1) for i in range(len(chs))]
    add("chapters_every_60_120s", len(chs) >= 3 and all(60 <= s <= 120 for s in spans), f"spans {spans}")
    for u, s in us.items():
        if u.startswith("short"):
            d = timings[u].get("total", 0)
            add(f"short_length_30_50s[{u}]", 30 <= d <= 50, f"{d:.1f}s narration")
    prices = [f"{u}/{p.id}" for u, s in us.items() for p in s.paragraphs if PRICE_RE.search(p.text)]
    add("no_fixed_prices", not prices, "none" if not prices else f"found in {prices}")
    ops = [f"{u}/{p.id}" for u, s in us.items() for p in s.paragraphs if OPERATOR_RE.search(p.text)]
    add("no_operator_claims", not ops, "none" if not ops else f"found in {ops}")
    facts = load_json(ctx.paths.video / "facts.json", default={})
    unsourced = [p.id for p in long_s.paragraphs if p.facts and any(f not in facts for f in p.facts)]
    add("facts_have_sources", not unsourced, "all cited facts in facts.json" if not unsourced else f"{unsourced}")

    # extra: thumbnails and description shape
    th = sorted(ctx.paths.out.glob("thumb-*.png"))
    th_ok = len(th) == 3
    sizes = []
    if th_ok:
        from PIL import Image

        for p in th:
            with Image.open(p) as im:
                sizes.append((im.size, p.stat().st_size))
        th_ok = all(sz == (1280, 720) and b < 2 * 1024 * 1024 for sz, b in sizes)
    add("thumbnails", th_ok, f"{len(th)} files " + ", ".join(f"{b // 1024}KB" for _, b in sizes))
    desc = ctx.paths.out / "description.txt"
    dl = desc.read_text(encoding="utf-8").splitlines() if desc.exists() else []
    tags = re.findall(r"(?<!\S)#\w+", "\n".join(dl))
    ok = (len(dl) > 2 and "commission" in dl[0].lower() and "aurum-transfers.com" in dl[1]
          and any(l.startswith("00:00 ") for l in dl) and len(tags) <= 3)
    add("description_shape", ok, f"line1 disclosure, line2 main link, 00:00 chapter, {len(tags)} hashtags")


    # extra: real-footage gates when an explicit used-sources plan is present
    plan_path = ctx.paths.video / "used-sources.json"
    if plan_path.exists() and "long" in us:
        plan = load_json(plan_path)
        cov = real_footage_coverage(tls.get("long") or {})
        min_cov = float(plan.get("min_real_footage_coverage", 0.80))
        n_clip = sum(1 for v in manifest["clips"].values() if v.get("asset_id") and not v.get("fallback"))
        n_fb = sum(1 for v in manifest["clips"].values() if v.get("fallback"))
        add("real_footage_coverage", cov["coverage"] >= min_cov,
            f"{cov['coverage']:.1%} of program before end card (min {min_cov:.0%}; {cov['clip_frames']}/{cov['program_frames']} frames)")
        # post-Bali spec: a fallback always FAILS the video; plan flags cannot waive it
        add("no_graphics_fallback", n_fb == 0 and cov["fallback_shots"] == 0,
            f"manifest fallback={n_fb}, timeline fallback={cov['fallback_shots']}")
        add("nonzero_real_footage", n_clip > 0 and cov["clip_frames"] > 0,
            f"{n_clip} sourced clips, {cov['clip_frames']} clip frames")

    # post-Bali spec HARD gates (tools/spec_gates.py) on the EDL build, when present
    edl_path = ctx.paths.build / "edl-long.json"
    if edl_path.exists():
        import sys as _sys
        _sys.path.insert(0, str(ROOT / "tools"))
        import spec_gates
        f = ctx.paths.out / out_name("long", getattr(ctx, 'output_stem', None))
        edl_d = load_json(edl_path)
        # v5: per-shot motion/luma/dHash and natural-sound lifts are measured on the rendered file, not trusted from the plan
        mo = spec_gates.measure_output(f, True, edl_d, ctx.paths.build / "ambd-hd.wav", ctx.paths.build / "narration.wav") if f.exists() else None
        spec = spec_gates.evaluate(edl_d, spec_gates.read_rows(ctx.paths.licence_log), mo, root=ctx.paths.video)
        for k, v in spec["gates"].items():
            add(f"spec:{k}", v["pass"], v["detail"] if isinstance(v["detail"], str) else str(v["detail"])[:400])

    report = {"slug": ctx.slug, "generated": now_iso(), "all_pass": all(r["pass"] for r in results),
              "passed": sum(r["pass"] for r in results), "total": len(results), "checks": results,
              "frame_grabs": grabs}
    save_json(ctx.paths.out / "checks.json", report)
    for r in results:
        log(f"{'PASS' if r['pass'] else 'FAIL'} {r['name']}: {r['detail']}")
    if not report["all_pass"]:
        raise PhaseError(f"{report['total'] - report['passed']} check(s) failed; see out/checks.json")
    return {"passed": report["passed"], "total": report["total"]}


def _fps(rate: str) -> float:
    n, d = rate.split("/")
    return float(n) / float(d or 1)
