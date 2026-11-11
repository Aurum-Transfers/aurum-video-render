#!/usr/bin/env python3
"""Pexels + Pixabay video API search with per-clip licence evidence (optional download).

Keys: env PEXELS_API_KEY / PIXABAY_API_KEY, or files /home/box/.secrets/aurum-reels/{pexels,pixabay}_api_key.txt.
Keys are never printed. A missing key skips that provider (logged) and is not an error: as of 2026-11-10 neither key
is on record (ACCESS-MAP), so the KIN worker searched the public pages in the browser instead.

Writes POOL/stock-search.json: hits {asset_id, provider, page_url, creator, width, height, fps, duration, download,
licence, queries}. With --download, files >= 1920 wide go to POOL/stock/<asset_id>.mp4 and evidence to
POOL/licence/<asset_id>/watchpage-licence.json (the same layout the KIN job used).

usage: stock_search.py POOLDIR --place REGEX [--download] "query" ["query" ...]
"""
import datetime, json, os, pathlib, re, sys, urllib.parse, urllib.request

SEC = pathlib.Path("/home/box/.secrets/aurum-reels")


def key(env, fn):
    k = os.environ.get(env)
    if not k and (SEC / fn).exists():
        k = (SEC / fn).read_text().strip()
    return k or None


def get(url, headers=None):
    req = urllib.request.Request(url, headers={"User-Agent": "aurum-reels/1.0", **(headers or {})})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def pexels(q, k):
    j = get("https://api.pexels.com/videos/search?" + urllib.parse.urlencode({"query": q, "per_page": 40, "size": "large"}), {"Authorization": k})
    for v in j.get("videos", []):
        fs = sorted([f for f in v.get("video_files", []) if (f.get("width") or 0) >= 1920 and f.get("file_type") == "video/mp4"],
                    key=lambda f: f["width"])
        if not fs:
            continue
        f = fs[0]
        yield {"asset_id": f"pexels-{v['id']}", "provider": "Pexels", "page_url": v["url"], "creator": (v.get("user") or {}).get("name", ""),
               "width": f["width"], "height": f["height"], "fps": f.get("fps"), "duration": v.get("duration"), "download": f["link"],
               "licence": "Pexels License", "text": v["url"]}


def pixabay(q, k):
    j = get("https://pixabay.com/api/videos/?" + urllib.parse.urlencode({"key": k, "q": q, "per_page": 50, "min_width": 1920}))
    for h in j.get("hits", []):
        vs = h.get("videos", {})
        f = vs.get("large") or {}
        if (f.get("width") or 0) < 1920:
            continue
        yield {"asset_id": f"pixabay-{h['id']}", "provider": "Pixabay", "page_url": h.get("pageURL", ""), "creator": h.get("user", ""),
               "width": f["width"], "height": f["height"], "fps": None, "duration": h.get("duration"), "download": f["url"],
               "licence": "Pixabay Content License", "text": (h.get("pageURL", "") + " " + h.get("tags", ""))}


def main(a):
    pool = pathlib.Path(a[0]); a = a[1:]
    place = re.compile(a[a.index("--place") + 1], re.I) if "--place" in a else None
    if "--place" in a:
        i = a.index("--place"); del a[i:i + 2]
    dl = "--download" in a
    a = [x for x in a if x != "--download"]
    pool.mkdir(parents=True, exist_ok=True)
    now = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
    out = pool / "stock-search.json"
    data = json.loads(out.read_text()) if out.exists() else {"hits": [], "log": []}
    hits = {h["asset_id"]: h for h in data["hits"]}
    prov = [("Pexels", key("PEXELS_API_KEY", "pexels_api_key.txt"), pexels), ("Pixabay", key("PIXABAY_API_KEY", "pixabay_api_key.txt"), pixabay)]
    for name, k, fn in prov:
        if not k:
            data["log"].append({"at": now, "provider": name, "skipped": "no API key on record"}); continue
        for q in a:
            try:
                for h in fn(q, k):
                    if place and not place.search(h["text"] + " " + q):
                        continue
                    e = hits.setdefault(h["asset_id"], {**h, "queries": []})
                    if q not in e["queries"]:
                        e["queries"].append(q)
            except Exception as e:
                data["log"].append({"at": now, "provider": name, "query": q, "error": type(e).__name__})
    if dl:
        for h in hits.values():
            f = pool / "stock" / f"{h['asset_id']}.mp4"
            ev = pool / "licence" / h["asset_id"] / "watchpage-licence.json"
            if not f.exists():
                f.parent.mkdir(parents=True, exist_ok=True)
                try:
                    urllib.request.urlretrieve(h["download"], f)
                except Exception as e:
                    h["dl_error"] = type(e).__name__; continue
            ev.parent.mkdir(parents=True, exist_ok=True)
            ev.write_text(json.dumps({"id": h["asset_id"], "url": h["page_url"], "uploader": h["creator"], "license": h["licence"],
                                      "width": h["width"], "height": h["height"], "checked_at": now,
                                      "method": f"{h['provider']} API metadata (licence is the provider's site-wide licence)"}, indent=1))
            h["file"] = str(f); h["evidence"] = str(ev)
    data["hits"] = list(hits.values()); data["updated"] = now
    out.write_text(json.dumps(data, indent=1, ensure_ascii=False))
    print(json.dumps({"hits": len(hits), "skipped": [l for l in data["log"] if l.get("at") == now and l.get("skipped")]}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
