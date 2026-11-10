"""description: YouTube descriptions for the long video and each Short.

Line 1: disclosure. Line 2: main link. Then chapters (00:00 first), links from
config/links.json only (each tagged with SubID yt_<videoId>), CC BY credits, sources, <= 3 hashtags.
"""
from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .assets import read_log
from .common import ROOT, PhaseError, fmt_ts, load_json, save_json, settings
from .script import selected_units, units

PENDING_ID = "PENDING"
URL_RE = re.compile(r"https?://[^\s)>\]]+")


def with_subid(url: str, param: str, video_id: str) -> str:
    parts = urlsplit(url)
    q = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k != param]
    q.append((param, f"yt_{video_id}"))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(q), parts.fragment))


def chapters_from_timing(script, timing: dict) -> list[tuple[float, str]]:
    tmap = {t["id"]: t["start"] for t in timing["paragraphs"]}
    out = []
    for i, (title, pid) in enumerate(script.chapters):
        out.append((0.0 if i == 0 else tmap[pid], title))
    return out


def parse_sources(md: str) -> list[tuple[str, str]]:
    """Unique (publisher, url) pairs from sources.md table rows."""
    seen, out = set(), []
    for line in md.splitlines():
        if not line.startswith("|") or "http" not in line:
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        url = next((m.group(0) for c in cells for m in [URL_RE.search(c)] if m), None)
        pub = cells[1] if len(cells) > 1 else ""
        if url and url not in seen:
            seen.add(url)
            out.append((pub, url))
    return out


def links_config(slug: str) -> dict:
    cfg = load_json(ROOT / "config" / "links.json")
    if slug not in cfg:
        raise PhaseError(f"config/links.json has no entry for {slug}")
    return {"subid_param": cfg.get("subid_param", "subid"), **cfg[slug]}



def ccby_credit_lines(rows: list[dict]) -> list[str]:
    """One CC BY footage credit per source URL (not per clip file)."""
    seen: set[str] = set()
    out: list[str] = []
    for r in rows:
        if not r["licence"].lower().startswith(("cc by", "creative commons attribution")):
            continue
        url = r["url"]
        if url in seen:
            continue
        seen.add(url)
        src = (r.get("source") or "").strip()
        title = src.split(")", 1)[-1].strip() if src.lower().startswith("youtube (cc by)") else (src or r.get("asset_id") or "")
        licence = r["licence"].split(" (")[0]
        if licence.lower().startswith("creative commons attribution"):
            licence = "CC BY"
        label = f'"{title}" ' if title else ""
        out.append(f"Footage: {label}by {r['creator']}, {url} ({licence})")
    return out


def build(ctx, unit: str, video_id: str = PENDING_ID) -> str:
    cfg = settings()
    meta = load_json(ctx.paths.video / "video.json")
    links = links_config(ctx.slug)
    param = links["subid_param"]
    script = units(ctx.paths.video)[unit]
    main = links["main"]
    if not main.get("url"):
        raise PhaseError("links.json: main link is empty")
    lines = [cfg["disclosure"]["description"],
             f"{main['label']}: {with_subid(main['url'], param, video_id)}", ""]
    m = meta["long"] if unit == "long" else meta["shorts"][unit]
    lines += [m["summary"], ""]
    if unit == "long":
        timing = load_json(ctx.paths.tts / unit / "timing.json")
        lines.append("Chapters")
        lines += [f"{fmt_ts(t)} {title}" for t, title in chapters_from_timing(script, timing)]
        lines.append("")
    extra = [l for l in links.get("links", []) if l.get("url")]
    if extra:
        lines.append("Links")
        lines += [f"{l['label']}: {with_subid(l['url'], param, video_id)}" for l in extra]
        lines.append("")
    rows = read_log(ctx.paths.licence_log)
    lines.append("Credits")
    lines.append(meta["credits_line"])
    lines += ccby_credit_lines(rows)
    lines.append("")
    if unit == "long":
        src = parse_sources((ctx.paths.video / "sources.md").read_text(encoding="utf-8"))
        lines.append(f"Sources (official pages, checked {meta['sources_checked_on']})")
        lines += [f"{pub}: {url}" for pub, url in src]
        lines.append("")
    lines.append(meta["advice_note"])
    lines.append("")
    tags = list(m.get("hashtags", meta["hashtags"]))
    if unit != "long" and "#Shorts" not in tags:
        tags = ["#Shorts"] + tags
    lines.append(" ".join(tags[:3]))
    text = "\n".join(lines).strip() + "\n"
    if len(text) > 5000:
        raise PhaseError(f"{unit}: description is {len(text)} chars (> 5000)")
    return text


def run_phase(ctx) -> dict:
    out = {}
    for unit in selected_units(ctx):
        text = build(ctx, unit)
        name = "description.txt" if unit == "long" else f"description-{unit}.txt"
        (ctx.paths.out / name).write_text(text, encoding="utf-8")
        out[unit] = name
    save_json(ctx.paths.build / "description.json", out)
    return out
