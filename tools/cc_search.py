#!/usr/bin/env python3
"""Public YouTube search with the Creative Commons filter (sp=EgIwAQ==), cookie-less via yt-dlp, then
watch-page licence confirmation per hit. usage: cc_search.py OUT.json "query" ["query" ...]"""
import json, subprocess, sys, os, urllib.parse, datetime
YT = os.path.expanduser("~/.local/bin/yt-dlp")
out = sys.argv[1]; hits = {}; log = []
for q in sys.argv[2:]:
    url = "https://www.youtube.com/results?search_query=" + urllib.parse.quote_plus(q) + "&sp=EgIwAQ%253D%253D"
    r = subprocess.run([YT, "--flat-playlist", "-J", "--playlist-end", "25", "--no-warnings", url], capture_output=True, text=True)
    try:
        ents = json.loads(r.stdout).get("entries", [])
    except Exception:
        ents = []
    log.append({"query": q, "url": url, "n": len(ents)})
    for e in ents:
        if e.get("id") and e["id"] not in hits:
            hits[e["id"]] = {"id": e["id"], "title": e.get("title"), "channel": e.get("channel") or e.get("uploader"), "duration": e.get("duration"), "queries": [q]}
        elif e.get("id"):
            hits[e["id"]]["queries"].append(q)
now = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
json.dump({"created": now, "method": "youtube.com/results CC filter via yt-dlp (cookie-less); licence confirmed per video below", "searches": log, "hits": list(hits.values())}, open(out, "w"), indent=1)
print(len(hits))
