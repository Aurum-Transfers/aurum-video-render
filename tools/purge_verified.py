#!/usr/bin/env python3
"""purge_verified.py - free box disk once a finished Aurum video's files have a hash-verified remote copy.

For each media file under the Aurum video work roots it:
  1. skips anything protected: active jobs (OCJ, PUJ and later, anything listed in purge_cards.json "active"), files a
     live job references (exact path, or a basename that does not already exist under an active job tree — finished-job
     duplicates of an active job's own clips are not kept), files touched in the last 30 min, git-tracked files,
     non-media/small records (json, csv, srt, md, txt, descriptions, licence logs, packages, checks.json, thumb/art
     stills), the 720p review copy, books, secrets, other bots' trees;
  2. hashes it (sha256, cached by path+size+mtime);
  3. looks for a remote copy with the SAME sha256:
       D:      existing archive manifests (usb-archive/MANIFEST.jsonl, gen-manifest-append.jsonl, <slug>-expect.json
               + .result.json from arch_assemble.ps1) - only sha256-verified rows count
       GitHub  release asset digests (gh api, sha256:...) and unexpired artifact digests
       Vultr   rows in research/vultr-archive/MANIFEST.jsonl, re-confirmed live with read-only `ssh host sha256sum`.
               --offload-vultr first copies files with no verified copy to Aurum Vultr (root@45.77.193.164:/srv/aurum-video-archive/<job>/,
               tar over ssh throttled by PURGE_BWLIMIT_MBPS, copy only, keeps >=20% free there), verifies, indexes (Marvin t241u/t242u/t117u)
  4. only if the location has an approval card in purge_cards.json: gate.py db-delete --bot aurum-reels --card <card>
     --item <path>; exit 2 = skip and log. Then re-checks size/mtime and deletes.
Every decision is appended to research/purge/purge-log.jsonl (path, bytes, action, reason, remote, local and remote sha256,
time). Anything without a verified remote copy stays put.

  purge_verified.py [--dry-run] [--slug SLUG] [--quiet]
Hooked from make_destination.py (archive stage) and finish_long.py (after a publish/schedule). Never raises in hooks.
"""
import argparse, fnmatch, hashlib, json, os, re, subprocess, sys, time
from datetime import datetime, timezone
from pathlib import Path

BOT = "aurum-reels"
GATE = "/workspace/ops/scripts/gate.py"
HANDOFF = Path("/workspace/handoff/aurum-youtube")
ARCH = HANDOFF / "research/usb-archive"
VULTR_MANIFEST = HANDOFF / "research/vultr-archive/MANIFEST.jsonl"
OUT = HANDOFF / "research/purge"
LOG = OUT / "purge-log.jsonl"
CACHE = OUT / "sha-cache.jsonl"
CARDS = HANDOFF / "tools/purge_cards.json"
REPO = Path("/workspace/work/aurum-video-render")
GH_REPO = "Aurum-Transfers/aurum-video-render"
ROOTS = ["/workspace/work/overnight", "/workspace/work/aurum-video-render/jobs", "/workspace/work/aruba-full-v2",
         "/workspace/work/v6p-dl", "/workspace/work/aruba-v6-preview-ranges", "/workspace/work/clips-v9"]
MEDIA = {".mp4", ".mov", ".mkv", ".webm", ".m4a", ".wav", ".mp3", ".aac", ".flac", ".ts", ".m4v", ".opus", ".ogg",
         ".part", ".y4m", ".avi"}
MIN_BYTES = 256 * 1024
DEFAULT_CFG = {
    "cards": {"D": "t204u", "github": None, "vultr": None},
    # active jobs / never-touch path parts (fnmatch against each path component)
    "active": ["jamaica-ocj*", "*ocj*", "dr-puj*", "*puj*", "books*", "books-ro", ".secrets", "movingrated*", "*mr-*"],
    # names kept even when verified (card t204u: keep 720p review copy, licence records, handoff package)
    "keep_names": ["*review-720p*", "*licen*", "*package*", "*description*", "video.json", "*.srt", "*.vtt",
                   "*thumb*", "*banner*", "checks.json"],
}

def now(): return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
def lj(p, d=None):
    try: return json.loads(Path(p).read_text())
    except Exception: return d
def jl(p):
    out = []
    try:
        for l in Path(p).read_text().splitlines():
            if l.strip():
                try: out.append(json.loads(l))
                except Exception: pass
    except FileNotFoundError: pass
    return out

def cfg():
    c = json.loads(json.dumps(DEFAULT_CFG)); u = lj(CARDS, {}) or {}
    for k, v in u.items():
        if isinstance(v, dict): c.setdefault(k, {}).update(v)
        elif k in c and isinstance(v, list): c[k] = v
    return c

# ---------------------------------------------------------------- remote indexes
def d_index():
    idx = {}
    for f in ("MANIFEST.jsonl", "gen-manifest-append.jsonl"):
        for e in jl(ARCH / f):
            if str(e.get("verification_status", "")).startswith("sha256-verified") and e.get("sha256"):
                idx.setdefault(e["sha256"], e.get("archive_path") or e.get("archive_rel"))
    for ex in ARCH.glob("*-expect.json"):
        res = lj(str(ex) + ".result.json")
        if res is None: continue
        res = res if isinstance(res, list) else [res]
        E = {e.get("name"): e for e in (lj(ex, []) or [])}
        for r in res:
            if r.get("status") not in ("sha256-verified", "already-verified"): continue
            e = E.get(r.get("name"), {}); h = (r.get("sha256") or e.get("sha256") or "").lower()
            if h and (not e.get("sha256") or e["sha256"].lower() == h):
                idx.setdefault(h, r.get("dest") or e.get("dest"))
    return idx

def gh_index():
    idx = {}
    def api(path, jq):
        p = subprocess.run(["gh", "api", "--paginate", path, "--jq", jq], capture_output=True, text=True, timeout=120)
        return p.stdout.splitlines() if p.returncode == 0 else []
    for l in api(f"repos/{GH_REPO}/releases?per_page=100",
                 '.[] | .tag_name as $t | .assets[] | select(.digest != null) | [.digest, $t, .name, (.size|tostring)] | @tsv'):
        d, t, n, s = l.split("\t")
        if d.startswith("sha256:"): idx.setdefault(d[7:], {"where": f"github release {GH_REPO}@{t}/{n}", "size": int(s)})
    for l in api(f"repos/{GH_REPO}/actions/artifacts?per_page=100",
                 '.artifacts[] | select(.expired == false and .digest != null) | [.digest, .name, (.id|tostring), (.size_in_bytes|tostring), .expires_at] | @tsv'):
        d, n, i, s, x = l.split("\t")
        if d.startswith("sha256:"): idx.setdefault(d[7:], {"where": f"github artifact {GH_REPO}#{i} {n} (expires {x})", "size": int(s)})
    return idx

def ssh(host, cmd, stdin=None, timeout=3600):
    return subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15", host, cmd], input=stdin,
                          capture_output=True, text=isinstance(stdin, str) or stdin is None, timeout=timeout)

def remote_sha(host, paths):
    """read-only: niced sha256sum of the given remote paths in one ssh call -> {path: sha}"""
    if not paths: return {}
    p = ssh(host, "xargs -0 -r nice -n 19 ionice -c3 sha256sum --", stdin="\0".join(paths) + "\0")
    out = {}
    for l in (p.stdout or "").splitlines():
        h, _, f = l.partition("  ")
        if len(h) == 64: out[f] = h.lower()
    return out

def vultr_confirm(rows):
    """rows: manifest rows {host, remote_path, sha256}; returns sha->(where, live_sha) for rows whose live sha matches."""
    out, by = {}, {}
    for r in rows:
        if r.get("host") and r.get("remote_path"): by.setdefault(r["host"], []).append(r)
    for host, rs in by.items():
        try: live = remote_sha(host, sorted({r["remote_path"] for r in rs}))
        except Exception: live = {}
        for r in rs:
            h = live.get(r["remote_path"], "")
            if h and h == str(r.get("sha256", "")).lower(): out[h] = (f"vultr {host}:{r['remote_path']}", h)
    return out

# ---------------------------------------------------------------- vultr offload (copy only; no rendering/transcoding there)
VULTR_HOST = os.environ.get("AURUM_VULTR_HOST", "root@45.77.193.164")  # Aurum's own Vultr (hostname vultr), not MR/TPR
VULTR_ROOT = "/srv/aurum-video-archive"
VULTR_MIN_FREE = 0.20      # keep >=20% free on the server
BWLIMIT = float(os.environ.get("PURGE_BWLIMIT_MBPS", "25")) * 1e6
JOB_ROOTS = ("/workspace/work/overnight", "/workspace/work/aurum-video-render/jobs")

def job_rel(p):
    for r in ROOTS:
        if p.startswith(r.rstrip("/") + "/"):
            rel = Path(p[len(r.rstrip("/")) + 1:])
            if r in JOB_ROOTS and len(rel.parts) > 1: return rel.parts[0], str(Path(*rel.parts[1:]))
            return Path(r).name, str(rel)
    return None, None

class Throttle:
    def __init__(self, f): self.f, self.t0, self.n = f, time.time(), 0
    def write(self, b):
        self.f.write(b); self.n += len(b)
        ahead = self.n / BWLIMIT - (time.time() - self.t0)
        if ahead > 0: time.sleep(ahead)
        return len(b)
    def flush(self): self.f.flush()

def vultr_offload(files, shas):
    """files: [(path, st)] with no verified copy. tar over ssh (throttled) into VULTR_ROOT/<job>/, then remote sha256sum,
    append verified rows to VULTR_MANIFEST. Returns (rows_added, notes)."""
    import tarfile
    notes = []
    p = ssh(VULTR_HOST, f"df -B1 --output=size,avail / | tail -1; hostname", timeout=60)
    try:
        size, avail = map(int, p.stdout.split()[:2]); host_name = p.stdout.split()[2]
    except Exception: return 0, [f"vultr df failed: {(p.stderr or '')[-200:]}"]
    need = sum(st.st_size for _, st in files)
    if (avail - need) / size < VULTR_MIN_FREE:
        return 0, [f"vultr would drop under {int(VULTR_MIN_FREE*100)}% free ({avail/1e9:.1f} GB free, need {need/1e9:.1f} GB): nothing copied"]
    groups = {}
    for fp, st in files:
        j, rel = job_rel(fp)
        if j: groups.setdefault(j, []).append((fp, rel, st))
    VULTR_MANIFEST.parent.mkdir(parents=True, exist_ok=True); added = 0
    for job, items in sorted(groups.items()):
        dest = f"{VULTR_ROOT}/{job}"
        proc = subprocess.Popen(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15", VULTR_HOST,
                                 f"umask 077 && mkdir -p '{dest}' && tar -x -C '{dest}' -f -"], stdin=subprocess.PIPE,
                                stderr=subprocess.PIPE)
        try:
            with tarfile.open(fileobj=Throttle(proc.stdin), mode="w|") as tf:
                for fp, rel, st in items: tf.add(fp, arcname=rel, recursive=False)
            proc.stdin.close(); err = proc.stderr.read().decode()[-200:]; rc = proc.wait(timeout=3600)
        except Exception as e:
            rc, err = 1, str(e)
        if rc:
            notes.append(f"{job}: copy failed rc={rc} {err}"); continue
        live = remote_sha(VULTR_HOST, [f"{dest}/{rel}" for _, rel, _ in items])
        with open(VULTR_MANIFEST, "a") as f:
            for fp, rel, st in items:
                rp = f"{dest}/{rel}"; h = live.get(rp)
                if h and h == shas.get(fp):
                    f.write(json.dumps({"host": VULTR_HOST, "hostname": host_name, "remote_path": rp, "sha256": h, "size": st.st_size,
                                        "local_path": fp, "job": job, "verified_at": now()}) + "\n"); added += 1
                else: notes.append(f"{fp}: remote sha mismatch/missing after copy (kept)")
    return added, notes

# ---------------------------------------------------------------- local side
def tracked():
    p = subprocess.run(["git", "-C", str(REPO), "ls-files", "-z"], capture_output=True, text=True)
    return {str(REPO / f) for f in p.stdout.split("\0") if f}

def is_active_path(p, c):
    return any(fnmatch.fnmatch(x, pat) for x in Path(p).parts for pat in c["active"])

def active_refs(c):
    """Names and exact paths referenced from json/txt in active job dirs, plus media basenames already in those trees.

    A finished-job file is only kept as 'referenced' when a live job names it (exact path) or names its basename
    and no same-named media file already exists under an active tree. Shared Jamaica clip names (OCJ has its own
    copy of the MBJ/KIN clip) must not pin the finished-job duplicates.
    """
    refs, path_refs, have = set(), set(), set()
    path_re = re.compile(r"(/[\w./\-]+\.(?:mp4|mov|mkv|webm|m4a|wav|mp3|aac))", re.I)
    base_re = re.compile(r"[\w.\-]+\.(?:mp4|mov|mkv|webm|m4a|wav|mp3|aac)", re.I)
    for root in ROOTS:
        for dp, dns, fns in os.walk(root):
            if not is_active_path(dp, c): continue
            for fn in fns:
                fp = os.path.join(dp, fn)
                if Path(fn).suffix.lower() in MEDIA: have.add(fn)
                if fn.endswith((".json", ".txt", ".csv", ".jsonl")) and os.path.getsize(fp) < 20_000_000:
                    try: text = open(fp, errors="ignore").read()
                    except Exception: continue
                    refs |= set(base_re.findall(text))
                    for m in path_re.findall(text):
                        if os.path.isfile(m): path_refs.add(os.path.abspath(m))
    return refs, path_refs, have

def sha_cached(p, st, cache):
    k = f"{p}|{st.st_size}|{int(st.st_mtime)}"
    if k in cache: return cache[k]
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 22), b""): h.update(b)
    cache[k] = h.hexdigest()
    with open(CACHE, "a") as f: f.write(json.dumps({"k": k, "sha256": cache[k]}) + "\n")
    return cache[k]

def classify(p, c, trk, refs, path_refs, have, slug):
    parts = Path(p).parts; name = Path(p).name
    if slug and not any(slug in x for x in parts): return "out-of-scope"
    if is_active_path(p, c): return "active job / protected tree"
    if p in trk: return "git-tracked (lives in the repo)"
    if Path(p).suffix.lower() not in MEDIA: return "record, not media (kept by rule)"
    if any(fnmatch.fnmatch(name.lower(), pat) for pat in c["keep_names"]): return "kept by name rule (review copy/licence/package/metadata)"
    ap = os.path.abspath(p)
    if ap in path_refs: return "referenced by an active job (exact path)"
    if name in refs and name not in have: return "referenced by an active job"
    return None

def log(row):
    with open(LOG, "a") as f: f.write(json.dumps(row) + "\n")

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--dry-run", action="store_true"); ap.add_argument("--slug")
    ap.add_argument("--quiet", action="store_true"); ap.add_argument("--offload-vultr", action="store_true",
                    help="first copy files with no verified remote copy to Aurum Vultr, verify, index")
    a = ap.parse_args()
    os.nice(10); OUT.mkdir(parents=True, exist_ok=True); c = cfg(); t0 = time.time()
    free0 = os.statvfs("/workspace"); free0 = free0.f_bavail * free0.f_frsize
    trk = tracked(); refs, path_refs, have = active_refs(c)
    cache = {r["k"]: r["sha256"] for r in jl(CACHE) if "k" in r}
    cand, kept = [], {}
    for root in ROOTS:
        for dp, dns, fns in os.walk(root):
            dns[:] = [d for d in dns if d not in (".git", "node_modules", ".venv")]
            for fn in fns:
                p = os.path.join(dp, fn)
                try: st = os.lstat(p)
                except FileNotFoundError: continue
                if not os.path.isfile(p) or os.path.islink(p) or st.st_size < MIN_BYTES: continue
                why = classify(p, c, trk, refs, path_refs, have, a.slug)
                if why == "out-of-scope": continue
                if not why and time.time() - st.st_mtime < 1800: why = "modified in the last 30 min (may be in use)"
                if why: kept.setdefault(why, []).append((p, st.st_size)); continue
                cand.append((p, st))
    D = d_index(); G = gh_index() if cand else {}
    vrows = jl(VULTR_MANIFEST); V = {}
    deleted, gate_skips = [], []
    shas = {}
    for p, st in cand:
        try: shas[p] = sha_cached(p, st, cache)
        except Exception as e: kept.setdefault(f"unreadable ({type(e).__name__})", []).append((p, st.st_size))
    off = None
    if a.offload_vultr and not a.dry_run:
        known = set(D) | set(G) | {str(r.get("sha256", "")).lower() for r in vrows}
        todo = [(p, st) for p, st in cand if shas.get(p) and shas[p] not in known]
        n, notes = vultr_offload(todo, shas); off = {"candidates": len(todo), "gb": round(sum(st.st_size for _, st in todo) / 1e9, 3),
                                                      "indexed": n, "notes": notes[:20]}
        vrows = jl(VULTR_MANIFEST)
    want_v = [r for r in vrows if str(r.get("sha256", "")).lower() in set(shas.values())]
    if want_v: V = vultr_confirm(want_v)
    for p, st in cand:
        h = shas.get(p)
        if not h: continue
        hit = None
        if h in D: hit = ("D", D[h], h)
        elif h in V: hit = ("vultr", V[h][0], V[h][1])
        elif h in G and G[h]["size"] == st.st_size: hit = ("github", G[h]["where"], h)
        if not hit:
            kept.setdefault("no hash-verified remote copy", []).append((p, st.st_size)); continue
        loc, where, rsha = hit; card = (c.get("cards") or {}).get(loc)
        row = {"time": now(), "path": p, "bytes": st.st_size, "remote_kind": loc, "remote": where, "local_sha256": h, "remote_sha256": rsha}
        if not card:
            kept.setdefault(f"verified on {loc} but no approval card covers deleting {loc}-only copies", []).append((p, st.st_size))
            log({**row, "action": "kept", "reason": f"no card for {loc}"}); continue
        if a.dry_run:
            deleted.append((p, st.st_size)); log({**row, "action": "would-delete (dry run)", "card": card}); continue
        g = subprocess.run(["python3", GATE, "db-delete", "--bot", BOT, "--card", card, "--item", p,
                            "--what", f"purge_verified: {p} ({st.st_size} B) sha256 {h[:16]} verified at {where}"],
                           capture_output=True, text=True)
        if g.returncode:
            gate_skips.append((p, st.st_size)); log({**row, "action": "skipped", "reason": f"gate exit {g.returncode}: {(g.stderr or g.stdout)[-240:]}"}); continue
        try:
            st2 = os.lstat(p)
            if (st2.st_size, int(st2.st_mtime)) != (st.st_size, int(st.st_mtime)):
                log({**row, "action": "skipped", "reason": "file changed after hashing"}); continue
            os.unlink(p); deleted.append((p, st.st_size)); log({**row, "action": "deleted", "card": card})
        except Exception as e:
            log({**row, "action": "skipped", "reason": f"unlink failed: {e}"})
    free1 = os.statvfs("/workspace"); free1 = free1.f_bavail * free1.f_frsize
    summ = {"at": now(), "dry_run": a.dry_run, "slug": a.slug, "seconds": round(time.time() - t0),
            "free_before_gb": round(free0 / 1e9, 2), "free_after_gb": round(free1 / 1e9, 2),
            "deleted_count": len(deleted), "deleted_gb": round(sum(b for _, b in deleted) / 1e9, 3),
            "gate_skipped": len(gate_skips),
            "kept": {k: {"count": len(v), "gb": round(sum(b for _, b in v) / 1e9, 3)} for k, v in sorted(kept.items())},
            "log": str(LOG), "remote_index": {"D": len(D), "github": len(G), "vultr_rows": len(vrows)}, "cards": c["cards"], "vultr_offload": off}
    tag = "preview" if a.dry_run else "run"
    (OUT / f"last-{tag}.json").write_text(json.dumps(summ, indent=1))
    (OUT / f"last-{tag}-items.json").write_text(json.dumps({"deleted": deleted, "kept": kept}, indent=0))
    if not a.quiet: print(json.dumps(summ, indent=1))
    else: print(json.dumps({k: summ[k] for k in ("deleted_count", "deleted_gb", "free_after_gb")}))

if __name__ == "__main__":
    try: main()
    except Exception as e:
        print(json.dumps({"purge_verified_error": f"{type(e).__name__}: {e}"})); sys.exit(1)
