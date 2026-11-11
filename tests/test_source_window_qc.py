"""Pre-render source-window QC must match post-render motion/luma aggregation."""
import json
import subprocess
from pathlib import Path

import numpy as np
import pytest

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import spec_gates


def _ffmpeg(*args):
    subprocess.check_call(["ffmpeg", "-loglevel", "error", "-y", *args])


def _gray_clip(path: Path, frames: list[int], w=96, h=54, fps=24):
    """Write a raw gray video with the given per-frame mean luma (constant frame)."""
    raw = path.with_suffix(".raw")
    buf = b"".join(bytes([int(y)]) * (w * h) for y in frames)
    raw.write_bytes(buf)
    _ffmpeg("-f", "rawvideo", "-pix_fmt", "gray", "-s", f"{w}x{h}", "-r", str(fps),
            "-i", str(raw), "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path))
    raw.unlink(missing_ok=True)


def test_per_frame_luma_catches_short_dark_flash(tmp_path):
    # 3 s at 24 fps, mid-gray, with a 4-frame (~0.17 s) black flash in second 1.
    # Per-second mean luma stays well above 60; per-frame min must fail.
    frames = [180] * 72
    for i in range(24, 28):
        frames[i] = 0
    clip = tmp_path / "flash.mp4"
    _gray_clip(clip, frames)
    shot = {"kind": "clip", "file": str(clip), "file_in": 0.0, "play_speed": 1.0, "t0": 0.0, "t1": 3.0, "clip_id": "flash"}
    qc = spec_gates.measure_source_window(shot, root=tmp_path)
    assert qc is not None
    assert qc["y_mean"] > 70, qc
    assert qc["y_min"] < 60, qc  # the flash is the point of this test
    # the old clipqc-style per-second mean would have missed it
    # (second 1 is 20 frames of 180 + 4 of 0 = mean 150)


def test_motion_is_measured_at_output_speed(tmp_path):
    # A white bar sliding across mid-gray; 2x play_speed must raise per-second motion.
    w, h, fps, seconds, bar = 96, 54, 24, 4, 12
    frames = []
    for i in range(fps * seconds):
        fr = np.full((h, w), 64, np.uint8)
        x = min(w - bar, i * 2)
        fr[20:36, x:x + bar] = 220
        frames.append(fr)
    src = tmp_path / "pan.mp4"
    raw = tmp_path / "pan.raw"
    raw.write_bytes(b"".join(f.tobytes() for f in frames))
    _ffmpeg("-f", "rawvideo", "-pix_fmt", "gray", "-s", f"{w}x{h}", "-r", str(fps),
            "-i", str(raw), "-c:v", "libx264", "-pix_fmt", "yuv420p", str(src))
    raw.unlink(missing_ok=True)
    base = {"kind": "clip", "file": str(src), "file_in": 0.0, "t0": 0.0, "clip_id": "pan"}
    qc1 = spec_gates.measure_source_window({**base, "play_speed": 1.0, "t1": 4.0}, root=tmp_path)
    qc2 = spec_gates.measure_source_window({**base, "play_speed": 2.0, "t1": 2.0}, root=tmp_path)
    assert qc1 and qc2, (qc1, qc2)
    assert qc1["mot_med"] > 0 and qc2["mot_med"] > qc1["mot_med"], (qc1, qc2)


def test_source_window_matches_measure_shots_on_a_sped_up_render(tmp_path):
    src = tmp_path / "sea.mp4"
    _ffmpeg("-f", "lavfi", "-i", "testsrc2=s=320x180:r=24:d=6",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(src))
    shot = {"kind": "clip", "file": str(src), "file_in": 0.5, "play_speed": 1.5,
            "t0": 0.0, "t1": 3.0, "clip_id": "sea"}
    qc_src = spec_gates.measure_source_window(shot, root=tmp_path)
    # render the same window the way title_runner.segments does, then measure_shots
    out = tmp_path / "out.mp4"
    _ffmpeg("-ss", "0.500", "-t", f"{3.0 * 1.5:.3f}", "-i", str(src),
            "-an", "-vf", "setpts=(PTS-STARTPTS)/1.5,fps=30,scale=320:180,setsar=1,format=yuv420p",
            "-frames:v", "90", "-c:v", "libx264", "-r", "30", str(out))
    meas = spec_gates.measure_shots(out, {"shots": [shot]})
    qc_out = meas["0.0"]
    assert qc_src is not None and qc_out is not None
    # same aggregation; allow a little encode jitter
    assert abs(qc_src["mot_min"] - qc_out["mot_min"]) < 0.25, (qc_src, qc_out)
    assert abs(qc_src["mot_med"] - qc_out["mot_med"]) < 0.35, (qc_src, qc_out)
    assert abs(qc_src["y_min"] - qc_out["y_min"]) < 5, (qc_src, qc_out)
    assert abs(qc_src["y_mean"] - qc_out["y_mean"]) < 5, (qc_src, qc_out)


def test_apply_source_window_qc_fails_closed_when_file_missing(tmp_path):
    edl = {"shots": [{"kind": "clip", "file": str(tmp_path / "nope.mp4"), "file_in": 0,
                      "play_speed": 1.0, "t0": 0.0, "t1": 2.0, "clip_id": "gone",
                      "qc": {"mot_med": 9, "mot_min": 9, "y_mean": 120, "y_min": 120, "dh": [1]}}]}
    info = spec_gates.apply_source_window_qc(edl, root=tmp_path)
    assert info["missing"]
    assert edl["shots"][0]["qc"]["mot_min"] is None
    assert edl["shots"][0]["qc"]["y_min"] is None
