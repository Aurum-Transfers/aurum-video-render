#!/usr/bin/env python3
"""Publishing package for one finished job, scripted (no AI): video.json (Bali live layout via the publishing worker's
build_package.py), captions SRT from TTS timing, thumbnail from the verified master, landing check.

Inputs (all already produced upstream):
  jobs/<job>/script.json  "package": {title, tags, line2, intro_chapter, hashtags, thumb_text, thumb_sub, main_url, airport, iata}
  facts.json (spec "facts" or jobs/<job>/facts.json) "links": {partner_key: landing_url}, "official_sites": [...]
  the downloaded master + its CI checks.json / edl-long.json / licence-log.csv (paths from the orchestrator state)
Affiliate partners: config/partner_templates.json, kept only when the read-only Aurum partner DB (partner_facts.py; the
cache when no RO DSN) lists "youtube" among the partner's allowed channels. Partners without a landing URL are skipped.

usage: package_video.py JOBDIR --master M --checks C --edl E --licence L --out VIDEODIR [--facts F] [--package-input P] [--no-landing-check]
--package-input: JSON {"package": {...}, "links": {...}, "official_sites": [...], "checked": "..."} overriding the above (tests).
Writes VIDEODIR/video.json, captions.en.srt, thumb/thumb.jpg, description.txt, package.md, landing-check.json.
"""
import argparse, json, re, subprocess, sys, urllib.parse
from pathlib import Path

HERE = Path(__file__).resolve().parent; ROOT = HERE.parent
HT = Path("/workspace/handoff/aurum-youtube/tools")
PF = "/workspace/ops/scripts/partner_facts.py"
FONT = "/usr/share/fonts/truetype/sand-box/google/Bebas Neue/BebasNeue-Regular.ttf"


def youtube_ok(key):
    r = subprocess.run([sys.executable, PF, "--vertical", "aurum", "--partner", key, "--json"], capture_output=True, text=True)
    if r.returncode:
        return False, "not in partner DB"
    raw = r.stdout[r.stdout.index("{"):]
    d = json.loads(raw).get(key, {})
    chans = [c.get("value") or {} for c in (d.get("facts") or {}).get("channels", [])]
    ok = any("youtube" in (v.get("allowed") or []) and "youtube" not in (v.get("banned") or []) for v in chans)
    return ok, "DB channels allow youtube" if ok else "DB channels do not list youtube"


def srt(timing, out):
    def ts(t):
        ms = int(round(t * 1000)); return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"
    L = []
    for n, ln in enumerate(timing["lines"], 1):
        L += [str(n), f"{ts(ln['t0'])} --> {ts(ln['t1'])}", ln["text"], ""]
    out.write_text("\n".join(L))


def main():
    ap = argparse.ArgumentParser()
    for a in ("job", "--master", "--checks", "--edl", "--licence", "--out"):
        ap.add_argument(a, required=a != "job") if a.startswith("--") else ap.add_argument(a)
    ap.add_argument("--facts"); ap.add_argument("--package-input")
    ap.add_argument("--no-landing-check", action="store_true")
    a = ap.parse_args()
    job = Path(a.job); out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    script = json.loads((job / "script.json").read_text()); spec = json.loads((job / "spec.json").read_text())
    pk = dict(script.get("package") or {})
    fp = Path(a.facts) if a.facts else job / "facts.json"
    facts = json.loads(fp.read_text()) if fp.exists() else {}
    facts = facts if isinstance(facts, dict) else {}
    if a.package_input:
        pi = json.loads(Path(a.package_input).read_text())
        pk.update(pi.get("package") or {})
        facts = {**facts, **{k: v for k, v in pi.items() if k != "package"}}
    links = facts.get("links")
    need = [k for k in ("title", "tags", "line2", "intro_chapter", "hashtags", "main_url", "airport", "iata") if not pk.get(k)]
    if need or not links:
        print(json.dumps({"stop": "NEEDS_AI", "why": f"script.json package missing {need}" if need else "facts.json has no 'links' (partner landing URLs)"}))
        return 3
    T = json.loads((ROOT / "config/partner_templates.json").read_text())
    place = spec.get("place", ""); sub = {"{PLACE}": place.split(",")[0], "{COUNTRY}": pk.get("country") or place.split(",")[-1].strip(), "{AIRPORT}": pk["airport"], "{IATA}": pk["iata"]}
    sections, log = [], []
    for s in T["sections"]:
        ls = []
        for key in s["partners"]:
            land = links.get(key)
            if not land:
                log.append({"partner": key, "skipped": "no landing URL in facts.json links"}); continue
            ok, why = youtube_ok(key)
            log.append({"partner": key, "youtube_ok": ok, "why": why})
            if not ok:
                continue
            p = T["partners"][key]; lab = p["label"]
            for k, v in sub.items():
                lab = lab.replace(k, v)
            tpl = p["template"].replace("{LANDING}", urllib.parse.quote(land, safe="")).replace("{LANDING_RAW}", land)
            ls.append({"partner": key, "label": lab, "template": tpl, "landing": land})
        if ls:
            sections.append({"heading": s["heading"], "links": ls})
    timing = json.loads((job / "build/timing.json").read_text())
    srt(timing, out / "captions.en.srt")
    (out / "thumb").mkdir(exist_ok=True)
    edl = json.loads(Path(a.edl).read_text())
    # candidates: first aerial, first beach, first landing shot after the hook (or pk.thumb_at); thumb.jpg = first.
    # Frame choice is a heuristic: the publishing worker / reviewer may swap in thumb-2/3 (light visual check).
    # clean frames (no burned-in overlays) come from the shot's own range clip when it is on disk, else the master
    srcs = [(a.master, float(pk["thumb_at"]))] if pk.get("thumb_at") is not None else []
    for pat in ("aerial|drone", "beach", "landing|approach"):
        c = [x for x in edl["shots"] if x.get("kind") == "clip" and x["t0"] > 5 and re.search(pat, x.get("tag") or "")]
        if c:
            x = c[0]; f = ROOT / x["file"]
            mid = float(x["file_in"]) + (x["t1"] - x["t0"]) * float(x.get("play_speed", 1)) / 2
            srcs.append((str(f), mid) if f.exists() else (a.master, (x["t0"] + x["t1"]) / 2))
    srcs = (srcs + [(a.master, edl["duration_s"] * f) for f in (0.35, 0.5, 0.65)])[:3]
    txt = (pk.get("thumb_text") or f"{place.split(',')[0].upper()} AIRPORT").replace(":", "\\:").replace("'", "")
    subt = (pk.get("thumb_sub") or "2026 ARRIVAL GUIDE").replace(":", "\\:").replace("'", "")
    vf = (f"scale=1280:720,drawbox=x=0:y=ih*0.62:w=iw:h=ih*0.38:color=black@0.55:t=fill,"
          f"drawtext=fontfile='{FONT}':text='{txt}':fontsize=110:fontcolor=white:x=(w-text_w)/2:y=h*0.66,"
          f"drawtext=fontfile='{FONT}':text='{subt}':fontsize=54:fontcolor=0xF2C14E:x=(w-text_w)/2:y=h*0.86")
    for i, (src, t) in enumerate(srcs, 1):
        name = "thumb.jpg" if i == 1 else f"thumb-{i}.jpg"
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-ss", f"{t:.2f}", "-i", src, "-frames:v", "1", "-vf", vf, "-q:v", "3",
                        str(out / "thumb" / name)], check=True)
    cfg = {"slug": spec["slug"], "title": pk["title"], "master": str(Path(a.master).resolve()), "checks": str(Path(a.checks).resolve()),
           "edl": str(Path(a.edl).resolve()), "licence": str(Path(a.licence).resolve()), "thumb": "thumb/thumb.jpg", "srt": "captions.en.srt",
           "synthetic": False, "tags": pk["tags"], "line2": pk["line2"], "main_heading": pk.get("main_heading", f"OUR {pk['airport'].upper()} PAGE"),
           "main_url": pk["main_url"], "sections": sections, "intro_chapter": pk["intro_chapter"],
           "official_sites": facts.get("official_sites") or pk.get("official_sites") or [], "checked": facts.get("checked") or pk.get("checked", ""),
           "credits_note": "Narration is a synthetic (AI) voice. All scenes are real licensed footage; maps and graphics by Aurum Transfers.",
           "music_line": "Music: none.", "hashtags": pk["hashtags"], "partner_log": log}
    (out / "video.json").write_text(json.dumps(cfg, indent=1, ensure_ascii=False))
    r = subprocess.run([sys.executable, str(HT / "build_package.py"), str(out / "video.json")], capture_output=True, text=True)
    if r.returncode:
        print(json.dumps({"stop": "FAILED", "why": "build_package: " + (r.stderr or r.stdout)[-400:]})); return 1
    if not a.no_landing_check:
        # headless Chromium = heavy job per GATE.md: through gate.py run; a refusal is WAITING (exit 5), not a failure
        r2 = subprocess.run(["python3", "/workspace/ops/scripts/gate.py", "run", "--bot", "aurum-reels", "--kind", "heavy", "--label",
                             f"landing check {spec['slug']}", "--", sys.executable, str(HT / "landing_check.py"), str(out / "video.json")],
                            capture_output=True, text=True)
        if r2.returncode == 2 and "GATE BLOCKED" in r2.stderr:
            print(json.dumps({"stop": "WAITING", "why": "heavy slot busy for the landing check; re-run"})); return 5
        if r2.returncode:
            print(json.dumps({"stop": "FAILED", "why": "landing check: a partner landing is not 200", "detail": r2.stdout[-400:]})); return 1
    print(json.dumps({"video_json": str(out / "video.json"), "sections": len(sections), "links": sum(len(s["links"]) for s in sections),
                      "skipped": [l for l in log if not l.get("youtube_ok")], "desc": r.stdout.strip()}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
