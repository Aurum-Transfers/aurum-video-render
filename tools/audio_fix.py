#!/usr/bin/env python3
"""Scripted audio-only fix for a CI render whose ONLY failed QA gates are audio gates (e.g. MBJ natural_sound_audible).

Remixes narration + natural sound with tools/audio_mix.py (level-targeted) onto the existing video streams (-c:v copy;
no re-render), re-measures the output with spec_gates.measure_output (no freeze pass: the video is bit-identical) and
re-evaluates every gate. A gate passes if it passes on the new measurement, or it is a non-audio gate that passed in
the CI checks.json (video unchanged). Writes OUTDIR/checks-audio-vN.json (same shape as the hand-run MBJ v2 file, plus
sha256 per output). Must run under `gate.py run --kind heavy`.

usage: audio_fix.py JOBDIR ARTDIR OUTDIR PREFIX VERSION     e.g. jobs/x .../art/aruba-v6-preview .../out/full jamaica-mbj-v6-full 2
"""
import hashlib, json, subprocess, sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent; sys.path.insert(0, str(HERE))
import spec_gates  # noqa: E402

AUDIO = {"music_ytal_or_none", "ambient_only_from_allowed_sources", "loudness_-14_tp_le_-1", "av_duration_match",
         "natural_sound_audible", "no_music_or_sfx_in_source_audio"}
job, art, out, pfx, v = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]), sys.argv[4], sys.argv[5]
ci = json.loads((art / "out/checks.json").read_text()); edl_p = art / "build/edl-long.json"; edl = json.loads(edl_p.read_text())
bad_non_audio = [g for g in ci.get("failed", []) if g not in AUDIO]
if bad_non_audio:
    print(json.dumps({"ok": False, "why": "non-audio gates failed; an audio remix cannot fix them", "failed": bad_non_audio})); sys.exit(1)
m, r = out / f"{pfx}-1080p-master.mp4", out / f"{pfx}-review-720p.mp4"
m2, r2 = out / f"{pfx}-1080p-master-v{v}.mp4", out / f"{pfx}-review-720p-v{v}.mp4"
subprocess.run([sys.executable, str(HERE / "audio_mix.py"), "remix", str(job), str(edl_p), str(m), str(m2), str(r), str(r2)], check=True)
rows = spec_gates.read_rows(art / "licence-log.csv")
ambd = out / "remix-audio" / "ambd.wav"
res_all = {}
for f in (m2, r2):
    mo = spec_gates.measure_output(f, False, edl, ambd, job / "build/narration.wav")
    ev = spec_gates.evaluate(edl, rows, mo, root=job)
    gates = ev["gates"]; ci_g = ci.get("gates", {})
    failed = [g for g, x in gates.items() if not x["pass"] and not (g not in AUDIO and ci_g.get(g, {}).get("pass"))]
    res_all[f.name] = {"all_pass": not failed, "failed": failed, "sha256": hashlib.sha256(f.read_bytes()).hexdigest(),
                       "audio_gates": {g: gates[g] for g in AUDIO if g in gates}}
doc = {"created": datetime.now().astimezone().isoformat(timespec="seconds"),
       "method": "audio-only remix (tools/audio_fix.py -> audio_mix.py), video stream copied; non-audio gates carried from CI checks.json",
       "ci_checks": str(art / "out/checks.json"), "results": res_all}
(out / f"checks-audio-v{v}.json").write_text(json.dumps(doc, indent=1, default=str))
print(json.dumps({"ok": all(x["all_pass"] for x in res_all.values()), "failed": {k: x["failed"] for k, x in res_all.items()}}))
sys.exit(0 if all(x["all_pass"] for x in res_all.values()) else 1)
