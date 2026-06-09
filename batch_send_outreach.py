"""
batch_send_outreach.py — WebByMaya Batch Outreach Email Sender
==============================================================
Reads prospects from either a CSV file or a Notion database, sends each
one a personalized cold-outreach email via Gmail, then marks them
"Contacted" in Notion and writes a send log.

SETUP
-----
1. Install dependencies:
       pip install google-auth google-auth-oauthlib google-auth-httplib2 \
                   google-api-python-client requests

2. Gmail OAuth2 credentials
   a) In Google Cloud Console, create an OAuth 2.0 Client ID (Desktop app).
   b) Download the JSON file and save it to:
          ~/.webbymaaya/gmail_credentials.json
   c) On first run the script opens a browser for you to approve access.
      The resulting token is saved to  ~/.webbymaaya/gmail_token.json
      and reused automatically on future runs.
   Required Gmail scope: https://www.googleapis.com/auth/gmail.send

3. Notion API key (only needed when --input notion):
       export NOTION_API_KEY="secret_..."
   The Notion integration must be connected to the "WebByMaya Outreach" database.
   Expected database properties:
       Name           (title)
       Status         (select) — values: "New", "Contacted"
       Date contacted (date)
       Category       (select or rich_text)  [optional, used for personalisation]
       Phone          (phone_number)          [optional]
       Address        (rich_text)             [optional]
       Maps URL       (url)                   [optional]
       Place ID       (rich_text)             [optional]

USAGE
-----
   # From CSV (10 emails max, real sends)
   python batch_send_outreach.py --input prospects_2026-05-27.csv

   # From Notion (real sends, custom limit)
   python batch_send_outreach.py --input notion --limit 5

   # Dry run — prints emails, sends nothing, does NOT update Notion
   python batch_send_outreach.py --input prospects_2026-05-27.csv --dry-run

FLAGS
-----
   --input PATH_OR_NOTION   CSV file path or the word "notion"  (required)
   --dry-run                Print emails only; do not send or update Notion
   --limit N                Max emails per run (default: 10)

OUTPUT
------
   send_log_YYYY-MM-DD.csv  — one row per attempted send
"""

import argparse
import csv
from sb import log_email
import datetime
import json
import os
import sys
import time
import base64
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pathlib import Path

# ---------------------------------------------------------------------------
# Optional imports — checked at runtime so error messages are helpful
# ---------------------------------------------------------------------------

def _require(package: str, install_hint: str):
    """Import a package or exit with a clear install instruction."""
    import importlib
    mod = importlib.import_module(package)
    return mod


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SENDER_EMAIL = "mayas.worldwide.web@gmail.com"
SENDER_NAME  = "Maya Sierra"

SENDGRID_API_KEY = os.environ.get("SENDGRID_API_KEY", "")

# Notion API base
NOTION_API_BASE = "https://api.notion.com/v1"
NOTION_VERSION  = "2022-06-28"

# Delay (seconds) between sends to stay well clear of spam filters
SEND_DELAY_SECONDS = 30

# Load suppressed (bounced/blocked) emails so we never retry them
def _load_suppressed() -> set:
    path = Path(__file__).parent / "bounce_log.csv"
    if not path.exists():
        return set()
    import csv as _csv
    with open(path, newline="") as f:
        return {row["email"].lower() for row in _csv.DictReader(f)}

SUPPRESSED_EMAILS = _load_suppressed()

# Default maximum emails per run
DEFAULT_LIMIT = 10

# ---------------------------------------------------------------------------
# Email template
# ---------------------------------------------------------------------------

EMAIL_SUBJECT = "Your next customer can't find you online"

# HTML template path — sits next to this script's parent directory
_SCRIPT_DIR   = Path(__file__).parent
_TEMPLATE_PATH = _SCRIPT_DIR.parent / "webbymaaya-email-template.html"

# Plain-text fallback (shown by email clients that block HTML)
EMAIL_PLAIN_TEMPLATE = """\
Hi there,

I noticed {business_name} doesn't have a website yet. Right now, anyone in \
Philadelphia searching for a {business_type} can't find you online — no Google \
listing, no hours, no way to reach you except word of mouth.

I'm Maya — a web designer based right here in Philly. I build clean, \
fast, mobile-ready websites for local businesses starting at an affordable price.

Book a free 20-min call: https://webbymaya.com/book

Or just reply to this email — I check it daily.

Maya Sierra
Web Designer · WebByMaya.com
mayas.worldwide.web@gmail.com
"""

# Category → friendly description map
_TYPE_MAP = {
    "restaurant":       "restaurant",
    "cafe":             "cafe",
    "bakery":           "bakery",
    "food":             "food business",
    "hair salon":       "hair salon",
    "nail salon":       "nail salon",
    "beauty salon":     "beauty salon",
    "spa":              "spa",
    "massage":          "massage business",
    "photographer":     "photography business",
    "videographer":     "videography business",
    "auto repair":      "auto repair shop",
    "mechanic":         "mechanic shop",
    "landscaping":      "landscaping business",
    "lawn care":        "lawn care business",
    "cleaning service": "cleaning service",
    "personal trainer": "personal training business",
    "gym":              "gym",
    "fitness":          "fitness business",
    "tattoo parlor":    "tattoo shop",
    "pet grooming":     "pet grooming business",
    "pet store":        "pet store",
    "florist":          "flower shop",
}


def _friendly_type(category: str) -> str:
    key = category.strip().lower() if category else ""
    return _TYPE_MAP.get(key, key or "business")


def build_email_body(name: str, category: str) -> tuple[str, str]:
    """Return (plain_text, html) tuple for the given business.

    The HTML version uses the branded WebByMaya template with {business_name}
    and {business_type} placeholders filled in. Falls back to inline HTML if
    the template file is missing.
    """
    friendly = _friendly_type(category)

    plain = EMAIL_PLAIN_TEMPLATE.format(
        business_name=name,
        business_type=friendly,
    )

    if _TEMPLATE_PATH.exists():
        raw_html = _TEMPLATE_PATH.read_text(encoding="utf-8")
        html = raw_html.replace("{business_name}", name).replace("{business_type}", friendly)
    else:
        # Minimal inline fallback so sends still work if template file is moved
        html = f"""<html><body style="font-family:Arial,sans-serif;color:#333;max-width:600px;margin:auto">
<p>Hi there,</p>
<p>I noticed <strong>{name}</strong> doesn't have a website yet. Right now anyone
searching for a {friendly} in Philadelphia can't find you online.</p>
<p>I'm Maya — a web designer based right here in Philly. I build clean, affordable sites
for local businesses.</p>
<p><a href="https://webbymaya.com/book" style="background:#C9A96E;color:#111;
padding:12px 24px;text-decoration:none;font-weight:bold;border-radius:3px;
display:inline-block">Book a free 20-min call →</a></p>
<p style="color:#888;font-size:12px">Or just reply — I check email daily.<br><br>
Maya Sierra · Web Designer · <a href="https://webbymaya.com">WebByMaya.com</a></p>
</body></html>"""

    return plain, html


# ---------------------------------------------------------------------------
# SendGrid helper
# ---------------------------------------------------------------------------

def send_email(to: str, subject: str, plain: str, html: str) -> bool:
    """Send a single email via SendGrid. Returns True on success."""
    import urllib.request
    import urllib.error

    if not SENDGRID_API_KEY:
        print("  [ERROR] SENDGRID_API_KEY not set. Run: source ~/.zshrc")
        return False

    payload = json.dumps({
        "personalizations": [{"to": [{"email": to}]}],
        "from": {"email": SENDER_EMAIL, "name": SENDER_NAME},
        "subject": subject,
        "content": [
            {"type": "text/plain", "value": plain},
            {"type": "text/html",  "value": html},
        ],
    }).encode("utf-8")

    req = urllib.request.Request(
        "https://api.sendgrid.com/v3/mail/send",
        data=payload,
        headers={
            "Authorization": f"Bearer {SENDGRID_API_KEY}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        urllib.request.urlopen(req)
        return True
    except urllib.error.HTTPError as e:
        print(f"  [ERROR] SendGrid {e.code}: {e.read().decode()}")
        return False
    except Exception as exc:
        print(f"  [ERROR] {exc}")
        return False


# ---------------------------------------------------------------------------
# Notion helpers
# ---------------------------------------------------------------------------

def _notion_headers() -> dict:
    api_key = os.environ.get("NOTION_API_KEY", "")
    if not api_key:
        sys.exit(
            "ERROR: NOTION_API_KEY environment variable is not set.\n"
            "Export it before running:  export NOTION_API_KEY='secret_...'"
        )
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type":  "application/json",
        "Notion-Version": NOTION_VERSION,
    }


def find_outreach_database_id() -> str:
    """Search Notion for the 'WebByMaya Outreach' database and return its ID."""
    try:
        import requests
    except ImportError:
        sys.exit("ERROR: requests package not found.  pip install requests")

    resp = requests.post(
        f"{NOTION_API_BASE}/search",
        headers=_notion_headers(),
        json={"query": "WebByMaya Outreach", "filter": {"value": "database", "property": "object"}},
    )
    resp.raise_for_status()
    results = resp.json().get("results", [])
    if not results:
        sys.exit(
            'ERROR: Could not find a Notion database named "WebByMaya Outreach".\n'
            "Make sure the database exists and your integration has access to it."
        )
    return results[0]["id"]


def fetch_notion_prospects(database_id: str) -> list[dict]:
    """
    Query the Notion database for rows where Status = "New".
    Returns a list of prospect dicts (same schema as CSV rows).
    """
    try:
        import requests
    except ImportError:
        sys.exit("ERROR: requests package not found.  pip install requests")

    prospects = []
    payload = {
        "filter": {
            "property": "Status",
            "select": {"equals": "New"},
        }
    }
    url = f"{NOTION_API_BASE}/databases/{database_id}/query"

    while True:
        resp = requests.post(url, headers=_notion_headers(), json=payload)
        resp.raise_for_status()
        data = resp.json()

        for page in data.get("results", []):
            props = page.get("properties", {})

            def get_title(prop_name):
                prop = props.get(prop_name, {})
                titles = prop.get("title", [])
                return titles[0]["plain_text"] if titles else ""

            def get_text(prop_name):
                prop = props.get(prop_name, {})
                rich = prop.get("rich_text", [])
                return rich[0]["plain_text"] if rich else ""

            def get_select(prop_name):
                prop = props.get(prop_name, {})
                sel = prop.get("select")
                return sel["name"] if sel else ""

            def get_phone(prop_name):
                prop = props.get(prop_name, {})
                return prop.get("phone_number", "")

            def get_url(prop_name):
                prop = props.get(prop_name, {})
                return prop.get("url", "")

            prospects.append({
                "notion_page_id": page["id"],
                "name":        get_title("Name"),
                "address":     get_text("Address"),
                "phone":       get_phone("Phone"),
                "category":    get_select("Category") or get_text("Category"),
                "place_id":    get_text("Place ID"),
                "maps_url":    get_url("Maps URL"),
                "has_website": "No",
                "notes":       get_text("Notes") if "Notes" in props else "",
            })

        if not data.get("has_more"):
            break
        payload["start_cursor"] = data["next_cursor"]

    return prospects


def mark_notion_contacted(page_id: str, today_str: str) -> None:
    """Update a Notion page: set Status = Contacted, Date contacted = today."""
    try:
        import requests
    except ImportError:
        return

    payload = {
        "properties": {
            "Status": {
                "select": {"name": "Contacted"}
            },
            "Date contacted": {
                "date": {"start": today_str}
            },
        }
    }
    try:
        resp = requests.patch(
            f"{NOTION_API_BASE}/pages/{page_id}",
            headers=_notion_headers(),
            json=payload,
        )
        resp.raise_for_status()
    except Exception as exc:
        print(f"  [WARN] Could not update Notion page {page_id}: {exc}")


# ---------------------------------------------------------------------------
# CSV helpers
# ---------------------------------------------------------------------------

def load_csv_prospects(path: str) -> list[dict]:
    """Read prospects from a CSV file. Returns list of row dicts."""
    if not os.path.exists(path):
        sys.exit(f"ERROR: CSV file not found: {path}")

    prospects = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            row["notion_page_id"] = ""  # not from Notion
            prospects.append(row)
    return prospects


# ---------------------------------------------------------------------------
# Send log
# ---------------------------------------------------------------------------

LOG_COLUMNS = [
    "timestamp",
    "name",
    "category",
    "email_sent_to",
    "subject",
    "status",
    "notes",
]


def write_log(log_rows: list[dict], output_dir: str = ".") -> str:
    today = datetime.date.today().strftime("%Y-%m-%d")
    path  = os.path.join(output_dir, f"send_log_{today}.csv")
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=LOG_COLUMNS)
        writer.writeheader()
        writer.writerows(log_rows)
    return path


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def parse_args():
    parser = argparse.ArgumentParser(
        description="WebByMaya — batch cold-outreach email sender",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--input",
        required=True,
        metavar="PATH_OR_NOTION",
        help='Path to prospects CSV  OR  the word "notion"',
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print emails without sending; skip Notion updates",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_LIMIT,
        help=f"Max emails to send per run (default: {DEFAULT_LIMIT})",
    )
    parser.add_argument(
        "--website-filter",
        choices=["none", "bad"],
        default=None,
        help="none = only no-website businesses, bad = only dead/parked/soon/social sites",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    today_str = datetime.date.today().strftime("%Y-%m-%d")

    # ---- Load prospects ---------------------------------------------------
    if args.input.lower() == "notion":
        print("Loading prospects from Notion (Status = New) ...")
        db_id = find_outreach_database_id()
        prospects = fetch_notion_prospects(db_id)
        print(f"  Found {len(prospects)} prospect(s) in Notion.")
    else:
        print(f"Loading prospects from CSV: {args.input} ...")
        prospects = load_csv_prospects(args.input)
        print(f"  Found {len(prospects)} prospect(s) in CSV.")

    if not prospects:
        print("No prospects to process. Exiting.")
        return

    # Apply --website-filter
    if args.website_filter == "none":
        prospects = [p for p in prospects if p.get("has_website", "").strip() == "No"]
        print(f"  After filter (no website): {len(prospects)} prospect(s).")
    elif args.website_filter == "bad":
        prospects = [p for p in prospects if p.get("has_website", "").strip().startswith("Yes -")]
        print(f"  After filter (bad/outdated site): {len(prospects)} prospect(s).")

    if not prospects:
        print("No prospects match the filter. Exiting.")
        return

    # Apply --limit
    if args.limit < len(prospects):
        print(f"Limiting to {args.limit} email(s) this run (--limit {args.limit}).")
    prospects = prospects[: args.limit]

    # ---- Validate SendGrid key (skip in dry-run) -------------------------
    if not args.dry_run and not SENDGRID_API_KEY:
        sys.exit("ERROR: SENDGRID_API_KEY not set.\nRun: source ~/.zshrc")

    # ---- Send loop -------------------------------------------------------
    log_rows: list[dict] = []
    sent_count  = 0
    failed_count = 0

    for i, prospect in enumerate(prospects):
        name     = prospect.get("name", "").strip()
        category = prospect.get("category", "").strip()
        phone    = prospect.get("phone", "").strip()
        page_id  = prospect.get("notion_page_id", "")

        if not name:
            print(f"[{i+1}/{len(prospects)}] Skipping row with no business name.")
            continue

        subject       = EMAIL_SUBJECT
        plain, html   = build_email_body(name, category)

        recipient_email = prospect.get("email", "").strip()

        print(f"\n[{i+1}/{len(prospects)}] {name}  ({category})")
        print(f"  Address : {prospect.get('address', '')}")
        print(f"  Phone   : {phone}")
        if recipient_email:
            print(f"  Email   : {recipient_email}")
        else:
            print("  Email   : [not available — skipping send]")

        if args.dry_run:
            print("  --- DRY RUN: email that would be sent ---")
            print(f"  To      : {recipient_email or '(no email on file)'}")
            print(f"  Subject : {subject}")
            print("  Format  : HTML + plain text fallback")
            print("  Preview :")
            for line in plain.splitlines()[:8]:
                print(f"    {line}")
            print("    ...")
            status = "dry_run"
            note   = "Dry run — not sent"
        elif not recipient_email:
            status = "skipped"
            note   = "No email address available"
            print(f"  Skipped — no email address on file.")
        elif recipient_email.lower() in SUPPRESSED_EMAILS:
            status = "skipped"
            note   = "Suppressed — previously bounced or blocked"
            print(f"  Skipped — {recipient_email} is on bounce suppression list.")
        else:
            success = send_email(recipient_email, subject, plain, html)
            if success:
                sent_count += 1
                status = "sent"
                note   = ""
                print(f"  Sent to {recipient_email}.")

                # Update Notion if the prospect came from there
                if page_id:
                    mark_notion_contacted(page_id, today_str)
                    print(f"  Notion updated: Status → Contacted.")
            else:
                failed_count += 1
                status = "failed"
                note   = "Gmail API error — see console output"

        log_rows.append({
            "timestamp":      datetime.datetime.now().isoformat(timespec="seconds"),
            "name":           name,
            "category":       category,
            "email_sent_to":  recipient_email,
            "subject":        subject,
            "status":         status,
            "notes":          note,
        })

        # Throttle between sends (skip delay after the last one or in dry-run)
        if not args.dry_run and recipient_email and i < len(prospects) - 1:
            print(f"  Waiting {SEND_DELAY_SECONDS}s before next send ...")
            time.sleep(SEND_DELAY_SECONDS)

    # ---- Write send log --------------------------------------------------
    log_path = write_log(log_rows)
    if not args.dry_run:
        log_email(log_rows)

    # ---- Summary ---------------------------------------------------------
    print("\n" + "=" * 50)
    if args.dry_run:
        print(f"DRY RUN complete. {len(prospects)} email(s) previewed.")
    else:
        print(f"Done. Sent: {sent_count}  |  Failed: {failed_count}  |  Skipped (no email): {len(log_rows) - sent_count - failed_count}")
    print(f"Send log written to: {log_path}")


if __name__ == "__main__":
    main()
