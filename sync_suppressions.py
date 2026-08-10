#!/usr/bin/env python3
"""
sync_suppressions.py — make the do-not-mail list survive the machine it lives on.

bounce_log.csv is the only thing standing between the pipeline and re-mailing
everyone who bounced, blocked, or unsubscribed. Two problems it solves:

  1. It is a local file that has been silently destroyed twice (08-09, 08-10),
     and the daily backup is only as old as the last good run.
  2. Cold sending moved to GitHub Actions on 08-09. The runner checks out the
     repo, and bounce_log.csv is gitignored — so the cloud job has been sending
     against SendGrid's suppressions alone, with none of the ~470 unverified
     pairings, none of the Brevo bounces, and none of the Supabase unsubscribes.

So Supabase becomes the durable copy: push anything local that is missing there,
pull the union back down. Run it on the Mac to publish, and in CI to receive.

Usage:
    python3 sync_suppressions.py            # push then pull (default)
    python3 sync_suppressions.py --pull     # CI: fetch only, no local list yet
    python3 sync_suppressions.py --push     # publish local additions only
    python3 sync_suppressions.py --dry-run
"""
from __future__ import annotations   # the Mac runs Python 3.9; CI runs 3.11

import argparse
import csv
import json
import os
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

SUPABASE_URL = os.environ.get("SUPABASE_URL") or "https://ycsauzlqsjjbusugshpz.supabase.co"
ANON_KEY = os.environ.get("SUPABASE_KEY") or (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Inljc2F1"
    "emxxc2pqYnVzdWdzaHB6Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3Nzk0NjMzMTQsImV4cCI6MjA5"
    "NTAzOTMxNH0._rjYuGZch-CA4sfm2rV3lvs_ixDcQfNFg90KWsbe1HI"
)

SCRIPT_DIR = Path(__file__).parent
BOUNCE_LOG = SCRIPT_DIR / "bounce_log.csv"
FIELDS = ["email", "phone", "reason", "date", "notes"]
PAGE = 1000

# A hard bounce outranks a soft "we could not verify this address belongs to
# this business" tag, so a merge never downgrades a real suppression.
RANK = {"spam": 6, "block": 5, "blocked": 5, "hard_bounce": 5, "hardbounce": 5,
        "bounce": 4, "invalid": 4, "sms_stop": 4, "unsubscribed": 3,
        "replied_unsubscribe": 3}


def _rank(reason: str) -> int:
    return RANK.get((reason or "").strip().lower(), 1)


def _headers(extra: dict | None = None) -> dict:
    h = {"apikey": ANON_KEY, "Authorization": f"Bearer {ANON_KEY}",
         "Content-Type": "application/json"}
    if extra:
        h.update(extra)
    return h


def fetch_all(table: str, select: str) -> list:
    """PostgREST caps a response at 1000 rows; walk it with Range headers."""
    out, offset = [], 0
    while True:
        req = urllib.request.Request(
            f"{SUPABASE_URL}/rest/v1/{table}?select={select}",
            headers=_headers({"Range": f"{offset}-{offset + PAGE - 1}"}),
        )
        try:
            rows = json.loads(urllib.request.urlopen(req, timeout=20).read())
        except Exception as e:
            print(f"  [warn] {table}: {e}")
            return out
        out.extend(rows)
        if len(rows) < PAGE:
            return out
        offset += PAGE


def read_local() -> dict:
    if not BOUNCE_LOG.exists():
        return {}
    merged = {}
    with open(BOUNCE_LOG, newline="", encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f)
        for r in reader:
            r.pop(None, None)
            email = (r.get("email") or "").strip().lower()
            phone = (r.get("phone") or "").strip()
            if not email and not phone:
                continue
            row = {c: (r.get(c) or "").strip() for c in FIELDS}
            row["email"] = email
            key = (email, phone)
            if key not in merged or _rank(row["reason"]) > _rank(merged[key]["reason"]):
                merged[key] = row
    return merged


def write_local(rows: dict) -> None:
    """Atomic, and never shrinks the list — a smaller result means a bad read."""
    existing = len(read_local())
    if existing and len(rows) < existing:
        raise SystemExit(
            f"[abort] refusing to write {len(rows)} rows over an existing {existing}. "
            "The suppression list only grows; this would be data loss."
        )
    tmp = BOUNCE_LOG.with_suffix(".csv.tmp")
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        for r in rows.values():
            w.writerow({c: r.get(c, "") for c in FIELDS})
    os.replace(tmp, BOUNCE_LOG)


def pull() -> dict:
    remote = {}
    for r in fetch_all("bounce_log", "email,type,reason,bounced_at"):
        email = (r.get("email") or "").strip().lower()
        if not email:
            continue
        remote[(email, "")] = {
            "email": email, "phone": "",
            "reason": (r.get("type") or "bounce").strip(),
            "date": (r.get("bounced_at") or "")[:10],
            "notes": (r.get("reason") or "")[:200],
        }
    for r in fetch_all("unsubscribes", "email,unsubscribed_at"):
        email = (r.get("email") or "").strip().lower()
        if not email:
            continue
        key = (email, "")
        cand = {"email": email, "phone": "", "reason": "unsubscribed",
                "date": (r.get("unsubscribed_at") or "")[:10], "notes": ""}
        if key not in remote or _rank(cand["reason"]) > _rank(remote[key]["reason"]):
            remote[key] = cand
    print(f"[pull] Supabase holds {len(remote)} suppressed address(es).")
    return remote


def push(local: dict, remote: dict, dry: bool) -> int:
    """Insert only what Supabase is missing.

    Plain insert, not upsert: merge-duplicates needs a unique index on email and
    there isn't one, so an upsert would quietly append a duplicate every run.
    """
    have = {k[0] for k in remote}
    new = [r for (email, _), r in local.items() if email and email not in have]
    if not new:
        print("[push] Supabase is already current.")
        return 0
    if dry:
        print(f"[push] DRY RUN — would publish {len(new)} address(es).")
        return len(new)

    sent = 0
    for i in range(0, len(new), 200):
        batch = [{"email": r["email"],
                  "type": r["reason"] or "unsubscribed",
                  "reason": (r["notes"] or r["reason"] or "")[:500],
                  "bounced_at": (r["date"] or date.today().isoformat()) + "T00:00:00Z"}
                 for r in new[i:i + 200]]
        req = urllib.request.Request(
            f"{SUPABASE_URL}/rest/v1/bounce_log",
            data=json.dumps(batch).encode(),
            headers=_headers({"Prefer": "resolution=ignore-duplicates,return=minimal"}),
            method="POST",
        )
        try:
            urllib.request.urlopen(req, timeout=30)
            sent += len(batch)
        except urllib.error.HTTPError as e:
            print(f"  [warn] batch {i // 200 + 1} rejected: {e.code} {e.read()[:200]!r}")
        except Exception as e:
            print(f"  [warn] batch {i // 200 + 1}: {e}")
    print(f"[push] Published {sent} new address(es) to Supabase.")
    return sent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pull", action="store_true", help="fetch only (use in CI)")
    ap.add_argument("--push", action="store_true", help="publish only")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    do_push = a.push or not a.pull
    do_pull = a.pull or not a.push

    local = read_local()
    print(f"[local] bounce_log.csv holds {len(local)} suppressed address(es).")
    remote = pull()

    # In CI this is the only source of the list. A failed fetch returns an empty
    # dict, which would hand the sender a blank do-not-mail list and quietly
    # re-mail every bounce and unsubscribe. Fail the job instead.
    if a.pull and not remote and not local:
        raise SystemExit(
            "[abort] Supabase returned no suppressions and there is no local list. "
            "Refusing to continue — sending now would mail every suppressed address."
        )

    if do_push:
        push(local, remote, a.dry_run)

    if do_pull:
        merged = dict(local)
        added = 0
        for key, row in remote.items():
            if key not in merged:
                merged[key] = row
                added += 1
            elif _rank(row["reason"]) > _rank(merged[key]["reason"]):
                merged[key] = row
        if a.dry_run:
            print(f"[pull] DRY RUN — local list would go {len(local)} → {len(merged)}.")
        else:
            write_local(merged)
            print(f"[pull] Local list {len(local)} → {len(merged)} (+{added} from Supabase).")


if __name__ == "__main__":
    main()
