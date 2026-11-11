# jamaica-kin (Norman Manley KIN) — full v6 progress

Per Marvin t220u/t221u: one video per international airport. Jamaica's international airports (Airports Authority of Jamaica, fact f2001, read 2026-11-07): Sangster MBJ (Montego Bay), Norman Manley KIN (Kingston), Ian Fleming OCJ (Ocho Rios / Boscobel). Order by passengers: MBJ, KIN, OCJ.

## Stages
- [x] facts (k001-k018: GAP/PACKAL, Airports Authority of Jamaica, Jamaica Tourist Board, GOV.UK; read 2026-11-10)
- [x] script (38 lines, ~745 words, 3 chapters) — /workspace/work/jm-sheets/mkscript_kin.py
- [ ] tts / stt
- [ ] footage (pool/jamaica-kin; licence evidence pool/jamaica-kin/licence)
- [ ] qc / plan / lock
- [ ] release jamaica-kin-ranges + render + fetch

## Log
- 2026-11-10 22:15 EST: KIN landing footage: only real 1080p CC BY source found is 8tevGZVbe88 (Love Charmzworld) window-seat descent + harbour approach (src 285-347 s; burned-in "WELCOME TO NORMAN MANLEY" text from ~348 s excluded). Others are flight sims / 720p / vlogs. Airport curb + Palisadoes road: B8Fo1ZQz8ec (Driving Time). Aerials: kth3xDGlYOo (Port Royal/Palisadoes), 12BhNaqKtPg (St Andrew), 6VvXOLRNFzA (Hellshire, generic sea only). Rejected: ivncWk0Geos (NZ), XFePOXM2FQA (Canada), mcHR2_t06Mk (Devon UK), BM1bq5TVu9g (vlogger faces).
- 2026-11-10 22:27 EST: TTS done (312.12 s, bm_george 1.0 en-gb). STT 31/31 after alias Palisadoes->"Palaisado's". Facts o001-o007 (OCJ) also added. YouTube started bot-checking anonymous metadata requests (~22:20); downloads slowed — no cookies used.
- 2026-11-10 22:50 EST: footage QC + first plan. RESULT: KIN does not have enough licensed footage to pass the gates -> SKIPPED (per Marvin t220u: report and move on). Not rendered.
  - Landing: the only real KIN landing source (8tevGZVbe88, window seat) measures lap_med 11.6-23.6 (gate sharp_lap_min 35) -> source_quality fails; no other 1080p CC BY landing/approach at Norman Manley found (others are flight sims, 720p, or vlogger faces).
  - Coverage: 6 usable source videos from 3 creators; Driving Time alone would be 57 % of footage (cap 30 %); video_uses_max 5 caps the cut at ~30 shots for ~69 needed. Plan: 51 gaps, footage 26 %.
  - Kept for a retry: script/TTS/STT (pass), facts k001-k018, clips + licence evidence, mkfootage_kin.py. Needs: a sharp KIN landing (CC BY / Pexels / Pixabay) and 3+ more Kingston aerial/street sources from other creators.
