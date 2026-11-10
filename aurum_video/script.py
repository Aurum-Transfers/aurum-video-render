"""Parse script.md / shorts/short-N.md into paragraphs and chapters.

Format:
    # Title                      (one, required)
    ## Chapter title             (starts a chapter; long video)
    Paragraph text...            (blank-line separated; each is one TTS unit)
    <!-- f80047, f80048 -->      (fact ids; stripped from narration)
Lines starting with '>' are production notes and are ignored.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

COMMENT_RE = re.compile(r"<!--(.*?)-->", re.S)
FACT_RE = re.compile(r"\bf\d{5}\b")
MD_RE = re.compile(r"[*_`]")


@dataclass
class Paragraph:
    id: str
    text: str
    chapter: str | None
    facts: list[str] = field(default_factory=list)

    @property
    def words(self) -> int:
        return len(self.text.split())


@dataclass
class Script:
    title: str
    paragraphs: list[Paragraph]

    @property
    def chapters(self) -> list[tuple[str, str]]:
        """[(chapter_title, first_paragraph_id)] in order."""
        seen, out = set(), []
        for p in self.paragraphs:
            if p.chapter and p.chapter not in seen:
                seen.add(p.chapter)
                out.append((p.chapter, p.id))
        return out

    @property
    def words(self) -> int:
        return sum(p.words for p in self.paragraphs)

    def para(self, pid: str) -> Paragraph:
        for p in self.paragraphs:
            if p.id == pid:
                return p
        raise KeyError(pid)


def parse_text(md: str) -> Script:
    title = None
    chapter = None
    paras: list[Paragraph] = []
    buf: list[str] = []
    buf_facts: list[str] = []

    def flush():
        nonlocal buf, buf_facts
        text = " ".join(" ".join(buf).split())
        if text:
            paras.append(Paragraph(id=f"p{len(paras) + 1:02d}", text=MD_RE.sub("", text),
                                   chapter=chapter, facts=list(dict.fromkeys(buf_facts))))
        elif buf_facts and paras:
            paras[-1].facts.extend(f for f in buf_facts if f not in paras[-1].facts)
        buf, buf_facts = [], []

    # pull comments out first so multi-line comments work
    def _comment(m):
        return " " + " ".join(f"@@{f}@@" for f in FACT_RE.findall(m.group(1))) + " "

    md = COMMENT_RE.sub(_comment, md)
    for raw in md.splitlines():
        line = raw.rstrip()
        stripped = line.strip()
        facts_here = re.findall(r"@@(f\d{5})@@", stripped)
        stripped = re.sub(r"@@f\d{5}@@", "", stripped).strip()
        buf_facts.extend(facts_here)
        if stripped.startswith("## "):
            flush()
            chapter = stripped[3:].strip()
        elif stripped.startswith("# "):
            flush()
            title = stripped[2:].strip()
        elif stripped.startswith(">"):
            continue
        elif not stripped:
            if buf:
                flush()
        else:
            buf.append(stripped)
    flush()
    if not title:
        raise ValueError("script has no '# Title' line")
    return Script(title=title, paragraphs=paras)


def parse_file(path: Path) -> Script:
    return parse_text(Path(path).read_text(encoding="utf-8"))


def tts_text(text: str, respell: dict[str, str]) -> str:
    """Apply pronunciation respellings (TTS only; captions keep the real spelling)."""
    for k in sorted(respell, key=len, reverse=True):
        text = re.sub(rf"(?<![\w-]){re.escape(k)}(?![\w-])", respell[k], text)
    return text


def units(video_dir: Path) -> dict[str, Script]:
    """All narration units for a slug: 'long' + 'short-N'."""
    out = {"long": parse_file(video_dir / "script.md")}
    for p in sorted((video_dir / "shorts").glob("short-*.md")):
        out[p.stem] = parse_file(p)
    return out

def selected_units(ctx, video_dir: Path | None = None) -> dict[str, Script]:
    """Return all script units, or only those named in ctx.units when that list is set."""
    all_u = units(video_dir or ctx.paths.video)
    wanted = set(getattr(ctx, "units", None) or [])
    if not wanted:
        return all_u
    return {k: v for k, v in all_u.items() if k in wanted}



PRICE_RE = re.compile(
    r"(\$\s?\d|US\$|USD\s?\d|\d\s?(dollars?|florins?|euros?|pounds?)\b|AWG\s?\d|\bfl\.?\s?\d|€\s?\d|£\s?\d"
    r"|\b(one|two|three|four|five|six|seven|eight|nine|ten|twenty|thirty|forty|fifty|hundred)\s+(dollars?|florins?|euros?)\b)",
    re.I,
)
OPERATOR_RE = re.compile(
    r"\b(our (drivers?|vehicles?|fleet|tours?|shuttles?)|we (operate|drive|run) (the )?(transfers?|tours?|shuttles?)"
    r"|book (directly )?with us)\b",
    re.I,
)
