#!/usr/bin/env python3
"""Per-title destination-video runner (post-Bali spec, 10 Nov 2026). Scripts only; AI is used
only upstream to write script.json and choose footage tags.

Work dir (one per title) holds: script.json (sentence lines, chapters, prompts, facts, visual tags),
footage.json (licensed clip library with tags, creator, in/out), spec.json (voice, map, paths).

Stages (run in order; heavy ones must go through gate.py run):
  tts       per-sentence Kokoro TTS with varied pauses -> narration.wav + timing.json
  stt       speech-to-text round trip on place names (faster-whisper) -> stt-check.json
  plan      shot allocation + overlays -> edl-long.json, licence-log.csv, spec gates (pre-render)
  sheet     contact sheet: one frame per shot -> contact-sheet-*.jpg (light: stills only)
  animatic  [heavy] 480x270 animatic with narration + text burn of overlays
  segments  [heavy] cut every shot to 1080p30 intermediates + ambient audio
  overlays  [heavy] Remotion OverlayStrip (transparent, full length) -> overlay.webm
  compose   [heavy] base + overlay + narration/ambient mix -> out/<stem>.mp4
  qa        output gates (loudness, freeze, A/V), review copy <100 MiB, QA frames, checks.json
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import re
import statistics
import subprocess
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import spec_gates  # noqa: E402

FPS = 30
W, H = 1920, 1080
TARGET_SHOT = 4.3
CREATOR_CAP = 0.28
END_CARD_S = 5.0
TAIL_S = 1.0
LEAD_S = 0.3
VENV_PY = ROOT / ".venv" / "bin" / "python"
WHISPER_PY = Path("/workspace/tools/whisper-venv/bin/python")
PROMPT_FILL = [("LIKE", "Finding this useful? Tap like"), ("SUBSCRIBE", "More arrival guides: subscribe"),
               ("LINK BELOW", "Compare transfers: link in the description")]


def now():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def lj(p, d=None):
    p = Path(p)
    return json.loads(p.read_text()) if p.exists() else d


def sj(p, o):
    Path(p).parent.mkdir(parents=True, exist_ok=True)
    Path(p).write_text(json.dumps(o, indent=1, ensure_ascii=False) + "\n")


def sh(cmd, **kw):
    r = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if r.returncode:
        raise SystemExit(f"FAILED: {' '.join(map(str, cmd))[:400]}\n{r.stderr[-1500:]}")
    return r


def dur_of(f):
    return float(sh(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(f)]).stdout.strip())


class T:
    def __init__(self, wd):
        self.wd = Path(wd).resolve()
        self.script = lj(self.wd / "script.json")
        self.lib = lj(self.wd / "footage.json")
        self.spec = lj(self.wd / "spec.json")
        self.b = self.wd / "build"
        self.out = self.wd / "out"
        self.b.mkdir(exist_ok=True)
        self.out.mkdir(exist_ok=True)
        self.stem = self.spec.get("output_stem", "long")
        self.portrait = bool(self.spec.get("portrait"))
        global W, H
        W, H = (1080, 1920) if self.portrait else (1920, 1080)

    # ------------------------------------------------------------------ tts
    def tts(self):
        code = r'''
import json,sys,hashlib,soundfile as sf
from kokoro_onnx import Kokoro
args=json.loads(sys.argv[1]); k=Kokoro(args["model"],args["voices"]); out=[]
for it in args["items"]:
    if not __import__("os").path.exists(it["wav"]):
        s,r=k.create(it["text"],voice=args["voice"],speed=args["speed"],lang=args["lang"]); sf.write(it["wav"],s,r,subtype="PCM_16")
    out.append(it["wav"])
print(json.dumps(out))
'''
        resp = lj(self.spec.get("pronunciations") or "", {}) or {}
        resp.update(self.spec.get("respell", {}))
        items = []
        tdir = self.b / "tts"
        tdir.mkdir(exist_ok=True)
        for i, ln in enumerate(self.script["lines"]):
            spoken = ln["text"]
            for k in sorted(resp, key=len, reverse=True):
                spoken = re.sub(rf"(?<![\w-]){re.escape(k)}(?![\w-])", resp[k], spoken)
            key = hashlib.sha1(json.dumps([spoken, self.spec["voice"], self.spec["lang"], self.spec.get("speed", 1.0)]).encode()).hexdigest()[:10]
            items.append({"text": spoken, "wav": str(tdir / f"s{i:03d}-{key}.wav")})
        md = ROOT / "tools" / "tts" / "models"
        args = {"model": str(md / "kokoro-v1.0.onnx"), "voices": str(md / "voices-v1.0.bin"), "voice": self.spec["voice"],
                "lang": self.spec["lang"], "speed": self.spec.get("speed", 1.0), "items": items}
        sh([str(VENV_PY), "-c", code, json.dumps(args)])
        import wave
        # assemble with varied pauses (deterministic jitter) and a breath before chapters
        t = LEAD_S
        timing = []
        parts = [("sil", LEAD_S)]
        for i, (ln, it) in enumerate(zip(self.script["lines"], items)):
            with wave.open(it["wav"]) as w:
                sr = w.getframerate()
                d = w.getnframes() / sr
            timing.append({"i": i, "t0": round(t, 3), "t1": round(t + d, 3), "text": ln["text"], "wav": it["wav"], "sr": sr})
            parts.append(("wav", it["wav"]))
            base = float(ln.get("pause", 0.35))
            jit = (int(hashlib.md5(ln["text"].encode()).hexdigest()[:4], 16) / 65535 - 0.5) * 0.3 * base
            gap = base + jit
            nxt = self.script["lines"][i + 1] if i + 1 < len(self.script["lines"]) else None
            if nxt and nxt.get("chapter"):
                gap += 0.6  # breath: ambient comes up between chapters
            if not nxt:
                gap = TAIL_S
            parts.append(("sil", gap))
            t += d + gap
        # write concat list for ffmpeg
        lst = self.b / "narr-concat.txt"
        lines = []
        for k, v in parts:
            if k == "sil":
                f = tdir / f"sil-{int(round(v * 1000))}.wav"
                if not f.exists():
                    sh(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono", "-t", f"{v:.3f}", "-c:a", "pcm_s16le", str(f)])
                lines.append(f"file '{f}'")
            else:
                lines.append(f"file '{v}'")
        lst.write_text("\n".join(lines) + "\n")
        sh(["ffmpeg", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le", str(self.b / "narration.wav")])
        total = dur_of(self.b / "narration.wav")
        sj(self.b / "timing.json", {"created": now(), "voice": self.spec["voice"], "lang": self.spec["lang"], "total": round(total, 3), "lines": timing})
        print(json.dumps({"lines": len(timing), "narration_s": round(total, 2)}))

    # ------------------------------------------------------------------ stt
    def stt(self):
        tm = lj(self.b / "timing.json")
        names = self.spec.get("place_names") or []
        targets = [x for x in tm["lines"] if any(n.lower() in x["text"].lower() for n in names)]
        code = r'''
import json,sys,subprocess,numpy as np
from faster_whisper import WhisperModel
a=json.loads(open(sys.argv[1]).read()); m=WhisperModel("base.en",device="cpu",compute_type="float32",cpu_threads=4); out=[]
for it in a["items"]:
    b=subprocess.run(["ffmpeg","-loglevel","error","-i",it["wav"],"-ac","1","-ar","16000","-f","f32le","-"],capture_output=True).stdout
    segs,_=m.transcribe(np.frombuffer(b,dtype=np.float32),beam_size=5,initial_prompt=None)
    out.append({"i":it["i"],"heard":" ".join(s.text.strip() for s in segs)})
print(json.dumps(out))
'''
        tmp = self.b / "stt-in.json"
        sj(tmp, {"items": [{"i": x["i"], "wav": x["wav"]} for x in targets]})
        heard = json.loads(sh([str(WHISPER_PY), "-c", code, str(tmp)]).stdout.strip().splitlines()[-1])
        norm = lambda s: re.sub(r"[^a-z0-9 ]", "", s.lower().replace("-", " "))
        res = []
        for h in heard:
            txt = tm["lines"][h["i"]]["text"]
            for n in names:
                if n.lower() in txt.lower():
                    alts = [n] + (self.spec.get("stt_alias", {}).get(n) or [])
                    ok = any(norm(a) in norm(h["heard"]) for a in alts)
                    res.append({"line": h["i"], "name": n, "heard": h["heard"], "round_trip_ok": ok})
        fails = [r for r in res if not r["round_trip_ok"]]
        sj(self.b / "stt-check.json", {"created": now(), "voice": self.spec["voice"], "lang": self.spec["lang"], "checks": res,
                                         "passed": len(res) - len(fails), "total": len(res), "failed_names": sorted({r["name"] for r in fails}),
                                         "note": "Proxy only: whisper base.en recognising the name does not prove natural pronunciation."})
        print(json.dumps({"stt_pass": len(res) - len(fails), "total": len(res), "failed": sorted({r['name'] for r in fails})}))

    # ------------------------------------------------------------------ plan
    def plan(self):
        tm = lj(self.b / "timing.json")
        lines = self.script["lines"]
        nl = tm["lines"]
        program_end = round(tm["total"], 3)
        end_card = float(self.spec.get("end_card_s", END_CARD_S))
        total = round(program_end + end_card, 3)
        clips = self.lib["clips"]
        syn = self.lib.get("synonyms", {})
        ptr = {c["id"]: c["f0"] for c in clips}
        by_creator = defaultdict(float)
        shots = []
        last_id = None
        est_footage = total

        def pick(tags, need_out, avoid):
            cand_tags = list(tags)
            for tg in tags:
                cand_tags += syn.get(tg, [])
            for pass_, av in ((0, avoid), (1, avoid), (0, None), (1, None), (2, avoid), (2, None)):
                pool = []
                for c in clips:
                    tagset = c["tags"]
                    if pass_ < 2 and not any(tg in tagset for tg in (tags if pass_ == 0 else cand_tags)):
                        continue
                    need_file = need_out * c["play_speed"]
                    if c["f1"] - ptr[c["id"]] < need_file:
                        continue
                    if av is not None and c["id"] == av:
                        continue
                    share = (by_creator[c["creator"]] + need_out) / est_footage
                    over = share > CREATOR_CAP
                    pool.append((over, by_creator[c["creator"]], -(c["f1"] - ptr[c["id"]]), c))
                if pool:
                    pool.sort(key=lambda x: (x[0], x[1], x[2]))
                    if not pool[0][0] or pass_ == 2:
                        return pool[0][3], pass_
            return None, None

        # spans per line: from line t0 (first line from 0) to next line t0; last line to total (end card over footage)
        spans = []
        for i, x in enumerate(nl):
            a = 0.0 if i == 0 else x["t0"]
            b = nl[i + 1]["t0"] if i + 1 < len(nl) else total
            spans.append((a, b))
        offtag = []
        for i, (a, b) in enumerate(spans):
            ln = lines[i]
            L = b - a
            n = max(1, round(L / TARGET_SHOT))
            while L / n > 6.0:
                n += 1
            while n > 1 and L / n < 3.0:
                n -= 1
            fr0 = round(a * FPS)
            frames_total = round(b * FPS) - fr0
            for j in range(n):
                f_a = fr0 + round(frames_total * j / n)
                f_b = fr0 + round(frames_total * (j + 1) / n)
                d = (f_b - f_a) / FPS
                c, pass_ = pick(ln.get("tags", []), d + 0.1, last_id)
                if c is None:
                    raise SystemExit(f"footage exhausted at line {i} tags {ln.get('tags')}: needs_footage")
                if pass_ == 2:
                    offtag.append({"line": i, "tags": ln.get("tags"), "used": c["id"]})
                fin = ptr[c["id"]]
                fout = fin + d * c["play_speed"]
                ptr[c["id"]] = fout + 0.6  # leave a gap: never reuse a range
                src_in = c["src_base"] + fin * c["src_speed"]
                src_out = c["src_base"] + fout * c["src_speed"]
                tag = ",".join(c["tags"])
                shots.append({"t0": round(f_a / FPS, 4), "t1": round(f_b / FPS, 4), "frames": f_b - f_a, "kind": "clip", "clip_id": c["id"],
                              "video_id": c["video_id"], "creator": c["creator"], "file": c["file"], "file_in": round(fin, 3),
                              "play_speed": c["play_speed"], "src_in": round(src_in, 3), "src_out": round(src_out, 3), "tag": tag,
                              "line": i, "audio_ok": bool(c.get("audio")) and not c.get("licensedContent"), "place": c.get("place")})
                if f_a / FPS < program_end:
                    by_creator[c["creator"]] += min(d, program_end - f_a / FPS)
                last_id = c["id"]
        # overlays
        ov = []
        hook_end = max((nl[i]["t1"] for i, l in enumerate(lines) if l.get("hook")), default=0)
        num = 0
        for i, l in enumerate(lines):
            t0 = nl[i]["t0"]
            span = spans[i][1] - spans[i][0]
            if l.get("chapter"):
                num += 1
                ov.append({"kind": "chapter", "t0": t0, "t1": t0 + 3.6, "text": l["chapter"], "number": num})
            if l.get("disclosure"):
                ov.append({"kind": "disclosure", "t0": t0, "t1": t0 + max(6.0, min(span, 9.0)), "text": self.spec["disclosure_overlay"]})
            if l.get("lower"):
                st = t0 + (4.0 if l.get("chapter") else 0.4)
                ov.append({"kind": "lower", "t0": st, "t1": st + 4.5, "text": l["lower"]["text"], "sub": l["lower"].get("sub")})
            if l.get("prompt"):
                ov.append({"kind": "prompt", "t0": t0 + 0.2, "t1": t0 + 0.2 + max(4.5, min(span, 6.0)), "badge": l["prompt"]["badge"], "text": l["prompt"]["text"], "spoken": True})
            if l.get("map"):
                st = t0 + 0.3
                ov.append({"kind": "mapinset", "t0": st, "t1": st + min(max(span - 0.5, 4.0), 7.0), "text": l["map"].get("text"), "route": l["map"]["route"],
                           "focus": l["map"].get("focus"), "focusFrom": l["map"].get("focusFrom")})
        # fill engagement gaps > 85 s with visual-only pills (not closer than 50 s to another prompt)
        k = 0
        for _ in range(0 if self.portrait else 20):
            pts = sorted(o["t0"] for o in ov if o["kind"] == "prompt")
            marks = [hook_end] + pts + [program_end]
            gaps = [(b - a, a, b) for a, b in zip(marks, marks[1:]) if b - a > 85]
            if not gaps:
                break
            g, a, b = max(gaps)
            t = a + g / 2
            badge, text = PROMPT_FILL[k % len(PROMPT_FILL)]
            k += 1
            ov.append({"kind": "prompt", "t0": round(t, 2), "t1": round(t + 4.5, 2), "badge": badge, "text": text, "spoken": False})
        if total > program_end + 0.5:
            ov.append({"kind": "endcard", "t0": program_end, "t1": total, "text": self.script["end_card"]["text"], "lines": self.script["end_card"]["lines"]})
        ov.sort(key=lambda o: o["t0"])
        sents = [{"t0": x["t0"], "t1": x["t1"], "text": x["text"], "disclosure": bool(lines[i].get("disclosure")), "facts": lines[i].get("facts", [])} for i, x in enumerate(nl)]
        amb = [{"t0": s["t0"], "t1": s["t1"], "video_id": s["video_id"], "licence_ok": True} for s in shots if s["audio_ok"]]
        edl = {"schema": "aurum-edl-v1", "created": now(), "slug": self.spec["slug"], "title": self.script["title"], "fps": FPS, "width": W, "height": H,
               "duration_s": total, "program_end_s": program_end, "hook_end_s": round(hook_end, 3), "shots": shots, "overlays": ov, "sentences": sents,
               "audio": {"narration": str(self.b / "narration.wav"), "music": "none", "ambient": amb}, "offtag_shots": offtag}
        sj(self.b / "edl-long.json", edl)
        self.licence_log(shots)
        res = spec_gates.evaluate(edl, spec_gates.read_rows(self.wd / "licence-log.csv"), None, root=self.wd)
        if self.portrait:
            res = self.short_filter(res, edl)
        sj(self.out / "scorecard-pre-render.json", {"created": now(), "stage": "pre-render (EDL)", **res})
        fs = [s["t1"] - s["t0"] for s in shots]
        print(json.dumps({"pass": res["pass"], "failed": res["failed"], "shots": len(shots), "median_shot": round(statistics.median(fs), 2),
                          "footage_ratio": res["gates"]["footage_ratio_ge_80"]["detail"]["ratio"], "creators": res["gates"].get("creator_share_le_30", {}).get("detail"),
                          "offtag": len(offtag), "duration_s": total}, ensure_ascii=False))

    SHORT_GATES = {"footage_ratio_ge_80", "map_ratio_le_10", "no_illustration_or_fallback_scenes", "no_picture_gaps", "no_shot_over_8s",
                   "no_clip_reuse", "footage_from_frame_1", "licence_rows_complete", "music_ytal_or_none", "ambient_only_from_allowed_sources",
                   "loudness_-14_tp_le_-1", "no_freeze_over_1s", "av_duration_match"}

    def short_filter(self, res, edl):
        g = {k: v for k, v in res["gates"].items() if k in self.SHORT_GATES}
        d = edl["duration_s"]
        g["short_le_60s"] = {"pass": d <= 60.0, "detail": d}
        g["first_second_hook_overlay"] = {"pass": bool(self.spec.get("hook_text")), "detail": self.spec.get("hook_text")}
        g["burned_captions"] = {"pass": True, "detail": "caption overlay items generated from sentence timings"}
        disc = any(s_.get("disclosure") for s_ in edl["sentences"])
        needs = any("aurum-transfers.com" in s_["text"] or "link" in s_["text"].lower() for s_ in edl["sentences"])
        g["disclosure_if_affiliate_cta"] = {"pass": disc or not needs, "detail": {"cta": needs, "disclosure": disc}}
        failed = [k for k, v in g.items() if not v["pass"]]
        return {"pass": not failed, "failed": failed, "gates": g, "spec": res["spec"]}

    def licence_log(self, shots):
        used = defaultdict(list)
        for s in shots:
            used[s["video_id"]].append(s)
        ev_dirs = self.spec.get("evidence_dirs", [])
        rows = []
        for vid, ss in used.items():
            c = next(c for c in self.lib["clips"] if c["video_id"] == vid)
            ev = None
            for d in ev_dirs:
                for cand in (Path(d) / f"{vid}.watchpage-licence.json", Path(d) / vid / "watchpage-licence.json"):
                    if cand.exists():
                        ev = cand
                        break
                if ev:
                    break
            evj = lj(ev, {}) if ev else {}
            rows.append({"asset_id": f"yt-{vid}", "video_id": vid, "file": c["file"], "source": "YouTube (Creative Commons Attribution)",
                         "creator": c["creator"], "url": c["url"], "title": c["title"],
                         "licence": evj.get("license") or "", "date": (evj.get("checked_at") or "")[:10],
                         "evidence": str(ev) if ev else "", "in_s": ";".join(f"{x['src_in']:.2f}" for x in ss),
                         "out_s": ";".join(f"{x['src_out']:.2f}" for x in ss), "audio_used": "yes" if any(x["audio_ok"] for x in ss) else "no",
                         "used_in": self.spec["slug"]})
        rows.append({"asset_id": "aurum-overlays", "video_id": "", "file": "remotion/src/Overlay.tsx", "source": "Aurum Transfers original Remotion overlays and maps",
                     "creator": "Aurum Transfers Limited", "url": "https://aurum-transfers.com", "title": "", "licence": "Original work", "date": now()[:10],
                     "evidence": "", "in_s": "", "out_s": "", "audio_used": "", "used_in": self.spec["slug"]})
        rows.append({"asset_id": "kokoro-bm_george", "video_id": "", "file": "build/narration.wav", "source": "Kokoro-82M ONNX (Apache-2.0), local", "creator": "hexgrad / thewh1teagle",
                     "url": "https://github.com/thewh1teagle/kokoro-onnx", "title": "", "licence": "Apache-2.0", "date": now()[:10], "evidence": "", "in_s": "", "out_s": "",
                     "audio_used": "", "used_in": self.spec["slug"]})
        with open(self.wd / "licence-log.csv", "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)

    # ------------------------------------------------------------------ sheet
    def sheet(self):
        edl = lj(self.b / "edl-long.json")
        sd = self.b / "sheet"
        sd.mkdir(exist_ok=True)
        files = []
        for k, s in enumerate(edl["shots"]):
            t = s["file_in"] + (s["t1"] - s["t0"]) * s["play_speed"] / 2
            f = sd / f"{k:04d}.jpg"
            if not f.exists():
                txt = f"{k} {int(s['t0'] // 60)}:{s['t0'] % 60:04.1f} {s['clip_id']}".replace(":", "\\:")
                sh(["ffmpeg", "-loglevel", "error", "-y", "-ss", f"{t:.2f}", "-i", s["file"], "-frames:v", "1", "-vf",
                    f"scale=320:180,drawtext=text='{txt}':x=3:y=3:fontsize=14:fontcolor=yellow:box=1:boxcolor=black@0.6", str(f)])
            files.append(f)
        per = 48
        outs = []
        for p in range(0, len(files), per):
            lst = self.b / f"sheet-{p // per}.txt"
            o = self.out / f"contact-sheet-{p // per + 1}.jpg"
            sh(["ffmpeg", "-loglevel", "error", "-y", "-pattern_type", "glob", "-i", str(sd / "*.jpg"), "-vf",
                f"select='between(n\\,{p}\\,{p + per - 1})',tile=6x8", "-frames:v", "1", "-vsync", "vfr", str(o)])
            outs.append(str(o))
        print(json.dumps({"sheets": outs, "shots": len(files)}))

    # ------------------------------------------------------------------ segments
    def segments(self, w=None, h=None, tag="hd", preset="veryfast", crf="18"):
        w, h = w or W, h or H
        edl = lj(self.b / "edl-long.json")
        # per-source crop (letterboxed sources: remove burned bars and any logo inside them)
        self.crops = {c["file"]: c["crop"] for c in lj(self.wd / "footage.json")["clips"] if c.get("crop")}
        sd = self.b / f"seg-{tag}"
        sd.mkdir(exist_ok=True)
        vl, al = [], []
        for k, s in enumerate(edl["shots"]):
            n = s["frames"]
            d = n / FPS
            sp = s["play_speed"]
            crop = self.crops.get(s["file"], "")
            key = hashlib.md5((f"{s['file']}|{s['file_in']:.3f}|{n}|{sp}|{w}x{h}" + (f"|{crop}" if crop else "")).encode()).hexdigest()[:10]
            keys_f = sd / "keys.json"
            keys = json.loads(keys_f.read_text()) if keys_f.exists() else {}
            vf = sd / f"{k:04d}.mp4"
            if keys.get(str(k), key) != key or not vf.exists() and (sd / f"{k:04d}-{key}.mp4").exists():
                vf = sd / f"{k:04d}-{key}.mp4"
            elif str(k) not in keys and vf.exists():
                keys[str(k)] = key
                keys_f.write_text(json.dumps(keys))
            if not vf.exists():
                filt = (f"crop={crop}," if crop else "") + f"setpts=(PTS-STARTPTS)/{sp},fps={FPS},scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},setsar=1,format=yuv420p,tpad=stop_mode=clone:stop_duration=1"
                sh(["ffmpeg", "-loglevel", "error", "-y", "-ss", f"{s['file_in']:.3f}", "-t", f"{d * sp + 1.0:.3f}", "-i", s["file"], "-an", "-vf", filt,
                    "-frames:v", str(n), "-c:v", "libx264", "-preset", preset, "-crf", crf, "-r", str(FPS), "-video_track_timescale", "15360", str(vf)])
            vl.append(f"file '{vf}'")
            af = sd / f"{k:04d}.wav"
            if not af.exists():
                c = next(c for c in self.lib["clips"] if c["id"] == s["clip_id"])
                ns = int(round(d * 48000))
                if s["audio_ok"] and c.get("audio"):
                    a = c["audio"]
                    st = s["src_in"] if a["mode"] == "source" else s["file_in"]
                    speed = (c["src_speed"] if a["mode"] == "source" else 1.0) * sp
                    tempo = []
                    x = speed
                    while x > 2.0:
                        tempo.append("atempo=2.0")
                        x /= 2.0
                    if abs(x - 1.0) > 1e-3:
                        tempo.append(f"atempo={x:.4f}")
                    af_f = ",".join(tempo + ["aresample=48000", "afade=t=in:d=0.08", f"afade=t=out:st={max(0, d - 0.08):.3f}:d=0.08", f"apad=whole_len={ns}", f"atrim=end_sample={ns}"])
                    sh(["ffmpeg", "-loglevel", "error", "-y", "-ss", f"{st:.3f}", "-t", f"{d * speed + 0.5:.3f}", "-i", a["file"], "-vn", "-ac", "2", "-af", af_f, "-c:a", "pcm_s16le", str(af)])
                else:
                    sh(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-af", f"atrim=end_sample={ns}", "-c:a", "pcm_s16le", str(af)])
            al.append(f"file '{af}'")
        (self.b / f"vlist-{tag}.txt").write_text("\n".join(vl) + "\n")
        (self.b / f"alist-{tag}.txt").write_text("\n".join(al) + "\n")
        sh(["ffmpeg", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(self.b / f"vlist-{tag}.txt"), "-c", "copy", str(self.b / f"base-{tag}.mp4")])
        sh(["ffmpeg", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(self.b / f"alist-{tag}.txt"), "-c:a", "pcm_s16le", str(self.b / f"ambient-{tag}.wav")])
        print(json.dumps({"base": str(self.b / f"base-{tag}.mp4"), "dur": dur_of(self.b / f"base-{tag}.mp4"), "edl_dur": edl["duration_s"]}))

    def mix(self, tag="hd"):
        """Narration + ambient (sidechain-ducked under the voice, up in the breaths), two-pass loudnorm to -14 LUFS / TP -1.5."""
        edl = lj(self.b / "edl-long.json")
        raw = self.b / f"mix-raw-{tag}.wav"
        total = edl["duration_s"]
        sh(["ffmpeg", "-loglevel", "error", "-y", "-i", str(self.b / "narration.wav"), "-i", str(self.b / f"ambient-{tag}.wav"), "-filter_complex",
            f"[0:a]apad=whole_dur={total:.3f},atrim=0:{total:.3f},asplit=2[n1][n2];[1:a]volume=0.30,atrim=0:{total:.3f}[amb];"
            "[amb][n1]sidechaincompress=threshold=0.015:ratio=10:attack=30:release=500:makeup=1[ambd];"
            "[n2][ambd]amix=inputs=2:normalize=0:duration=first[m]", "-map", "[m]", "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le", str(raw)])
        r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(raw), "-af", "loudnorm=I=-14:TP=-1.5:LRA=11:print_format=json", "-f", "null", "-"], capture_output=True, text=True)
        st = json.loads(re.findall(r"\{[^{}]*\"input_i\"[^{}]*\}", r.stderr, re.S)[-1])
        af = (f"loudnorm=I=-14:TP=-1.5:LRA=11:measured_I={st['input_i']}:measured_TP={st['input_tp']}:measured_LRA={st['input_lra']}"
              f":measured_thresh={st['input_thresh']}:offset={st['target_offset']}:linear=true")
        sh(["ffmpeg", "-loglevel", "error", "-y", "-i", str(raw), "-af", af, "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le", str(self.b / f"mix-{tag}.wav")])

    # ------------------------------------------------------------------ animatic
    def animatic(self):
        self.segments(480, 270, "lo", "ultrafast", "30")
        self.mix("lo")
        edl = lj(self.b / "edl-long.json")
        dt = []
        for o in edl["overlays"]:
            if o["kind"] in ("chapter", "prompt", "lower", "disclosure", "mapinset", "endcard"):
                lab = {"chapter": "CH", "prompt": "PROMPT", "lower": "LT", "disclosure": "DISCLOSURE", "mapinset": "MAP", "endcard": "END"}[o["kind"]]
                txt = re.sub(r"[^A-Za-z0-9 ,.&+-]", "", f"{lab} {o.get('badge', '')} {o.get('text', '')}")[:60]
                dt.append(f"drawtext=text='{txt}':x=6:y=h-24:fontsize=13:fontcolor=white:box=1:boxcolor=black@0.6:enable='between(t,{o['t0']:.2f},{o['t1']:.2f})'")
        vf = ",".join(dt) if dt else "null"
        sh(["ffmpeg", "-loglevel", "error", "-y", "-i", str(self.b / "base-lo.mp4"), "-i", str(self.b / "mix-lo.wav"), "-vf", vf, "-map", "0:v", "-map", "1:a",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "30", "-c:a", "aac", "-b:a", "96k", "-shortest", str(self.out / f"{self.stem}-animatic-270p.mp4")])
        print(json.dumps({"animatic": str(self.out / f"{self.stem}-animatic-270p.mp4")}))

    # ------------------------------------------------------------------ overlays
    def overlays(self):
        edl = lj(self.b / "edl-long.json")
        mp = self.map_data()
        items = []
        for o in edl["overlays"]:
            f0 = round(o["t0"] * FPS)
            it = {"kind": o["kind"], "from": f0, "dur": max(1, round(o["t1"] * FPS) - f0)}
            for k in ("text", "sub", "number", "badge", "route", "focus", "focusFrom", "lines"):
                if o.get(k) is not None:
                    it[k] = o[k]
            items.append(it)
        if self.portrait:
            for c in self.captions(edl):
                f0 = round(c["t0"] * FPS)
                items.append({"kind": "caption", "from": f0, "dur": max(1, round(c["t1"] * FPS) - f0), "text": c["text"]})
            if self.spec.get("hook_text"):
                items.append({"kind": "hook", "from": 0, "dur": round(2.6 * FPS), "text": self.spec["hook_text"]})
        props = {"fps": FPS, "width": W, "height": H, "durationInFrames": round(edl["duration_s"] * FPS), "portrait": self.portrait, "items": items,
                 "map": mp, "brand": self.spec.get("brand", "AURUM TRANSFERS")}
        pp = self.b / "overlay-props.json"
        sj(pp, props)
        rdir = ROOT / "remotion"
        sh(["npx", "remotion", "render", "src/index.ts", "OverlayStrip", str(self.b / "overlay.webm"), f"--props={pp}", "--codec=vp8",
            "--pixel-format=yuva420p", "--image-format=png", "--concurrency=3", "--log=warn", f"--public-dir={self.spec['public_dir']}",
            "--chrome-mode=headless-shell", "--gl=swangle", "--timeout=120000"], cwd=rdir)
        print(json.dumps({"overlay": str(self.b / "overlay.webm"), "dur": dur_of(self.b / "overlay.webm")}))

    def captions(self, edl, maxc=28):
        caps = []
        for snt in edl["sentences"]:
            words = snt["text"].split()
            chunks, cur = [], ""
            for w_ in words:
                if len(cur) + len(w_) + 1 > maxc and cur:
                    chunks.append(cur)
                    cur = w_
                else:
                    cur = (cur + " " + w_).strip()
            if cur:
                chunks.append(cur)
            tot = sum(len(c) for c in chunks) or 1
            t = snt["t0"]
            for c in chunks:
                d = (snt["t1"] - snt["t0"]) * len(c) / tot
                caps.append({"t0": round(t, 3), "t1": round(t + d, 3), "text": c})
                t += d
        return caps

    def map_data(self):
        code = ("import json,sys;sys.path.insert(0,sys.argv[1]);from aurum_video.maps import build_map;from pathlib import Path;"
                "pl=json.load(open(sys.argv[3]));print(json.dumps(build_map(Path(sys.argv[2]),pl['places'])))")
        return json.loads(sh([sys.executable, "-c", code, str(ROOT), self.spec["map"]["geojson"], self.spec["map"]["places"]]).stdout)

    # ------------------------------------------------------------------ compose
    def compose(self):
        self.segments()
        self.mix("hd")
        out = self.out / f"{self.stem}.mp4"
        sh(["ffmpeg", "-loglevel", "error", "-y", "-i", str(self.b / "base-hd.mp4"), "-c:v", "libvpx", "-i", str(self.b / "overlay.webm"), "-i", str(self.b / "mix-hd.wav"),
            "-filter_complex", "[0:v][1:v]overlay=eof_action=pass:format=auto,format=yuv420p[v]", "-map", "[v]", "-map", "2:a",
            "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-r", str(FPS), "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-shortest", "-movflags", "+faststart", str(out)])
        print(json.dumps({"out": str(out), "dur": dur_of(out)}))

    # ------------------------------------------------------------------ qa
    def qa(self):
        out = self.out / f"{self.stem}.mp4"
        edl = lj(self.b / "edl-long.json")
        mo = spec_gates.measure_output(out, True)
        res = spec_gates.evaluate(edl, spec_gates.read_rows(self.wd / "licence-log.csv"), mo, root=self.wd)
        if self.portrait:
            res = self.short_filter(res, edl)
        qa = self.out / "qa"
        qa.mkdir(exist_ok=True)
        d = dur_of(out)
        grabs = []
        for pct in (0, 25, 50, 75, 100):
            t = min(max(d * pct / 100, 0.5 if pct == 0 else 0), d - 0.6)
            f = qa / f"{self.stem}-{pct:03d}.jpg"
            sh(["ffmpeg", "-loglevel", "error", "-y", "-ss", f"{t:.2f}", "-i", str(out), "-frames:v", "1", "-q:v", "3", str(f)])
            grabs.append(str(f))
        rv = self.out / f"{self.stem}-review-720p.mp4"
        br = int(min(2_400_000, (95 * 1024 * 1024 * 8) / d - 128_000))
        sh(["ffmpeg", "-loglevel", "error", "-y", "-i", str(out), "-vf", "scale=1280:720", "-c:v", "libx264", "-preset", "veryfast", "-b:v", str(br), "-maxrate", str(int(br * 1.3)),
            "-bufsize", str(br * 2), "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(rv)])
        sha = hashlib.sha256(out.read_bytes()).hexdigest()
        chk = {"slug": self.spec["slug"], "created": now(), "output": str(out), "sha256": sha, "bytes": out.stat().st_size, "duration_s": d,
               "review_copy": str(rv), "review_bytes": rv.stat().st_size, "frame_grabs": grabs, "measured": mo, "stt": lj(self.b / "stt-check.json"),
               **res, "not_measured": ["narration naturalness and taste (needs human/videoReview)", "whether ambient sources contain no music (whisper/flatness proxy only)",
                                       "place identity of each clip beyond creator titles and contact-sheet review"]}
        sj(self.out / "checks.json", chk)
        print(json.dumps({"pass": res["pass"], "failed": res["failed"], "lufs": mo.get("lufs"), "tp": mo.get("true_peak"), "freeze": mo.get("freeze"),
                          "review_mb": round(rv.stat().st_size / 1048576, 1)}))


if __name__ == "__main__":
    t = T(sys.argv[1])
    for st in sys.argv[2:]:
        getattr(t, st)()
