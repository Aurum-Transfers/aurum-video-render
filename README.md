# aurum-video-render

Private Aurum Reels render pipeline. **Footage is never stored in git.** Runners download only the planned YouTube CC BY ranges at job time, then upload outputs as **private** Actions artifacts.

This repository is for the Aurum Transfers vertical only. It is private and must stay private.

## What is in git

- Pipeline code (Python + Remotion source, no `node_modules`)
- Plans, scripts, licence log and watch-page licence evidence (metadata only)
- Aruba v6 preview narration (`jobs/aruba-v6/build/`, WAV/FLAC only)

## What is never in git

- Video footage, renders, or storyboard images
- Secrets, cookies, YouTube account credentials, or upload tokens
- `AURUM_YT_TOKEN`, Pexels, or Pixabay keys

## YouTube publish

**Do not upload or publish to YouTube from this repo or its workflows.** Do not set `AURUM_YT_TOKEN` in Actions secrets. Local and CI renders stay off YouTube until Marvin approves a separate, manual publish step.

## Actions minutes (no spend)

GitHub Free includes a monthly allowance of Actions minutes for private repos (2,000 minutes on the standard plan, subject to GitHub's current billing). The workflows in this repo are **`workflow_dispatch` only** so a push does not start a run.

Confirm remaining included minutes before dispatching a job. Do not run a job that would exceed the included allowance or incur charges.

## Workflows

Workflow YAML lives in `ci/workflows/` until a GitHub token with the `workflow` scope can copy it to `.github/workflows/`. The box `gh` token currently has only the `repo` scope, which can create the private repo and push code, but GitHub will reject a push that adds or updates workflow files.

To install the workflows (one-time, on a machine logged in as Aurum-Transfers):

```
gh auth refresh -h github.com -s workflow,user
mkdir -p .github/workflows
cp ci/workflows/*.yml .github/workflows/
git add .github/workflows && git commit -m "Install Actions workflows" && git push
```

The `user` scope is also needed to read remaining Actions minutes via the billing API. Do not dispatch a job until that number is confirmed and the run fits in the included allowance.

### `smoke-download`

Downloads a single 20-second 1080p range with cookie-less yt-dlp. Use this first. YouTube often bot-blocks datacenter IPs; the job classifies that clearly and does not use cookies or account credentials.

```
gh workflow run smoke-download.yml -R Aurum-Transfers/aurum-video-render
```

Default clip: `sbcjtH8dehc` (Baby Beach, Aruba, CC BY, 1080p) from 0s to 20s.

### `render-preview`

Aruba v6 720p preview (hook + arrival, about 60–90 s). Only dispatch after a successful smoke test **and** a confirmed minutes budget. Fails fast if the shot list (`jobs/aruba-v6/footage.json`) has no clips.

## Fallback if runners cannot download

If the smoke job is bot-blocked, do not add cookies or credentials to the runner. Download the planned ranges in small batches on the Aurum box (or another non-datacenter IP), then attach them as **private** GitHub Release assets or a private cache the render job can fetch, still without putting footage in git.
