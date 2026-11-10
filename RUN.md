# Aurum video pipeline — how to run a landscape cut

Scripts only. No AI inside the pipeline. Books, manuscripts, and the book tracker stay read-only. This command never uploads.

## Master command (Aruba improved landscape cut)

From the project root (`C:\Users\MHB53\aurum-videos` on the production PC, or a synced worktree):

```
python pipeline.py aruba-travel-guide --all --no-upload --unit long --output-stem long-v2
```

What this does:

- Renders only the long (landscape 1920×1080) unit.
- Writes `videos/aruba-travel-guide/out/long-v2.mp4`. It does **not** overwrite `out/long.mp4`.
- Requires `videos/aruba-travel-guide/used-sources.json` and a local footage library (see below). Pexels/Pixabay keys and a YouTube upload token are **not** required for this offline path.
- Fails closed if a listed clip file is missing, if real-footage coverage of the program (timeline minus end card) is under 80%, if any clip slot falls back to graphics, or if zero clips are sourced.

A gated box run of the same command must go through:

```
python3 /workspace/ops/scripts/gate.py run --bot aurum-reels --label aruba-full-v2-render -- python pipeline.py aruba-travel-guide --all --no-upload --unit long --output-stem long-v2
```

One heavy job at a time. Do not start an ungated render on the PC as a workaround when the box is blocked.

## Footage library

Set `AURUM_FOOTAGE_LIBRARY` to a folder that contains either:

- full source files named `{YouTube video id}.mp4`, or
- pre-cut muted 1920×1080 segments at `{clip_id}.mp4` or `clips/{clip_id}.mp4` (preferred when copying files that must stay under 100 MiB).

`videos/aruba-travel-guide/used-sources.json` also lists `library_dir_hints`. Prepare the Aruba segments with:

```
python tools/prepare_used_clips.py --slug aruba-travel-guide --library assets/cc-library/aruba-full-v2-sources
```

That script re-reads each source's YouTube watch-page licence the day of use (cookie-less yt-dlp, no login). If a source is no longer labelled Creative Commons Attribution, it is skipped and the later pipeline run must fail closed rather than substitute graphics.

## Phases

`prereqs`, `tts`, `assets`, `captions`, `render`, `thumbs`, `description`, `checks`, `upload` (skipped with `--no-upload`).

Useful flags: `--only <phase>`, `--force`, `--unit`, `--output-stem`, `--stop-after-<phase>`.
