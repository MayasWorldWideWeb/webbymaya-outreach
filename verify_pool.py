#!/usr/bin/env python3
"""Parallel pre-warm of the SMTP mailbox-verify cache so the re-contact send
doesn't do slow serial probes. Verifies every email in the input CSV with a
thread pool, then saves batch_send_outreach's verify cache to disk."""
import argparse, csv, importlib.util, threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
spec = importlib.util.spec_from_file_location("bso", SCRIPT_DIR / "batch_send_outreach.py")
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)

ap = argparse.ArgumentParser()
ap.add_argument("--input", required=True)
ap.add_argument("--workers", type=int, default=20)
ap.add_argument("--timeout", type=int, default=8)
args = ap.parse_args()

emails = []
seen = set()
for r in csv.DictReader(open(args.input, errors="replace")):
    e = (r.get("email") or "").strip().lower()
    if e and "@" in e and e not in seen and e not in m._VERIFY_CACHE:
        seen.add(e); emails.append(e)

print(f"verifying {len(emails)} uncached mailboxes with {args.workers} workers...", flush=True)
lock = threading.Lock(); done = [0]; good = [0]; bad = [0]

def work(e):
    ok, reason = m.verify_mailbox(e, timeout=args.timeout)
    with lock:
        done[0] += 1
        if ok: good[0] += 1
        else: bad[0] += 1
        if done[0] % 100 == 0:
            print(f"  {done[0]}/{len(emails)}  (sendable={good[0]} bad={bad[0]})", flush=True)
            m._save_verify_cache()
    return ok

with ThreadPoolExecutor(max_workers=args.workers) as ex:
    for _ in as_completed([ex.submit(work, e) for e in emails]):
        pass

m._save_verify_cache()
print(f"DONE. verified={done[0]} sendable={good[0]} bad_mailbox={bad[0]}", flush=True)
