#!/usr/bin/env python3
"""purge_verified.py - free box disk once a finished Aurum video's files have a hash-verified remote copy.

For each media file under the Aurum video work roots it:
  1. skips anything protected: active jobs (OCJ, PUJ and later, anything listed in purge_cards.json "active"), files a
     live job references, files touched in the last 30 min, git-tracked files, non-media/small records (json, csv, srt,
     md, txt, descriptions, licence logs, packages), the 720p review copy, books, secrets, other bots' trees;
  2. hashes it (sha256, cached by path+size+mtime);
  3. looks for a remote copy with the SAME sha256:
       D:      existing archive manifests (usb-archive/MANIFEST.jsonl, gen-manifest-append.jsonl, <slug>-expect.json
               + .result.json from arch_assemble.ps1) - only sha256-verified rows count
       GitHub  release asset digests (gh api, sha256:...) and unexpired artifact digests
       Vultr   rows in research/vultr-archive/MANIFEST.jsonl, re-confirmed live with read-only `ssh host sha256sum`
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
    "keep_names": ["*review-720p*", "*licen*", "*package*", "*description*", "video.json", "*.srt", "*.vtt"],
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

def vultr_confirm(rows):
    """rows: manifest rows {host, remote_path, sha256}; returns sha->(where, live_sha) for rows whose live sha matches."""
    out = {}
    for r in rows:
        host, rp = r.get("host"), r.get("remote_path")
        if not host or not rp or "'" in rp: continue
        try:
            p = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", host,
                                f"nice -n 19 ionice -c3 sha256sum -- '{rp}'"], capture_output=True, text=True, timeout=600)
            live = p.stdout.split()[0].lower() if p.returncode == 0 and p.stdout else ""
        except Exception: live = ""
        if live and live == str(r.get("sha256", "")).lower(): out[live] = (f"vultr {host}:{rp}", live)
    return out

# ---------------------------------------------------------------- local side
def tracked():
    p = subprocess.run(["git", "-C", str(REPO), "ls-files", "-z"], capture_output=True, text=True)
    return {str(REPO / f) for f in p.stdout.split("\0") if f}

def active_refs(c):
    """basenames referenced from any json/txt in active job dirs (so a shared clip a live job uses is never deleted)."""
    refs = set()
    for root in ROOTS:
        for dp, dns, fns in os.walk(root):
            if not any(fnmatch.fnmatch(x, pat) for x in Path(dp).parts for pat in c["active"]): continue
            for fn in fns:
                if fn.endswith((".json", ".txt", ".csv", ".jsonl")) and os.path.getsize(os.path.join(dp, fn)) < 20_000_000:
                    try: refs |= set(re.findall(r"[\w.\-]+\.(?:mp4|mov|mkv|webm|m4a|wav|mp3|aac)", open(os.path.join(dp, fn), errors="ignore").read()))
                    except Exception: pass
    return refs

def sha_cached(p, st, cache):
    k = f"{p}|{st.st_size}|{int(st.st_mtime)}"
    if k in cache: return cache[k]
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 22), b""): h.update(b)
    cache[k] = h.hexdigest()
    with open(CACHE, "a") as f: f.write(json.dumps({"k": k, "sha256": cache[k]}) + "\n")
    return cache[k]

def classify(p, c, trk, refs, slug):
    parts = Path(p).parts; name = Path(p).name
    if slug and not any(slug in x for x in parts): return "out-of-scope"
    if any(fnmatch.fnmatch(x, pat) for x in parts for pat in c["active"]): return "active job / protected tree"
    if p in trk: return "git-tracked (lives in the repo)"
    if Path(p).suffix.lower() not in MEDIA: return "record, not media (kept by rule)"
    if any(fnmatch.fnmatch(name.lower(), pat) for pat in c["keep_names"]): return "kept by name rule (review copy/licence/package/metadata)"
    if name in refs: return "referenced by an active job"
    return None

def log(row):
    with open(LOG, "a") as f: f.write(json.dumps(row) + "\n")

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--dry-run", action="store_true"); ap.add_argument("--slug")
    ap.add_argument("--quiet", action="store_true"); a = ap.parse_args()
    os.nice(10); OUT.mkdir(parents=True, exist_ok=True); c = cfg(); t0 = time.time()
    free0 = os.statvfs("/workspace"); free0 = free0.f_bavail * free0.f_frsize
    trk, refs = tracked(), active_refs(c)
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
                why = classify(p, c, trk, refs, a.slug)
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
            "log": str(LOG), "remote_index": {"D": len(D), "github": len(G), "vultr_rows": len(vrows)}, "cards": c["cards"]}
    tag = "preview" if a.dry_run else "run"
    (OUT / f"last-{tag}.json").write_text(json.dumps(summ, indent=1))
    (OUT / f"last-{tag}-items.json").write_text(json.dumps({"deleted": deleted, "kept": kept}, indent=0))
    if not a.quiet: print(json.dumps(summ, indent=1))
    else: print(json.dumps({k: summ[k] for k in ("deleted_count", "deleted_gb", "free_after_gb")}))

if __name__ == "__main__":
    try: main()
    except Exception as e:
        print(json.dumps({"purge_verified_error": f"{type(e).__name__}: {e}"})); sys.exit(1)
