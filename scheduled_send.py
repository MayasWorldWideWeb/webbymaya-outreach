#!/usr/bin/env python3
"""
scheduled_send.py — Auto-send SMS + email for WebByMaya
Finds today's enriched CSV and sends up to --sms-limit texts
and --email-limit emails from it.
"""
import argparse
import base64
import csv
import datetime
import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent


def sms_approved():
    """Return True only if toll-free verification is APPROVED."""
    sid   = os.environ.get("TWILIO_ACCOUNT_SID", "")
    token = os.environ.get("TWILIO_AUTH_TOKEN", "")
    if not sid or not token:
        return False
    tf_verify_sid = "HH6c4e4cc29c8e87a8d14eef69c21df282"
    creds = base64.b64encode(f"{sid}:{token}".encode()).decode()
    req   = urllib.request.Request(
        f"https://messaging.twilio.com/v1/Tollfree/Verifications/{tf_verify_sid}",
        headers={"Authorization": f"Basic {creds}"})
    try:
        data   = json.loads(urllib.request.urlopen(req, timeout=10).read())
        status = data.get("status", "UNKNOWN")
        return status in ("APPROVED", "TWILIO_APPROVED")
    except Exception:
        return False


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--sms-limit",   type=int, default=200)
    p.add_argument("--email-limit", type=int, default=500)
    return p.parse_args()


def find_csv():
    """Return today's CSV, or build a combined unsent CSV from all historical enriched CSVs."""
    today = datetime.date.today().strftime("%Y-%m-%d")
    enriched = SCRIPT_DIR / f"prospects_{today}_enriched.csv"
    plain    = SCRIPT_DIR / f"prospects_{today}.csv"
    if enriched.exists():
        return str(enriched)
    if plain.exists():
        return str(plain)
    # Build combined unsent list from ALL enriched CSVs (avoids running out of leads)
    result = subprocess.run(
        [sys.executable, str(SCRIPT_DIR / "build_unsent_csv.py")],
        capture_output=True, text=True
    )
    if result.returncode == 0:
        built = SCRIPT_DIR / f"prospects_{today}.csv"
        if built.exists():
            return str(built)
    # Last resort: most recent enriched CSV
    csvs = sorted(SCRIPT_DIR.glob("prospects_*_enriched.csv"), reverse=True)
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
        if not sms_approved():
            print("[scheduled_send] SMS blocked — toll-free verification not approved yet.")
        else:
            print(f"--- Sending SMS ---")
            sms_cmd = [
                sys.executable, str(SCRIPT_DIR / "sms_outreach.py"),
                "--input", csv_path,
                "--limit", str(args.sms_limit),
                "--workers", "20",
                "--no-lookup",
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
