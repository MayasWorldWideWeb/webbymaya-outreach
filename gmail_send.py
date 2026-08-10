#!/usr/bin/env python3
"""
gmail_send.py — WebByMaya send path that Maya can actually see.

WHY THIS EXISTS
---------------
~6,200 emails went out through Brevo/SendGrid between May 26 and Aug 9 2026
and produced 0 sales, 0 genuine human replies, and no way to inspect what was
actually sent. This module sends a much smaller number of emails through
channels that leave a visible trail and have their own reputation:

  MODE "direct"  (Option A — first touch)
      From:  mayas.worldwide.web@gmail.com
      Via:   smtp.gmail.com — Google's own IPs and sending reputation.
      This is the only mode that improves inbox placement. The From address is
      a plain @gmail.com, which is normal for this audience: 38% of the
      prospect addresses in the send logs are themselves gmail/yahoo/aol.

  MODE "domain"  (Option B — follow-ups)
      From:  maya@webbymaya.com
      Via:   smtp-relay.brevo.com — DKIM-signed for webbymaya.com.
      Same IP pool as the old pipeline, so this does NOT improve deliverability;
      it buys the branded From address for people who already got touch #1.

Both modes IMAP-APPEND a copy into the Gmail "Sent Mail" folder, so every
send — whichever route it took — is visible in one inbox. maya@webbymaya.com
is a Porkbun forwarder into that same Gmail, so replies land beside the sends
and thread correctly.

Plain text only. No HTML template, no tracking pixel, no mockup screenshot.
That is deliberate: the polished HTML version is the one that produced zero
sales, and it costs a headless-Chrome launch per send.

SETUP
-----
Already present in ~/.zshrc — nothing to configure:
    GMAIL_APP_PASSWORD    (16-char app password for mayas.worldwide.web@gmail.com)
    BREVO_SMTP_LOGIN / BREVO_SMTP_KEY   (for --mode domain)

USAGE
-----
    python3 gmail_send.py --to someone@example.com --subject "Hi" --body-file note.txt
    python3 gmail_send.py --csv warm.csv --mode direct --limit 50
    python3 gmail_send.py --csv warm.csv --mode direct --dry-run
    python3 gmail_send.py --status
"""
from __future__ import annotations

import argparse
import csv
import imaplib
import json
import os
import random
import smtplib
import ssl
import sys
import time
from datetime import date, datetime, timedelta
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
STATE_FILE = SCRIPT_DIR / ".gmail_send_state.json"
LOG_HEADER = ["timestamp", "email", "business", "subject", "mode", "status", "notes"]

GMAIL_ADDRESS = os.environ.get("GMAIL_ADDRESS", "mayas.worldwide.web@gmail.com")
DOMAIN_FROM   = os.environ.get("WBM_FROM", "maya@webbymaya.com")
REPLY_TO      = os.environ.get("WBM_REPLY_TO", GMAIL_ADDRESS)

# ---------------------------------------------------------------------------
# Volume control
# ---------------------------------------------------------------------------
# Maya set the target at 50/day. Google's published ceiling for a free account
# is 500/day, but that is for ordinary mail — cold outreach gets an account
# throttled or suspended far below it, and this mailbox has no sending history
# at all. So the cap is 50, reached over two weeks rather than on day one.
# Set GMAIL_RAMP=0 to ignore the ramp and use DAILY_CAP immediately.
DAILY_CAP = int(os.environ.get("GMAIL_DAILY_CAP", "50"))
RAMP_ON   = os.environ.get("GMAIL_RAMP", "1") != "0"
RAMP_SCHEDULE = [(0, 10), (4, 25), (10, 50)]   # (days since first send, cap)

# Cold mail sent in a burst is the single clearest bot signal. Default spacing
# puts 50 sends across roughly 40 minutes.
DELAY_MIN, DELAY_MAX = 30, 65


def _load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text())
    except Exception:
        return {}


def _save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2, sort_keys=True))


def todays_cap(state: dict) -> int:
    """The send ceiling for right now, honouring the warm-up ramp."""
    if not RAMP_ON:
        return DAILY_CAP
    started = state.get("ramp_start")
    if not started:
        return RAMP_SCHEDULE[0][1]
    try:
        days = (date.today() - date.fromisoformat(started)).days
    except Exception:
        return RAMP_SCHEDULE[0][1]
    cap = RAMP_SCHEDULE[0][1]
    for after_days, value in RAMP_SCHEDULE:
        if days >= after_days:
            cap = value
    return min(cap, DAILY_CAP)


def sent_today(state: dict) -> int:
    return int(state.get("counts", {}).get(date.today().isoformat(), 0))


def _record_send(state: dict) -> None:
    today = date.today().isoformat()
    state.setdefault("ramp_start", today)
    counts = state.setdefault("counts", {})
    counts[today] = int(counts.get(today, 0)) + 1
    # Keep the file small — 60 days of history is plenty.
    cutoff = (date.today() - timedelta(days=60)).isoformat()
    state["counts"] = {k: v for k, v in counts.items() if k >= cutoff}
    _save_state(state)


# ---------------------------------------------------------------------------
# Suppression — reuse the existing bounce/unsubscribe list
# ---------------------------------------------------------------------------
try:
    from batch_send_outreach import SUPPRESSED_EMAILS, _list_unsub_headers
except Exception:                                        # standalone fallback
    SUPPRESSED_EMAILS = set()

    def _list_unsub_headers(to: str) -> dict:            # noqa: D103
        return {}

try:
    import offer
    BUSINESS_ADDRESS = offer.BUSINESS_ADDRESS
except Exception:
    BUSINESS_ADDRESS = "7213 Montour St, Philadelphia, PA 19111"


def _footer() -> str:
    """CAN-SPAM requires a physical address and a working opt-out."""
    return (
        "\n\n--\nMaya Sierra · WebByMaya · webbymaya.com\n"
        f"{BUSINESS_ADDRESS}\n"
        "Not interested? Reply STOP and I won't write again."
    )


# ---------------------------------------------------------------------------
# Transport
# ---------------------------------------------------------------------------

def _smtp_settings(mode: str) -> tuple[str, int, str, str, str]:
    """(host, port, username, password, from_address) for the chosen mode."""
    if mode == "direct":
        pw = (os.environ.get("GMAIL_APP_PASSWORD") or "").replace(" ", "")
        if not pw:
            sys.exit("ERROR: GMAIL_APP_PASSWORD not set (check ~/.zshrc).")
        return "smtp.gmail.com", 587, GMAIL_ADDRESS, pw, GMAIL_ADDRESS
    sys.exit(f"ERROR: unknown mode {mode!r} for SMTP (use 'direct')")


def _send_via_brevo_api(msg: EmailMessage, to: str, subject: str, body: str) -> tuple[bool, str]:
    """Option B transport.

    The stored BREVO_SMTP_KEY no longer authenticates (535 on every login
    variant as of 2026-08-09), so the branded-From route goes through Brevo's
    HTTP API instead — the same path batch_send_outreach already uses, and the
    one that logged successful sends today. BREVO_API_KEY_2 is the validated
    sender; BREVO_API_KEY (account #1) is tried only as a fallback."""
    import urllib.request

    keys = [k for k in (os.environ.get("BREVO_API_KEY_2"),
                        os.environ.get("BREVO_API_KEY")) if k]
    if not keys:
        return False, "no BREVO_API_KEY_2 / BREVO_API_KEY set"

    payload = {
        "sender":      {"name": "Maya Sierra", "email": DOMAIN_FROM},
        "replyTo":     {"email": REPLY_TO},
        "to":          [{"email": to}],
        "subject":     subject,
        "textContent": body.rstrip() + _footer(),
    }
    last = "unknown"
    for key in keys:
        req = urllib.request.Request(
            "https://api.brevo.com/v3/smtp/email",
            data=json.dumps(payload).encode(),
            headers={"api-key": key, "content-type": "application/json",
                     "accept": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                if resp.status in (200, 201, 202):
                    return True, "brevo_api"
                last = f"HTTP {resp.status}"
        except Exception as exc:
            last = f"{type(exc).__name__}: {str(exc)[:100]}"
    return False, last


def build_message(to: str, subject: str, body: str, from_addr: str) -> EmailMessage:
    msg = EmailMessage()
    msg["From"]     = f"Maya Sierra <{from_addr}>"
    msg["To"]       = to
    msg["Subject"]  = subject
    msg["Date"]     = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=from_addr.split("@")[-1])
    if REPLY_TO and REPLY_TO != from_addr:
        msg["Reply-To"] = REPLY_TO
    for header, value in (_list_unsub_headers(to) or {}).items():
        msg[header] = value
    msg.set_content(body.rstrip() + _footer())
    return msg


def append_to_sent(msg: EmailMessage) -> bool:
    """Put a copy in Gmail's Sent folder so every send is visible in one place.

    Gmail does this automatically for mail it sends itself, but not for mail
    relayed through Brevo — without this, --mode domain would be invisible."""
    pw = (os.environ.get("GMAIL_APP_PASSWORD") or "").replace(" ", "")
    if not pw:
        return False
    try:
        with imaplib.IMAP4_SSL("imap.gmail.com", ssl_context=ssl.create_default_context()) as imap:
            imap.login(GMAIL_ADDRESS, pw)
            imap.append('"[Gmail]/Sent Mail"', "\\Seen",
                        imaplib.Time2Internaldate(time.time()),
                        msg.as_bytes())
        return True
    except Exception:
        return False


def send_one(to: str, subject: str, body: str, mode: str = "direct",
             dry_run: bool = False) -> tuple[bool, str]:
    """Send a single plain-text email. Returns (ok, note)."""
    if to.lower() in SUPPRESSED_EMAILS:
        return False, "suppressed"

    from_addr = DOMAIN_FROM if mode == "domain" else GMAIL_ADDRESS
    msg = build_message(to, subject, body, from_addr)

    if dry_run:
        return True, "dry_run"

    if mode == "domain":
        ok, note = _send_via_brevo_api(msg, to, subject, body)
        if ok:
            # Brevo doesn't file anything in Gmail, so without this the whole
            # follow-up stream would be invisible again.
            append_to_sent(msg)
        return ok, note

    host, port, user, pw, _ = _smtp_settings(mode)
    try:
        with smtplib.SMTP(host, port, timeout=30) as smtp:
            smtp.starttls(context=ssl.create_default_context())
            smtp.login(user, pw)
            smtp.send_message(msg)
    except Exception as exc:
        return False, f"{type(exc).__name__}: {str(exc)[:120]}"
    return True, mode


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def log_send(email: str, business: str, subject: str, mode: str,
             status: str, notes: str) -> None:
    path = SCRIPT_DIR / f"gmail_send_log_{date.today().isoformat()}.csv"
    new = not path.exists()
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(LOG_HEADER)
        w.writerow([datetime.now().isoformat(timespec="seconds"), email,
                    business, subject, mode, status, notes])


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args():
    p = argparse.ArgumentParser(description="WebByMaya — visible, low-volume email sending")
    p.add_argument("--mode", choices=["direct", "domain"], default="direct",
                   help="direct = Gmail/Google IPs (first touch); "
                        "domain = maya@webbymaya.com via Brevo (follow-ups)")
    p.add_argument("--csv", metavar="FILE",
                   help="CSV with columns: email, name (optional), subject, body")
    p.add_argument("--to", metavar="ADDR", help="Send a single email to this address")
    p.add_argument("--subject", help="Subject for --to")
    p.add_argument("--body-file", metavar="FILE", help="Plain-text body file for --to")
    p.add_argument("--limit", type=int, default=None,
                   help=f"Max sends this run (default: today's cap, ceiling {DAILY_CAP})")
    p.add_argument("--delay", type=int, default=None,
                   help=f"Seconds between sends (default: random {DELAY_MIN}-{DELAY_MAX})")
    p.add_argument("--dry-run", action="store_true", help="Compose and log, send nothing")
    p.add_argument("--status", action="store_true", help="Show today's cap and usage, then exit")
    return p.parse_args()


def main():
    args = parse_args()
    state = _load_state()
    cap = todays_cap(state)
    used = sent_today(state)

    if args.status:
        started = state.get("ramp_start", "not started")
        print(f"\nGmail send status — {date.today().isoformat()}")
        print(f"  From (direct):  {GMAIL_ADDRESS}")
        print(f"  From (domain):  {DOMAIN_FROM}")
        print(f"  Ramp started:   {started}")
        print(f"  Today's cap:    {cap}   (ceiling {DAILY_CAP}, ramp {'on' if RAMP_ON else 'off'})")
        print(f"  Sent today:     {used}")
        print(f"  Remaining:      {max(0, cap - used)}\n")
        return

    remaining = max(0, cap - used)
    if args.limit is not None:
        remaining = min(remaining, args.limit)

    # ── single send ──────────────────────────────────────────────────────────
    if args.to:
        if not args.subject:
            sys.exit("ERROR: --subject is required with --to")
        body = Path(args.body_file).read_text() if args.body_file else sys.stdin.read()
        ok, note = send_one(args.to, args.subject, body, args.mode, args.dry_run)
        log_send(args.to, "", args.subject, args.mode,
                 "sent" if ok else "failed", note)
        print(f"{'✓' if ok else '✗'} {args.to} — {note}")
        if ok and not args.dry_run:
            _record_send(state)
        return

    if not args.csv:
        sys.exit("ERROR: pass --csv FILE or --to ADDR. See --help.")

    rows = list(csv.DictReader(open(args.csv, newline="", encoding="utf-8")))
    if not rows:
        sys.exit(f"No rows in {args.csv}")

    print(f"\n{args.csv}: {len(rows)} rows")
    print(f"Mode: {args.mode}  |  cap today: {cap}  |  already sent: {used}  "
          f"|  will send up to: {remaining}\n")
    if remaining <= 0:
        print("Daily cap reached. Nothing sent.")
        return

    done = failed = 0
    for row in rows:
        if done >= remaining:
            print(f"\nStopped at today's cap ({cap}). {len(rows) - done} rows left for tomorrow.")
            break
        email   = (row.get("email") or "").strip()
        name    = (row.get("name") or row.get("business") or "").strip()
        subject = (row.get("subject") or "").strip()
        body    = (row.get("body") or "").strip()
        if not (email and subject and body):
            log_send(email, name, subject, args.mode, "skipped", "missing field")
            continue

        ok, note = send_one(email, subject, body, args.mode, args.dry_run)
        log_send(email, name, subject, args.mode, "sent" if ok else "failed", note)
        if ok:
            done += 1
            if not args.dry_run:
                _record_send(state)
            print(f"  ✓ {name or email} <{email}>")
        else:
            failed += 1
            print(f"  ✗ {email} — {note}")

        if done < remaining and not args.dry_run:
            time.sleep(args.delay if args.delay is not None
                       else random.randint(DELAY_MIN, DELAY_MAX))

    print(f"\n✓ {done} sent, {failed} failed. "
          f"Log: gmail_send_log_{date.today().isoformat()}.csv")
    print(f"  Everything sent is in {GMAIL_ADDRESS}'s Sent folder.")


if __name__ == "__main__":
    main()
