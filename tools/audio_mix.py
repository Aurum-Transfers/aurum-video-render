#!/usr/bin/env python3
"""Narration + natural-sound mixer (v8, 10 Nov 2026: MBJ v6 full failed natural_sound_audible: lifts at -33/-32 dBFS
and ambient only -6 dB under the voice; the old sidechaincompress mix had no level targets).

Level-targeted mix instead of a fixed compressor:
  * under the voice the ambient sits AMB_UNDER_VOICE_DB below the narration (spec gate window -26..-10 dB)
  * in voice-free breaths it rises BREATH_LIFT_DB above that
  * inside each planned lift it is gained to LIFT_TARGET_DBFS in the final mix (gate: >= -32 dBFS), verified after
    loudnorm and corrected (up to 3 passes)
  * two-pass loudnorm to -14 LUFS / TP -1.5 as before.

usage:
  audio_mix.py remix JOBDIR EDL VIDEO_IN VIDEO_OUT [VIDEO_IN2 VIDEO_OUT2 ...]
      rebuild the ambient stem from EDL + JOBDIR/footage.json, remix, remux (video stream copied, no re-encode)
"""
import json, math, re, subprocess, sys, tempfile
from pathlib import Path
import numpy as np

SR = 48000
AMB_UNDER_VOICE_DB = -16.0
BREATH_LIFT_DB = 6.0
LIFT_TARGET_DBFS = -24.0
VOICE_RMS = 0.02  # same voice-activity threshold as spec_gates.measure_audio (8 kHz mono, 50 ms frames)


def sh(cmd):
    subprocess.run(cmd, check=True)


def load(f, sr=SR, ch=2):
    b = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", str(f), "-vn", "-ac", str(ch), "-ar", str(sr), "-f", "f32le", "-"],
                       capture_output=True, check=True).stdout
    return np.frombuffer(b, np.float32).reshape(-1, ch).copy()


def save(f, x, sr=SR):
    p = subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "f32le", "-ar", str(sr), "-ac", str(x.shape[1]), "-i", "-",
                        "-c:a", "pcm_s16le", str(f)], input=np.clip(x, -1, 1).astype(np.float32).tobytes(), check=True)


def db(x):
    return float(20 * np.log10(np.sqrt((np.asarray(x, np.float64) ** 2).mean()) + 1e-9)) if len(x) else -180.0


def build_ambient(edl, root, out_wav, fps=30):
    """Per-shot natural sound exactly as title_runner.segments() builds it (audio-licensed shots only, else silence)."""
    root = Path(root)
    lib = json.loads((root / "footage.json").read_text()) if (root / "footage.json").exists() else {"clips": []}
    clips = {c["id"]: c for c in lib.get("clips", [])}
    tmp = Path(tempfile.mkdtemp(prefix="amb-"))
    al = []
    base = root.parent.parent  # repo root (jobs/<job>)
    for k, s in enumerate(edl["shots"]):
        d = s["frames"] / fps; sp = s["play_speed"]; ns = int(round(d * SR))
        af = tmp / f"{k:04d}.wav"
        c = clips.get(s.get("clip_id")) or {}
        if s.get("audio_ok") and c.get("audio", True):
            a = c.get("audio") if isinstance(c.get("audio"), dict) else {"mode": "file", "file": s["file"]}
            st = s["src_in"] if a["mode"] == "source" else s["file_in"]
            speed = (c.get("src_speed", 1.0) if a["mode"] == "source" else 1.0) * sp
            tempo, x = [], speed
            while x > 2.0:
                tempo.append("atempo=2.0"); x /= 2.0
            if abs(x - 1.0) > 1e-3:
                tempo.append(f"atempo={x:.4f}")
            src = Path(a["file"]); src = src if src.is_absolute() else base / src
            af_f = ",".join(tempo + [f"aresample={SR}", "afade=t=in:d=0.08", f"afade=t=out:st={max(0, d - 0.08):.3f}:d=0.08",
                                      f"apad=whole_len={ns}", f"atrim=end_sample={ns}"])
            sh(["ffmpeg", "-loglevel", "error", "-y", "-ss", f"{st:.3f}", "-t", f"{d * speed + 0.5:.3f}", "-i", str(src), "-vn", "-ac", "2",
                "-af", af_f, "-c:a", "pcm_s16le", str(af)])
        else:
            sh(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", f"anullsrc=r={SR}:cl=stereo", "-af", f"atrim=end_sample={ns}",
                "-c:a", "pcm_s16le", str(af)])
        al.append(f"file '{af}'")
    (tmp / "list.txt").write_text("\n".join(al) + "\n")
    sh(["ffmpeg", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(tmp / "list.txt"), "-c:a", "pcm_s16le", str(out_wav)])
    return out_wav


def _smooth(g, n):
    if n <= 1:
        return g
    k = np.ones(n) / n
    return np.convolve(np.pad(g, (n // 2, n - 1 - n // 2), mode="edge"), k, mode="valid")


def loudnorm(raw, out):
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(raw), "-af", "loudnorm=I=-14:TP=-1.5:LRA=11:print_format=json",
                        "-f", "null", "-"], capture_output=True, text=True)
    st = json.loads(re.findall(r"\{[^{}]*\"input_i\"[^{}]*\}", r.stderr, re.S)[-1])
    af = (f"loudnorm=I=-14:TP=-1.5:LRA=11:measured_I={st['input_i']}:measured_TP={st['input_tp']}:measured_LRA={st['input_lra']}"
          f":measured_thresh={st['input_thresh']}:offset={st['target_offset']}:linear=true")
    sh(["ffmpeg", "-loglevel", "error", "-y", "-i", str(raw), "-af", af, "-ar", str(SR), "-ac", "2", "-c:a", "pcm_s16le", str(out)])


def mix(narration_wav, ambient_wav, edl, out_mix, out_ambd, ambient_gain=0.9, log=print):
    total = float(edl["duration_s"]); n = int(round(total * SR))
    nar = load(narration_wav); amb = load(ambient_wav) * ambient_gain
    nar = np.pad(nar, ((0, max(0, n - len(nar))), (0, 0)))[:n]; amb = np.pad(amb, ((0, max(0, n - len(amb))), (0, 0)))[:n]
    fr = int(0.05 * SR); nf = n // fr
    nm = nar[:nf * fr].mean(1).reshape(nf, fr); am = amb[:nf * fr].mean(1).reshape(nf, fr)
    n_rms = np.sqrt((nm ** 2).mean(1)); a_rms = np.sqrt((am ** 2).mean(1))
    voice = n_rms > VOICE_RMS
    # hold the duck 250 ms past each word (release) and 50 ms before (attack)
    v = voice.copy()
    for s_ in range(1, 6):
        v[s_:] |= voice[:-s_]
    v[:-1] |= voice[1:]
    has_amb = a_rms > 1e-4
    sel = voice & has_amb
    if sel.any():
        A = db(am[sel].ravel()); N = db(nm[sel].ravel())
        g_duck = 10 ** ((AMB_UNDER_VOICE_DB - (A - N)) / 20)
    else:
        g_duck = 1.0
    g_duck = float(np.clip(g_duck, 0.02, 4.0)); g_open = min(g_duck * 10 ** (BREATH_LIFT_DB / 20), 6.0)
    gf = np.where(v, g_duck, g_open).astype(np.float64)
    lifts = edl.get("lifts") or []
    lift_gain = {}
    for i, L in enumerate(lifts):
        a0, a1 = int(L["t0"] * SR / fr), int(math.ceil(L["t1"] * SR / fr))
        lev = db(am[a0:a1].ravel())
        lift_gain[i] = float(np.clip(10 ** ((LIFT_TARGET_DBFS - 6.0 - lev) / 20), 0.05, 16.0)) if lev > -80 else 1.0  # pre-loudnorm guess
    for it in range(3):
        g = gf.copy()
        for i, L in enumerate(lifts):
            a0, a1 = int(L["t0"] * SR / fr), int(math.ceil(L["t1"] * SR / fr))
            g[max(0, a0 - 2):a1 + 2] = lift_gain[i]
        g = _smooth(g, 3)  # 150 ms ramps
        gs = np.repeat(g, fr); gs = np.pad(gs, (0, n - len(gs)), mode="edge")[:n, None]
        ambd = amb * gs
        raw = Path(out_mix).with_suffix(".raw.wav")
        save(raw, nar + ambd)
        loudnorm(raw, out_mix)
        fin = load(out_mix, 8000, 1)[:, 0]
        meas = [db(fin[int(L["t0"] * 8000):int(L["t1"] * 8000)]) for L in lifts]
        short = {i: m for i, m in enumerate(meas) if m < LIFT_TARGET_DBFS - 2.0}
        log(json.dumps({"pass": it, "g_duck_db": round(20 * math.log10(g_duck), 1), "lift_dbfs": [round(m, 1) for m in meas],
                        "lift_gain_db": [round(20 * math.log10(lift_gain[i]), 1) for i in range(len(lifts))]}))
        if not short:
            break
        for i, m in short.items():
            lift_gain[i] = float(min(lift_gain[i] * 10 ** ((LIFT_TARGET_DBFS - m) / 20), 32.0))
    save(out_ambd, ambd)
    return {"lift_dbfs": meas, "g_duck": g_duck}


def remux(video_in, mix_wav, video_out):
    sh(["ffmpeg", "-loglevel", "error", "-y", "-i", str(video_in), "-i", str(mix_wav), "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy",
        "-c:a", "aac", "-b:a", "192k", "-ar", str(SR), "-shortest", "-movflags", "+faststart", str(video_out)])


def main():
    if len(sys.argv) < 6 or sys.argv[1] != "remix":
        print(__doc__); raise SystemExit(2)
    job, edl_p = Path(sys.argv[2]), Path(sys.argv[3])
    pairs = list(zip(sys.argv[4::2], sys.argv[5::2]))
    edl = json.loads(edl_p.read_text())
    spec = json.loads((job / "spec.json").read_text()) if (job / "spec.json").exists() else {}
    outdir = Path(pairs[0][1]).parent / "remix-audio"; outdir.mkdir(exist_ok=True)
    amb = build_ambient(edl, job, outdir / "ambient.wav")
    res = mix(job / "build" / "narration.wav", amb, edl, outdir / "mix.wav", outdir / "ambd.wav", float(spec.get("ambient_gain", 0.9)))
    for vi, vo in pairs:
        remux(vi, outdir / "mix.wav", vo)
    print(json.dumps({"ok": True, **{k: v for k, v in res.items()}, "outputs": [vo for _, vo in pairs]}))


if __name__ == "__main__":
    main()
