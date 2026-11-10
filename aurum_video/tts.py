"""tts: per-paragraph Kokoro render, concat with gaps, ffmpeg loudnorm (two-pass) to 48 kHz."""
from __future__ import annotations

import hashlib
import json
import re

from .common import PhaseError, ROOT, load_json, log, run, save_json, settings, tool
from .prereqs import MODEL_DIR
from .script import selected_units, tts_text, units


def _loudnorm(src, dst, I, TP, LRA) -> dict:
    ff = tool("ffmpeg") or "ffmpeg"
    first = run([ff, "-hide_banner", "-nostats", "-i", str(src), "-af",
                 f"loudnorm=I={I}:TP={TP}:LRA={LRA}:print_format=json", "-f", "null", "-"], capture=True)
    m = re.findall(r"\{[^{}]*\"input_i\"[^{}]*\}", first.stderr, re.S)
    if not m:
        raise PhaseError("loudnorm pass 1 produced no stats")
    st = json.loads(m[-1])
    af = (f"loudnorm=I={I}:TP={TP}:LRA={LRA}:measured_I={st['input_i']}:measured_TP={st['input_tp']}"
          f":measured_LRA={st['input_lra']}:measured_thresh={st['input_thresh']}:offset={st['target_offset']}"
          f":linear=true:print_format=json")
    second = run([ff, "-hide_banner", "-nostats", "-y", "-i", str(src), "-af", af, "-ar", "48000", "-ac", "2",
                  "-c:a", "pcm_s16le", str(dst)], capture=True)
    m2 = re.findall(r"\{[^{}]*\"output_i\"[^{}]*\}", second.stderr, re.S)
    return json.loads(m2[-1]) if m2 else {}


def measure_loudness(path) -> dict:
    """Integrated LUFS and true peak of any media file (used by checks too)."""
    ff = tool("ffmpeg") or "ffmpeg"
    res = run([ff, "-hide_banner", "-nostats", "-i", str(path), "-vn", "-af",
               "loudnorm=I=-14:TP=-1.5:LRA=11:print_format=json", "-f", "null", "-"], capture=True)
    m = re.findall(r"\{[^{}]*\"input_i\"[^{}]*\}", res.stderr, re.S)
    if not m:
        raise PhaseError(f"could not measure loudness of {path}")
    st = json.loads(m[-1])
    return {"lufs": float(st["input_i"]), "true_peak": float(st["input_tp"]), "lra": float(st["input_lra"])}


def run_phase(ctx) -> dict:
    import numpy as np
    import soundfile as sf
    from kokoro_onnx import Kokoro

    cfg = settings()["tts"]
    ln = settings()["loudnorm"]
    respell = load_json(ctx.paths.video / "pronunciations.json", default={})
    k = None
    summary = {}
    for unit, script in selected_units(ctx).items():
        udir = ctx.paths.tts / unit
        udir.mkdir(parents=True, exist_ok=True)
        sr = None
        timing, chunks, t = [], [], 0.0
        lead = cfg["lead_in_s"]
        for i, p in enumerate(script.paragraphs):
            spoken = tts_text(p.text, respell)
            key = hashlib.sha1(json.dumps([spoken, cfg["voice"], cfg["lang"], cfg["speed"], "kokoro-v1.0"]).encode()).hexdigest()[:12]
            wav = udir / f"{p.id}-{key}.wav"
            if not wav.exists():
                if k is None:
                    log("loading Kokoro v1.0")
                    k = Kokoro(str(MODEL_DIR / "kokoro-v1.0.onnx"), str(MODEL_DIR / "voices-v1.0.bin"))
                log(f"tts {unit}/{p.id} ({p.words} words)")
                samples, rate = k.create(spoken, voice=cfg["voice"], speed=cfg["speed"], lang=cfg["lang"])
                sf.write(wav, samples, rate, subtype="PCM_16")
            data, rate = sf.read(wav, dtype="float32")
            sr = sr or rate
            if rate != sr:
                raise PhaseError("sample rate mismatch between paragraphs")
            if i == 0:
                chunks.append(np.zeros(int(lead * sr), dtype="float32"))
                t = lead
            dur = len(data) / sr
            timing.append({"id": p.id, "start": round(t, 3), "end": round(t + dur, 3), "speech": round(dur, 3),
                           "chapter": p.chapter, "file": wav.name})
            chunks.append(data)
            gap = cfg["gap_s"] if i < len(script.paragraphs) - 1 else cfg["tail_s"]
            chunks.append(np.zeros(int(gap * sr), dtype="float32"))
            t += dur + gap
        raw = udir / "raw.wav"
        sf.write(raw, np.concatenate(chunks), sr, subtype="PCM_16")
        # drop stale per-paragraph wavs from earlier script versions
        keep = {x["file"] for x in timing}
        for old in udir.glob("p*-*.wav"):
            if old.name not in keep:
                old.unlink()
        out = ctx.paths.public / f"narration-{unit}.wav"
        stats = _loudnorm(raw, out, ln["I"], ln["TP"], ln["LRA"])
        total = round(t, 3)
        save_json(udir / "timing.json", {"unit": unit, "total": total, "paragraphs": timing, "loudnorm": stats})
        summary[unit] = {"seconds": total, "words": script.words}
        log(f"{unit}: {total:.1f}s, {script.words} words")
    return summary
