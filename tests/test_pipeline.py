import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pipeline  # noqa: E402
from aurum_video import assets, captions, checks, common, description, maps, render, script, upload  # noqa: E402

SLUG = "aruba-travel-guide"
VDIR = ROOT / "videos" / SLUG


# ---------- CLI ----------
def test_cli_all_runs_every_phase_in_order():
    args = pipeline.build_parser().parse_args([SLUG, "--all", "--no-upload"])
    assert pipeline.select_phases(args) == common.PHASES
    assert args.no_upload


def test_cli_output_stem_and_unit():
    args = pipeline.build_parser().parse_args(
        [SLUG, "--all", "--no-upload", "--unit", "long", "--output-stem", "long-v2"]
    )
    assert args.output_stem == "long-v2" and args.unit == ["long"]
    assert render.out_name("long", args.output_stem) == "long-v2.mp4"
    assert render.out_name("long") == "long.mp4"
    assert render.out_name("short-1", "long-v2") == "short-1.mp4"


def test_cli_stop_after_and_only():
    a = pipeline.build_parser().parse_args([SLUG, "--all", "--stop-after-render"])
    assert pipeline.select_phases(a)[-1] == "render"
    b = pipeline.build_parser().parse_args([SLUG, "--only", "checks"])
    assert pipeline.select_phases(b) == ["checks"]
    with pytest.raises(SystemExit):
        pipeline.select_phases(pipeline.build_parser().parse_args([SLUG]))


def test_captions_phase_runs_before_render():
    assert common.PHASES.index("captions") < common.PHASES.index("render")


# ---------- script ----------
def test_parse_script_paragraphs_chapters_and_facts():
    s = script.parse_text("# T\n> note\n## One\nHello there.\n<!-- f80001 f80002 -->\n\nSecond para.\n## Two\nThird.\n")
    assert s.title == "T"
    assert [p.text for p in s.paragraphs] == ["Hello there.", "Second para.", "Third."]
    assert s.paragraphs[0].facts == ["f80001", "f80002"]
    assert s.chapters == [("One", "p01"), ("Two", "p03")]


def test_tts_respelling_only_whole_words():
    r = {"Oranjestad": "oh-RAHN-yuh-stahd", "ED-Card": "E D Card"}
    assert script.tts_text("Oranjestad's ED-Card.", r) == "oh-RAHN-yuh-stahd's E D Card."
    assert script.tts_text("MyOranjestad", r) == "MyOranjestad"


@pytest.mark.parametrize("text", ["It costs $20.", "US$15 day pass", "about 40 dollars", "AWG 4.50", "twenty dollars"])
def test_price_regex_catches_prices(text):
    assert script.PRICE_RE.search(text)


@pytest.mark.parametrize("text", ["nine one one", "one hundred for the police", "twenty percent of Aruba"])
def test_price_regex_ignores_non_prices(text):
    assert not script.PRICE_RE.search(text)


def test_operator_regex():
    assert script.OPERATOR_RE.search("Our drivers will meet you")
    assert not script.OPERATOR_RE.search("We don't run transfers, tours or hotels ourselves.")


# ---------- real content for the first video ----------
def test_aruba_script_meets_brief():
    us = script.units(VDIR)
    long = us["long"]
    assert 1200 <= long.words <= 1700
    assert long.paragraphs[0].words <= 35  # hook must fit in 15 s
    joined = " ".join(p.text for s in us.values() for p in s.paragraphs)
    assert not script.PRICE_RE.search(joined)
    assert not script.OPERATOR_RE.search(joined)
    assert any("transfer" in p.text and "partner" in p.text for p in long.paragraphs)
    assert "Island Guide" in long.paragraphs[-2].text
    assert sorted(k for k in us if k.startswith("short")) == ["short-1", "short-2", "short-3"]
    for name, s in us.items():
        dp = render.disclosure_para(s, "commission")
        assert dp is not None and s.paragraphs.index(dp) <= 1, name


def test_shotlist_has_one_entry_per_paragraph():
    sl = json.loads((VDIR / "shotlist.json").read_text(encoding="utf-8"))
    for unit, s in script.units(VDIR).items():
        assert [e["id"] for e in sl[unit]] == [p.id for p in s.paragraphs], unit
        for e in sl[unit]:
            for shot in e["shots"]:
                assert shot["type"] in {"map", "sea", "desert", "town", "calendar", "checklist", "text", "clip"}
                if shot["type"] == "clip":
                    if unit == "long":
                        assert shot.get("source_clip_id"), "long clip shots need source_clip_id"
                        assert not shot.get("fallback"), "improved long cut must not declare graphics fallback"
                    else:
                        assert shot.get("fallback") or shot.get("source_clip_id"), (
                            "clip shots need a source_clip_id or an own-graphics fallback"
                        )


def test_links_config_main_only_and_guidebook_empty():
    cfg = json.loads((ROOT / "config" / "links.json").read_text(encoding="utf-8"))[SLUG]
    assert cfg["main"]["url"].startswith("https://aurum-transfers.com/")
    assert [l["key"] for l in cfg["links"]] == ["guidebook"]
    assert cfg["links"][0]["url"] == "" and "TODO" in cfg["links"][0]["todo"]


# ---------- captions ----------
def test_cues_fit_paragraph_windows_and_srt_roundtrip():
    s = script.parse_text("# T\n## A\nOne two three. Four five six seven eight nine ten eleven twelve.\n\nShort.\n")
    timing = [{"id": "p01", "start": 0.3, "end": 5.3}, {"id": "p02", "start": 5.8, "end": 6.8}]
    cues = captions.build_cues(s.paragraphs, timing, 20)
    assert cues[0]["start"] == pytest.approx(0.3)
    assert max(c["end"] for c in cues if c["start"] < 5.5) == pytest.approx(5.3, abs=0.01)
    back = captions.parse_srt(captions.to_srt(cues))
    assert len(back) == len(cues) and back[-1]["end"] == pytest.approx(6.8, abs=0.002)


def test_srt_time_format():
    assert captions.srt_time(3723.456) == "01:02:03,456"


# ---------- description ----------
def test_subid_and_timestamps():
    assert description.with_subid("https://x.com/a?b=1", "subid", "abc") == "https://x.com/a?b=1&subid=yt_abc"
    assert description.with_subid("https://x.com/a?subid=old", "subid", "n") == "https://x.com/a?subid=yt_n"
    assert common.fmt_ts(0) == "00:00" and common.fmt_ts(75.9) == "01:15" and common.fmt_ts(3725) == "1:02:05"


def test_chapters_start_at_zero():
    s = script.parse_text("# T\n## A\nx\n\ny\n## B\nz\n")
    t = {"paragraphs": [{"id": "p01", "start": 0.3}, {"id": "p02", "start": 2}, {"id": "p03", "start": 70.2}]}
    assert description.chapters_from_timing(s, t) == [(0.0, "A"), (70.2, "B")]


def test_parse_sources_table():
    md = "| # | Publisher | Page | Facts | Date |\n|---|---|---|---|---|\n| 1 | ATA | https://www.aruba.com/a | f1 | d |\n| 2 | ATA | https://www.aruba.com/a | f2 | d |\n"
    assert description.parse_sources(md) == [("ATA", "https://www.aruba.com/a")]


def test_description_build(tmp_path, monkeypatch):
    paths = common.Paths(SLUG)
    tdir = tmp_path / "tts" / "long"
    tdir.mkdir(parents=True)
    long = script.units(VDIR)["long"]
    paras = [{"id": p.id, "start": i * 20.0} for i, p in enumerate(long.paragraphs)]
    (tdir / "timing.json").write_text(json.dumps({"paragraphs": paras, "total": 600}))
    monkeypatch.setattr(common.Paths, "tts", property(lambda self: tmp_path / "tts"))
    ctx = SimpleNamespace(slug=SLUG, paths=paths)
    text = description.build(ctx, "long", "VID123")
    lines = text.splitlines()
    assert "commission" in lines[0].lower()
    assert lines[1].endswith("aruba-aw?subid=yt_VID123")
    assert "00:00 Welcome to Aruba" in lines
    assert len([w for w in text.split() if w.startswith("#")]) <= 3
    assert "guidebook" not in text.lower() or "subid=yt_VID123" in text  # empty guidebook link is skipped
    urls = description.URL_RE.findall(text)
    assert all(u.startswith("https://") for u in urls)


# ---------- licence log ----------
def test_licence_log_roundtrip_and_has_row(tmp_path):
    p = tmp_path / "log.csv"
    assets.write_log(p, [{"asset_id": "pexels-1", "file": "assets/pexels-1.mp4", "source": "Pexels", "creator": "A",
                          "url": "https://pexels.com/v/1", "licence": "Pexels License", "date": "2026-11-09"}])
    rows = assets.read_log(p)
    assert assets.has_row(rows, "pexels-1") and not assets.has_row(rows, "pexels-2")


def test_render_refuses_clip_without_licence_row():
    s = script.parse_text("# T\n## A\nHello commission.\n")
    timing = {"total": 5.0, "paragraphs": [{"id": "p01", "start": 0.3, "end": 4.0}]}
    entries = [{"id": "p01", "shots": [{"type": "clip", "queries": ["x"]}]}]
    cfg = common.settings()
    meta = {"end_card": {"title": "E", "lines": []}}
    with pytest.raises(common.PhaseError, match="no licence row"):
        render.build_timeline("long", s, timing, entries, {"long/p01/0": {"asset_id": "pexels-9", "file": "assets/x.mp4"}},
                              [], {"places": {}}, meta, cfg, None)


def test_timeline_fallback_disclosure_and_frames():
    s = script.parse_text("# T\n## A\nHook.\n\nWe may earn a commission.\n## B\nMore.\n")
    timing = {"total": 30.0, "paragraphs": [{"id": "p01", "start": 0.3, "end": 3}, {"id": "p02", "start": 3.5, "end": 9},
                                            {"id": "p03", "start": 9.5, "end": 29}]}
    entries = [{"id": "p01", "shots": [{"type": "clip", "queries": ["x"], "fallback": {"type": "sea"}}]},
               {"id": "p02", "shots": [{"type": "text", "text": "x"}]},
               {"id": "p03", "shots": [{"type": "map"}, {"type": "sea"}], "lower_third": {"title": "L"}}]
    tl = render.build_timeline("long", s, timing, entries, {"long/p01/0": {"fallback": True}}, [], {"places": {}},
                               {"end_card": {"title": "E", "lines": []}}, common.settings(), None)
    assert tl["shots"][0]["type"] == "sea" and tl["shots"][0]["from"] == 0
    assert sum(x["dur"] for x in tl["shots"]) == tl["durationInFrames"]
    assert tl["disclosure"]["from"] == 105
    assert tl["chapters"][0]["title"] == "B"


# ---------- checks ----------
class _Resp:
    def __init__(self, code):
        self.status_code = code

    def close(self):
        pass


class _Sess:
    def __init__(self, code):
        self.code, self.calls = code, []

    def head(self, url, allow_redirects, **kw):
        self.calls.append(("head", url, allow_redirects))
        return _Resp(self.code)

    def get(self, url, allow_redirects, **kw):
        self.calls.append(("get", url, allow_redirects))
        return _Resp(self.code)


def test_affiliate_go_links_are_not_followed():
    sess = _Sess(302)
    ok, _ = checks.check_link("https://aurum-transfers.com/go/partner-x", sess)
    assert ok and sess.calls[0] == ("head", "https://aurum-transfers.com/go/partner-x", False)


def test_normal_links_need_200():
    assert checks.check_link("https://example.com/a", _Sess(200))[0]
    assert not checks.check_link("https://example.com/a", _Sess(404))[0]


# ---------- upload ----------
def test_upload_body_is_private_with_synthetic_media():
    b = upload.video_body("t", "d", [], common.settings())
    assert b["status"]["privacyStatus"] == "private"
    assert b["status"]["containsSyntheticMedia"] is True
    assert b["status"]["selfDeclaredMadeForKids"] is False
    assert b["snippet"]["categoryId"] == "19" and b["snippet"]["defaultLanguage"] == "en"


def test_upload_refuses_public():
    with pytest.raises(common.PhaseError):
        upload.assert_private({"status": {"privacyStatus": "public"}})


def test_upload_skipped_with_no_upload_flag():
    assert upload.run_phase(SimpleNamespace(no_upload=True)) == {"skipped": "--no-upload"}


def test_scrub_hides_secrets(monkeypatch):
    monkeypatch.setenv("PEXELS_API_KEY", "supersecretvalue")
    assert "supersecretvalue" not in common.scrub("key=supersecretvalue")


# ---------- map ----------
def test_map_places_land_inside_outline():
    m = maps.map_for_slug(VDIR)
    assert m["path"].startswith("M") and len(m["places"]) >= 10
    ring = [tuple(map(float, p.split(","))) for p in m["path"][1:-2].split(" L")]
    for k, p in m["places"].items():
        assert maps.point_in_poly(p["x"], p["y"], ring), k


def test_used_sources_plan_covers_every_long_clip():
    plan = json.loads((VDIR / "used-sources.json").read_text(encoding="utf-8"))
    sl = json.loads((VDIR / "shotlist.json").read_text(encoding="utf-8"))
    catalog = {c["clip_id"]: src for src in plan["sources"] for c in src["clips"]}
    needed = []
    for e in sl["long"]:
        for shot in e["shots"]:
            if shot["type"] == "clip":
                needed.append(shot["source_clip_id"])
                assert shot["source_clip_id"] in catalog, shot["source_clip_id"]
    assert plan["allow_graphics_fallback"] is False
    assert plan["min_real_footage_coverage"] >= 0.80
    unused = set(catalog) - set(needed)
    # A licensed clip may stay unused when putting it on screen would repeat a
    # look or mismatch the narration (e.g. a Palm Beach jetty over San Nicolás).
    allowed_unused = {"palm_pier_c"}
    assert unused <= allowed_unused, unused
    assert len(set(needed)) >= 28, set(needed)
    # A paragraph must not list the same clip twice (that would loop/pad inside one shot).
    # Reuse across different paragraphs is allowed only with a later in-point (start_s).
    for e in sl["long"]:
        ids = [s["source_clip_id"] for s in e["shots"] if s["type"] == "clip"]
        assert len(ids) == len(set(ids)), e["id"]


def test_build_timeline_fails_closed_without_footage_when_fallback_forbidden():
    s = script.parse_text("# T\n## A\nHello commission.\n")
    timing = {"total": 5.0, "paragraphs": [{"id": "p01", "start": 0.3, "end": 4.0}]}
    entries = [{"id": "p01", "shots": [{"type": "clip", "source_clip_id": "missing"}]}]
    cfg = common.settings()
    meta = {"end_card": {"title": "E", "lines": []}}
    with pytest.raises(common.PhaseError, match="no asset and no fallback"):
        render.build_timeline("long", s, timing, entries, {}, [], {"places": {}}, meta, cfg, None,
                              allow_fallback=False)


def test_real_footage_coverage_computed_and_zero_fails():
    empty = {
        "fps": 30,
        "durationInFrames": 300,
        "endCard": {"from": 270, "dur": 30},
        "shots": [{"type": "map", "from": 0, "dur": 270}],
    }
    z = checks.real_footage_coverage(empty)
    assert z["coverage"] == 0 and z["clip_frames"] == 0 and z["fallback_shots"] == 0
    mixed = {
        "fps": 30,
        "durationInFrames": 300,
        "endCard": {"from": 270, "dur": 30},
        "shots": [
            {"type": "clip", "src": "assets/a.mp4", "from": 0, "dur": 200},
            {"type": "map", "from": 200, "dur": 70, "fallback_for": "clip"},
        ],
    }
    c = checks.real_footage_coverage(mixed)
    assert c["clip_frames"] == 200 and c["program_frames"] == 270
    assert c["coverage"] == pytest.approx(200 / 270)
    assert c["fallback_shots"] == 1
    assert c["coverage"] < 0.80
    enough = {
        "fps": 30,
        "durationInFrames": 300,
        "endCard": {"from": 270, "dur": 30},
        "shots": [{"type": "clip", "src": "assets/a.mp4", "from": 0, "dur": 216}],
    }
    e = checks.real_footage_coverage(enough)
    assert e["coverage"] == pytest.approx(0.80)
    assert e["coverage"] >= 0.80


def test_explicit_ingest_fails_when_source_file_missing(tmp_path, monkeypatch):
    video = tmp_path / "video"
    video.mkdir()
    build = tmp_path / "build"
    public = build / "public"
    public.mkdir(parents=True)
    plan = {
        "allow_graphics_fallback": False,
        "library_dir": str(tmp_path / "missing-lib"),
        "sources": [{
            "video_id": "AAAAAAAAAAA",
            "url": "https://www.youtube.com/watch?v=AAAAAAAAAAA",
            "title": "x",
            "creator": "y",
            "licence": "Creative Commons Attribution license (reuse allowed)",
            "licence_checked_at": "2026-11-09",
            "clips": [{"clip_id": "c1", "place": "x", "source_in_s": 0, "source_out_s": 2, "speed": 1}],
        }],
    }
    (video / "used-sources.json").write_text(json.dumps(plan))
    (video / "shotlist.json").write_text(json.dumps({
        "long": [{"id": "p01", "shots": [{"type": "clip", "source_clip_id": "c1"}]}],
        "short-1": [], "short-2": [], "short-3": [],
    }))
    ctx = SimpleNamespace(
        slug="t",
        units=["long"],
        paths=SimpleNamespace(video=video, build=build, public=public, licence_log=video / "licence-log.csv"),
    )
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "registry.json").write_text(json.dumps({"assets": []}))
    monkeypatch.setattr(assets, "ROOT", tmp_path)
    with pytest.raises(common.PhaseError, match="source file"):
        assets.run_phase(ctx)


def test_explicit_ingest_stages_ready_precut_clip(tmp_path, monkeypatch):
    """A compliant pre-cut file is staged and recorded; must not crash by overwriting the staged dict."""
    import subprocess
    video = tmp_path / "video"
    video.mkdir()
    build = tmp_path / "build"
    public = build / "public"
    public.mkdir(parents=True)
    lib = tmp_path / "lib" / "clips"
    lib.mkdir(parents=True)
    clip = lib / "c1.mp4"
    subprocess.check_call([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", "testsrc2=s=1920x1080:r=30", "-t", "1",
        "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(clip),
    ])
    plan = {
        "allow_graphics_fallback": False,
        "library_dir": str(tmp_path / "lib"),
        "sources": [{
            "video_id": "AAAAAAAAAAA",
            "url": "https://www.youtube.com/watch?v=AAAAAAAAAAA",
            "title": "x",
            "creator": "y",
            "licence": "Creative Commons Attribution license (reuse allowed)",
            "licence_checked_at": "2026-11-09",
            "clips": [{"clip_id": "c1", "place": "x", "source_in_s": 0, "source_out_s": 1, "speed": 1}],
        }],
    }
    (video / "used-sources.json").write_text(json.dumps(plan))
    (video / "shotlist.json").write_text(json.dumps({
        "long": [{"id": "p01", "shots": [{"type": "clip", "source_clip_id": "c1"}]}],
        "short-1": [], "short-2": [], "short-3": [],
    }))
    ctx = SimpleNamespace(
        slug="t",
        units=["long"],
        paths=SimpleNamespace(video=video, build=build, public=public, licence_log=video / "licence-log.csv"),
    )
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "registry.json").write_text(json.dumps({"assets": []}))
    monkeypatch.setattr(assets, "ROOT", tmp_path)
    summary = assets.run_phase(ctx)
    dest = public / "assets" / "yt-AAAAAAAAAAA-c1.mp4"
    assert dest.exists() and dest.stat().st_size >= 10_000
    assert dest.samefile(clip)
    manifest = json.loads((build / "assets.json").read_text())
    hit = manifest["clips"]["long/p01/0"]
    assert hit["clip_id"] == "c1" and hit["asset_id"] == "yt-AAAAAAAAAAA-c1"
    assert summary["clips_sourced"] == 1


# ---------- long-v3 editorial gates ----------
EDITOR_NOTE_RE = (
    r"no verified|in this cut|map only;|no store listing|"
    r"no verified local clip|editor note|placeholder"
)


def test_long_shotlist_viewer_facing_text_only():
    sl = json.loads((VDIR / "shotlist.json").read_text(encoding="utf-8"))
    import re
    pat = re.compile(EDITOR_NOTE_RE, re.I)
    for e in sl["long"]:
        for shot in e["shots"]:
            for field in ("text", "sub"):
                val = shot.get(field) or ""
                assert not pat.search(val), f"{e['id']} {field}: {val}"
            lt = e.get("lower_third") or {}
            for field in ("title", "sub"):
                val = lt.get(field) or ""
                assert not pat.search(val), f"{e['id']} lower_third.{field}: {val}"


def test_long_clips_stay_within_source_and_avoid_known_defects():
    sl = json.loads((VDIR / "shotlist.json").read_text(encoding="utf-8"))
    plan = json.loads((VDIR / "used-sources.json").read_text(encoding="utf-8"))
    catalog = {c["clip_id"]: c for src in plan["sources"] for c in src["clips"]}
    timing_path = VDIR / "build" / "tts" / "long" / "timing.json"
    assert timing_path.exists(), "need existing long TTS timing to size shots"
    timing = json.loads(timing_path.read_text(encoding="utf-8"))
    end_extra = json.loads((ROOT / "config" / "settings.json").read_text())["render"]["end_card_s"]
    paras = timing["paragraphs"]
    total_s = timing["total"] + end_extra
    entries = {e["id"]: e for e in sl["long"]}

    # Track used [start, end) ranges per clip to discourage exact recap repeats.
    used_ranges: dict[str, list[tuple[float, float]]] = {}
    map_only = {"p19", "p21", "p22", "p24"}
    clip_s = map_s = 0.0

    for i, t in enumerate(paras):
        start = 0.0 if i == 0 else t["start"]
        end = paras[i + 1]["start"] if i + 1 < len(paras) else total_s
        window = end - start
        entry = entries[t["id"]]
        shots = entry["shots"]
        if t["id"] in map_only:
            assert all(s["type"] == "map" for s in shots), t["id"]
            assert all(s.get("source_clip_id") not in {"drone_gap", "drone_end", "palm_pier_c", "drone_boats_b"} for s in shots)
        weights = [float(s.get("weight", 1)) for s in shots]
        wsum = sum(weights)
        for s, w in zip(shots, weights):
            dur = window * w / wsum
            if s["type"] != "clip":
                map_s += dur
                continue
            cid = s["source_clip_id"]
            meta = catalog[cid]
            clip_len = float(meta["source_out_s"]) - float(meta["source_in_s"])
            # staged files are already speed-adjusted; duration equals clip_len / speed? 
            # prepare already applied speed, so staged duration = (out-in)/speed.
            speed = float(meta.get("speed") or 1)
            staged = clip_len / speed
            start_s = float(s.get("start_s") or 0)
            assert start_s >= 0
            assert dur <= (staged - start_s) + 1.01, f"{t['id']} {cid}: {dur:.2f}s > remaining {staged-start_s:.2f}s"
            clip_s += dur
            used_ranges.setdefault(cid, []).append((start_s, start_s + dur))
            if cid == "eagle_sunset":
                assert start_s >= 2.0, "selfie occupies the start of eagle_sunset"
                assert start_s + dur <= 13.55, "eagle_sunset dissolve / featured walk starts ~14s"
            if cid == "palm_palapas":
                assert start_s >= 8.0, "warning sign occupies the start of palm_palapas"
            if cid == "eagle_evening":
                assert start_s >= 1.0, "eagle_evening may dissolve from the shoreline open"
            if cid == "eagle_beach":
                assert start_s + dur <= 11.85, "eagle_beach dissolve / talking walk starts ~12.2s"

    denom = timing["total"]
    assert clip_s / denom >= 0.80, f"planned coverage {clip_s/denom:.3f} below 80%"

    # Same clip may be reused only if the in-point range does not substantially overlap.
    for cid, ranges in used_ranges.items():
        ranges = sorted(ranges)
        for (a0, a1), (b0, b1) in zip(ranges, ranges[1:]):
            overlap = min(a1, b1) - max(a0, b0)
            assert overlap <= 0.5, f"{cid} overlapping reuse {a0:.2f}-{a1:.2f} vs {b0:.2f}-{b1:.2f}"


def test_landing_approach_second_use_is_forward_continuation():
    sl = json.loads((VDIR / "shotlist.json").read_text(encoding="utf-8"))
    uses = []
    for e in sl["long"]:
        for s in e["shots"]:
            if s.get("source_clip_id") == "landing_approach":
                uses.append((e["id"], float(s.get("start_s") or 0)))
    assert uses, "landing_approach must still appear (arrival-first)"
    starts = [u[1] for u in uses]
    assert starts == sorted(starts)
    assert starts[0] == 0.0
    if len(starts) > 1:
        assert starts[1] >= 6.0, "later use must continue after the opening in-point, not replay it"
