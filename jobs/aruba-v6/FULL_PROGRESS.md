# Aruba v6 FULL cut — progress log

Job folder: `jobs/aruba-v6-full/` (spec scope=full, output_stem v6-full). Voice bm_george, speed 1.0, en-gb, Oranjestad IPA fix.
Range clips: release `aruba-v6-preview-ranges` (range clips only; never full sources or full renders).
Render: GitHub Actions `render-preview.yml` with `job=aruba-v6-full`; outputs via the 1-day run artifact only.
Box download target: `/workspace/work/overnight/aruba-travel-guide/out/v6full/`. No YouTube upload.

## Stages
- [x] 1. Script (37 lines, 4 numbered chapters, 4 spoken prompts), kept preview-2 rewrites (line 4 airport welcome, line 8 "From the air..."). Facts cite aruba.com / airportaruba.com / gov.uk (videos/aruba-travel-guide/facts.json).
- [x] 2. TTS narration + STT check (build/narration.wav, timing.json, stt-check.json) on box TTS venv.
- [x] 3. Clip QC + EDL plan: pre-render scorecard PASS, 0 failed (319.88 s, 70 shots, median 4.5 s, map 6.5%, footage 100%).
- [ ] 4. Upload 2 missing range clips + full licence-log.csv to release.
- [ ] 5. CI export: qa writes 720p review alias + 1080p master into artifact-matched paths.
- [ ] 6. Dispatch render on GitHub Actions.
- [ ] 7. Download artifact to box, verify sha256/duration, review frames.

## Log
- 2026-11-10 18:30 EST: stages 1-3 found complete on box from previous worker (uncommitted); committing now.
