#!/usr/bin/env python3
"""YouTube Data API v3 Creative Commons search -> POOL/cc-search.json (same "hits" format as cc_search.py, merged).

search.list with videoLicense=creativeCommon, videoDefinition=high, type=video (100 quota units per query page).
Key: env YOUTUBE_API_KEY or /home/box/.secrets/aurum-reels/youtube_api_key.txt (ACCESS-MAP). The key is never printed
or written anywhere. The API's licence filter is a pre-filter only: pool_screen.py still confirms the watch-page
licence per video (cookie-less yt-dlp) before anything is used.

usage: yt_api_search.py POOLDIR "query" ["query" ...] [--max 25]
Exit 0 ok, 2 no key (caller falls back to cc_search.py), 1 API error.
"""
import datetime, json, os, pathlib, sys, urllib.parse, urllib.request

KEYFILE = pathlib.Path("/home/box/.secrets/aurum-reels/youtube_api_key.txt")


def key():
    k = os.environ.get("YOUTUBE_API_KEY")
    if not k and KEYFILE.exists():
        k = KEYFILE.read_text().strip()
    return k or None


def main(argv):
    args = list(argv)
    mx = 25
    if "--max" in args:
        i = args.index("--max"); mx = int(args[i + 1]); del args[i:i + 2]
    pool = pathlib.Path(args[0]); queries = args[1:]
    pool.mkdir(parents=True, exist_ok=True)
    k = key()
    if not k:
        print(json.dumps({"error": "no YouTube API key (env YOUTUBE_API_KEY or ACCESS-MAP file)"})); return 2
    p = pool / "cc-search.json"
    data = json.loads(p.read_text()) if p.exists() else {"created": None, "searches": [], "hits": []}
    hits = {h["id"]: h for h in data.get("hits", [])}
    now = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
    new = 0
    for q in queries:
        params = {"part": "snippet", "q": q, "type": "video", "videoLicense": "creativeCommon", "videoDefinition": "high",
                  "maxResults": min(50, mx), "key": k}
        url = "https://www.googleapis.com/youtube/v3/search?" + urllib.parse.urlencode(params)
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                j = json.load(r)
        except Exception as e:  # never echo the URL (it carries the key)
            print(json.dumps({"query": q, "error": type(e).__name__ + ": " + str(getattr(e, "code", ""))})); return 1
        items = j.get("items", [])
        data.setdefault("searches", []).append({"query": q, "method": "YouTube Data API v3 search.list videoLicense=creativeCommon videoDefinition=high",
                                                "n": len(items), "at": now})
        for it in items:
            vid = it["id"].get("videoId")
            if not vid:
                continue
            h = hits.setdefault(vid, {"id": vid, "title": it["snippet"].get("title"), "channel": it["snippet"].get("channelTitle"), "queries": []})
            if q not in h.setdefault("queries", []):
                h["queries"].append(q)
            new += 1
    data["created"] = data.get("created") or now
    data["updated"] = now
    data["hits"] = list(hits.values())
    p.write_text(json.dumps(data, indent=1, ensure_ascii=False))
    print(json.dumps({"queries": len(queries), "results": new, "unique_hits": len(hits), "out": str(p)}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
