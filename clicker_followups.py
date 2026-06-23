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
import re
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import timezone, timedelta
from batch_send_outreach import html_card, _ep, _ecta
from pathlib import Path

SCRIPT_DIR       = Path(__file__).parent
SENDER_EMAIL     = "maya@webbymaya.com"
SENDER_NAME      = "Maya Sierra"
SG               = os.environ.get("SENDGRID_API_KEY", "")
GMAIL_TOKEN_PATH = Path.home() / ".webbymaaya/gmail_token.json"
DEFAULT_LIMIT    = 20
MIN_HOURS        = 4
MAX_DAYS         = 14
SEND_DELAY_SEC   = 20

# Subject lines — more specific, acknowledge they actually viewed the preview
SUBJECT_MOCKUP = "You viewed the {name} preview — a few thoughts"
SUBJECT_PLAIN  = "Wanted to check in about {name}'s website"

PLAIN_MOCKUP = """\
Hi,

Just wanted to follow up — I noticed you spent some time on the {name} preview I built.

I take that as a good sign.

If you liked what you saw, I put together a quick form just for you — it shows the \
preview again, lets you tell me what you'd change, and shows you exactly what your \
total would be based on what you select:

{intake_url}

Takes about 5 minutes. No calls, no obligation — just tell me what you want and I'll \
send you a final quote.

I only take on 3–4 new sites per week, so if you're interested, sooner is better.

— Maya
WebByMaya.com · maya@webbymaya.com
"""

PLAIN_PLAIN = """\
Hi,

I saw you opened my email about building a website for {name} — wanted to follow up.

I'd love to build you a free preview so you can see exactly what your site could \
look like before committing to anything.

If you're interested, just reply YES and I'll send one over same day.

— Maya
WebByMaya.com · maya@webbymaya.com
"""

def _html_mockup(name: str, intake_url: str, email: str = "") -> str:
    return html_card(
        _ep(f"Just wanted to follow up — I noticed you spent some time on the <strong>{name}</strong> preview I built. I take that as a good sign.")
        + _ep("I put together a quick form just for you — it shows the preview again, lets you tell me what you'd change, and shows you <strong>exactly what your total would be</strong> based on what you select. Takes about 5 minutes.")
        + _ecta(intake_url, "Open My Personalized Form &rarr;")
        + _ep("No calls &nbsp;&middot;&nbsp; No obligation &nbsp;&middot;&nbsp; See your price before you commit", muted=True, small=True)
        + _ep("I only take on 3–4 new sites per week — if you're interested, sooner is better.", muted=True, small=True, italic=True),
        email=email,
    )

def _html_plain(name: str, email: str = "") -> str:
    return html_card(
        _ep(f"I saw you opened my email about building a website for <strong>{name}</strong> — wanted to follow up.")
        + _ep("I'd love to build you a <strong>free preview</strong> so you can see exactly what your site could look like before committing to anything.")
        + _ecta("", f'Just reply <span style="color:#C9A96E;">YES</span> and I\'ll send one over the same day.', dark=True)
        + _ep("Starting at $499 &nbsp;&middot;&nbsp; Live in 7 days &nbsp;&middot;&nbsp; No monthly fees", muted=True, small=True),
        email=email,
    )

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
    # Try Gmail OAuth first
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
            print(f"  [GMAIL ERROR] {e.code} — falling back to SendGrid")
        except Exception as exc:
            print(f"  [GMAIL ERROR] {exc} — falling back to SendGrid")

    # Fallback: SendGrid
    if SG:
        try:
            body = json.dumps({
                "personalizations": [{"to": [{"email": to}]}],
                "from":    {"email": SENDER_EMAIL, "name": SENDER_NAME},
                "subject": subject,
                "content": [
                    {"type": "text/plain", "value": plain},
                    {"type": "text/html",  "value": html},
                ],
            }).encode()
            req = urllib.request.Request(
                "https://api.sendgrid.com/v3/mail/send",
                data=body, method="POST",
                headers={"Authorization": f"Bearer {SG}",
                         "Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=10)
            return True
        except Exception as e:
            print(f"  [SENDGRID ERROR] {e}")

    print("  [ERROR] No sender available (no Gmail token, no SendGrid key)")
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

        results.append({
            "email":      email_addr,
            "name":       "",  # filled in below from send log
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

    # Cross-reference send logs to get real business name + category
    # and filter out domain mismatches (enrichment errors)
    email_to_biz: dict[str, dict] = {}
    for p in sorted(SCRIPT_DIR.glob("send_log_*.csv")):
        try:
            with open(p, newline="", encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    if row.get("status") == "sent":
                        em = row.get("email_sent_to", "").lower().strip()
                        if em and em not in email_to_biz:
                            email_to_biz[em] = {
                                "name":     row.get("name", ""),
                                "category": row.get("category", ""),
                            }
        except Exception:
            pass

    final = []
    for r in seen.values():
        em   = r["email"]
        biz  = email_to_biz.get(em, {})
        name = biz.get("name", "")
        if not name:
            continue  # skip if not in send log — not a prospect we contacted
        # Domain mismatch check: ≥1 word (3+ chars) from biz name must appear in email domain
        biz_words = set(re.findall(r"[a-z]{3,}", name.lower()))
        domain    = em.split("@")[-1].split(".")[0]  # e.g. "rittenhousehotel"
        if biz_words and not any(w in domain for w in biz_words):
            continue  # enrichment mismatch — skip
        r["name"]     = name
        r["category"] = biz.get("category", "")
        final.append(r)

    return final


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
    """Emails that already successfully got the clicker follow-up."""
    sent = set()
    for p in SCRIPT_DIR.glob("clicker_followup_log_*.csv"):
        with open(p, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if row.get("status", "").startswith("sent"):
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
    print(f"Due ({args.hours}h+ ago)    : {len(due)}")
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

        # Try to get mockup URL + generate personalized intake form
        mockup_url = None
        intake_url = None
        if not args.dry_run:
            mockup_url = try_generate_mockup(name, to, lead_row)
            if mockup_url:
                # Generate personalized intake form (shows mockup + add-on pricing)
                try:
                    import sys as _sys
                    _sys.path.insert(0, str(SCRIPT_DIR))
                    from generate_intake_form import upload_intake_form
                    cat = (lead_row or {}).get("category", "")
                    intake_url = upload_intake_form(name, cat, mockup_url)
                    print(f"  Intake form : {intake_url}")
                except Exception as _e:
                    intake_url = mockup_url  # fallback to mockup link

        if mockup_url and intake_url:
            subject = SUBJECT_MOCKUP.format(name=name)
            plain   = PLAIN_MOCKUP.format(name=name, intake_url=intake_url)
            html    = _html_mockup(name, intake_url, email=c["email"])
        else:
            subject = SUBJECT_PLAIN.format(name=name)
            plain   = PLAIN_PLAIN.format(name=name)
            html    = _html_plain(name, email=c["email"])

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
