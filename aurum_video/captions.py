"""captions: SRT from script paragraphs + per-paragraph wav durations.

Each paragraph's speech window is split into short cues (sentence, then <= max_chars),
with time shared out in proportion to characters.
"""
from __future__ import annotations

import re

from .common import load_json, save_json, settings
from .script import selected_units, units

SENT_RE = re.compile(r"(?<=[.!?;:])\s+")


def chunk_text(text: str, max_chars: int) -> list[str]:
    out: list[str] = []
    for sent in SENT_RE.split(text.strip()):
        words, cur = sent.split(), ""
        for w in words:
            if cur and len(cur) + 1 + len(w) > max_chars:
                out.append(cur)
                cur = w
            else:
                cur = f"{cur} {w}".strip()
        if cur:
            out.append(cur)
    # merge a dangling one/two-word tail into the previous cue when it fits
    merged: list[str] = []
    for c in out:
        if merged and len(c.split()) <= 2 and len(merged[-1]) + 1 + len(c) <= max_chars + 12:
            merged[-1] = f"{merged[-1]} {c}"
        else:
            merged.append(c)
    return merged


def build_cues(paragraphs, timing: list[dict], max_chars: int) -> list[dict]:
    tmap = {t["id"]: t for t in timing}
    cues = []
    for p in paragraphs:
        t = tmap[p.id]
        parts = chunk_text(p.text, max_chars)
        total_chars = sum(len(x) for x in parts) or 1
        cur = t["start"]
        span = t["end"] - t["start"]
        for x in parts:
            d = span * len(x) / total_chars
            cues.append({"start": round(cur, 3), "end": round(cur + d, 3), "text": x})
            cur += d
    return cues


def srt_time(s: float) -> str:
    ms = int(round(s * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    sec, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{sec:02d},{ms:03d}"


def to_srt(cues: list[dict], line_len: int = 42) -> str:
    blocks = []
    for i, c in enumerate(cues, 1):
        text = c["text"]
        if len(text) > line_len:  # split into two balanced lines
            words = text.split()
            best = min(range(1, len(words)), key=lambda k: abs(len(" ".join(words[:k])) - len(" ".join(words[k:]))))
            text = " ".join(words[:best]) + "\n" + " ".join(words[best:])
        blocks.append(f"{i}\n{srt_time(c['start'])} --> {srt_time(c['end'])}\n{text}\n")
    return "\n".join(blocks)


def parse_srt(text: str) -> list[dict]:
    cues = []
    for block in re.split(r"\n\s*\n", text.strip()):
        lines = block.strip().splitlines()
        if len(lines) < 3 or "-->" not in lines[1]:
            continue
        a, b = [x.strip() for x in lines[1].split("-->")]

        def sec(ts):
            h, m, rest = ts.split(":")
            s, ms = rest.split(",")
            return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000

        cues.append({"start": sec(a), "end": sec(b), "text": " ".join(lines[2:])})
    return cues


def run_phase(ctx) -> dict:
    cfg = settings()["captions"]
    summary = {}
    for unit, script in selected_units(ctx).items():
        timing = load_json(ctx.paths.tts / unit / "timing.json")
        max_chars = cfg["short_max_chars"] if unit.startswith("short") else cfg["long_max_chars"]
        cues = build_cues(script.paragraphs, timing["paragraphs"], max_chars)
        (ctx.paths.out / f"{unit}.srt").write_text(to_srt(cues), encoding="utf-8")
        save_json(ctx.paths.build / f"cues-{unit}.json", cues)
        summary[unit] = len(cues)
    return summary
