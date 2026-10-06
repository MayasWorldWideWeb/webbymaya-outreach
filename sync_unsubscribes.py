#!/usr/bin/env python3
"""
sync_unsubscribes.py — Pull unsubscribes from Supabase into bounce_log.csv.
Run this before any send session so the suppression list is current.

    python3 sync_unsubscribes.py --dry-run
    python3 sync_unsubscribes.py

WHY THIS IS NOT A PLAIN COPY
----------------------------
Most rows in public.unsubscribes have an ANONYMIZED local part. The domain
survives intact, the local part does not:

    vaab@bagelsngrinds.com      is really  info@bagelsngrinds.com
    fbyff@barnet.com                       sales@barnet.com
    dbagbdg@blissohio.com                  contact@blissohio.com
    dfdvyvb.begvm@phila.gov                cecilia.ortiz@phila.gov

Neither our sender (batch_send_outreach._list_unsub_headers / html_card, which
percent-encode the address and nothing more) nor the `unsubscribe` edge function
(which stores what it receives, verbatim and lowercased) does this. The rewrite
happens in transit — corporate mail-security scanners that follow the RFC 8058
one-click link anonymize the address before fetching it.

It is NOT a cipher and cannot be decoded. Proof: in the known-good pair
dfdvyvb.begvm -> cecilia.ortiz, the input letter 'b' becomes 'a' at position 7
and 'o' at position 8. One input letter, two outputs, inside a single plaintext.
A fixed substitution cannot do that, which is why ROT13 gets tantalisingly close
(inno@, hsllo@) and is always wrong.

What IS reliable: the domain is untouched, and the anonymizer preserves local-part
LENGTH exactly (vaab/info = 4, dbagbdg/contact = 7). So we suppress by DOMAIN,
matching each opted-out domain against addresses we have actually mailed.

If a domain resolves to several addresses we mailed, we suppress ALL of them.
That is the safe direction for a do-not-mail list: over-suppressing costs a
prospect, under-suppressing mails someone who explicitly opted out.

THE BUG THIS REPLACES: the old version compared the garbled Supabase values
against the garbled values already in bounce_log.csv. They always matched after
the first run, so it printed "No new unsubscribes" forever while the senders —
which compare REAL addresses — never matched a single one. Suppression had been
a no-op for every obscured row.
"""
import argparse
import csv
import datetime
import glob
import json
import os
import urllib.request
from collections import defaultdict
from pathlib import Path

SUPABASE_URL = "https://ycsauzlqsjjbusugshpz.supabase.co"
ANON_KEY     = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Inljc2F1emxxc2pqYnVzdWdzaHB6Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3Nzk0NjMzMTQsImV4cCI6MjA5NTAzOTMxNH0._rjYuGZch-CA4sfm2rV3lvs_ixDcQfNFg90KWsbe1HI"
HERE         = Path(__file__).parent
BOUNCE_LOG   = HERE / "bounce_log.csv"

# bounce_log.csv's real header. A mismatched fieldname list writes positionally
# and silently shifts every value one column left.
FIELDS = ["email", "phone", "reason", "date", "notes"]


def fetch_unsubscribes() -> set:
    req = urllib.request.Request(
        f"{SUPABASE_URL}/rest/v1/unsubscribes?select=email&order=unsubscribed_at.desc",
        headers={"apikey": ANON_KEY, "Authorization": f"Bearer {ANON_KEY}"},
    )
    try:
        rows = json.loads(urllib.request.urlopen(req, timeout=20).read())
    except Exception as e:
        print(f"[sync] Supabase fetch failed: {e}")
        return set()
    return {r["email"].strip().lower() for r in rows
            if r.get("email") and "@" in r["email"]}


def mailed_addresses() -> dict:
    """domain -> {addresses we have actually sent to}, from every send log."""
    by_domain = defaultdict(set)

    def add(value):
        v = (value or "").strip().lower()
        if "@" in v and not v.endswith("@"):
            by_domain[v.split("@")[1]].add(v)

    for path in glob.glob(str(HERE / "*.csv")):
        if os.path.basename(path) == BOUNCE_LOG.name:
            continue
        try:
            with open(path, newline="", encoding="utf-8", errors="ignore") as fh:
                reader = csv.DictReader(fh)
                if not reader.fieldnames:
                    continue
                cols = [c for c in reader.fieldnames
                        if c and c.strip().lower() in
                        ("email", "email_sent_to", "to", "recipient")]
                if not cols:
                    continue
                for row in reader:
                    for c in cols:
                        add(row.get(c))
        except Exception as e:
            print(f"[sync] skipped {os.path.basename(path)}: {e}")
    return by_domain


def load_suppressed() -> set:
    if not BOUNCE_LOG.exists():
        return set()
    with open(BOUNCE_LOG, newline="", encoding="utf-8", errors="ignore") as fh:
        return {(row.get("email") or "").strip().lower()
                for row in csv.DictReader(fh)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="show what would be suppressed, write nothing")
    args = ap.parse_args()

    unsubs = fetch_unsubscribes()
    if not unsubs:
        print("[sync] nothing fetched — aborting without changes.")
        return

    by_domain = mailed_addresses()
    already   = load_suppressed()
    today     = datetime.date.today().isoformat()

    opted_out_domains = {a.split("@")[1] for a in unsubs}
    pending, unmatched = [], []

    # 1. the raw values themselves, so repeat runs stay idempotent
    for addr in sorted(unsubs):
        if addr not in already:
            pending.append({"email": addr, "phone": "", "reason": "unsubscribed",
                            "date": today, "notes": "as recorded by unsubscribe endpoint"})

    # 2. every real address we mailed at an opted-out domain
    for domain in sorted(opted_out_domains):
        reals = sorted(a for a in by_domain.get(domain, set()) if a not in unsubs)
        if not reals:
            unmatched.append(domain)
            continue
        note = ("domain opted out; matched from send logs"
                + (f" (1 of {len(reals)} at this domain)" if len(reals) > 1 else ""))
        for addr in reals:
            if addr not in already:
                pending.append({"email": addr, "phone": "",
                                "reason": "unsubscribed_domain_match",
                                "date": today, "notes": note})

    real_new = [p for p in pending if p["reason"] == "unsubscribed_domain_match"]
    print(f"[sync] {len(unsubs)} opt-out records across {len(opted_out_domains)} domains")
    print(f"[sync] {len(opted_out_domains) - len(unmatched)} domains matched to a mailed address")
    print(f"[sync] {len(real_new)} REAL addresses to suppress that senders can actually match")
    if unmatched:
        print(f"[sync] {len(unmatched)} domains with nothing on file (nothing to suppress): "
              + ", ".join(unmatched[:6]) + ("…" if len(unmatched) > 6 else ""))

    if not pending:
        print("[sync] suppression list already current.")
        return

    if args.dry_run:
        print("\n[sync] --dry-run, writing nothing. Would add:")
        for p in real_new[:40]:
            print(f"    {p['email']}")
        if len(real_new) > 40:
            print(f"    … and {len(real_new) - 40} more")
        return

    with open(BOUNCE_LOG, "a", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS)
        for row in pending:
            writer.writerow(row)

    print(f"\n[sync] appended {len(pending)} row(s) to {BOUNCE_LOG.name} "
          f"({len(real_new)} of them real, matchable addresses).")


if __name__ == "__main__":
    main()
