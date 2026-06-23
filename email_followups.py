#!/usr/bin/env python3
"""
email_followups.py — WebByMaya Email Follow-up Sender
======================================================
Finds businesses that were emailed 7+ days ago with no reply and sends
a short warm follow-up. Skips anyone already followed up, bounced, or
who replied.

USAGE
-----
    python3 email_followups.py              # send up to 10 follow-ups
    python3 email_followups.py --dry-run    # preview, send nothing
    python3 email_followups.py --limit 20   # send up to 20
    python3 email_followups.py --days 5     # follow up after 5 days instead of 7
    python3 email_followups.py --round 2    # 14-day second follow-up (different message)
"""

import argparse
import base64
import csv
import datetime
import email.mime.multipart
import email.mime.text
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import timezone, timedelta
from pathlib import Path

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

SCRIPT_DIR       = Path(__file__).parent
SENDER_EMAIL     = "maya@webbymaya.com"
SENDER_NAME      = "Maya Sierra"
SENDGRID_API_KEY = os.environ.get("SENDGRID_API_KEY", "")
GMAIL_TOKEN_PATH = Path.home() / ".webbymaaya/gmail_token.json"
DEFAULT_LIMIT    = 10
DEFAULT_MIN_DAYS = 7
SEND_DELAY_SEC   = 30

# ── Round 1 (7-day) ──────────────────────────────────────────────────────────

FOLLOWUP_SUBJECT = "Did my last email reach you, {name}?"

FOLLOWUP_PLAIN = """\
Hi {business_name} team,

Just checking in — I reached out a little while ago about building a website \
for {business_name}, and wanted to make sure it didn't get buried.

If the timing isn't right, no worries at all. But if getting {business_name} \
online has been on your mind, I'd love to help. I build clean, fast, \
mobile-ready sites for Philly businesses starting at $799 — live in 7 days.

Get started (takes 10 min, no calls needed): https://webbymaya.com/book
Or just reply here — I check this daily.

— Maya
Web Designer · WebByMaya.com
maya@webbymaya.com
"""

FOLLOWUP_HTML = """\
<html><body style="font-family:Arial,sans-serif;color:#333;max-width:600px;margin:auto;padding:20px">
<p>Hi <strong>{business_name}</strong> team,</p>
<p>Just checking in — I reached out a little while ago about building a website
for <strong>{business_name}</strong>, and wanted to make sure it didn't get buried.</p>
<p>If the timing isn't right, no worries at all. But if getting
<strong>{business_name}</strong> online has been on your mind, I'd love to help.
I build clean, fast, mobile-ready sites for Philly businesses
<strong>starting at $799 — live in 7 days.</strong></p>
<p><a href="https://webbymaya.com/book" style="background:#C9A96E;color:#000;padding:10px 20px;text-decoration:none;border-radius:4px;display:inline-block;font-weight:bold">Get started — no calls needed →</a></p>
<p>Or just reply here — I check this daily.</p>
<p>— Maya<br>Web Designer · <a href="https://webbymaya.com">WebByMaya.com</a></p>
</body></html>
"""

# ── Round 2 (14-day) — shorter, softer last touch ────────────────────────────

FOLLOWUP2_SUBJECT = "Last one from me, {name}"

FOLLOWUP2_PLAIN = """\
Hi {business_name} team,

I won't keep reaching out after this — just wanted to leave the door open.

If a website for {business_name} ever makes sense, I'm here. starting at $499, \
live in 7 days, no calls needed.

https://webbymaya.com/book

— Maya
"""

FOLLOWUP2_HTML = """\
<html><body style="font-family:Arial,sans-serif;color:#333;max-width:600px;margin:auto;padding:20px">
<p>Hi <strong>{business_name}</strong> team,</p>
<p>I won't keep reaching out after this — just wanted to leave the door open.</p>
<p>If a website for <strong>{business_name}</strong> ever makes sense, I'm here.
<strong>starting at $499, live in 7 days, no calls needed.</strong></p>
<p><a href="https://webbymaya.com/book" style="background:#C9A96E;color:#000;padding:10px 20px;text-decoration:none;border-radius:4px;display:inline-block;font-weight:bold">Start here →</a></p>
<p>— Maya<br>Web Designer · <a href="https://webbymaya.com">WebByMaya.com</a></p>
</body></html>
"""

# ── Round 3 (21-day) — closing-the-file scarcity play ────────────────────────

FOLLOWUP3_SUBJECT = "closing your file — {name}"

FOLLOWUP3_PLAIN = """\
Hi {business_name} team,

I've reached out a couple of times now and haven't heard back, so I'm going \
to close out your file and move on to other businesses.

If the timing was never right, no hard feelings at all.

But if a website for {business_name} is still on your radar — even months \
from now — my form stays open:

https://webbymaya.com/book

starting at $499, no monthly fees, live in 7 days.

Wishing you and your business the best.

— Maya
Web Designer · WebByMaya.com
"""

FOLLOWUP3_HTML = """\
<html><body style="font-family:Arial,sans-serif;color:#555;max-width:580px;margin:auto;padding:24px">
<p style="font-size:13px;color:#aaa;margin-bottom:18px">Final note from WebByMaya</p>
<p style="font-size:15px;color:#333">Hi <strong>{business_name}</strong> team,</p>
<p>I've reached out a couple of times and haven't heard back — so I'm going to close
out your file and stop following up.</p>
<p>If the timing was never right, truly no hard feelings.</p>
<p>But if a website ever makes sense for <strong>{business_name}</strong>, my form
stays open. <strong style="color:#333">starting at $499 · live in 7 days &middot; no calls needed.</strong></p>
<p style="margin:24px 0">
  <a href="https://webbymaya.com/book"
    style="background:#C9A96E;color:#000;padding:11px 22px;text-decoration:none;
    border-radius:4px;display:inline-block;font-weight:bold;font-size:14px">
    webbymaya.com/book
  </a>
</p>
<p style="color:#888;font-size:13px">Wishing you and your business the best.</p>
<p style="color:#888;font-size:13px">— Maya<br>
<a href="https://webbymaya.com" style="color:#C9A96E;text-decoration:none">WebByMaya.com</a></p>
</body></html>
"""

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Domains that are clearly not the business's own email
_JUNK_DOMAINS = {
    "fresha.com", "birdeye.com", "yelp.com", "yext.com", "thryv.com",
    "grubhub.com", "doordash.com", "ubereats.com", "opentable.com",
    "booking.com", "tripadvisor.com", "squareup.com", "toasttab.com",
    "phila.gov", "courts.phila.gov", "pa.gov", "philasd.org",
    "adr.org", "bbb.org",
    "info.com", "weeklyad.us.com",
    "suplery.com", "marketingmavericks.co.uk",
    "aspwv.com", "pasenate.com",
    "tommybahama.com", "mayfairhotels.com",
    "instantstreetview.com", "riversidecounseling.net",
    "motomundohn.com", "nbd.ltd", "ewb.rs",
}

# Personal/small-biz email providers — always trustworthy
_PERSONAL_DOMAINS = {
    "gmail.com", "yahoo.com", "outlook.com", "hotmail.com",
    "icloud.com", "aol.com", "live.com", "msn.com",
}

def _is_junk_email(email: str) -> bool:
    domain = email.split("@")[-1].lower() if "@" in email else ""
    if domain in _JUNK_DOMAINS:
        return True
    if domain.endswith(".gov") or domain.endswith(".edu"):
        return True
    local = email.split("@")[0].lower()
    if local in {"info", "server", "contact", "noreply", "no-reply",
                 "support", "hello", "customerservice", "admin",
                 "webmaster", "profiles", "rebuild", "jury",
                 "collegeandcareer", "accessibility", "reservations",
                 "frontdesk", "office", "servicio", "service"}:
        return True
    return False


def _is_safe_email(email: str) -> bool:
    """True when the email is a personal account or a org-email address."""
    domain = email.split("@")[-1].lower() if "@" in email else ""
    return domain in _PERSONAL_DOMAINS


def load_suppressed() -> set:
    path = SCRIPT_DIR / "bounce_log.csv"
    if not path.exists():
        return set()
    with open(path, newline="") as f:
        return {row["email"].lower() for row in csv.DictReader(f)}


def load_sent_emails() -> dict:
    """Returns dict: email -> {name, category, first_sent (date str)}"""
    contacts = {}
    for p in sorted(SCRIPT_DIR.glob("send_log_*.csv")):
        with open(p, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if row.get("status") != "sent":
                    continue
                email = row.get("email_sent_to", "").strip().lower()
                if not email:
                    continue
                ts = row.get("timestamp", "")[:10]
                name = row.get("name", "").strip()
                category = row.get("category", "").strip()
                if email not in contacts:
                    contacts[email] = {"email": email, "name": name,
                                       "category": category, "first_sent": ts}
                elif ts < contacts[email]["first_sent"]:
                    contacts[email]["first_sent"] = ts
    return contacts


def load_already_followed_up(round: int = 1) -> set:
    """Return set of emails that already got the given round of follow-up."""
    followed = set()
    pattern = {1: "email_followup_log_*.csv",
               2: "email_followup2_log_*.csv",
               3: "email_followup3_log_*.csv"}.get(round, "email_followup_log_*.csv")
    for p in SCRIPT_DIR.glob(pattern):
        with open(p, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                e = row.get("email", "").strip().lower()
                if e:
                    followed.add(e)
    return followed


def log_followup(email: str, name: str, status: str, round: int = 1):
    today = datetime.date.today().isoformat()
    prefix = {1: "email_followup_log", 2: "email_followup2_log",
              3: "email_followup3_log"}.get(round, "email_followup_log")
    path   = SCRIPT_DIR / f"{prefix}_{today}.csv"
    exists = path.exists()
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["timestamp", "email", "name", "status"])
        if not exists:
            w.writeheader()
        w.writerow({
            "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
            "email": email,
            "name": name,
            "status": status,
        })


def _gmail_access_token() -> str:
    if not GMAIL_TOKEN_PATH.exists():
        return ""
    tok = json.loads(GMAIL_TOKEN_PATH.read_text())
    access = tok.get("token", "")
    try:
        exp = datetime.datetime.fromisoformat(tok["expiry"].replace("Z", "+00:00"))
        if datetime.datetime.now(timezone.utc) >= exp - timedelta(seconds=60):
            data = urllib.parse.urlencode({
                "client_id":     tok["client_id"],
                "client_secret": tok["client_secret"],
                "refresh_token": tok["refresh_token"],
                "grant_type":    "refresh_token",
            }).encode()
            resp = json.loads(urllib.request.urlopen(
                urllib.request.Request("https://oauth2.googleapis.com/token", data=data),
                timeout=10).read())
            access = resp["access_token"]
            tok["token"]  = access
            tok["expiry"] = (datetime.datetime.now(timezone.utc) +
                             timedelta(seconds=resp.get("expires_in", 3600))
                             ).strftime("%Y-%m-%dT%H:%M:%SZ")
            GMAIL_TOKEN_PATH.write_text(json.dumps(tok))
    except Exception:
        pass
    return access


def send_email(to: str, subject: str, plain: str, html: str) -> bool:
    access = _gmail_access_token()
    if access:
        try:
            msg = email.mime.multipart.MIMEMultipart("alternative")
            msg["To"]      = to
            msg["From"]    = f"{SENDER_NAME} <{SENDER_EMAIL}>"
            msg["Subject"] = subject
            msg.attach(email.mime.text.MIMEText(plain, "plain"))
            msg.attach(email.mime.text.MIMEText(html,  "html"))
            raw     = base64.urlsafe_b64encode(msg.as_bytes()).decode()
            payload = json.dumps({"raw": raw}).encode()
            req = urllib.request.Request(
                "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
                data=payload,
                headers={"Authorization": f"Bearer {access}", "Content-Type": "application/json"},
                method="POST",
            )
            urllib.request.urlopen(req, timeout=10)
            return True
        except urllib.error.HTTPError as e:
            print(f"  [GMAIL ERROR] {e.code}: {e.read().decode()[:200]}")
        except Exception as exc:
            print(f"  [GMAIL ERROR] {exc}")

    # Fallback: SendGrid
    if not SENDGRID_API_KEY:
        print("  [ERROR] No Gmail token and no SENDGRID_API_KEY — cannot send")
        return False
    payload = json.dumps({
        "personalizations": [{"to": [{"email": to}]}],
        "from": {"email": SENDER_EMAIL, "name": SENDER_NAME},
        "subject": subject,
        "content": [{"type": "text/plain", "value": plain},
                    {"type": "text/html",  "value": html}],
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://api.sendgrid.com/v3/mail/send", data=payload,
        headers={"Authorization": f"Bearer {SENDGRID_API_KEY}",
                 "Content-Type": "application/json"}, method="POST")
    try:
        urllib.request.urlopen(req)
        return True
    except urllib.error.HTTPError as e:
        print(f"  [SG ERROR] {e.code}: {e.read().decode()[:200]}")
        return False
    except Exception as exc:
        print(f"  [ERROR] {exc}")
        return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def parse_args():
    p = argparse.ArgumentParser(description="WebByMaya — follow-up emails to cold-outreach prospects")
    p.add_argument("--dry-run",   action="store_true", help="Preview emails, send nothing")
    p.add_argument("--limit",     type=int, default=DEFAULT_LIMIT, help=f"Max emails to send (default: {DEFAULT_LIMIT})")
    p.add_argument("--days",      type=int, default=DEFAULT_MIN_DAYS, help=f"Min days since first contact (default: {DEFAULT_MIN_DAYS})")
    p.add_argument("--safe-only", action="store_true", help="Only send to gmail/yahoo/outlook/hotmail addresses")
    p.add_argument("--round",     type=int, default=1, choices=[1, 2, 3], help="Follow-up round: 1=7-day, 2=14-day last-touch, 3=21-day goodbye (default: 1)")
    return p.parse_args()


def main():
    args       = parse_args()
    today      = datetime.date.today()
    suppressed = load_suppressed()
    sent       = load_sent_emails()
    followed   = load_already_followed_up(round=args.round)

    # Round 2/3 require prior rounds to have been sent
    round1_sent = load_already_followed_up(round=1) if args.round >= 2 else set()
    round2_sent = load_already_followed_up(round=2) if args.round == 3 else set()

    # Pick templates based on round
    if args.round == 3:
        min_days      = 21
        subject_tmpl  = FOLLOWUP3_SUBJECT
        plain_tmpl    = FOLLOWUP3_PLAIN
        html_tmpl     = FOLLOWUP3_HTML
        log_label     = "email_followup3_log"
    elif args.round == 2:
        min_days      = 14
        subject_tmpl  = FOLLOWUP2_SUBJECT
        plain_tmpl    = FOLLOWUP2_PLAIN
        html_tmpl     = FOLLOWUP2_HTML
        log_label     = "email_followup2_log"
    else:
        min_days      = args.days
        subject_tmpl  = FOLLOWUP_SUBJECT
        plain_tmpl    = FOLLOWUP_PLAIN
        html_tmpl     = FOLLOWUP_HTML
        log_label     = "email_followup_log"

    # Build list of due follow-ups
    due = []
    for email, c in sent.items():
        if email in suppressed:
            continue
        if email in followed:
            continue
        if args.round >= 2 and email not in round1_sent:
            continue  # must have received round 1 first
        if args.round == 3 and email not in round2_sent:
            continue  # must have received round 2 first
        if _is_junk_email(email):
            continue
        if args.safe_only and not _is_safe_email(email):
            continue
        try:
            first = datetime.date.fromisoformat(c["first_sent"])
        except Exception:
            continue
        if (today - first).days >= min_days:
            due.append(c)

    due.sort(key=lambda x: x["first_sent"])  # oldest first

    label = f"round {args.round}"
    print(f"\nFollow-up candidates ({label}): {len(due)}  (contacted {min_days}+ days ago, not yet followed up)")
    print(f"Will send: {min(len(due), args.limit)}")
    if args.dry_run:
        print("MODE: DRY RUN — nothing will be sent\n")

    sent_count = failed_count = skipped_count = 0

    for i, c in enumerate(due[:args.limit]):
        email    = c["email"]
        name     = c["name"] or "your business"
        subject  = subject_tmpl.format(name=name)
        plain    = plain_tmpl.format(business_name=name)
        html     = html_tmpl.format(business_name=name)

        print(f"\n[{i+1}/{min(len(due), args.limit)}] {name}")
        print(f"  Email  : {email}")
        print(f"  Subject: {subject}")
        print(f"  First contacted: {c['first_sent']}")

        if args.dry_run:
            print("  [DRY RUN] Would send ↑")
            print(f"  Preview:\n    {plain.splitlines()[2][:80]}")
            skipped_count += 1
            continue

        success = send_email(email, subject, plain, html)
        if success:
            log_followup(email, name, "sent", round=args.round)
            sent_count += 1
            print(f"  Sent.")
            if i < min(len(due), args.limit) - 1:
                time.sleep(SEND_DELAY_SEC)
        else:
            log_followup(email, name, "failed", round=args.round)
            failed_count += 1

    print(f"\n{'─'*40}")
    if args.dry_run:
        print(f"Dry run complete — {skipped_count} would be sent.")
    else:
        print(f"Done — {sent_count} sent, {failed_count} failed.")
        if sent_count:
            print(f"Log: {log_label}_{today.isoformat()}.csv")


if __name__ == "__main__":
    main()
