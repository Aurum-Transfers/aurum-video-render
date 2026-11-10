"""prereqs: check/install toolchain, download Kokoro models, report env vars and RAM."""
from __future__ import annotations

import ctypes
import os
import re
import subprocess
import sys
import venv
from pathlib import Path

from .common import IS_WIN, ROOT, PhaseError, log, run, save_json, tool

MODEL_DIR = ROOT / "tools" / "tts" / "models"
MODEL_BASE = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/"
MODELS = {  # name -> minimum plausible size in bytes (guards against HTML error pages)
    "kokoro-v1.0.onnx": 200_000_000,
    "voices-v1.0.bin": 20_000_000,
}
VENV = ROOT / ".venv"
ENV_NEEDS = {
    "PEXELS_API_KEY": ["assets"],
    "PIXABAY_API_KEY": ["assets"],
    "AURUM_YT_TOKEN": ["upload"],
}


def venv_python() -> Path:
    return VENV / ("Scripts/python.exe" if IS_WIN else "bin/python")


def in_venv() -> bool:
    try:
        return Path(sys.prefix).resolve() == VENV.resolve()
    except OSError:
        return False


def free_ram_gb() -> float | None:
    try:
        if IS_WIN:
            class MEMSTAT(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("sullAvailExtendedVirtual", ctypes.c_ulonglong)]
            st = MEMSTAT()
            st.dwLength = ctypes.sizeof(MEMSTAT)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st))
            return st.ullAvailPhys / 2**30
        with open("/proc/meminfo") as f:
            info = dict(line.split(":", 1) for line in f)
        return int(info["MemAvailable"].strip().split()[0]) / 2**20
    except Exception:
        return None


def _version(cmd: list[str]) -> str | None:
    exe = tool(cmd[0])
    if not exe:
        return None
    try:
        res = subprocess.run([exe] + cmd[1:], capture_output=True, text=True, timeout=60)
        return (res.stdout or res.stderr).strip().splitlines()[0] if (res.stdout or res.stderr) else None
    except Exception:
        return None


def ensure_venv(report: dict) -> None:
    if not venv_python().exists():
        log("creating .venv")
        venv.EnvBuilder(with_pip=True).create(VENV)
        report["installed"].append(".venv")
    req = ROOT / "requirements.txt"
    probe = subprocess.run([str(venv_python()), "-c",
                            "import importlib.metadata as m; print(m.version('kokoro-onnx'));"
                            "import soundfile, requests, PIL, yt_dlp, pytest"],
                           capture_output=True, text=True)
    if probe.returncode != 0 or probe.stdout.strip() != "0.6.1":
        log("installing Python requirements into .venv")
        run([str(venv_python()), "-m", "pip", "install", "-q", "-r", str(req)])
        report["installed"].append("python requirements (kokoro-onnx 0.6.1, soundfile, yt-dlp, ...)")


def ensure_models(report: dict) -> None:
    import urllib.request

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    for name, min_size in MODELS.items():
        dest = MODEL_DIR / name
        if dest.exists() and dest.stat().st_size >= min_size:
            continue
        log(f"downloading {name} from the kokoro-onnx GitHub release")
        tmp = dest.with_suffix(dest.suffix + ".part")
        with urllib.request.urlopen(MODEL_BASE + name, timeout=120) as r, open(tmp, "wb") as f:
            while chunk := r.read(1 << 20):
                f.write(chunk)
        if tmp.stat().st_size < min_size:
            tmp.unlink()
            raise PhaseError(f"{name}: download too small; check network")
        os.replace(tmp, dest)
        report["installed"].append(f"model {name}")


def ensure_remotion(report: dict) -> None:
    rdir = ROOT / "remotion"
    if not (rdir / "node_modules" / "remotion").exists():
        log("installing Remotion (npm ci)")
        run(["npm", "ci" if (rdir / "package-lock.json").exists() else "install", "--no-audit", "--no-fund"], cwd=rdir)
        report["installed"].append("remotion node_modules")
    res = run(["npx", "remotion", "versions"], cwd=rdir, capture=True, check=False)
    report["tools"]["remotion"] = "ok" if res.returncode == 0 else "error"
    m = re.search(r"remotion\D+(4\.\d+\.\d+)", res.stdout or "")
    if m:
        report["tools"]["remotion"] = m.group(1)


def run_phase(ctx) -> dict:
    report = {"tools": {}, "installed": [], "missing": [], "env": {}, "warnings": []}
    py = sys.version_info
    report["tools"]["python"] = f"{py.major}.{py.minor}.{py.micro}"
    if py < (3, 10):
        raise PhaseError("Python 3.10+ required")

    node = _version(["node", "--version"])
    report["tools"]["node"] = node
    if not node or int(node.lstrip("v").split(".")[0]) < 18:
        report["missing"].append("node>=18")
    for t in ("ffmpeg", "ffprobe"):
        v = _version([t, "-version"])
        report["tools"][t] = v.split(" Copyright")[0] if v else None
        if not v:
            report["missing"].append(t)

    ensure_venv(report)
    report["tools"]["yt-dlp"] = _version(["yt-dlp", "--version"])
    if not report["tools"]["yt-dlp"]:
        report["missing"].append("yt-dlp")
    ensure_models(report)
    if "node>=18" not in report["missing"]:
        ensure_remotion(report)

    for k, phases in ENV_NEEDS.items():
        present = bool(os.environ.get(k))
        report["env"][k] = "set" if present else f"MISSING (needed by: {', '.join(phases)})"
    token = os.environ.get("AURUM_YT_TOKEN")
    if token and not Path(token).exists():
        report["env"]["AURUM_YT_TOKEN"] = "set, but file not found"

    ram = free_ram_gb()
    report["free_ram_gb"] = round(ram, 2) if ram is not None else None
    if ram is not None and ram < 8:
        report["warnings"].append(f"free RAM {ram:.1f} GB < 8 GB (render drops to concurrency 1 below 4 GB)")

    save_json(ctx.paths.build / "prereqs.json", report)
    for k, v in report["env"].items():
        log(f"env {k}: {v}")
    for w in report["warnings"]:
        log("WARN " + w)
    if report["missing"]:
        raise PhaseError("missing prerequisites: " + ", ".join(report["missing"]))
    return report
