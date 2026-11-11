# Jamaica v6 FULL cut — progress log

Template: jobs/aruba-v6-full (approved by Marvin t219u). Voice bm_george 1.0 en-gb (Bali voice), TTS venv /workspace/work/aruba-full-v2/pc-src/.venv.
Range clips + licence-log only: release `jamaica-v6-full-ranges`. Render: render-preview.yml, job=jamaica-v6-full; outputs via 1-day artifact only.
Box download target: /workspace/work/overnight/jamaica-travel-guide/out/full/. No YouTube upload or publication.
Completed-book list (box copy of TITLE_TRACKER.csv, 2026-11-09 21:18 EST; PC offline so live tracker not read): READY = Jamaica, Dominican Republic, Puerto Rico. Bahamas/Mexico in progress; Colombia/Barbados/California deferred.

## Stages
- [ ] 1. Footage: CC BY search (pool/jamaica/cc-search.json), watch-page licence evidence + metadata prefilter (screen.json), storyboard visual screen, shortlist.
- [ ] 2. Range clips cut/downloaded on box (cookie-less yt-dlp), footage.json v6 schema (shows/subject/parent).
- [ ] 3. Script (from 10 Nov draft, Knutsford coach line removed: no public transport), facts from videos/jamaica-travel-guide/facts.json.
- [ ] 4. TTS + STT check.
- [ ] 5. Clip QC + plan: pre-render scorecard PASS, 0 gaps.
- [ ] 6. Upload range clips + licence-log.csv to release.
- [ ] 7. Dispatch render-preview.yml; background watcher downloads artifact.
- [ ] 8. Verify sha256/duration, frame grabs; place 720p + 1080p master in out/full.

## Log
- 2026-11-10 20:26 EST: job created; CC search 35 queries -> 508 hits; pool_screen running.
- 2026-11-10 20:54 EST: stage 3-4 done: script 40 lines/739 words/5 numbered chapters (Knutsford coach line dropped), TTS bm_george 313.3 s, STT 29/29 after aliases (Sankster/Jay Kal/Nagrill). Facts re-verified live today: mbjairport.com taxi-cabs + passenger-services, gov.uk entry-requirements. Footage pool screened (508 hits, 319 prefilter pass); range clips downloading.

## 2026-11-10 21:36 EST — MBJ footage/plan iteration (resumed after interruption)
- t220u: this job = jamaica-mbj (Sangster MBJ). Title/script say MBJ; KIN and OCJ get own jobs.
- t221u: every international airport at every destination gets its own video; airport list per destination from primary sources, logged in that destination's progress file; order by passenger volume.
- Footage: driving/aerial clips split into sub-clips (distinct subjects); slow drone clips play at 2x; landing clips tagged "landing"; Negril clips tagged beach.
- Added sources (CC BY, watch pages in pool/jamaica/licence): Ymw6leiGhXw, onzcja6gqlw, OaDLJ5KtI2Y (Chris Cafiero, Runaway Bay drone), 55-rBgI1MUA (Driving Time, highway). Rejected: jSOlgxRqZWw (static), RKkN8qAstc0 (watermark), 2-g8Rv4v7Eg (faces).
- Chapters merged to 3 (60-120 s gate). Line 7 reworded ("the large majority", fact f068) for STT recall; re-TTS done (312.33 s).
- Plan status before these edits: 9 gaps, failed chapters/landing/cue/narration -> fixes applied, re-plan pending.

## 2026-11-10 ~21:58 EST — plan PASS, EDL locked
- Planner on box: pass, 0 gaps, 70 shots, median 4.42 s, footage 100 %, 3 lifts, 317.3 s. Max creator share Chris Cafiero ~0.20.
- doctors_cave_b dropped (lap 23.5 on its used window).
- New tools/lock_release.py: cuts one short window per used clip (+1.5 s), writes edl-lock.json + release footage.json (planning lib kept in build/footage-plan.json). title_runner plan now re-runs all gates on edl-lock.json (AURUM_REPLAN=1 to re-plan).
- Locked EDL re-QC'd on the windows: all pre-render gates pass.
- Release exposure per source (union of windows / source length): max OTRnEh4qUwE 29/55 s (53 %, a 55-s promo), uZG3PnwB1bY 10/22 s; all others <= 37 %. No full sources.
- 22:02 EST dispatched run 42949975528 (release jamaica-v6-full-ranges, 68 windows + licence-log). Watcher -> /workspace/work/overnight/jamaica-mbj/out/full

## 2026-11-10 23:58 JT: audio-only fix (v2), no re-render
- CI run 42949975528 QA: the only failure was natural_sound_audible. Lifts measured -33.1 / -10.8 / -32.1 dBFS (gate >= -32), and ambient under voice was -6.0 dB (gate window -26..-10).
- Fix: new level-targeted mixer tools/audio_mix.py, which replaces the fixed sidechaincompress in title_runner.mix(). Ambient sits -16 dB under the voice and +6 dB in the breaths, each lift is gained to about -24 dBFS, and the result is checked after two-pass loudnorm.
- Remix: the ambient stem was rebuilt on the box from the CI EDL and the local range clips. Local narration.wav was confirmed identical to the render (envelope r=0.999, lag 0). Audio was remuxed onto the existing video streams (-c:v copy, AAC 192k), run under gate.py heavy.
- Outputs (/workspace/work/overnight/jamaica-mbj/out/full/): jamaica-mbj-v6-full-1080p-master-v2.mp4 and jamaica-mbj-v6-full-review-720p-v2.mp4.
- Local audio gates (checks-audio-v2.json): all pass. Lifts -18.9 / -19.0 / -18.7 dBFS, ambient under voice -15.9 dB, -14.05 LUFS, TP -1.42. Non-audio measurements are carried over from CI checks.json, and the full gate set passes on both files.
- clip_qc cache key now includes the audio flag, so turning audio on forces a tonality measurement.
