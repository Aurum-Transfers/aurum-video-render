#!/usr/bin/env python
"""Aurum faceless travel-video pipeline.

    python pipeline.py <slug> --all --no-upload --unit long --output-stem long-v2

Master command for an offline landscape guide that does NOT overwrite out/long.mp4.
Requires videos/<slug>/used-sources.json with explicit clips. Missing stock/YouTube
upload credentials do not block this offline path. Phases: prereqs, tts, assets,
captions, render, thumbs, description, checks, upload (skipped with --no-upload).
Scripts only: no AI inside.
"""
from __future__ import annotations

import argparse
import importlib
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from aurum_video.common import PHASES, ROOT, Paths, PhaseError, load_json, log, now_iso, save_json, scrub  # noqa: E402


@dataclass
class Ctx:
    slug: str
    paths: Paths
    no_upload: bool = False
    force: bool = False
    units: list[str] = field(default_factory=list)
    output_stem: str | None = None


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="pipeline.py", description=__doc__.split("\n\n")[0])
    p.add_argument("slug")
    p.add_argument("--all", action="store_true", help="run every phase in order")
    p.add_argument("--only", choices=PHASES, help="run a single phase")
    p.add_argument("--no-upload", action="store_true", help="never upload (upload phase is skipped)")
    p.add_argument("--force", action="store_true", help="re-render even if inputs are unchanged")
    p.add_argument("--unit", action="append", default=[], help="limit render/checks to unit(s): long, short-1 ...")
    p.add_argument("--output-stem", default=None,
                   help="filename stem for the long output (default long). Use long-v2 to leave out/long.mp4 intact.")
    for ph in PHASES:
        p.add_argument(f"--stop-after-{ph}", action="store_true", dest=f"stop_after_{ph}",
                       help=f"stop after the {ph} phase")
    p.add_argument("--_phases", help=argparse.SUPPRESS)
    return p


def select_phases(args) -> list[str]:
    if args._phases:
        return [x for x in args._phases.split(",") if x]
    if args.only:
        return [args.only]
    if not args.all:
        raise SystemExit("choose --all or --only <phase>")
    out = []
    for ph in PHASES:
        out.append(ph)
        if getattr(args, f"stop_after_{ph}"):
            break
    return out


def _in_venv() -> bool:
    from aurum_video.prereqs import in_venv

    return in_venv()


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    phases = select_phases(args)
    paths = Paths(args.slug)
    if not paths.video.exists():
        log(f"no such video folder: videos/{args.slug}")
        return 2
    paths.ensure()
    ctx = Ctx(slug=args.slug, paths=paths, no_upload=args.no_upload, force=args.force,
              units=args.unit, output_stem=args.output_stem)

    # Phases after prereqs need the project venv (kokoro-onnx, soundfile, requests, Pillow).
    from aurum_video.prereqs import venv_python

    if not _in_venv() and os.environ.get("AURUM_NO_VENV") != "1":
        rest = list(phases)
        if rest and rest[0] == "prereqs":
            if not run_phases(ctx, ["prereqs"]):
                return 1
            rest = rest[1:]
        if not rest:
            return 0
        if not venv_python().exists():
            log("no .venv yet: run the prereqs phase first")
            return 1
        cmd = [str(venv_python()), str(ROOT / "pipeline.py"), args.slug, f"--_phases={','.join(rest)}"]
        cmd += ["--no-upload"] if args.no_upload else []
        cmd += ["--force"] if args.force else []
        if args.output_stem:
            cmd += ["--output-stem", args.output_stem]
        for u in args.unit:
            cmd += ["--unit", u]
        return subprocess.call(cmd)
    return 0 if run_phases(ctx, phases) else 1


def run_phases(ctx: Ctx, phases: list[str]) -> bool:
    state = load_json(ctx.paths.state, default={"phases": {}})
    for ph in phases:
        mod = importlib.import_module(f"aurum_video.{ph}")
        log(f"=== {ph} ===")
        t0 = time.time()
        try:
            result = mod.run_phase(ctx)
            status = "skipped" if isinstance(result, dict) and "skipped" in result else "pass"
            state["phases"][ph] = {"status": status, "at": now_iso(), "seconds": round(time.time() - t0, 1),
                                   "result": result}
            save_json(ctx.paths.state, state)
            log(f"{ph}: {status} ({time.time() - t0:.0f}s)")
        except PhaseError as e:
            msg = scrub(str(e))
            state["phases"][ph] = {"status": "fail", "at": now_iso(), "error": msg}
            save_json(ctx.paths.state, state)
            log(f"{ph}: FAIL - {msg}")
            return False
    return True


if __name__ == "__main__":
    sys.exit(main())
