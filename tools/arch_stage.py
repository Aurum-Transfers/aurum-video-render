#!/usr/bin/env python3
"""Stage files for the D: USB archive in <=95 MiB parts (CopyFromBox limit 100 MiB).
usage: arch_stage.py stage PLAN.json SRC ARCHIVE_REL KIND VIDEO   -> appends entry, writes parts to /tmp/aurum-arch/<sha12>/
       arch_stage.py list PLAN.json                                -> prints pending parts
Parts are box scratch only; the source file is never modified or deleted here."""
import hashlib, json, os, sys, pathlib, time
PART = 40 * 1024 * 1024
STAGE = pathlib.Path("/tmp/aurum-arch")
def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()
cmd, plan = sys.argv[1], pathlib.Path(sys.argv[2])
P = json.loads(plan.read_text()) if plan.exists() else {"entries": []}
if cmd == "stage":
    src, rel, kind, video = sys.argv[3:7]
    st = os.stat(src); h = sha(src)
    d = STAGE / h[:12]; d.mkdir(parents=True, exist_ok=True)
    parts = []
    with open(src, "rb") as f:
        i = 0
        while True:
            b = f.read(PART)
            if not b: break
            pp = d / f"part{i:03d}"
            pp.write_bytes(b); parts.append({"path": str(pp), "sha256": hashlib.sha256(b).hexdigest(), "size": len(b)}); i += 1
    P["entries"].append({"original_path": src, "archive_rel": rel, "kind": kind, "video": video, "size": st.st_size, "mtime_epoch": st.st_mtime,
                         "mtime": time.strftime("%Y-%m-%d %H:%M:%S JT", time.localtime(st.st_mtime)), "sha256": h, "parts": parts, "status": "staged"})
    plan.write_text(json.dumps(P, indent=1)); print(json.dumps({"src": src, "sha256": h, "parts": len(parts)}))
elif cmd == "list":
    for e in P["entries"]:
        print(e["status"], e["sha256"][:12], len(e["parts"]), e["archive_rel"])
