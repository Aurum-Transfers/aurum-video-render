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
