"""
sms_outreach.py — WebByMaya SMS Outreach
=========================================
Sends a short cold-outreach text to mobile phone numbers from a prospects CSV.
Uses Twilio Lookup to skip landlines, VoIP, and toll-free numbers.

SETUP
-----
1. Sign up at twilio.com — free trial includes $15 credit
2. From the Twilio Console get:
     Account SID  → https://console.twilio.com  (top of dashboard)
     Auth Token   → same page
     Phone Number → buy one (~$1/mo) under Phone Numbers > Manage > Buy

3. Add to ~/.zshrc:
     export TWILIO_ACCOUNT_SID="ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
     export TWILIO_AUTH_TOKEN="your_auth_token"
     export TWILIO_PHONE_NUMBER="+12155550100"   # your Twilio number

4. Install dependency:
     pip3 install twilio

USAGE
-----
    # Dry run — prints messages, sends nothing
    python3 sms_outreach.py --input prospects_2026-05-28.csv --dry-run

    # Send up to 20 texts (default)
    python3 sms_outreach.py --input prospects_2026-05-28.csv

    # Send up to 50, skip carrier lookup (faster, saves $0.005/number)
    python3 sms_outreach.py --input prospects_2026-05-28.csv --limit 50 --no-lookup

FLAGS
-----
    --input CSV      Prospects CSV file (required)
    --dry-run        Preview texts without sending
    --limit N        Max texts per run (default: 20)
    --no-lookup      Skip Twilio carrier lookup — sends to all numbers regardless of type
    --workers N      Parallel lookup threads (default: 10)

OUTPUT
------
    Adds/updates sms_status column in the CSV: sent | skipped | failed | landline
    Writes sms_log_YYYY-MM-DD.csv with one row per attempt
"""

import argparse
import csv
import datetime
import os
import re
from sb import log_sms
import sys
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

# ---------------------------------------------------------------------------
# Check dependency
# ---------------------------------------------------------------------------

try:
    from twilio.rest import Client as TwilioClient
    from twilio.base.exceptions import TwilioRestException
except ImportError:
    sys.exit("ERROR: twilio not found.\nInstall with:  pip3 install twilio")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

ACCOUNT_SID  = os.environ.get("TWILIO_ACCOUNT_SID", "")
AUTH_TOKEN   = os.environ.get("TWILIO_AUTH_TOKEN", "")
FROM_NUMBER  = os.environ.get("TWILIO_PHONE_NUMBER", "")

SEND_DELAY   = 1      # seconds between sends (Twilio rate limit: ~1/sec per number)
DEFAULT_LIMIT = 20

# Mobile-type values from Twilio Lookup v2 that we'll text
MOBILE_TYPES = {"mobile", "prepaid"}

SMS_TEMPLATE = (
    "Hi! I'm Maya, a web designer in Philly. "
    "I noticed {name} doesn't have a website — I build affordable sites for local businesses. "
    "Free consult: webbymaya.com/book "
    "Reply STOP to opt out."
)

LOG_COLUMNS = [
    "timestamp", "name", "phone", "category",
    "carrier_type", "status", "notes",
]

# ---------------------------------------------------------------------------
# Phone number helpers
# ---------------------------------------------------------------------------

US_DIGITS_RE = re.compile(r"\D")


def to_e164(phone: str) -> str:
    """Convert a US phone number string to E.164 format (+1XXXXXXXXXX)."""
    digits = US_DIGITS_RE.sub("", phone)
    if len(digits) == 10:
        return f"+1{digits}"
    if len(digits) == 11 and digits.startswith("1"):
        return f"+{digits}"
    return ""


# ---------------------------------------------------------------------------
# Twilio helpers
# ---------------------------------------------------------------------------

def get_client() -> TwilioClient:
    missing = [k for k, v in [
        ("TWILIO_ACCOUNT_SID", ACCOUNT_SID),
        ("TWILIO_AUTH_TOKEN", AUTH_TOKEN),
        ("TWILIO_PHONE_NUMBER", FROM_NUMBER),
    ] if not v]
    if missing:
        sys.exit(
            f"ERROR: Missing environment variable(s): {', '.join(missing)}\n"
            "Add them to ~/.zshrc and run:  source ~/.zshrc"
        )
    return TwilioClient(ACCOUNT_SID, AUTH_TOKEN)


def lookup_carrier_type(client: TwilioClient, e164: str) -> str:
    """
    Returns the line type string from Twilio Lookup v2.
    Returns 'unknown' on error. Costs ~$0.005 per lookup.
    """
    try:
        result = client.lookups.v2.phone_numbers(e164).fetch(
            fields=["line_type_intelligence"]
        )
        info = result.line_type_intelligence or {}
        return (info.get("type") or "unknown").lower()
    except Exception:
        return "unknown"


def send_sms(client: TwilioClient, to: str, body: str) -> tuple[bool, str]:
    """Send an SMS. Returns (success, error_message)."""
    try:
        client.messages.create(body=body, from_=FROM_NUMBER, to=to)
        return True, ""
    except TwilioRestException as e:
        return False, str(e)
    except Exception as e:
        return False, str(e)


# ---------------------------------------------------------------------------
# CSV helpers
# ---------------------------------------------------------------------------

def load_prospects(path: str) -> tuple[list[dict], list[str]]:
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)
    if "sms_status" not in fieldnames:
        fieldnames.append("sms_status")
        for row in rows:
            row.setdefault("sms_status", "")
    return rows, fieldnames


def save_prospects(rows: list[dict], fieldnames: list[str], path: str):
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_log(log_rows: list[dict]) -> str:
    today = datetime.date.today().strftime("%Y-%m-%d")
    path = Path(__file__).parent / f"sms_log_{today}.csv"
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=LOG_COLUMNS)
        writer.writeheader()
        writer.writerows(log_rows)
    return str(path)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def parse_args():
    parser = argparse.ArgumentParser(
        description="WebByMaya — SMS outreach to mobile numbers in prospects CSV",
    )
    parser.add_argument("--input", required=True, metavar="CSV",
                        help="Prospects CSV file")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview messages without sending")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT, metavar="N",
                        help=f"Max texts per run (default: {DEFAULT_LIMIT})")
    parser.add_argument("--no-lookup", action="store_true",
                        help="Skip carrier lookup — texts all numbers with a phone")
    parser.add_argument("--workers", type=int, default=10, metavar="N",
                        help="Parallel lookup threads (default: 10)")
    return parser.parse_args()


def main():
    args = parse_args()

    if not os.path.exists(args.input):
        sys.exit(f"ERROR: File not found: {args.input}")

    prospects, fieldnames = load_prospects(args.input)

    # Only rows with a phone number that haven't been texted yet
    pending = [
        p for p in prospects
        if p.get("phone", "").strip()
        and p.get("sms_status", "").strip() not in ("sent", "landline", "skipped")
    ]

    print(f"\nLoaded {len(prospects)} total prospects.")
    print(f"  {len(pending)} have phone numbers and haven't been texted yet.")

    if not pending:
        print("Nothing to send. Exiting.")
        return

    to_send = pending[: args.limit]
    print(f"  Will process {len(to_send)} this run (limit: {args.limit}).\n")

    client = None if args.dry_run else get_client()

    # ── Carrier lookup ────────────────────────────────────────────────────────
    if not args.no_lookup and not args.dry_run:
        print(f"Running carrier lookup on {len(to_send)} numbers "
              f"({args.workers} parallel workers) ...")
        lock = threading.Lock()
        done_count = [0]

        def do_lookup(prospect):
            e164 = to_e164(prospect.get("phone", ""))
            if not e164:
                return prospect, "invalid"
            carrier_type = lookup_carrier_type(client, e164)
            with lock:
                done_count[0] += 1
                print(f"  [{done_count[0]}/{len(to_send)}] "
                      f"{prospect.get('name', '')[:30]} → {carrier_type}")
            return prospect, carrier_type

        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = {pool.submit(do_lookup, p): p for p in to_send}
            carrier_map = {}
            for f in as_completed(futures):
                prospect, ctype = f.result()
                carrier_map[id(prospect)] = ctype

        # Filter to mobile only
        mobile = [p for p in to_send if carrier_map.get(id(p)) in MOBILE_TYPES]
        landline = [p for p in to_send if carrier_map.get(id(p)) not in MOBILE_TYPES
                    and carrier_map.get(id(p)) not in (None,)]

        # Mark landlines in CSV now
        for p in landline:
            p["sms_status"] = carrier_map.get(id(p), "non-mobile")
        save_prospects(prospects, fieldnames, args.input)

        print(f"\n  {len(mobile)} mobile  |  {len(landline)} landline/VoIP/other (marked, skipped)\n")
        to_send = mobile
    else:
        carrier_map = {}

    if not to_send:
        print("No mobile numbers to text. Done.")
        return

    # ── Send loop ─────────────────────────────────────────────────────────────
    log_rows = []
    sent = failed = 0

    print(f"{'─'*55}")
    if args.dry_run:
        print(f"  DRY RUN — {len(to_send)} message(s) that would be sent:\n")
    else:
        print(f"  Sending {len(to_send)} text(s) ...\n")

    for i, prospect in enumerate(to_send):
        name     = prospect.get("name", "").strip() or "your business"
        phone    = prospect.get("phone", "").strip()
        category = prospect.get("category", "").strip()
        e164     = to_e164(phone)
        body     = SMS_TEMPLATE.format(name=name)
        ctype    = carrier_map.get(id(prospect), "unknown")

        print(f"[{i+1}/{len(to_send)}] {name}")
        print(f"  Phone   : {phone}  ({e164})")
        print(f"  Message : {body[:80]}{'...' if len(body) > 80 else ''}")
        print(f"  Chars   : {len(body)}")

        if args.dry_run:
            status = "dry_run"
            note   = ""
            print(f"  → DRY RUN, not sent\n")
        elif not e164:
            status = "skipped"
            note   = "Could not parse phone number"
            prospect["sms_status"] = "skipped"
            print(f"  → Skipped (invalid number)\n")
        else:
            success, error = send_sms(client, e164, body)
            if success:
                sent += 1
                status = "sent"
                note   = ""
                prospect["sms_status"] = "sent"
                print(f"  → Sent\n")
            else:
                failed += 1
                status = "failed"
                note   = error
                prospect["sms_status"] = f"failed"
                print(f"  → FAILED: {error}\n")

            if i < len(to_send) - 1:
                time.sleep(SEND_DELAY)

        log_rows.append({
            "timestamp":   datetime.datetime.now().isoformat(timespec="seconds"),
            "name":        name,
            "phone":       e164 or phone,
            "category":    category,
            "carrier_type": ctype,
            "status":      status,
            "notes":       note,
        })

    # ── Save & summary ────────────────────────────────────────────────────────
    if not args.dry_run:
        save_prospects(prospects, fieldnames, args.input)
        log_path = write_log(log_rows)
        log_sms(log_rows)
        print(f"{'─'*55}")
        print(f"Done.  Sent: {sent}  |  Failed: {failed}")
        print(f"CSV updated: {args.input}")
        print(f"Log written: {log_path}")
    else:
        print(f"{'─'*55}")
        print(f"Dry run complete. {len(to_send)} message(s) previewed. Nothing sent.")


if __name__ == "__main__":
    main()
