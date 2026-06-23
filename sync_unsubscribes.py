#!/usr/bin/env python3
"""
sync_unsubscribes.py — Pull unsubscribes from Supabase and add to bounce_log.csv.
Run this before any send session so the suppression list is current.

Usage:
    python3 sync_unsubscribes.py
"""
import csv, json, os, urllib.request, urllib.error
from pathlib import Path

SUPABASE_URL = "https://ycsauzlqsjjbusugshpz.supabase.co"
ANON_KEY     = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Inljc2F1emxxc2pqYnVzdWdzaHB6Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3Nzk0NjMzMTQsImV4cCI6MjA5NTAzOTMxNH0._rjYuGZch-CA4sfm2rV3lvs_ixDcQfNFg90KWsbe1HI"
BOUNCE_LOG   = Path(__file__).parent / "bounce_log.csv"


def fetch_unsubscribes() -> list[str]:
    req = urllib.request.Request(
        f"{SUPABASE_URL}/rest/v1/unsubscribes?select=email&order=unsubscribed_at.desc",
        headers={"apikey": ANON_KEY, "Authorization": f"Bearer {ANON_KEY}"},
    )
    try:
        rows = json.loads(urllib.request.urlopen(req, timeout=10).read())
        return [r["email"].strip().lower() for r in rows if r.get("email")]
    except Exception as e:
        print(f"[sync] Supabase fetch failed: {e}")
        return []


def load_bounce_log() -> set:
    if not BOUNCE_LOG.exists():
        return set()
    with open(BOUNCE_LOG, newline="", encoding="utf-8") as f:
        return {row.get("email", "").strip().lower() for row in csv.DictReader(f)}


def main():
    unsubs   = fetch_unsubscribes()
    existing = load_bounce_log()
    new_ones = [e for e in unsubs if e and e not in existing]

    if not new_ones:
        print(f"[sync] No new unsubscribes. ({len(unsubs)} total in Supabase)")
        return

    # Append to bounce_log.csv
    write_header = not BOUNCE_LOG.exists()
    with open(BOUNCE_LOG, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["email", "reason", "timestamp"])
        if write_header:
            writer.writeheader()
        import datetime
        for email in new_ones:
            writer.writerow({"email": email, "reason": "unsubscribed", "timestamp": datetime.datetime.utcnow().isoformat()})

    print(f"[sync] Added {len(new_ones)} unsubscribe(s) to bounce_log.csv:")
    for e in new_ones:
        print(f"  - {e}")


if __name__ == "__main__":
    main()
