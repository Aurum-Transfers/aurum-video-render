#!/usr/bin/env python3
"""Build out/description.txt and out/thumb-{1,2,3}.jpg for a title_runner work dir.
usage: desc_build.py WORKDIR LINK_URL   (no prices; credits from licence-log.csv; sources from facts.json cited lines)"""
import csv, json, sys, pathlib, subprocess, urllib.parse
wd = pathlib.Path(sys.argv[1]).resolve(); link = sys.argv[2]
spec = json.load(open(wd / "spec.json")); script = json.load(open(wd / "script.json"))
edl = json.load(open(wd / "build/edl-long.json")); facts = json.load(open(spec["facts"]))
def ts(t):
    t = int(t); return f"{t//60:02d}:{t%60:02d}"
ch = [o for o in edl["overlays"] if o["kind"] == "chapter"]
lines = [f"00:00 {spec['place']} arrival: the 3 ways in 15 seconds"] + [f"{ts(o['t0'])} {o['text'].split('. ',1)[-1]}" for o in ch]
cited = []
for l in script["lines"]:
    for f in l.get("facts", []):
        u = facts[f]["url"]
        if u not in cited: cited.append(u)
cred, seen = [], set()
for r in csv.DictReader(open(wd / "licence-log.csv")):
    if r["video_id"] in seen: continue
    seen.add(r["video_id"]); cred.append(f'Footage: "{r["title"]}" by {r["creator"]}, {r["url"]} (CC BY)')
place = spec["place"]
txt = f"""Disclosure: Aurum Transfers is a travel-affiliate brand. Links below may earn us a commission at no extra cost to you. We don't operate transfers, tours or hotels; bookings are with our partners.
Compare {place} airport transfers with Aurum's partners: {link}

{script['title']}. Just landed and not sure how to reach your hotel? This guide covers landing and the airport, entry paperwork, the three ways to your hotel (pre-booked transfer, taxi, rental car), the best time to go, the beaches and practical tips. Facts come from official sources listed below; no prices are quoted, so check current details before you book.

Chapters
""" + "\n".join(lines) + f"""

Credits
Narration: AI-generated voice (Kokoro). Maps and route animations: Aurum Transfers, using a Natural Earth outline (public domain). Fonts: Montserrat and Bebas Neue (SIL OFL). Music: none.
""" + "\n".join(cred) + "\n\nSources (official pages; checked dates in the project facts file)\n" + "\n".join(cited) + f"""

This video is general travel information, not legal, health or immigration advice. Entry rules change; check the official pages above before you travel.

#{place.replace(' ','')} #{place.replace(' ','')}Travel #TravelTips
"""
out = wd / "out"; out.mkdir(exist_ok=True)
(out / "description.txt").write_text(txt)
# thumbnails: 3 frames from the master with brand text (Bebas Neue)
master = out / f"{spec.get('output_stem','long')}.mp4"
font = pathlib.Path(spec["public_dir"]) / "fonts/BebasNeue-Regular.ttf"
hooks = [f"{place.upper()} AIRPORT\\: 3 WAYS", "TRANSFER · TAXI · RENTAL", f"LANDED IN {place.upper()}?"]
for i, (t, h) in enumerate(zip([0.35, 0.5, 0.65], hooks), 1):
    tt = edl["duration_s"] * t
    vf = (f"scale=1280:720,drawbox=x=0:y=ih*0.62:w=iw:h=ih*0.38:color=black@0.55:t=fill,"
          f"drawtext=fontfile={font}:text='{h}':fontsize=110:fontcolor=white:x=(w-text_w)/2:y=h*0.68,"
          f"drawtext=fontfile={font}:text='2026 ARRIVAL GUIDE':fontsize=54:fontcolor=0xF2C14E:x=(w-text_w)/2:y=h*0.86")
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-ss", f"{tt:.2f}", "-i", str(master), "-frames:v", "1", "-vf", vf, "-q:v", "3", str(out / f"thumb-{i}.jpg")], check=True)
print(json.dumps({"description": str(out / "description.txt"), "chapters": len(lines), "credits": len(cred), "sources": len(cited)}))
