"""portrait_no_letterbox_or_blur_pad must catch a real 16:9 blur pad, not a sky + dashboard."""
import subprocess
from pathlib import Path

import numpy as np
import pytest

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import portrait_gate


def _h264(raw: Path, out: Path, w: int, h: int, fps: int = 30):
    subprocess.check_call([
        "ffmpeg", "-loglevel", "error", "-y",
        "-f", "rawvideo", "-pix_fmt", "gray", "-s", f"{w}x{h}", "-r", str(fps),
        "-i", str(raw), "-c:v", "libx264", "-pix_fmt", "yuv420p", str(out),
    ])
    raw.unlink(missing_ok=True)


def test_classic_16x9_blur_pad_fails(tmp_path):
    # The real failure mode: a 16:9 clip fitted to 9:16 with a blurred copy behind it.
    rng = np.random.default_rng(0)
    src_frames = 15
    raw = tmp_path / "src16x9.raw"
    raw.write_bytes(rng.integers(0, 255, size=(1080, 1920), dtype=np.uint8).tobytes() * src_frames)
    src = tmp_path / "src16x9.mp4"
    _h264(raw, src, 1920, 1080)
    out = tmp_path / "blurpad.mp4"
    vf = (
        "scale=1080:1920:force_original_aspect_ratio=decrease,split[s][p];"
        "[p]scale=1080:1920,boxblur=20:10[p];"
        "[s]pad=1080:1920:(ow-iw)/2:(oh-ih)/2[s];"
        "[p][s]overlay=(W-w)/2:(H-h)/2"
    )
    subprocess.check_call([
        "ffmpeg", "-loglevel", "error", "-y", "-i", str(src), "-vf", vf,
        "-c:v", "libx264", "-pix_fmt", "yuv420p", str(out),
    ])
    res = portrait_gate.check_video(out, n=4)
    assert res["pass"] is False, res
    assert all(b.get("blur_pad") for b in res["detail"]["bad"]), res


def test_sky_and_dashboard_is_not_a_blur_pad(tmp_path):
    # Full-bleed 9:16: soft sky, detailed mid, sharp dashboard — one seam, not two strong pad edges.
    H, W = 1920, 1080
    frame = np.zeros((H, W), dtype=np.float32)
    for y in range(int(H * 0.40)):
        frame[y] = 180 - y * 0.04
        frame[y] += 2 * np.sin(np.arange(W) * 0.01)
    rng = np.random.default_rng(2)
    frame[int(H * 0.40): int(H * 0.78)] = rng.integers(50, 200, size=(int(H * 0.78) - int(H * 0.40), W))
    frame[int(H * 0.66): int(H * 0.67)] = 30
    frame[int(H * 0.80):] = 25
    raw = tmp_path / "dash.raw"
    raw.write_bytes(frame.clip(0, 255).astype(np.uint8).tobytes() * 8)
    path = tmp_path / "dashcam.mp4"
    _h264(raw, path, W, H)
    res = portrait_gate.check_video(path, n=4)
    assert res["pass"] is True, res


def test_existing_short1_master_is_full_bleed():
    path = Path("/workspace/work/overnight/jamaica-kin-short-1/out/full/jamaica-kin-short-1-short-1-1080p-master.mp4")
    if not path.exists():
        pytest.skip("short-1 master not on this box")
    res = portrait_gate.check_video(path)
    assert res["pass"] is True, res
