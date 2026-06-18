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
API_KEY      = os.environ.get("TWILIO_API_KEY", "")
API_SECRET   = os.environ.get("TWILIO_API_SECRET", "")
FROM_NUMBER  = os.environ.get("TWILIO_PHONE_NUMBER", "")

SEND_DELAY   = 1      # seconds between sends (Twilio rate limit: ~1/sec per number)

DEFAULT_LIMIT = 20

# Category → niche landing page
CATEGORY_URLS = {
    "hair salon":       "webbymaya.com/salons",
    "nail salon":       "webbymaya.com/salons",
    "beauty salon":     "webbymaya.com/salons",
    "salon":            "webbymaya.com/salons",
    "spa":              "webbymaya.com/salons",
    "massage":          "webbymaya.com/salons",
    "barber":           "webbymaya.com/salons",
    "restaurant":       "webbymaya.com/restaurants",
    "cafe":             "webbymaya.com/restaurants",
    "bakery":           "webbymaya.com/restaurants",
    "food":             "webbymaya.com/restaurants",
    "auto repair":      "webbymaya.com/auto",
    "mechanic":         "webbymaya.com/auto",
    "auto":             "webbymaya.com/auto",
}

# Niche-specific SMS templates — more relevant = more replies
_SMS_TEMPLATES = {
    "salon": (
        "Hi {name}! Clients search for salons online before they book. "
        "I build salon sites with your menu + booking from $799, live in 7 days. "
        "{url} · Reply STOP to opt out."
    ),
    "restaurant": (
        "Hi {name}! Hungry locals search online before they pick a spot. "
        "I build restaurant sites with your menu + hours from $799, live in 7 days. "
        "{url} · Reply STOP to opt out."
    ),
    "auto": (
        "Hi {name}! Most people Google auto shops before they call. "
        "I build shop sites with your services + reviews from $799, live in 7 days. "
        "{url} · Reply STOP to opt out."
    ),
    "default": (
        "Hi {name}! No website yet? "
        "I build Philly business sites from $799, live in 7 days. "
        "{url} · Reply STOP to opt out."
    ),
}

def _get_sms_template(category: str) -> str:
    key = (category or "").strip().lower()
    if any(k in key for k in ("salon", "spa", "barber", "massage", "nail", "hair", "beauty")):
        return _SMS_TEMPLATES["salon"]
    if any(k in key for k in ("restaurant", "cafe", "bakery", "food", "pizza", "diner")):
        return _SMS_TEMPLATES["restaurant"]
    if any(k in key for k in ("auto", "mechanic", "repair", "tire", "oil")):
        return _SMS_TEMPLATES["auto"]
    return _SMS_TEMPLATES["default"]

def get_url_for_category(category: str) -> str:
    key = (category or "").strip().lower()
    for k, url in CATEGORY_URLS.items():
        if k in key:
            return url
    return "webbymaya.com/get-online"

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
# Free phone type detection (phonenumbers library — no API cost)
# ---------------------------------------------------------------------------

try:
    import phonenumbers
    from phonenumbers import number_type as pn_type, PhoneNumberType
    _PN_OK = True
except ImportError:
    _PN_OK = False

def classify_phone(e164: str) -> str:
    """
    Classify a US phone number using the free phonenumbers library.

    Limitation: US uses number pooling, so FIXED_LINE_OR_MOBILE is returned
    for most valid US numbers — the library can't tell mobile vs landline
    from the digits alone. We use it to catch definite non-mobile types:
      - TOLL_FREE (800/888/877 etc.) → skip
      - PREMIUM_RATE (900 etc.)      → skip
      - VOIP                         → skip
      - FIXED_LINE_OR_MOBILE         → assume sendable (best effort)
    """
    if not _PN_OK or not e164:
        return "unknown"
    try:
        n  = phonenumbers.parse(e164, None)
        if not phonenumbers.is_valid_number(n):
            return "invalid"
        nt = pn_type(n)
        if nt == PhoneNumberType.TOLL_FREE:
            return "toll_free"
        if nt == PhoneNumberType.PREMIUM_RATE:
            return "premium"
        if nt == PhoneNumberType.VOIP:
            return "voip"
        if nt == PhoneNumberType.SHARED_COST:
            return "shared_cost"
        # MOBILE, FIXED_LINE, FIXED_LINE_OR_MOBILE → treat as sendable
        return "mobile"
    except Exception:
        return "unknown"

# ---------------------------------------------------------------------------
# Twilio helpers
# ---------------------------------------------------------------------------

def get_client() -> TwilioClient:
    if not FROM_NUMBER:
        sys.exit("ERROR: Missing TWILIO_PHONE_NUMBER. Add to ~/.zshrc and run: source ~/.zshrc")
    if API_KEY and API_SECRET and ACCOUNT_SID:
        return TwilioClient(API_KEY, API_SECRET, ACCOUNT_SID)
    if ACCOUNT_SID and AUTH_TOKEN:
        return TwilioClient(ACCOUNT_SID, AUTH_TOKEN)
    sys.exit("ERROR: Missing Twilio credentials.")


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


def sms_approved():
    """Return True only if toll-free verification is APPROVED."""
    import base64, json, urllib.request
    tf_verify_sid = "HH6c4e4cc29c8e87a8d14eef69c21df282"
    if not ACCOUNT_SID or not AUTH_TOKEN:
        return False
    creds = base64.b64encode(f"{ACCOUNT_SID}:{AUTH_TOKEN}".encode()).decode()
    req   = urllib.request.Request(
        f"https://messaging.twilio.com/v1/Tollfree/Verifications/{tf_verify_sid}",
        headers={"Authorization": f"Basic {creds}"})
    try:
        data   = json.loads(urllib.request.urlopen(req, timeout=10).read())
        status = data.get("status", "UNKNOWN")
        return status in ("APPROVED", "TWILIO_APPROVED")
    except Exception:
        return False


def main():
    args = parse_args()

    if not args.dry_run and not sms_approved():
        sys.exit("[sms_outreach] BLOCKED — toll-free verification not approved yet. No SMS sent.")

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

    # ── Phone type classification (free — phonenumbers library, no API cost) ──
    carrier_map = {}
    if not args.dry_run:
        if _PN_OK:
            print(f"Classifying {len(to_send)} numbers (free phonenumbers library) ...")
            landline = []
            mobile   = []
            for p in to_send:
                e164  = to_e164(p.get("phone", ""))
                ctype = classify_phone(e164) if e164 else "invalid"
                carrier_map[id(p)] = ctype
                if ctype in ("landline", "voip", "invalid"):
                    p["sms_status"] = ctype
                    landline.append(p)
                else:
                    mobile.append(p)
            if landline:
                save_prospects(prospects, fieldnames, args.input)
            print(f"  {len(mobile)} mobile  |  {len(landline)} landline/VoIP/invalid (skipped, free)\n")
            to_send = mobile
        else:
            print("  [INFO] phonenumbers not installed — sending to all numbers.")
            print("  [INFO] Run:  pip3 install phonenumbers  to enable free landline filtering.\n")

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
        body     = _get_sms_template(category).format(name=name, url=get_url_for_category(category))
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
