#!/usr/bin/env python3
"""
scheduled_send.py — Auto-send SMS + email for WebByMaya
Finds today's enriched CSV and sends up to --sms-limit texts
and --email-limit emails from it.
"""
import argparse
import csv
import datetime
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--sms-limit",   type=int, default=200)
    p.add_argument("--email-limit", type=int, default=50)
    return p.parse_args()


def find_csv():
    today = datetime.date.today().strftime("%Y-%m-%d")
    enriched = SCRIPT_DIR / f"prospects_{today}_enriched.csv"
    plain    = SCRIPT_DIR / f"prospects_{today}.csv"
    if enriched.exists():
        return str(enriched)
    if plain.exists():
        return str(plain)
    # Fall back to most recent CSV
    csvs = sorted(SCRIPT_DIR.glob("prospects_*_enriched.csv"), reverse=True)
    if csvs:
        return str(csvs[0])
    csvs = sorted(SCRIPT_DIR.glob("prospects_*.csv"), reverse=True)
    if csvs:
        return str(csvs[0])
    return None


def count_sendable(csv_path):
    rows = list(csv.DictReader(open(csv_path)))
    sms_ready = [r for r in rows
                 if r.get("phone","").strip()
                 and r.get("sms_status","").strip() not in ("sent","landline","skipped")]
    email_ready = [r for r in rows
                   if r.get("email","").strip()
                   and r.get("email_status","").strip() not in ("sent",)]
    return len(sms_ready), len(email_ready)


def main():
    args = parse_args()
    today = datetime.date.today().strftime("%Y-%m-%d")

    csv_path = find_csv()
    if not csv_path:
        print("No prospects CSV found for today. Run scheduled_find.py first.")
        sys.exit(1)

    sms_ready, email_ready = count_sendable(csv_path)

    print(f"\n{'='*60}")
    print(f"  WebByMaya Scheduled Send")
    print(f"  Date      : {today}")
    print(f"  CSV       : {Path(csv_path).name}")
    print(f"  SMS ready : {sms_ready}  (sending up to {args.sms_limit})")
    print(f"  Email ready: {email_ready}  (sending up to {args.email_limit})")
    print(f"{'='*60}\n")

    # ── SMS ──────────────────────────────────────────────────────────────────
    if sms_ready > 0:
        print(f"--- Sending SMS ---")
        sms_cmd = [
            sys.executable, str(SCRIPT_DIR / "sms_outreach.py"),
            "--input", csv_path,
            "--limit", str(args.sms_limit),
            "--workers", "20",
        ]
        result = subprocess.run(sms_cmd)
        if result.returncode != 0:
            print("[scheduled_send] SMS step failed.")
    else:
        print("No SMS leads ready to send.")

    # ── Email ─────────────────────────────────────────────────────────────────
    if email_ready > 0:
        print(f"\n--- Sending Emails ---")
        email_cmd = [
            sys.executable, str(SCRIPT_DIR / "batch_send_outreach.py"),
            "--input", csv_path,
            "--limit", str(args.email_limit),
        ]
        result = subprocess.run(email_cmd)
        if result.returncode != 0:
            print("[scheduled_send] Email step failed.")
    else:
        print("No email leads ready to send.")

    print(f"\nDone. Check sms_log_{today}.csv and send_log_{today}.csv for results.")


if __name__ == "__main__":
    main()
