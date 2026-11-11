#!/usr/bin/env python3
"""One-command, resumable destination-video orchestrator (Marvin t229u: script everything a script can do).

    python3 tools/make_destination.py <job> [--dry-run] [--from STAGE] [--only STAGE] [--watch] [--delete-card ID]

<job> is a folder under jobs/. Stages run in order; each one is skipped when its outputs are already valid, and the
state file records every result, so a re-run after an interruption resumes at the first unfinished stage.

  inputs   facts.json pulled from the facts database (facts_pull.py: book exports, earlier video facts, partner DB; spec
           "facts_db"); script.json lines are the ONLY AI-written input (+ research for listed DB gaps); lint
  footage  [no ranges.json] YouTube Data API CC search (+cc_search.py fallback), Pexels/Pixabay API, pool_screen.py
           licence + 1080p prefilter, storyboard sheets -> STOP for the visual pick (ranges.json)
           [ranges.json] footage_from_ranges.py (cookie-less yt-dlp) -> clip_qc.py (sharpness, motion, luma, music
           tonality) -> clip_autoqc.py (watermark / face / text heuristics)
  tts      title_runner tts + stt (Kokoro bm_george 1.0 en-gb, Bali voice); STT name + completeness check
  plan     title_runner plan -> lock_release.py -> plan again on the locked EDL (all pre-render gates) + contact sheet
  render   commit job inputs (no footage) -> release <job>-ranges (range windows + licence-log only) -> dispatch
           render-preview.yml -> tools/ci/watch_and_fetch.sh (download artifact, verify master sha256 vs checks.json)
  shorts   3 true 9:16 Shorts from script.json "shorts" (AI writes their lines): one jobs/<job>-short-<k>/ each, sharing
           the long's release windows (hard links, no new downloads); tts+stt -> plan -> portrait_reframe.py (crop + pan
           on the subject) -> locked EDL -> gates incl. portrait_shots_reframed -> GH render of the Remotion 1080x1920
           "Short" path -> portrait_no_letterbox_or_blur_pad gate on the output (CI qa). One render at a time.
  package  package_video.py: video.json in the live Bali layout, SRT, thumbnail, partner landing check
  handoff  READY_TO_PUBLISH.json + publish-queue.jsonl line for the publishing worker (this tool never uploads)
  archive  after the publishing worker's result.json is ok: stage master/project/licences for D: (arch_stage.py),
           write the PC copy plan; once arch_assemble.ps1's result shows every file sha256-verified, delete box working
           copies only with --delete-card <card> and gate.py db-delete exit 0

Exit codes: 0 finished (or dry run ok), 3 NEEDS_AI (facts/script), 4 NEEDS_REVIEW (human/visual judgement),
5 WAITING (render running, publishing or PC archive copy pending, or the heavy slot busy), 1 FAILED.
Heavy ffmpeg/TTS work runs through `gate.py run --kind heavy`; a refusal (exit 2) stops with WAITING, never retried
around. Never prints secrets; never pkill/killall; books are not touched.

--dry-run: no git, release, dispatch, download, upload, heavy job or delete. State and any package files go to
/workspace/work/pipeline-dryrun/<job>/; nothing is written into the job folder. Light read-only checks (gates on the
locked EDL, sha256 of an existing master, package build into the scratch dir) still run so the chain is proven.
"""
from __future__ import annotations

import argparse, csv, glob, hashlib, json, os, re, shutil, subprocess, sys, time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent; ROOT = HERE.parent
GATE = "/workspace/ops/scripts/gate.py"; BOT = "aurum-reels"
REPO = "Aurum-Transfers/aurum-video-render"
TTS_PY = "/workspace/work/aruba-full-v2/pc-src/.venv/bin/python"
HANDOFF = Path("/workspace/handoff/aurum-youtube")
STAGES = ["inputs", "footage", "tts", "plan", "render", "shorts", "package", "handoff", "archive"]
OK, FAILED, NEEDS_AI, NEEDS_REVIEW, WAITING = 0, 1, 3, 4, 5
NAMES = {0: "OK", 1: "FAILED", 3: "NEEDS_AI", 4: "NEEDS_REVIEW", 5: "WAITING"}


class Stop(Exception):
    def __init__(self, code, msg, **kw):
        super().__init__(msg); self.code, self.msg, self.kw = code, msg, kw


def now():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def lj(p, d=None):
    p = Path(p)
    return json.loads(p.read_text()) if p.exists() else d


def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def run(cmd, check=False, env=None, cwd=ROOT):
    r = subprocess.run([str(c) for c in cmd], capture_output=True, text=True, cwd=cwd, env={**os.environ, **(env or {})})
    if check and r.returncode:
        raise Stop(FAILED, f"command failed ({r.returncode}): {' '.join(map(str, cmd))[:200]}", stderr=(r.stderr or r.stdout)[-800:])
    return r


class Job:
    def __init__(self, name, dry):
        self.name, self.dry = name, dry
        self.wd = ROOT / "jobs" / name
        if not self.wd.is_dir():
            raise SystemExit(f"no such job folder: {self.wd}")
        self.scratch = Path("/workspace/work/pipeline-dryrun") / name
        self.state_p = (self.scratch if dry else self.wd) / "pipeline-state.json"
        self.state = lj(self.state_p, {"job": name, "stages": {}})
        self.spec = lj(self.wd / "spec.json", {})
        self.slug = self.spec.get("slug", name)
        self.stem = self.spec.get("output_stem", "long")
        self.outdir = Path(f"/workspace/work/overnight/{self.slug}/out/full")
        self.vdir = (self.scratch / "package") if dry else HANDOFF / "videos" / self.slug

    # ------------------------------------------------------------------ helpers
    def save(self):
        self.state_p.parent.mkdir(parents=True, exist_ok=True)
        self.state["updated"] = now()
        self.state_p.write_text(json.dumps(self.state, indent=1, ensure_ascii=False))

    def note(self, stage, **kw):
        st = self.state["stages"].setdefault(stage, {}); st.update(kw); st["at"] = now(); self.save()

    def heavy(self, label, cmd, env=None):
        """gate.py run --kind heavy; exit 2 = refused (slot busy / memory) -> WAITING, command never ran."""
        if self.dry:
            return {"dry_run": True, "would_run": "gate.py run --kind heavy -- " + " ".join(map(str, cmd))[:300]}
        r = run(["python3", GATE, "run", "--bot", BOT, "--kind", "heavy", "--label", f"{self.name} {label}", "--", *cmd], env=env)
        if r.returncode == 2 and "GATE BLOCKED" in (r.stderr or ""):
            raise Stop(WAITING, f"heavy slot refused for '{label}'; re-run later", gate=r.stderr.strip()[-300:])
        if r.returncode:
            raise Stop(FAILED, f"{label} failed (exit {r.returncode})", stderr=(r.stderr or r.stdout)[-1200:])
        return {"stdout_tail": r.stdout.strip()[-600:]}

    def facts_path(self):
        for p in ((self.scratch / "facts.json") if self.dry else self.wd / "facts.json", self.wd / "facts.json", ROOT / self.spec.get("facts", "__none__")):
            if p.is_file():
                return p
        return None

    def lock(self):
        return lj(self.wd / "edl-lock.json")

    # ------------------------------------------------------------------ 1 inputs
    def pull_facts(self):
        """facts.json from the facts database (book exports, earlier video facts, partner DB) via facts_pull.py.
        Needs spec "facts_db": {"dest": "jamaica", "iata": "KIN", "airport": "Norman Manley", "place": "Kingston"}."""
        db = self.spec.get("facts_db")
        if not db:
            return None
        out = (self.scratch if self.dry else self.wd) / "facts.json"
        r = run(["python3", HERE / "facts_pull.py", db["dest"], "--iata", db["iata"], "--airport", db["airport"], "--place", db.get("place", ""),
                 "--out", out, "--cited", self.wd / "script.json"]
                + (["--include", ROOT / self.spec["facts"]] if (ROOT / self.spec.get("facts", "__none__")).is_file() else []))
        if r.returncode == 2:
            raise Stop(NEEDS_REVIEW, f"no fact database for {db['dest']} on the box: CopyToBox the book's export/place.json from the PC "
                                     f"(C:\\Users\\MHB53\\gb-{db['dest']}\\books\\{db['dest']}\\export\\place.json) into "
                                     f"/workspace/aurum-guidebooks/books/{db['dest']}/export/")
        if r.returncode:
            raise Stop(FAILED, "facts_pull failed", stderr=r.stderr[-400:])
        return out

    def s_inputs(self):
        pulled = self.pull_facts()
        sc = lj(self.wd / "script.json"); fp = pulled or self.facts_path()
        gaps = ((lj(fp, {}) or {}).get("_meta") or {}).get("gaps_for_ai_research", []) if fp else []
        if fp and not (sc and sc.get("lines")):
            raise Stop(NEEDS_AI, f"facts pulled from the database ({fp}); write script.json lines citing those fact ids"
                                 + (f"; research only these gaps: {gaps}" if gaps else ""))
        miss = [n for n, ok in (("script.json", sc and sc.get("lines")), ("facts.json", fp)) if not ok]
        if miss:
            raise Stop(NEEDS_AI, f"missing AI inputs: {', '.join(miss)} (research facts from primary sources; write script.json to the v6 template)")
        if not self.spec:
            raise Stop(NEEDS_AI, "spec.json missing: copy jobs/aruba-v6-full/spec.json and set slug/place/place_names/map/facts")
        bad = []
        for i, ln in enumerate(sc["lines"]):
            t = ln["text"]
            if re.search(r"\b(we|our)\s+(operate|drive|drivers|cars|fleet|vans)\b|aurum (operates|drives)", t, re.I):
                bad.append((i, "operator claim"))
            if re.search(r"[$€£]\s?\d|\b\d+\s?(usd|dollars|euros)\b", t, re.I):
                bad.append((i, "fixed price"))
            fx = lj(fp, {}) or {}
            for f in ln.get("facts") or []:
                if isinstance(fx, dict) and f not in fx:
                    bad.append((i, f"fact id {f} not in facts.json"))
        if bad:
            raise Stop(NEEDS_AI, "script lint failed (rewrite these lines)", lines=bad)
        words = sum(len(l["text"].split()) for l in sc["lines"])
        return {"lines": len(sc["lines"]), "words": words, "facts": str(fp), "facts_from_db": bool(pulled), "gaps_for_ai": gaps,
                "package_fields": sorted((sc.get("package") or {}).keys())}

    # ------------------------------------------------------------------ 2 footage
    def queries(self):
        sc = lj(self.wd / "script.json"); place = self.spec.get("place", self.slug).split(",")[0]
        tags = []
        for ln in sc["lines"]:
            for t in (ln.get("need") or []) + (ln.get("tags") or []):
                if t not in tags:
                    tags.append(t)
        base = [f"{place} 4k", f"{place} drone 4k", f"{place} airport", f"landing {place}", f"{place} beach 4k", f"{place} driving 4k"]
        return base + [f"{place} {t.replace('-', ' ')}" for t in tags[:20]]

    def s_footage(self):
        lib = lj(self.wd / "footage.json", {}) or {}
        clips = lib.get("clips") or []
        if clips:
            spec_gates = self._sg()
            spec_gates.resolve_clip_files(lib, self.wd)
            missing = [c["file"] for c in clips if not Path(c["file"]).exists() and not (ROOT / c["file"]).exists()]
            if missing and not self.lock():
                raise Stop(FAILED, f"{len(missing)} clip files missing", files=missing[:10])
            qc = lj(self.wd / "build/clipqc.json", {}) or {}
            unq = [c["id"] for c in clips if c["id"] not in qc and c.get("parent") not in qc]
            info = {"clips": len(clips), "files_missing": len(missing), "clipqc_missing": len(unq)}
            if unq or missing:
                if self.dry:
                    return {**info, "dry_run": True, "would_run": "clip_qc.py (gated)"}
                info["clip_qc"] = self.heavy("clip_qc", ["python3", HERE / "clip_qc.py", f"jobs/{self.name}"])
            out = (self.scratch if self.dry else self.wd / "build") / "autoqc.json"
            r = self.heavy("clip_autoqc", ["python3", HERE / "clip_autoqc.py", f"jobs/{self.name}", out]) if not self.dry else None
            if self.dry:
                info["autoqc"] = {"dry_run": True, "would_run": f"clip_autoqc.py jobs/{self.name} {out}"}
                return info
            aq = lj(out, {})
            if aq.get("flagged_unacked"):
                raise Stop(NEEDS_REVIEW, "auto QC flagged clips (watermark/face/text): look at them, then drop the range or add its id to "
                                         "ranges.json autoqc_ack", flagged=aq["flagged_unacked"])
            return info
        if (self.wd / "ranges.json").exists():
            if self.dry:
                return {"dry_run": True, "would_run": "footage_from_ranges.py, clip_qc.py, clip_autoqc.py"}
            r = run(["python3", HERE / "footage_from_ranges.py", f"jobs/{self.name}"])
            if r.returncode:
                raise Stop(FAILED, "range download/footage.json build failed", out=(r.stdout + r.stderr)[-800:])
            return self.s_footage()
        # search -> screen -> sheets -> stop for the visual pick
        pool = ROOT / "pool" / self.spec.get("pool", self.slug.split("-")[0])
        place_re = self.spec.get("place_regex") or "|".join(re.escape(n) for n in [self.spec.get("place", "").split(",")[0]] + self.spec.get("place_names", [])[:6])
        qs = self.queries()
        if self.dry:
            return {"dry_run": True, "pool": str(pool), "queries": qs, "would_run": ["yt_api_search.py", "stock_search.py", "pool_screen.py", "sb_sheet.py"]}
        r = run(["python3", HERE / "yt_api_search.py", pool, *qs])
        if r.returncode == 2:  # no API key: public CC-filtered results page, cookie-less
            run(["python3", HERE / "cc_search.py", pool / "cc-search.json", *qs])
        run(["python3", HERE / "stock_search.py", pool, "--place", place_re, "--download", *qs])
        run(["python3", HERE / "pool_screen.py", pool, "--place", place_re], check=True)
        scr = lj(pool / "screen.json", [])
        ok = [x["id"] for x in scr if not x.get("reject") and "error" not in x and x.get("sb")]
        if ok:
            run(["python3", HERE / "sb_sheet.py", pool, *ok])
        review = {"created": now(), "pool": str(pool), "candidates": ok, "sheets": [str(pool / "screen" / i / "sheet-sb.jpg") for i in ok],
                  "stock": str(pool / "stock-search.json"),
                  "todo": f"Pick ranges (one subject per range, landing first) into jobs/{self.name}/ranges.json (schema: tools/footage_from_ranges.py)."}
        (self.wd / "build").mkdir(exist_ok=True)
        (self.wd / "build/footage-review.json").write_text(json.dumps(review, indent=1))
        raise Stop(NEEDS_REVIEW, f"{len(ok)} screened CC BY candidates + stock hits ready; visual range pick needed (ranges.json)",
                   review=str(self.wd / "build/footage-review.json"))

    def _sg(self):
        sys.path.insert(0, str(HERE)); import spec_gates  # noqa
        return spec_gates

    # ------------------------------------------------------------------ 3 tts
    def s_tts(self):
        tm, stt = lj(self.wd / "build/timing.json"), lj(self.wd / "build/stt-check.json")
        sc = lj(self.wd / "script.json")
        fresh = tm and stt and [l["text"] for l in tm["lines"]] == [l["text"] for l in sc["lines"]]
        if not fresh:
            if self.dry:
                return {"dry_run": True, "would_run": "title_runner.py tts stt (gated, AURUM_TTS_PY=" + TTS_PY + ")"}
            self.heavy("tts+stt", ["python3", HERE / "title_runner.py", f"jobs/{self.name}", "tts", "stt"], env={"AURUM_TTS_PY": TTS_PY})
            tm, stt = lj(self.wd / "build/timing.json"), lj(self.wd / "build/stt-check.json")
        if (self.spec.get("voice"), self.spec.get("lang"), float(self.spec.get("speed", 0))) != ("bm_george", "en-gb", 1.0):
            raise Stop(NEEDS_REVIEW, "spec voice is not the approved Bali voice (bm_george, en-gb, 1.0)")
        weak = [f for f in stt.get("full_lines", []) if f["recall"] < 0.8 or not f["last_word_heard"]]
        if stt.get("failed_names") or weak:
            raise Stop(NEEDS_AI, "STT check: fix respellings/stt_alias in spec.json or reword lines", failed_names=stt.get("failed_names"),
                       weak_lines=[(f["line"], f["recall"]) for f in weak][:12])
        return {"narration_s": tm["total"], "stt_pass": f"{stt['passed']}/{stt['total']}", "lines": len(tm["lines"])}

    # ------------------------------------------------------------------ 4 plan
    def s_plan(self):
        sg = self._sg()
        lock = self.lock()
        if self.dry:
            if not lock:
                return {"dry_run": True, "would_run": "title_runner plan -> lock_release.py -> title_runner plan (locked) -> sheet"}
            lock["gate_exceptions"] = self.spec.get("gate_exceptions", {})
            lic = self.wd / "licence-log.csv"
            res = sg.evaluate(lock, sg.read_rows(lic), None, root=self.wd)
            (self.scratch / "scorecard-pre-render.json").write_text(json.dumps(res, indent=1, default=str))
            if not res["pass"]:
                raise Stop(NEEDS_REVIEW, "pre-render gates fail on the locked EDL", failed=res["failed"])
            return {"locked": True, "gates_pass": True, "gates": len(res["gates"]), "shots": len(lock["shots"]), "duration_s": lock["duration_s"]}
        if not lock and self.spec.get("portrait"):
            # Short: plan on the long's release windows, then subject-tracking reframe; the windows are already short
            # release cuts, so the planned EDL itself is locked (no lock_release re-cut).
            self.heavy("plan(short)", ["python3", HERE / "title_runner.py", f"jobs/{self.name}", "plan"])
            pre = lj(self.wd / "out/scorecard-pre-render.json", {})
            other = [g for g in (pre.get("failed") or []) if g != "portrait_shots_reframed"]
            if other:
                raise Stop(NEEDS_REVIEW, "short plan fails gates", failed=other)
            self.heavy("reframe", ["python3", HERE / "portrait_reframe.py", f"jobs/{self.name}", self.wd / "build/edl-long.json",
                                   self.wd / "edl-lock.json"])
        elif not lock:
            self.heavy("plan", ["python3", HERE / "title_runner.py", f"jobs/{self.name}", "plan"])
            pre = lj(self.wd / "out/scorecard-pre-render.json", {})
            gaps = (lj(self.wd / "build/needs-footage.json", {}) or {}).get("gaps")
            if not pre.get("pass") or gaps:
                raise Stop(NEEDS_REVIEW, "plan fails gates or has footage gaps: add/re-tag ranges, then re-run", failed=pre.get("failed"),
                           gaps=(gaps or [])[:10])
            self.heavy("lock_release", ["python3", HERE / "lock_release.py", f"jobs/{self.name}"])
        self.heavy("plan(locked)", ["python3", HERE / "title_runner.py", f"jobs/{self.name}", "plan", "sheet"])
        pre = lj(self.wd / "out/scorecard-pre-render.json", {})
        if not pre.get("pass"):
            raise Stop(NEEDS_REVIEW, "locked EDL fails pre-render gates", failed=pre.get("failed"))
        return {"locked": True, "gates_pass": True, "contact_sheets": sorted(glob.glob(str(self.wd / "out/contact-sheet-*.jpg")))}

    # ------------------------------------------------------------------ 5 render
    def s_render(self, watch):
        st = self.state["stages"].get("render", {})
        tag = self.spec.get("release_tag") or f"{self.name}-ranges"
        pfx = f"{self.slug}-{self.stem}"
        master = self.outdir / f"{pfx}-1080p-master.mp4"
        art = sorted(self.outdir.glob("art/*/out/checks.json"))
        if master.exists() and art:  # already rendered + fetched: verify only
            chk = lj(art[-1]); h = sha256(master); a = art[-1].parent.parent
            if h != chk.get("sha256"):
                raise Stop(FAILED, "downloaded master sha256 does not match CI checks.json", master=str(master))
            info = {"master": str(master), "sha256": h, "duration_s": chk.get("duration_s"), "qa_pass": True,
                    "checks": str(art[-1]), "edl": str(a / "build/edl-long.json"), "licence": str(a / "licence-log.csv"),
                    "review": str(self.outdir / f"{pfx}-review-720p.mp4"), "ci_sha256": chk.get("sha256")}
            if chk.get("pass"):
                return info
            # audio-only fix (tools/audio_fix.py): newest checks-audio-vN.json whose outputs all pass replaces the CI master
            fixes = sorted(self.outdir.glob("checks-audio-v*.json"), key=lambda p: int(re.sub(r"\D", "", p.stem) or 0))
            for fx in reversed(fixes):
                v = re.sub(r"\D", "", fx.stem); m2 = self.outdir / f"{pfx}-1080p-master-v{v}.mp4"; r2 = self.outdir / f"{pfx}-review-720p-v{v}.mp4"
                res = (lj(fx) or {}).get("results", {})
                if m2.exists() and res.get(m2.name, {}).get("all_pass") and res.get(r2.name, {}).get("all_pass"):
                    want = res[m2.name].get("sha256"); h2 = sha256(m2)
                    if want and want != h2:
                        raise Stop(FAILED, f"{m2.name} sha256 differs from {fx.name}")
                    return {**info, "master": str(m2), "sha256": h2, "review": str(r2), "audio_fix": str(fx),
                            "ci_failed": chk.get("failed"), "audio_fix_sha_recorded": bool(want)}
            audio = {"music_ytal_or_none", "ambient_only_from_allowed_sources", "loudness_-14_tp_le_-1", "av_duration_match",
                     "natural_sound_audible", "no_music_or_sfx_in_source_audio"}
            if set(chk.get("failed") or []) <= audio:
                v = str(len(fixes) + 2)
                cmd = ["python3", HERE / "audio_fix.py", f"jobs/{self.name}", a, self.outdir, pfx, v]
                if self.dry:
                    return {**info, "qa_pass": False, "ci_failed": chk.get("failed"), "dry_run": True, "would_run": "gated " + " ".join(map(str, cmd))}
                self.heavy("audio_fix", cmd)
                return self.s_render(False)
            raise Stop(NEEDS_REVIEW, "CI QA gates failed on the render (not audio-only)", failed=chk.get("failed"))
        files = self.release_files()
        if self.dry:
            return {"dry_run": True, "release": tag, "release_files": len(files),
                    "would_run": ["git add (job inputs only) + commit + gate.py merge + pull --rebase + push",
                                  f"gh release upload {tag} <{len(files)} range windows + licence-log.csv>",
                                  f"gh workflow run render-preview.yml -f job={self.name} -f release_tag={tag}",
                                  f"tools/ci/watch_and_fetch.sh RUN {self.outdir} {pfx}"]}
        if st.get("run_id"):
            log = self.outdir / "watch.log"
            if log.exists() and "fetch_done" in log.read_text():
                if not master.exists():
                    raise Stop(FAILED, "render finished but no master in artifact", log=log.read_text()[-800:])
                return self.s_render(watch)
            if watch:
                run(["bash", HERE / "ci/watch_and_fetch.sh", st["run_id"], self.outdir, pfx])
                return self.s_render(False)
            raise Stop(WAITING, f"render run {st['run_id']} in progress; watcher writes {log}")
        self.commit_inputs()
        if self.spec.get("release_shared"):  # Short: the long's release already holds every window it uses
            pass
        elif run(["gh", "release", "view", tag, "-R", REPO]).returncode:
            run(["gh", "release", "create", tag, "-R", REPO, "--title", f"{self.name} range clips", "--notes",
                 "Short CC BY / Pexels range windows around used shots + licence-log only (tools/lock_release.py). No full sources, no renders."], check=True)
        if not self.spec.get("release_shared"):
            run(["gh", "release", "upload", tag, "-R", REPO, "--clobber", *files], check=True)
        t0 = time.time()
        run(["gh", "workflow", "run", "render-preview.yml", "-R", REPO, "-f", f"job={self.name}", "-f", f"release_tag={tag}"], check=True)
        rid = None
        for _ in range(12):
            time.sleep(5)
            r = run(["gh", "run", "list", "-R", REPO, "--workflow", "render-preview.yml", "-L", "5", "--json", "databaseId,createdAt,event"])
            for x in json.loads(r.stdout or "[]"):
                if x["event"] == "workflow_dispatch" and datetime.fromisoformat(x["createdAt"].replace("Z", "+00:00")).timestamp() >= t0 - 30:
                    rid = str(x["databaseId"]); break
            if rid:
                break
        if not rid:
            raise Stop(FAILED, "dispatched, but the run id was not found")
        self.note("render", run_id=rid, release=tag)
        self.outdir.mkdir(parents=True, exist_ok=True)
        if watch:
            run(["bash", HERE / "ci/watch_and_fetch.sh", rid, self.outdir, pfx])
            return self.s_render(False)
        subprocess.Popen(["setsid", "bash", str(HERE / "ci/watch_and_fetch.sh"), rid, str(self.outdir), pfx], cwd=ROOT,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        raise Stop(WAITING, f"dispatched run {rid}; background watcher will fetch to {self.outdir} (re-run to continue)")

    def release_files(self):
        lib = lj(self.wd / "footage.json", {}) or {}
        fs = sorted({str(self.wd / c["file"]) for c in lib.get("clips", [])})
        return fs + [str(self.wd / "licence-log.csv")]

    def commit_inputs(self):
        pats = ["script.json", "spec.json", "footage.json", "edl-lock.json", "licence-log.csv", "ranges.json",
                "build/narration.wav", "build/timing.json", "build/stt-check.json", "build/tts", "build/footage-plan.json"]
        paths = [f"jobs/{self.name}/{p}" for p in pats if (self.wd / p).exists()]
        run(["git", "add", "--", *paths], check=True)
        if run(["git", "diff", "--cached", "--quiet"]).returncode == 0:
            return
        run(["git", "commit", "-m", f"{self.name}: render inputs (make_destination.py)", "--", *paths], check=True)
        g = run(["python3", GATE, "merge", "--bot", BOT, "--what", f"push {self.name} render inputs to aurum-video-render main"])
        if g.returncode:
            raise Stop(WAITING, "gate.py merge refused the push", gate=g.stderr[-300:])
        run(["git", "pull", "--rebase", "--autostash"], check=True)
        run(["git", "push"], check=True)
        run(["python3", GATE, "release", "--bot", BOT])

    # ------------------------------------------------------------------ 5b shorts
    def s_shorts(self, watch):
        sc = lj(self.wd / "script.json"); shorts = sc.get("shorts") or []
        if len(shorts) < 3 or any(not x.get("lines") for x in shorts[:3]):
            raise Stop(NEEDS_AI, "script.json needs 'shorts': 3 x {title, hook_text, lines[...]} (30-50 s each, own first-second hook)")
        tag = self.spec.get("release_tag") or f"{self.name}-ranges"
        res = {}
        for k, short in enumerate(shorts[:3], 1):
            sn = f"{self.name}-short-{k}"; sd = ROOT / "jobs" / sn
            spec = {**self.spec, "slug": f"{self.slug}-short-{k}", "portrait": True, "output_stem": f"short-{k}", "hook_text": short["hook_text"],
                    "lift_min_count": 1, "end_card_s": float(short.get("end_card_s", 2.0)), "release_tag": tag, "release_shared": True,
                    "public_dir": f"jobs/{sn}/build/public", "parent_job": self.name}
            spec.pop("facts_db", None)
            if self.dry:
                res[sn] = {"dry_run": True, "lines": len(short["lines"]), "would": "write job, hard-link windows, tts, plan, reframe, lock, render"}
                continue
            sd.mkdir(exist_ok=True); (sd / "clips").mkdir(exist_ok=True)
            if not (sd / "spec.json").exists():
                (sd / "spec.json").write_text(json.dumps(spec, indent=1, ensure_ascii=False))
                (sd / "script.json").write_text(json.dumps({"slug": spec["slug"], "title": short.get("title", ""), "lines": short["lines"],
                                                            "end_card": short.get("end_card", sc.get("end_card"))}, indent=1, ensure_ascii=False))
                lib = lj(self.wd / "footage.json"); lib["job"] = sn
                (sd / "footage.json").write_text(json.dumps(lib, indent=1, ensure_ascii=False))
                shutil.copy(self.wd / "licence-log.csv", sd / "licence-log.csv")
                pub = self.wd / "build/public"
                if pub.exists() and not (sd / "build/public").exists():
                    shutil.copytree(pub, sd / "build/public", copy_function=os.link)
            for c in lj(sd / "footage.json")["clips"]:  # hard links: no extra disk, no downloads
                dst = sd / c["file"]
                if not dst.exists() and (self.wd / c["file"]).exists():
                    os.link(self.wd / c["file"], dst)
            sub = Job(sn, False); sub.args = self.args
            for st in ("tts", "plan", "render"):
                if sub.state["stages"].get(st, {}).get("status") == "done" and st != "render":
                    continue
                try:
                    info = getattr(sub, f"s_{st}")(watch) if st == "render" else getattr(sub, f"s_{st}")()
                    sub.note(st, status="done", info=info)
                except Stop as e:
                    sub.note(st, status=NAMES[e.code].lower(), message=e.msg, detail=e.kw)
                    raise Stop(e.code, f"{sn}: {e.msg}", **e.kw)
            res[sn] = sub.state["stages"]["render"]["info"]
        return res

    # ------------------------------------------------------------------ 6 package
    def s_package(self):
        r = self.state["stages"].get("render", {}).get("info") or {}
        if self.dry and not r.get("master"):
            self.dry_norender = True
            return {"dry_run": True, "would_run": "package_video.py after the render (no master yet)"}
        if not r.get("master"):
            raise Stop(FAILED, "render stage has no verified master")
        cmd = ["python3", HERE / "package_video.py", f"jobs/{self.name}", "--master", r["master"], "--checks", r["checks"], "--edl", r["edl"],
               "--licence", r["licence"], "--out", self.vdir]
        if self.facts_path():
            cmd += ["--facts", self.facts_path()]
        if self.args.package_input:
            cmd += ["--package-input", self.args.package_input]
        if self.dry:
            cmd += ["--no-landing-check"]  # headless browser = heavy slot; dry runs never take it
        p = run(cmd)
        last = (p.stdout.strip().splitlines() or ["{}"])[-1]
        try:
            info = json.loads(last)
        except ValueError:
            info = {"raw": (p.stdout + p.stderr)[-600:]}
        if p.returncode == 3:
            raise Stop(NEEDS_AI, info.get("why", "package inputs missing"))
        if p.returncode == 5:
            raise Stop(WAITING, info.get("why", "heavy slot busy"))
        if p.returncode:
            raise Stop(FAILED, info.get("why", "package failed"), detail=info)
        return info

    # ------------------------------------------------------------------ 7 handoff
    def s_handoff(self):
        if getattr(self, "dry_norender", False):
            return {"dry_run": True, "would_write": "READY_TO_PUBLISH.json + publish-queue.jsonl"}
        r = self.state["stages"]["render"]["info"]; vj = self.vdir / "video.json"
        if not vj.exists():
            raise Stop(FAILED, "no video.json from the package stage")
        mk = {"slug": self.slug, "job": self.name, "created": now(), "video_json": str(vj), "master": r["master"], "sha256": r["sha256"],
              "duration_s": r.get("duration_s"), "qa_pass": True, "review_copy": r.get("review"),
              "publish": "publishing worker: publish_long.py <video_json> --mode public|schedule (3 days after the previous slot)",
              "shorts": {k: {"master": v.get("master"), "sha256": v.get("sha256")} for k, v in
                         ((self.state["stages"].get("shorts") or {}).get("info") or {}).items() if isinstance(v, dict)},
              "shorts_note": "true 9:16 renders (portrait gate passed); schedule via OpusClip to all connected socials, no overlap with the next long slot",
              "by": "tools/make_destination.py"}
        (self.vdir / "READY_TO_PUBLISH.json").write_text(json.dumps(mk, indent=1))
        if not self.dry:
            q = HANDOFF / "publish-queue.jsonl"
            done = q.exists() and any(json.loads(l).get("slug") == self.slug for l in q.read_text().splitlines() if l.strip())
            if not done:
                with open(q, "a") as f:
                    f.write(json.dumps({"slug": self.slug, "ready": str(self.vdir / "READY_TO_PUBLISH.json"), "at": now()}) + "\n")
        return {"marker": str(self.vdir / "READY_TO_PUBLISH.json")}

    # ------------------------------------------------------------------ 8 archive
    def s_archive(self, delete_card):
        res = lj(self.vdir / "result.json")
        if getattr(self, "dry_norender", False):
            return {"dry_run": True, "would_run": "archive after publish"}
        if self.dry and not res:
            r = self.state["stages"]["render"]["info"]
            return {"dry_run": True, "note": "real run waits for the publishing worker's result.json first",
                    "would_stage": [p for p in (r["master"], r.get("review"), str(self.wd / "edl-lock.json"), str(self.wd / "licence-log.csv")) if p],
                    "then": "arch_stage.py -> expect file -> agent CopyFromBox + arch_assemble.ps1 -> verify -> gate.py db-delete --card (only with --delete-card)"}
        if not res or not res.get("ok") or not res.get("video_id"):
            raise Stop(WAITING, "waiting for the publishing worker's result.json (ok + video_id) before archiving")
        plan = HANDOFF / "research/usb-archive" / f"{self.slug}-plan.json"
        expect = HANDOFF / "research/usb-archive" / f"{self.slug}-expect.json"
        r = self.state["stages"]["render"]["info"]
        items = [(r["master"], "masters"), (r.get("review"), "masters"), (str(self.vdir / "video.json"), "project"),
                 (str(self.vdir / "description.txt"), "project"), (str(self.wd / "script.json"), "project"),
                 (str(self.wd / "edl-lock.json"), "project"), (str(self.wd / "footage.json"), "licences"), (str(self.wd / "licence-log.csv"), "licences")]
        items = [(p, k) for p, k in items if p and Path(p).exists()]
        if self.dry:
            return {"dry_run": True, "would_stage": [p for p, _ in items]}
        if not expect.exists():
            for p, k in items:
                run(["python3", HERE / "arch_stage.py", "stage", plan, p, f"{self.slug}/{k}/{Path(p).name}", k, self.slug], check=True)
            P = lj(plan)
            ex = [{"name": f"{e['sha256'][:12]}-{Path(e['archive_rel']).name}", "dest": "D:\\Aurum-Video-Archive\\" + e["archive_rel"].replace("/", "\\"),
                   "sha256": e["sha256"], "size": e["size"], "parts": len(e["parts"]),
                   "copy": [{"box": pp["path"], "pc": f"C:\\Users\\MHB53\\aurum-arch-stage\\parts\\{e['sha256'][:12]}-{Path(e['archive_rel']).name}.part{i:03d}"}
                            for i, pp in enumerate(e["parts"])]} for e in P["entries"] if e["video"] == self.slug]
            expect.write_text(json.dumps(ex, indent=1))
        result = Path(str(expect) + ".result.json")
        if not result.exists():
            raise Stop(WAITING, "agent step: CopyFromBox every 'copy' part in the expect file to the PC, CopyFromBox the expect file, run "
                                "tools/arch_assemble.ps1 -Expect <it> on the PC, then CopyToBox the .result.json next to the expect file",
                       expect=str(expect))
        rs = lj(result); rs = rs if isinstance(rs, list) else [rs]
        bad = [x for x in rs if x.get("status") not in ("sha256-verified", "already-verified")]
        if bad or len(rs) < len(lj(expect)):
            raise Stop(FAILED, "D: archive not fully verified", bad=bad)
        # standing rule 11 Nov: purge box copies that now have a sha256-verified remote copy (gate-carded, non-fatal)
        pv = run(["python3", HERE / "purge_verified.py", "--offload-vultr", "--slug", self.slug, "--quiet"])
        print(json.dumps({"stage": "archive", "purge_verified": (pv.stdout or pv.stderr).strip()[-300:]}))
        if not delete_card:
            return {"archived": len(rs), "deleted": 0, "note": "archive verified; box copies kept (pass --delete-card to free space)"}
        g = run(["python3", GATE, "db-delete", "--bot", BOT, "--card", delete_card, "--what",
                 f"box working copies of {self.slug} after sha256-verified D: archive ({len(rs)} files)"])
        if g.returncode:
            raise Stop(NEEDS_REVIEW, "gate.py db-delete refused; box copies kept", gate=g.stderr[-300:])
        gone = []
        for f in [r["master"], r.get("review")] + [str(self.wd / c["file"]) for c in (lj(self.wd / "footage.json", {}) or {}).get("clips", [])]:
            if f and Path(f).is_file():
                Path(f).unlink(); gone.append(f)
        return {"archived": len(rs), "deleted": len(gone)}

    # ------------------------------------------------------------------ driver
    def go(self, args):
        self.args = args; self.pending = []
        if args.facts_db:
            d, i, ap_, pl = (args.facts_db.split(":") + ["", "", "", ""])[:4]
            self.spec["facts_db"] = {"dest": d, "iata": i, "airport": ap_, "place": pl}
        order = STAGES[STAGES.index(args.from_stage):] if args.from_stage else STAGES
        if args.only:
            order = [args.only]
        for s in order:
            done = self.state["stages"].get(s, {})
            if done.get("status") == "done" and not args.only and s not in ("render",) and not self.dry:
                print(json.dumps({"stage": s, "status": "done (state)"})); continue
            try:
                fn = getattr(self, f"s_{s}")
                info = fn(args.watch) if s in ("render", "shorts") else fn(args.delete_card) if s == "archive" else fn()
                self.note(s, status="done", info=info)
                print(json.dumps({"stage": s, "status": "dry-run ok" if self.dry else "done", "info": info}, ensure_ascii=False, default=str))
            except Stop as e:
                self.note(s, status=NAMES[e.code].lower(), message=e.msg, detail=e.kw)
                print(json.dumps({"stage": s, "status": NAMES[e.code], "message": e.msg, **e.kw}, ensure_ascii=False, default=str))
                if self.dry and e.code == NEEDS_AI and s in ("package", "shorts"):
                    self.pending.append(s); continue  # dry run: report and keep proving the rest of the chain
                return e.code
        if self.pending:
            print(json.dumps({"dry_run_pending_ai_inputs": self.pending}))
        return OK


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("job"); ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--from", dest="from_stage", choices=STAGES); ap.add_argument("--only", choices=STAGES)
    ap.add_argument("--watch", action="store_true", help="block on the render (gh run watch) instead of a background watcher")
    ap.add_argument("--delete-card", help="approval card for deleting box copies after a verified D: archive (gate.py db-delete)")
    ap.add_argument("--package-input", help="JSON with package/links/official_sites to use when script.json/facts.json lack them (tests)")
    ap.add_argument("--facts-db", help="dest:IATA:airport:place override for spec facts_db (e.g. jamaica:MBJ:Sangster:Montego Bay)")
    a = ap.parse_args()
    j = Job(a.job, a.dry_run)
    code = j.go(a)
    print(json.dumps({"job": a.job, "result": NAMES[code], "state": str(j.state_p)}))
    return code


if __name__ == "__main__":
    sys.exit(main())
