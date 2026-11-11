#!/usr/bin/env python3
"""Pull a job's facts from the existing facts database (Marvin t230u: facts come from the database, not AI research).

Sources, read-only, first hit per destination wins for each fact id:
  1. the guidebook's own fact export: <books root>/<dest>/export/place.json ("facts": [{id, claim, source_url, kind, checked_on}])
     roots: /workspace/aurum-guidebooks/books, /workspace/gb-*/books, /workspace/books-final-review-20261109 (box copies)
  2. the guidebook's QA fact list: <books root>/<dest>/qa/facts/all.json
  3. existing video fact files: videos/*/facts.json whose ids/claims mention the destination (earlier verified picks)
  4. the read-only Aurum partner DB (partner_facts.py cache): which partners list this airport (IATA) or destination
Facts are selected by airport/arrival topic (airport name or IATA, immigration/entry, customs, taxis, transfers, car hire
and driving side, currency, weather/season, safety advisories) and written as {id: {claim, url, checked_on, kind, source}}.
A per-topic gap list says what the database does not cover: only those gaps go to AI research.

usage: facts_pull.py DEST_ID --iata MBJ --airport "Sangster" [--place "Montego Bay"] --out FACTS.json [--books-root DIR ...]
Exit 0 ok (gaps may exist; see the "gaps" key), 2 no fact database for the destination on the box (copy the book's
export/place.json from the PC with CopyToBox: it is small JSON).
"""
import argparse, glob, json, re, subprocess, sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ROOTS = ["/workspace/aurum-guidebooks/books", *sorted(glob.glob("/workspace/gb-*/books")), "/workspace/books-final-review-20261109"]
TOPICS = {
    "airport": r"airport|terminal|arrivals? hall|runway|aerodrome",
    "entry": r"immigration|passport|visa|entry (form|requirement)|ed-?card|c5|e-?ticket|declaration|customs|duty[- ]free allowance",
    "taxi": r"\btaxi|cab\b|jutа|juta|jcal|licensed (driver|operator)|red plates?|pp plates?",
    "transfer": r"transfer|shuttle|pre-?booked|private (car|driver)|chauffeur",
    "car_rental": r"car (hire|rental)|rent(al)? a car|driv(e|ing) on the (left|right)|driving licen|driving permit",
    "money": r"currency|dollar|exchange|atm|cash|card(s)? (are|widely)",
    "season": r"hurricane|rainy|dry season|best time|temperature|weather",
    "safety": r"advis(ory|e)|fcdo|state department|travel\.gc|safety|crime",
}


def load_book(dest, roots):
    out, used = {}, []
    for r in roots:
        for rel in ("export/place.json", "place.json", "qa/facts/all.json"):
            p = Path(r) / dest / rel
            if not p.is_file():
                continue
            d = json.loads(p.read_text())
            facts = d.get("facts", []) if isinstance(d, dict) else d
            n = 0
            for f in facts:
                fid = f.get("id")
                if fid and fid not in out and f.get("claim") and (f.get("source_url") or f.get("url")):
                    out[fid] = {"claim": f["claim"], "url": f.get("source_url") or f.get("url"), "checked_on": f.get("checked_on"),
                                "kind": f.get("kind") or f.get("primary_kind"), "source": f"{p} (read-only)"}
                    n += 1
            used.append({"file": str(p), "facts": n})
    return out, used


def partners(iata, place):
    r = subprocess.run([sys.executable, "/workspace/ops/scripts/partner_facts.py", "--vertical", "aurum", "--json"], capture_output=True, text=True)
    if r.returncode:
        return []
    d = json.loads(r.stdout[r.stdout.index("{"):])
    res = []
    for k, p in (d.get("partners", d)).items():
        F = p.get("facts", {}) if isinstance(p, dict) else {}
        aps = [v for c in F.get("airports", []) for v in (c.get("value") if isinstance(c.get("value"), list) else [c.get("value")]) if v]
        geo = " ".join(str(c.get("value")) for c in F.get("geo_coverage", []))
        ch = [c.get("value") or {} for c in F.get("channels", [])]
        yt = any("youtube" in (v.get("allowed") or []) for v in ch if isinstance(v, dict))
        if iata in aps or (place and place.lower() in geo.lower()):
            res.append({"partner": k, "airport_listed": iata in aps, "geo_match": bool(place and place.lower() in geo.lower()), "youtube_ok": yt})
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dest"); ap.add_argument("--iata", required=True); ap.add_argument("--airport", required=True)
    ap.add_argument("--place", default=""); ap.add_argument("--out", required=True); ap.add_argument("--books-root", action="append")
    a = ap.parse_args()
    book, used = load_book(a.dest, a.books_root or ROOTS)
    for vf in glob.glob(str(ROOT / "videos/*/facts.json")):
        d = json.loads(Path(vf).read_text())
        if isinstance(d, dict):
            for k, f in d.items():
                if isinstance(f, dict) and f.get("claim") and k not in book and re.search(re.escape(a.dest.replace("-", " ")), f["claim"] + " " + f.get("source", ""), re.I):
                    book[k] = {**f, "source": f"{vf} (earlier verified pick)"}
    if not book:
        print(json.dumps({"error": f"no fact database for '{a.dest}' on the box", "looked_in": a.books_root or ROOTS})); return 2
    airport_re = re.compile(rf"{re.escape(a.airport)}|\b{re.escape(a.iata)}\b", re.I)
    pick, by_topic = {}, {t: [] for t in TOPICS}
    for fid, f in book.items():
        c = f["claim"]
        hit = [t for t, rx in TOPICS.items() if re.search(rx, c, re.I)]
        on_airport = bool(airport_re.search(c))
        if not hit and not on_airport:
            continue
        # airport-specific topics need this airport (not another airport on the island) when an airport is named
        if ("airport" in hit or "taxi" in hit) and re.search(r"airport", c, re.I) and not on_airport and re.search(r"international airport|aerodrome", c, re.I):
            continue
        pick[fid] = {**f, "topics": hit + (["this_airport"] if on_airport else [])}
        for t in hit:
            by_topic[t].append(fid)
    gaps = [t for t, ids in by_topic.items() if not ids]
    if not any(airport_re.search(book[i]["claim"]) for i in pick):
        gaps.insert(0, "this_airport (no fact names the airport or its IATA code)")
    out = Path(a.out)
    prev = json.loads(out.read_text()) if out.exists() else {}
    keep = {k: v for k, v in prev.items() if not k.startswith("_")}  # never drop facts a script already cites
    keep.update(pick)
    keep["_meta"] = {"pulled": date.today().isoformat(), "by": "tools/facts_pull.py", "dest": a.dest, "iata": a.iata, "airport": a.airport,
                     "sources": used, "gaps_for_ai_research": gaps, "partners_db": partners(a.iata, a.place or a.dest.replace("-", " ").title()),
                     "counts": {t: len(v) for t, v in by_topic.items()}}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(keep, indent=1, ensure_ascii=False))
    print(json.dumps({"facts": len(pick), "by_topic": keep["_meta"]["counts"], "gaps": gaps, "partners": len(keep["_meta"]["partners_db"]), "out": str(out)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
