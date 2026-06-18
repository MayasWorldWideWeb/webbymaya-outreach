#!/usr/bin/env python3
"""
check_replies.py — WebByMaya Gmail Reply Checker
=================================================
Scans Gmail inbox for replies from any business you've contacted.
Shows name, email, date, and message preview.
Sends a Mac desktop notification for replies you haven't seen yet.

SETUP (one time only):
    python3 gmail_auth.py   # opens browser, grants Gmail read access

USAGE:
    python3 check_replies.py          # show unseen replies + notify
    python3 check_replies.py --all    # show all replies ever
"""

import base64
import csv
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

SCRIPT_DIR  = Path(__file__).parent
STATE_FILE  = SCRIPT_DIR / ".seen_replies.json"
CREDS_PATH  = Path.home() / ".webbymaaya/gmail_credentials.json"
TOKEN_PATH  = Path.home() / ".webbymaaya/gmail_token.json"

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

BOLD  = "\033[1m"
G     = "\033[32m"
Y     = "\033[33m"
C     = "\033[36m"
DIM   = "\033[2m"
R     = "\033[0m"


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

def get_gmail_service():
    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
    except ImportError:
        sys.exit(
            "Missing Google libraries. Run:\n"
            "  pip install google-auth google-auth-oauthlib google-auth-httplib2 google-api-python-client"
        )

    if not TOKEN_PATH.exists():
        sys.exit(
            "Gmail not authorized yet. Run this first:\n"
            "  python3 gmail_auth.py"
        )

    creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        TOKEN_PATH.write_text(creds.to_json())

    return build("gmail", "v1", credentials=creds)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_contacted_emails() -> dict:
    """Returns {email_lower: business_name} for all sent emails."""
    contacts = {}
    for p in sorted(SCRIPT_DIR.glob("send_log_*.csv")):
        with open(p, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if row.get("status") != "sent":
                    continue
                email = row.get("email_sent_to", "").strip().lower()
                name  = row.get("name", "").strip()
                if email:
                    contacts[email] = name
    return contacts


def load_seen() -> set:
    if STATE_FILE.exists():
        return set(json.loads(STATE_FILE.read_text()))
    return set()


def save_seen(seen: set):
    STATE_FILE.write_text(json.dumps(sorted(seen)))


def decode_body(payload) -> str:
    """Extract plain text from a Gmail message payload."""
    def _decode(data):
        try:
            return base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace")
        except Exception:
            return ""

    mime = payload.get("mimeType", "")
    if mime == "text/plain":
        return _decode(payload.get("body", {}).get("data", ""))
    if mime.startswith("multipart"):
        for part in payload.get("parts", []):
            text = decode_body(part)
            if text.strip():
                return text
    return ""


def mac_notify(title: str, message: str):
    script = f'display notification "{message}" with title "{title}" sound name "Glass"'
    try:
        subprocess.run(["osascript", "-e", script], check=False, capture_output=True)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    import argparse
    parser = argparse.ArgumentParser(description="WebByMaya — check Gmail for replies")
    parser.add_argument("--all", action="store_true", help="Show all replies, not just unseen")
    args = parser.parse_args()

    contacts = load_contacted_emails()
    if not contacts:
        print("No sent emails found in send logs.")
        return

    print(f"\n  {BOLD}{C}WebByMaya — Reply Checker{R}")
    print(f"  {DIM}Scanning Gmail for replies from {len(contacts)} contacted businesses…{R}\n")

    service = get_gmail_service()
    seen    = load_seen()

    # Build search query in batches (Gmail query length limit)
    email_list = list(contacts.keys())
    batch_size = 30
    all_message_ids = []

    for i in range(0, len(email_list), batch_size):
        batch   = email_list[i:i+batch_size]
        from_q  = " OR ".join(f"from:{e}" for e in batch)
        query   = f"in:inbox ({from_q})"
        result  = service.users().messages().list(userId="me", q=query, maxResults=50).execute()
        all_message_ids.extend(result.get("messages", []))

    if not all_message_ids:
        print(f"  {DIM}No replies found yet. Check back after 24–48 hours.{R}\n")
        return

    replies    = []
    new_ids    = []

    for msg_ref in all_message_ids:
        mid = msg_ref["id"]
        msg = service.users().messages().get(
            userId="me", id=mid, format="full"
        ).execute()

        headers = {h["name"].lower(): h["value"] for h in msg["payload"].get("headers", [])}
        from_raw = headers.get("from", "")
        # Extract bare email from "Name <email>" format
        if "<" in from_raw:
            from_email = from_raw.split("<")[1].rstrip(">").strip().lower()
        else:
            from_email = from_raw.strip().lower()

        subject  = headers.get("subject", "(no subject)")
        date_str = headers.get("date", "")
        body     = decode_body(msg["payload"])
        snippet  = body.strip().replace("\n", " ")[:120]
        biz_name = contacts.get(from_email, from_email)
        is_new   = mid not in seen

        replies.append({
            "id": mid, "from": from_email, "name": biz_name,
            "subject": subject, "date": date_str,
            "snippet": snippet, "is_new": is_new,
        })
        if is_new:
            new_ids.append(mid)

    # Filter to unseen unless --all
    to_show = replies if args.all else [r for r in replies if r["is_new"]]

    if not to_show:
        total = len(replies)
        print(f"  {G}No new replies.{R} {DIM}({total} total replies seen previously){R}\n")
        return

    # Mac notification for new replies
    if new_ids:
        names = ", ".join(r["name"] for r in replies if r["is_new"])[:60]
        mac_notify("WebByMaya — New Reply!", f"{len(new_ids)} reply from: {names}")

    label = "NEW REPLIES" if not args.all else "ALL REPLIES"
    print(f"  {BOLD}{G}{'─'*54}{R}")
    print(f"  {BOLD}{G}{label} ({len(to_show)}){R}")
    print(f"  {BOLD}{G}{'─'*54}{R}\n")

    for r in to_show:
        badge = f"{G}● NEW{R}  " if r["is_new"] else f"{DIM}○ seen{R} "
        print(f"  {badge}{BOLD}{r['name']}{R}")
        print(f"  {DIM}From   :{R} {r['from']}")
        print(f"  {DIM}Subject:{R} {r['subject']}")
        print(f"  {DIM}Date   :{R} {r['date']}")
        if r["snippet"]:
            print(f"  {DIM}Preview:{R} {r['snippet']}")
        print()

    # Mark all as seen
    seen.update(r["id"] for r in replies)
    save_seen(seen)


if __name__ == "__main__":
    main()
