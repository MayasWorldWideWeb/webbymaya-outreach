#!/usr/bin/env python3
"""
clicker_followups.py — Auto follow-up for people who clicked the site link.

Pulls SendGrid click events, finds anyone who clicked 48+ hours ago but
hasn't been followed up yet, and sends them the mockup offer via Gmail.

Runs daily via run_daily.sh. Safe to re-run — skips already-contacted.

USAGE
    python3 clicker_followups.py              # send up to 20
    python3 clicker_followups.py --dry-run    # preview only
    python3 clicker_followups.py --limit 5    # cap sends
    python3 clicker_followups.py --hours 24   # shorter window (default: 48)
"""

import argparse
import base64
import csv
import datetime
import email.mime.multipart
import email.mime.text
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import timezone, timedelta
from pathlib import Path

SCRIPT_DIR       = Path(__file__).parent
SENDER_EMAIL     = "maya@webbymaya.com"
SENDER_NAME      = "Maya Sierra"
SG               = os.environ.get("SENDGRID_API_KEY", "")
GMAIL_TOKEN_PATH = Path.home() / ".webbymaaya/gmail_token.json"
DEFAULT_LIMIT    = 20
MIN_HOURS        = 48
MAX_DAYS         = 14
SEND_DELAY_SEC   = 20

# Subject when a mockup was successfully pre-built
SUBJECT_MOCKUP = "I already built a free website preview for you, {name}"
# Fallback subject when no mockup
SUBJECT_PLAIN  = "Quick follow-up, {name}"

PLAIN_MOCKUP = """\
Hi,

I saw you opened my email — I already built a free website preview for {name}. \
Here it is:

{mockup_url}

It's live and ready. If you like it, just fill out my quick intake form and I'll \
get started building the real thing:

https://webbymaya.com/book

Sites start at $799 and go live within a week. No calls needed — everything by email.

— Maya
Web Designer · WebByMaya.com
maya@webbymaya.com
"""

HTML_MOCKUP = """\
<html><body style="font-family:Arial,sans-serif;color:#333;max-width:600px;margin:auto;padding:20px">
<p>Hi,</p>
<p>I saw you opened my email — I already built a free website preview for <strong>{name}</strong>.</p>
<table width="100%" cellpadding="0" cellspacing="0" style="margin:20px 0;">
  <tr>
    <td style="background:#0d0d0d;border-radius:8px;padding:24px;text-align:center;">
      <div style="font-size:11px;text-transform:uppercase;letter-spacing:2px;color:#C9A96E;margin-bottom:10px;font-family:Arial,sans-serif;">Your free website preview</div>
      <a href="{mockup_url}" style="display:inline-block;background:#C9A96E;color:#0d0d0d;padding:14px 32px;border-radius:6px;font-weight:800;font-size:15px;font-family:Arial,sans-serif;text-decoration:none;">
        &#128064;&nbsp; View Your Preview &rarr;
      </a>
      <div style="font-size:12px;color:#666;margin-top:10px;font-family:Arial,sans-serif;">It's live and ready — takes 2 minutes to look at</div>
    </td>
  </tr>
</table>
<p>If you like it, fill out my quick intake form and I'll build the real thing:</p>
<p><a href="https://webbymaya.com/book" style="background:#C9A96E;color:#111;padding:10px 22px;text-decoration:none;font-weight:bold;border-radius:4px;display:inline-block;font-family:Arial,sans-serif;">Fill Out My Website Form &rarr;</a></p>
<p style="color:#888;font-size:13px;">Sites start at $799 · Live in one week · No calls needed</p>
<p>— Maya<br>Web Designer · <a href="https://webbymaya.com">WebByMaya.com</a></p>
</body></html>
"""

PLAIN_PLAIN = """\
Hi,

I saw you opened my email — thanks for taking a look!

I'd love to build a free website preview for your business. \
If you're curious, just fill out my quick intake form and I'll send one over within 24 hours:

https://webbymaya.com/book

Sites start at $799 and go live within a week. No calls needed.

— Maya
Web Designer · WebByMaya.com
"""

HTML_PLAIN = """\
<html><body style="font-family:Arial,sans-serif;color:#333;max-width:600px;margin:auto;padding:20px">
<p>Hi,</p>
<p>I saw you opened my email — thanks for taking a look!</p>
<p>I'd love to build a <strong>free website preview</strong> for your business. \
Fill out my quick intake form and I'll send one over within 24 hours:</p>
<p><a href="https://webbymaya.com/book" style="background:#C9A96E;color:#111;padding:10px 22px;text-decoration:none;font-weight:bold;border-radius:4px;display:inline-block;font-family:Arial,sans-serif;">Fill Out My Website Form &rarr;</a></p>
<p style="color:#888;font-size:13px;">Sites start at $799 · Live in one week · No calls needed</p>
<p>— Maya<br>Web Designer · <a href="https://webbymaya.com">WebByMaya.com</a></p>
</body></html>
"""

# Domains that are bots / wrong enrichment — skip these
BOT_DOMAINS = {
    "sba.gov","dnr.ohio.gov","dnr.gov","usda.gov","hhs.gov","nih.gov","adr.org",
    "ftc.gov","irs.gov","state.pa.us","state.nj.us","epa.gov","cdc.gov",
    "phila.gov","pa.gov","nj.gov","courts.phila.gov",
    "pennmedicine.upenn.edu","upenn.edu","temple.edu","drexel.edu",
    "meta.com","facebook.com","google.com","microsoft.com","apple.com","amazon.com",
    "dailymail.com","billypenn.com","nytimes.com","washingtonpost.com","cnn.com",
    "reuters.com","apnews.com","bloomberg.com","wsj.com","forbes.com","inc.com",
    "aura.com","zendesk.com","hubspot.com","salesforce.com","stripe.com",
    "prweb.com","businesswire.com","prnewswire.com",
    "fresha.com","birdeye.com","yelp.com","yext.com","thryv.com",
    "grubhub.com","doordash.com","ubereats.com","opentable.com",
    "squareup.com","toasttab.com",
}


# ── Mockup auto-generator ─────────────────────────────────────────────────────

def _load_lead_status() -> dict:
    """email (lowercase) → row dict from lead_status.csv"""
    path = SCRIPT_DIR / "lead_status.csv"
    if not path.exists():
        return {}
    out = {}
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            e = row.get("email", row.get("phone", "")).strip().lower()
            if e and "@" in e:
                out[e] = row
    return out

def try_generate_mockup(name: str, email_addr: str, lead_row: dict):
    """Generate a mockup for this lead. Returns local dashboard URL or None."""
    try:
        sys.path.insert(0, str(SCRIPT_DIR))
        import generate_mockup as gm
        category = lead_row.get("category", "").strip() if lead_row else ""
        phone    = lead_row.get("phone", "").strip()    if lead_row else ""
        address  = lead_row.get("address", "").strip()  if lead_row else ""
        if "@" in phone:   # phone column sometimes holds email fallback
            phone = ""
        city   = lead_row.get("city", "Philadelphia, PA").strip() if lead_row else "Philadelphia, PA"
        theme  = gm.get_theme(category)
        fkeys  = gm.get_flickr_keys(category)
        html   = gm.generate_html(name, category, phone, city, theme, fkeys, address=address)
        fname  = gm.slug(name) + ".html"
        out    = gm.MOCKUPS_DIR / fname
        out.write_text(html, encoding="utf-8")
        # Upload to Supabase so the URL works for external recipients
        try:
            from mockup_uploader import upload_mockup
            public_url = upload_mockup(name, category, phone, city)
            if public_url:
                return public_url
        except Exception:
            pass
        return f"http://localhost:8787/mockup/{fname}"
    except Exception as e:
        print(f"  [mockup] failed: {e}")
        return None


# ── Gmail send ────────────────────────────────────────────────────────────────

def _gmail_token() -> str:
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
    access = _gmail_token()
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
                headers={"Authorization": f"Bearer {access}",
                         "Content-Type": "application/json"},
                method="POST",
            )
            urllib.request.urlopen(req, timeout=10)
            return True
        except urllib.error.HTTPError as e:
            print(f"  [GMAIL ERROR] {e.code}: {e.read().decode()[:200]}")
        except Exception as exc:
            print(f"  [GMAIL ERROR] {exc}")
    print("  [ERROR] No valid Gmail token — skipping")
    return False


# ── SendGrid clicker fetch ────────────────────────────────────────────────────

def fetch_clickers() -> list[dict]:
    """Pull recent emails from SendGrid that have at least 1 click."""
    if not SG:
        print("[ERROR] SENDGRID_API_KEY not set")
        return []
    try:
        req  = urllib.request.Request(
            "https://api.sendgrid.com/v3/messages?limit=1000",
            headers={"Authorization": f"Bearer {SG}"})
        msgs = json.loads(urllib.request.urlopen(req, timeout=15).read()).get("messages", [])
    except Exception as e:
        print(f"[ERROR] SendGrid fetch failed: {e}")
        return []

    now     = datetime.datetime.now(timezone.utc)
    cutoff  = now - timedelta(days=MAX_DAYS)
    results = []

    for m in msgs:
        if m.get("clicks_count", 0) < 1:
            continue

        email_addr = m.get("to_email", "").lower().strip()
        if not email_addr or "@" not in email_addr:
            continue

        domain = email_addr.split("@")[-1]
        if domain in BOT_DOMAINS:
            continue

        opens  = m.get("opens_count", 0)
        clicks = m.get("clicks_count", 0)
        # High clicks + zero opens = link scanner bot
        if clicks >= 4 and opens == 0:
            continue

        # Parse click time from last_event_time
        raw_ts = m.get("last_event_time", "")
        try:
            click_time = datetime.datetime.fromisoformat(raw_ts.replace("Z", "+00:00"))
        except Exception:
            continue

        if click_time < cutoff:
            continue

        subj = m.get("subject", "")
        name = (subj
                .replace("Quick question, ", "")
                .replace("Still thinking about it, ", "")
                .rstrip("?").strip()) or email_addr.split("@")[0]

        results.append({
            "email":      email_addr,
            "name":       name,
            "click_time": click_time,
            "clicks":     clicks,
            "opens":      opens,
        })

    # Dedupe — keep most recent click per email
    seen: dict[str, dict] = {}
    for r in results:
        e = r["email"]
        if e not in seen or r["click_time"] > seen[e]["click_time"]:
            seen[e] = r
    return list(seen.values())


# ── State helpers ─────────────────────────────────────────────────────────────

def load_suppressed() -> set:
    out = set()
    path = SCRIPT_DIR / "bounce_log.csv"
    if path.exists():
        with open(path, newline="") as f:
            for row in csv.DictReader(f):
                out.add(row.get("email", "").lower())
    return out


def load_already_sent() -> set:
    """Emails that already got the clicker follow-up."""
    sent = set()
    for p in SCRIPT_DIR.glob("clicker_followup_log_*.csv"):
        with open(p, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                e = row.get("email", "").strip().lower()
                if e:
                    sent.add(e)
    return sent


def log_send(email_addr: str, name: str, status: str):
    today = datetime.date.today().isoformat()
    path  = SCRIPT_DIR / f"clicker_followup_log_{today}.csv"
    new   = not path.exists()
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["timestamp", "email", "name", "status"])
        if new:
            w.writeheader()
        w.writerow({
            "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
            "email":     email_addr,
            "name":      name,
            "status":    status,
        })


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run",  action="store_true")
    p.add_argument("--limit",    type=int, default=DEFAULT_LIMIT)
    p.add_argument("--hours",    type=int, default=MIN_HOURS,
                   help="Min hours since click before sending (default: 48)")
    args = p.parse_args()

    now        = datetime.datetime.now(timezone.utc)
    suppressed = load_suppressed()
    already    = load_already_sent()
    clickers   = fetch_clickers()
    leads      = _load_lead_status()

    due = []
    for c in clickers:
        if c["email"] in suppressed:
            continue
        if c["email"] in already:
            continue
        hours_since = (now - c["click_time"]).total_seconds() / 3600
        if hours_since < args.hours:
            continue
        due.append(c)

    due.sort(key=lambda x: x["click_time"])

    print(f"\nClicker follow-up — {datetime.date.today()}")
    print(f"Clickers found    : {len(clickers)}")
    print(f"Due (48h+ ago)    : {len(due)}")
    print(f"Will send         : {min(len(due), args.limit)}")
    if args.dry_run:
        print("MODE: DRY RUN\n")

    sent_count = failed = 0

    for i, c in enumerate(due[:args.limit]):
        name      = c["name"]
        to        = c["email"]
        hrs       = round((now - c["click_time"]).total_seconds() / 3600, 1)
        lead_row  = leads.get(to)

        print(f"\n[{i+1}/{min(len(due), args.limit)}] {name} <{to}>  ({hrs}h ago)")

        # Try to pre-generate mockup
        mockup_url = None
        if not args.dry_run:
            print("  Generating mockup...")
            mockup_url = try_generate_mockup(name, to, lead_row)
            if mockup_url:
                print(f"  Mockup ready: {mockup_url}")

        if mockup_url:
            subject = SUBJECT_MOCKUP.format(name=name)
            plain   = PLAIN_MOCKUP.format(name=name, mockup_url=mockup_url)
            html    = HTML_MOCKUP.format(name=name, mockup_url=mockup_url)
        else:
            subject = SUBJECT_PLAIN.format(name=name)
            plain   = PLAIN_PLAIN
            html    = HTML_PLAIN

        print(f"  Subject  : {subject}")

        if args.dry_run:
            print("  [DRY RUN] Would send ↑")
            continue

        ok = send_email(to, subject, plain, html)
        if ok:
            log_send(to, name, "sent_mockup" if mockup_url else "sent")
            sent_count += 1
            print("  Sent.")
            if i < min(len(due), args.limit) - 1:
                time.sleep(SEND_DELAY_SEC)
        else:
            log_send(to, name, "failed")
            failed += 1

    print(f"\n{'─'*40}")
    if args.dry_run:
        print(f"Dry run — {len(due[:args.limit])} would be sent.")
    else:
        print(f"Done — {sent_count} sent, {failed} failed.")


if __name__ == "__main__":
    main()
