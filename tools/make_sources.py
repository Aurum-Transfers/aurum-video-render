"""Build videos/<slug>/facts.json and sources.md from a verified fact record.

    python tools/make_sources.py <slug> <fact-record.json>

The fact record is a JSON list of {id, claim, source_url, checked_on} (e.g. the gb-aruba
book's qa/facts/all.json, read only). Only facts cited in the scripts are kept.
"""
import json
import re
import sys
from collections import OrderedDict
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
PUBLISHERS = {
    "aruba.com": "Aruba Tourism Authority",
    "airportaruba.com": "Aruba Airport Authority (Queen Beatrix International Airport)",
    "arubus.com": "Arubus N.V. (public bus operator)",
    "gov.uk": "UK Government, FCDO travel advice",
    "travel.gc.ca": "Government of Canada, travel advice",
    "cbaruba.org": "Centrale Bank van Aruba",
}


def publisher(url: str) -> str:
    host = urlsplit(url).netloc.lower().removeprefix("www.")
    for k, v in PUBLISHERS.items():
        if host == k or host.endswith("." + k):
            return v
    raise SystemExit(f"not an approved primary source: {url}")


def main(slug: str, record: str) -> None:
    vdir = ROOT / "videos" / slug
    texts = [(vdir / "script.md").read_text(encoding="utf-8")]
    texts += [p.read_text(encoding="utf-8") for p in sorted((vdir / "shorts").glob("short-*.md"))]
    used = sorted(set(re.findall(r"\bf\d{5}\b", "\n".join(texts))))
    data = json.loads(Path(record).read_text(encoding="utf-8"))
    by_id = {f["id"]: f for f in (data if isinstance(data, list) else data.values())}
    missing = [i for i in used if i not in by_id]
    if missing:
        raise SystemExit(f"facts cited but not in record: {missing}")
    facts = OrderedDict((i, {"claim": by_id[i]["claim"], "url": by_id[i].get("source_url") or by_id[i]["url"],
                             "checked_on": by_id[i]["checked_on"]}) for i in used)
    (vdir / "facts.json").write_text(json.dumps(facts, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    pages = OrderedDict()
    for i, f in facts.items():
        pages.setdefault(f["url"], []).append(i)
    lines = [f"# Sources: {slug}", "",
             "Primary sources only. Every factual sentence in script.md and the Shorts cites fact ids",
             "(HTML comments) that map to the pages below. Editorial lines carry no facts. No prices are stated.",
             "Facts come from the Aurum Aruba guidebook's verified fact record (gb-aruba, read only);",
             "the checked-on date is the date that record last verified the page.", "",
             "| # | Publisher | Page | Facts used | Checked on |", "|---|---|---|---|---|"]
    for n, (url, ids) in enumerate(pages.items(), 1):
        dates = sorted({facts[i]["checked_on"] for i in ids})
        lines.append(f"| {n} | {publisher(url)} | {url} | {', '.join(ids)} | {', '.join(dates)} |")
    lines += ["", "## Facts", ""]
    for i, f in facts.items():
        lines.append(f"- **{i}**: {f['claim']} ({f['url']}, checked {f['checked_on']})")
    (vdir / "sources.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"{len(facts)} facts from {len(pages)} pages -> facts.json, sources.md")


if __name__ == "__main__":
    main(*sys.argv[1:3])
