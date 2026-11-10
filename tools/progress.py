#!/usr/bin/env python3
"""Update the overnight progress file: progress.py SLUG KEY=JSONVALUE ...  (creates title entry if missing)"""
import json, sys, datetime, pathlib
P = pathlib.Path("/workspace/handoff/aurum-youtube/research/overnight-videos-progress-2026-11-10.json")
d = json.loads(P.read_text())
slug = sys.argv[1]
t = next((x for x in d["titles"] if x.get("slug") == slug), None)
if t is None:
    t = {"slug": slug}; d["titles"].append(t)
for kv in sys.argv[2:]:
    k, v = kv.split("=", 1)
    try: v = json.loads(v)
    except Exception: pass
    t[k] = v
d["updated"] = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
P.write_text(json.dumps(d, indent=1, ensure_ascii=False))
