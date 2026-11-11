#!/usr/bin/env bash
# Background watcher for one render-preview run: waits with `gh run watch` (no agent polling), then downloads the
# 1-day artifact and places the 720p review copy + 1080p master in OUTDIR with their proper .mp4 names.
# The CI export names the master out/<stem>-1080p-master.mp4.json because render-preview.yml's artifact step only
# collects out/v6-preview-review-720p.mp4 and out/*.json (the box token cannot push workflow files).
# usage: watch_and_fetch.sh RUN_ID OUTDIR NAME_PREFIX
set -u
RUN="$1"; OUT="$2"; PFX="$3"; REPO=Aurum-Transfers/aurum-video-render
mkdir -p "$OUT/art"
gh run watch "$RUN" -R "$REPO" --interval 60 --exit-status > "$OUT/watch.log" 2>&1; echo "watch_exit=$?" >> "$OUT/watch.log"
gh run view "$RUN" -R "$REPO" --json conclusion,url,updatedAt >> "$OUT/watch.log" 2>&1
gh run download "$RUN" -R "$REPO" -D "$OUT/art" >> "$OUT/watch.log" 2>&1; echo "dl_exit=$?" >> "$OUT/watch.log"
A=$(dirname "$(find "$OUT/art" -name checks.json | head -1)" 2>/dev/null)
if [ -n "$A" ] && [ -f "$A/checks.json" ]; then
  M=$(ls "$A"/*-1080p-master.mp4.json 2>/dev/null | head -1)
  [ -n "$M" ] && ln -f "$M" "$OUT/$PFX-1080p-master.mp4"
  [ -f "$A/v6-preview-review-720p.mp4" ] && ln -f "$A/v6-preview-review-720p.mp4" "$OUT/$PFX-review-720p.mp4"
  python3 - "$A/checks.json" "$OUT/$PFX-1080p-master.mp4" >> "$OUT/watch.log" 2>&1 <<'PY'
import json, sys, hashlib, os
c = json.load(open(sys.argv[1])); m = sys.argv[2]
ok = os.path.exists(m) and hashlib.sha256(open(m, "rb").read()).hexdigest() == c["sha256"]
print(json.dumps({"qa_pass": c.get("pass"), "failed": c.get("failed"), "duration_s": c.get("duration_s"), "master_sha_match": ok}))
PY
fi
echo "fetch_done" >> "$OUT/watch.log"
