#!/usr/bin/env python3
"""
check_bounces.py — WebByMaya Bounce & Rejection Tracker
Pulls bounces, blocks, and spam reports from SendGrid and writes
them to bounce_log.csv. Also marks any matching emails in existing
send logs so they're never retried.
"""
import csv
import datetime
import json
import os
import urllib.request
from pathlib import Path
from sb import log_bounce

SCRIPT_DIR = Path(__file__).parent
BOUNCE_LOG = SCRIPT_DIR / "bounce_log.csv"
API_KEY    = os.environ.get("SENDGRID_API_KEY", "")

ENDPOINTS = [
    ("bounce",  "https://api.sendgrid.com/v3/suppression/bounces?limit=500"),
    ("block",   "https://api.sendgrid.com/v3/suppression/blocks?limit=500"),
    ("spam",    "https://api.sendgrid.com/v3/suppression/spam_reports?limit=500"),
    ("invalid", "https://api.sendgrid.com/v3/suppression/invalid_emails?limit=500"),
]


def fetch(url: str) -> list:
    req = urllib.request.Request(
        url, headers={"Authorization": f"Bearer {API_KEY}"}
    )
    try:
        return json.loads(urllib.request.urlopen(req).read())
    except Exception as e:
        print(f"  [warn] {url}: {e}")
        return []


def load_existing_bounces() -> set:
    if not BOUNCE_LOG.exists():
        return set()
    with open(BOUNCE_LOG, newline="") as f:
        return {row["email"].lower() for row in csv.DictReader(f)}


def main():
    if not API_KEY:
        raise SystemExit("SENDGRID_API_KEY not set. Run: source ~/.zshrc")

    existing = load_existing_bounces()
    new_rows  = []

    for kind, url in ENDPOINTS:
        records = fetch(url)
        for r in records:
            email = r.get("email", "").lower()
            if not email or email in existing:
                continue
            new_rows.append({
                "timestamp": r.get("created", datetime.datetime.now().isoformat()),
                "email":     email,
                "type":      kind,
                "reason":    r.get("reason", r.get("description", ""))[:200],
            })
            existing.add(email)

    # Write / append to bounce_log.csv
    write_header = not BOUNCE_LOG.exists()
    with open(BOUNCE_LOG, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["timestamp","email","type","reason"])
        if write_header:
            writer.writeheader()
        writer.writerows(new_rows)
    for row in new_rows:
        log_bounce(row["email"], row["type"], row["reason"])

    print(f"Bounce log: {len(new_rows)} new record(s) added → {BOUNCE_LOG.name}")

    # Mark bounced emails in all existing send logs so they won't be retried
    if new_rows:
        bounced_emails = {r["email"] for r in new_rows}
        send_logs = sorted(SCRIPT_DIR.glob("send_log_*.csv"))
        for log_path in send_logs:
            rows = list(csv.DictReader(open(log_path, newline="")))
            updated = False
            for row in rows:
                if row.get("email_sent_to","").lower() in bounced_emails and row.get("status") == "sent":
                    row["status"] = "bounced"
                    updated = True
            if updated:
                with open(log_path, "w", newline="") as f:
                    writer = csv.DictWriter(f, fieldnames=rows[0].keys())
                    writer.writeheader()
                    writer.writerows(rows)
                print(f"  Updated {log_path.name}")

    # Print summary
    all_bounces = load_existing_bounces()
    print(f"\nTotal suppressed emails on file: {len(all_bounces)}")

    if BOUNCE_LOG.exists():
        rows = list(csv.DictReader(open(BOUNCE_LOG, newline="")))
        by_type: dict = {}
        for r in rows:
            by_type[r["type"]] = by_type.get(r["type"], 0) + 1
        for t, count in sorted(by_type.items()):
            print(f"  {t:<10} {count}")


if __name__ == "__main__":
    main()
