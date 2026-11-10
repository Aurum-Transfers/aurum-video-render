"""Shared helpers: paths, JSON IO, subprocess, ffprobe. No AI anywhere in this package."""
from __future__ import annotations

import datetime as _dt
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
IS_WIN = os.name == "nt"

PHASES = [
    "prereqs",
    "tts",
    "assets",
    "captions",  # before render: Shorts burn captions in
    "render",
    "thumbs",
    "description",
    "checks",
    "upload",
]

SECRET_ENV = ("PEXELS_API_KEY", "PIXABAY_API_KEY", "AURUM_YT_TOKEN")


class PhaseError(RuntimeError):
    """A phase failed; message is safe to print (never contains secrets)."""


@dataclass(frozen=True)
class Paths:
    slug: str

    @property
    def video(self) -> Path:
        return ROOT / "videos" / self.slug

    @property
    def build(self) -> Path:
        return self.video / "build"

    @property
    def out(self) -> Path:
        return self.video / "out"

    @property
    def qa(self) -> Path:
        return self.out / "qa"

    @property
    def public(self) -> Path:
        """Remotion --public-dir for this slug."""
        return self.build / "public"

    @property
    def tts(self) -> Path:
        return self.build / "tts"

    @property
    def assets(self) -> Path:
        return self.public / "assets"

    @property
    def licence_log(self) -> Path:
        return self.video / "licence-log.csv"

    @property
    def state(self) -> Path:
        return self.build / "state.json"

    def ensure(self) -> "Paths":
        for p in (self.build, self.out, self.qa, self.public, self.tts, self.assets):
            p.mkdir(parents=True, exist_ok=True)
        return self


def today() -> str:
    return _dt.date.today().isoformat()


def now_iso() -> str:
    return _dt.datetime.now().replace(microsecond=0).isoformat()


def load_json(path: Path, default=None):
    path = Path(path)
    if not path.exists():
        if default is not None:
            return default
        raise PhaseError(f"missing file: {path.relative_to(ROOT) if path.is_relative_to(ROOT) else path}")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, path)


def settings() -> dict:
    return load_json(ROOT / "config" / "settings.json")


def log(msg: str) -> None:
    print(f"[{_dt.datetime.now():%H:%M:%S}] {msg}", flush=True)


def scrub(text: str) -> str:
    """Remove any secret env values from text before it is printed or saved."""
    for k in SECRET_ENV:
        v = os.environ.get(k)
        if v and len(v) > 3:
            text = text.replace(v, f"<{k}>")
    return text


def tool(name: str) -> str | None:
    """Find an executable, preferring the project venv (yt-dlp lives there)."""
    venv_bin = ROOT / ".venv" / ("Scripts" if IS_WIN else "bin")
    for cand in (venv_bin / (name + (".exe" if IS_WIN else "")), venv_bin / name):
        if cand.exists():
            return str(cand)
    found = shutil.which(name)
    if found:
        return found
    if IS_WIN:
        return shutil.which(name + ".cmd") or shutil.which(name + ".exe")
    return None


def run(cmd: list[str], cwd: Path | None = None, check: bool = True, capture: bool = False,
        timeout: int | None = None) -> subprocess.CompletedProcess:
    exe = cmd[0]
    if IS_WIN and exe in ("npm", "npx"):
        cmd = [exe + ".cmd"] + cmd[1:]
    log("$ " + scrub(" ".join(str(c) for c in cmd)))
    try:
        res = subprocess.run(
            [str(c) for c in cmd], cwd=str(cwd) if cwd else None, check=False,
            capture_output=capture, text=True, encoding="utf-8", errors="replace", timeout=timeout,
        )
    except FileNotFoundError as e:
        raise PhaseError(f"command not found: {exe}") from e
    if check and res.returncode != 0:
        tail = ""
        if capture:
            tail = scrub(((res.stdout or "") + (res.stderr or ""))[-2000:])
        raise PhaseError(f"command failed ({res.returncode}): {exe} {tail}")
    return res


def ffprobe_json(path: Path) -> dict:
    res = run([tool("ffprobe") or "ffprobe", "-v", "error", "-print_format", "json", "-show_format",
               "-show_streams", str(path)], capture=True)
    return json.loads(res.stdout)


def media_duration(path: Path) -> float:
    return float(ffprobe_json(path)["format"]["duration"])


def fmt_ts(seconds: float) -> str:
    """YouTube chapter timestamp: M:SS / MM:SS / H:MM:SS, first must be 00:00."""
    s = int(seconds)
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{sec:02d}"
    return f"{m:02d}:{sec:02d}"


def python_exe() -> str:
    return sys.executable
