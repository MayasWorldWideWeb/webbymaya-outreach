#!/usr/bin/env python3
"""
auto_reply.py — WebByMaya Hot-Lead Auto-Reply & Opt-Out Handler
================================================================
Runs after check_replies.py in the daily pipeline.

What it does:
  1. Scans new Gmail replies for interest keywords → sends pricing email
  2. Scans new Gmail replies for opt-out keywords → adds to suppression list
  3. Scans new Twilio inbound SMS for interest keywords → replies with pricing SMS
  4. Scans new Twilio inbound SMS for opt-out keywords → adds to suppression list

No calls, no Calendly — all written communication.

USAGE
-----
    python3 auto_reply.py            # process new replies
    python3 auto_reply.py --dry-run  # preview without sending
"""

import argparse, base64, csv, datetime, json, os, re, sys, urllib.request, urllib.error
from pathlib import Path
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

SCRIPT_DIR    = Path(__file__).parent
STATE_FILE    = SCRIPT_DIR / ".auto_replied.json"
SUPPRESS_FILE = SCRIPT_DIR / "bounce_log.csv"
TOKEN_PATH    = Path.home() / ".webbymaaya/gmail_token.json"

SENDGRID_KEY  = os.environ.get("SENDGRID_API_KEY", "")
TWILIO_SID    = os.environ.get("TWILIO_ACCOUNT_SID", "")
TWILIO_TOKEN  = os.environ.get("TWILIO_AUTH_TOKEN", "")
TWILIO_PHONE  = os.environ.get("TWILIO_PHONE_NUMBER", "")
MY_PHONE      = "+12154602084"

FROM_EMAIL    = "maya@webbymaya.com"
FROM_NAME     = "Maya Sierra"

# ---------------------------------------------------------------------------
# Keyword detection
# ---------------------------------------------------------------------------

INTEREST_WORDS = [
    "interested", "how much", "price", "cost", "quote", "rates",
    "what do you charge", "tell me more", "yes", "sounds good",
    "i need", "can you", "would like", "want a website",
    "looking for", "need a website", "get started", "more info",
    "how does it work", "what's included", "package",
]
OPTOUT_WORDS = [
    "stop", "unsubscribe", "remove me", "remove from list",
    "not interested", "no thanks", "please stop", "take me off",
    "opt out", "opt-out", "don't contact", "do not contact",
    "do not email", "don't email",
]
ALREADY_HAS_SITE_WORDS = [
    "already have a website", "already have one", "we have a website",
    "we have a site", "have a website", "have a web", "have one already",
    "got a website", "got a site", "we use", "currently use squarespace",
    "currently use wix", "currently use shopify", "have squarespace",
    "have wix", "have shopify", "built by", "our website is",
]
NOT_NOW_WORDS = [
    "not right now", "not at this time", "maybe later", "in the future",
    "down the road", "another time", "currently not", "right now isn't",
    "not a good time", "busy right now", "not the right time",
    "will keep in mind", "keep you in mind", "reach out later",
]

def _classify(text: str) -> str:
    """
    Returns one of:
      optout         — wants off the list
      already_has_site — has a website, different pitch needed
      not_now        — timing isn't right, soft hold
      interest       — wants pricing / more info
      other          — unclear, flag for manual review
    """
    t = text.lower()
    if any(w in t for w in OPTOUT_WORDS):
        return "optout"
    if any(w in t for w in ALREADY_HAS_SITE_WORDS):
        return "already_has_site"
    if any(w in t for w in NOT_NOW_WORDS):
        return "not_now"
    if any(w in t for w in INTEREST_WORDS):
        return "interest"
    return "other"

# ---------------------------------------------------------------------------
# Suppression list
# ---------------------------------------------------------------------------

def add_suppression(email: str = "", phone: str = "", reason: str = "unsubscribed"):
    """Add email and/or phone to bounce_log.csv so they're never contacted again."""
    rows = []
    if SUPPRESS_FILE.exists():
        with open(SUPPRESS_FILE, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))

    existing_emails = {r.get("email","").lower() for r in rows}
    existing_phones = {r.get("phone","") for r in rows}
    added = False

    if email and email.lower() not in existing_emails:
        rows.append({"email": email.lower(), "phone": "", "reason": reason,
                     "date": datetime.date.today().isoformat()})
        added = True
    if phone and phone not in existing_phones:
        rows.append({"email": "", "phone": phone, "reason": reason,
                     "date": datetime.date.today().isoformat()})
        added = True

    if added:
        fields = ["email", "phone", "reason", "date"]
        with open(SUPPRESS_FILE, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            w.writerows(rows)

# ---------------------------------------------------------------------------
# Pricing email
# ---------------------------------------------------------------------------

PRICING_SUBJECT = "Re: Your message — WebByMaya pricing"

PRICING_PLAIN = """\
Hi there,

Thanks for reaching out — I'm glad you're interested!

Here's what I offer:

━━━━━━━━━━━━━━━━━━━━━━━━━━━━
LITE  — $499
• 1 page (all your key info, clean and professional)
• Mobile-ready
• Live in 1 week
• Payment plan: $150 now, $349 on launch

STARTER  — $799  ← most popular
• 5 pages (Home, About, Services, Gallery, Contact)
• Mobile-ready design
• Google Analytics & Search Console setup
• Live in 2 weeks
• Payment plan: $200 now, $599 on launch

STANDARD  — $1,299
• 8 pages + contact/quote form
• On-page SEO (titles, descriptions, local keywords)
• Online booking or reservation integration
• Live in 3 weeks
• Payment plan: $300 now, $999 on launch

CUSTOM  — Starting at $1,999
• Fully custom design matched to your brand
• E-commerce, memberships, menus, or any special features
• Timeline discussed based on scope
━━━━━━━━━━━━━━━━━━━━━━━━━━━━

All packages include:
✓ Hosting for the first year (free)
✓ SSL certificate (https, secure)
✓ Domain connection
✓ 30 days of post-launch support

Ready to move forward? Fill out my quick intake form:

  👉 https://webbymaya.com/book

No calls needed — I build from your answers.

Maya Sierra
WebByMaya · Philadelphia, PA
maya@webbymaya.com
webbymaya.com
"""

PRICING_HTML = """\
<!DOCTYPE html><html><body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Arial,sans-serif;
background:#f9f9f9;margin:0;padding:24px">
<div style="max-width:580px;margin:0 auto;background:#fff;border-radius:12px;overflow:hidden;
box-shadow:0 2px 12px rgba(0,0,0,.08)">

  <div style="background:#0d0d0d;padding:32px 36px">
    <div style="font-size:22px;font-weight:800;color:#fff">WebBy<span style="color:#C9A96E">Maya</span></div>
    <div style="font-size:13px;color:#888;margin-top:4px">Philadelphia Web Design · Starting at $499 · Payment plans available</div>
  </div>

  <div style="padding:32px 36px">
    <p style="color:#333;font-size:15px;margin-bottom:20px">
      Thanks for reaching out — I'm glad you're interested! Here's a quick breakdown of our packages:
    </p>

    <!-- LITE -->
    <div style="border:1.5px solid #e8e8e8;border-radius:10px;padding:20px 24px;margin-bottom:14px">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px">
        <div style="font-size:17px;font-weight:800;color:#0d0d0d">Lite</div>
        <div style="font-size:20px;font-weight:900;color:#C9A96E">$499</div>
      </div>
      <ul style="color:#555;font-size:14px;line-height:1.9;padding-left:18px;margin:0 0 8px 0">
        <li>1 page — all your key info, clean &amp; professional</li>
        <li>Mobile-ready &amp; fast loading</li>
        <li style="color:#C9A96E;font-weight:600">Live in 1 week</li>
      </ul>
      <div style="font-size:12px;color:#888;background:#f9f9f9;border-radius:6px;padding:8px 12px">
        Payment plan: <strong style="color:#555">$150 now · $349 on launch</strong>
      </div>
    </div>

    <!-- STARTER -->
    <div style="border:2px solid #C9A96E;border-radius:10px;padding:20px 24px;margin-bottom:14px;position:relative">
      <div style="position:absolute;top:-11px;left:20px;background:#C9A96E;color:#0d0d0d;
        font-size:10px;font-weight:800;padding:3px 10px;border-radius:20px;letter-spacing:.05em">MOST POPULAR</div>
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px">
        <div style="font-size:17px;font-weight:800;color:#0d0d0d">Starter</div>
        <div style="font-size:20px;font-weight:900;color:#C9A96E">$799</div>
      </div>
      <ul style="color:#555;font-size:14px;line-height:1.9;padding-left:18px;margin:0 0 8px 0">
        <li>5 pages — Home, About, Services, Gallery, Contact</li>
        <li>Mobile-ready &amp; fast loading</li>
        <li>Google Analytics setup</li>
        <li style="color:#C9A96E;font-weight:600">Live in 2 weeks</li>
      </ul>
      <div style="font-size:12px;color:#888;background:#fdf8f0;border-radius:6px;padding:8px 12px">
        Payment plan: <strong style="color:#555">$200 now · $599 on launch</strong>
      </div>
    </div>

    <!-- STANDARD -->
    <div style="border:1.5px solid #e8e8e8;border-radius:10px;padding:20px 24px;margin-bottom:14px">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px">
        <div style="font-size:17px;font-weight:800;color:#0d0d0d">Standard</div>
        <div style="font-size:20px;font-weight:900;color:#C9A96E">$1,299</div>
      </div>
      <ul style="color:#555;font-size:14px;line-height:1.9;padding-left:18px;margin:0 0 8px 0">
        <li>8 pages + contact/quote form</li>
        <li>On-page SEO — show up on Google</li>
        <li>Online booking or reservation integration</li>
        <li style="color:#C9A96E;font-weight:600">Live in 3 weeks</li>
      </ul>
      <div style="font-size:12px;color:#888;background:#f9f9f9;border-radius:6px;padding:8px 12px">
        Payment plan: <strong style="color:#555">$300 now · $999 on launch</strong>
      </div>
    </div>

    <!-- CUSTOM -->
    <div style="border:1.5px solid #e8e8e8;border-radius:10px;padding:20px 24px;margin-bottom:24px">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px">
        <div style="font-size:17px;font-weight:800;color:#0d0d0d">Custom</div>
        <div style="font-size:20px;font-weight:900;color:#C9A96E">$1,999+</div>
      </div>
      <ul style="color:#555;font-size:14px;line-height:1.9;padding-left:18px;margin:0">
        <li>Fully custom design matched to your brand</li>
        <li>E-commerce, menus, memberships — anything you need</li>
        <li>Timeline based on scope</li>
      </ul>
    </div>

    <div style="background:#f5f5f5;border-radius:8px;padding:16px 20px;margin-bottom:28px;font-size:13px;color:#555">
      <strong style="color:#333">All packages include:</strong>
      &nbsp; ✓ 1 year free hosting &nbsp; ✓ SSL certificate &nbsp; ✓ Domain setup &nbsp; ✓ 30-day support
    </div>

    <p style="color:#333;font-size:15px;margin-bottom:20px">
      Ready to move forward? Fill out my website intake form — it covers everything I need to build your site. <strong>No calls needed.</strong>
    </p>

    <div style="text-align:center;margin-bottom:28px">
      <a href="https://webbymaya.com/book"
        style="display:inline-block;background:#C9A96E;color:#0d0d0d;padding:16px 36px;
        border-radius:10px;font-weight:800;font-size:16px;text-decoration:none;letter-spacing:0.3px">
        Fill Out My Website Form →
      </a>
      <div style="font-size:12px;color:#999;margin-top:8px">Takes 10–15 min · I build from your answers · No calls needed</div>
    </div>

    <a href="https://webbymaya.com" style="display:inline-block;color:#C9A96E;
      font-weight:600;font-size:13px;text-decoration:none">
      View portfolio → webbymaya.com
    </a>
  </div>

  <div style="background:#f9f9f9;border-top:1px solid #eee;padding:20px 36px;
    font-size:12px;color:#999;text-align:center">
    Maya Sierra · WebByMaya · Philadelphia, PA<br>
    <a href="mailto:maya@webbymaya.com" style="color:#C9A96E">maya@webbymaya.com</a>
    &nbsp;·&nbsp; <a href="https://webbymaya.com" style="color:#C9A96E">webbymaya.com</a>
  </div>
</div>
</body></html>"""

OPTOUT_PLAIN = "Got it — you've been removed from our list. You won't hear from us again. Sorry for the disruption!\n\nMaya Sierra · WebByMaya"

ALREADY_HAS_SITE_SUBJECT = "Re: your website — a free audit"

ALREADY_HAS_SITE_PLAIN = """\
Hi there,

Thanks for letting me know — good to hear you already have a site!

Quick question: is it mobile-friendly and loading fast? Most sites built \
more than 3 years ago score poorly on Google's mobile test, which directly \
hurts how often you show up in search results.

I offer a free site audit — I'll run your current site through Google's tools \
and send you a short report on what's working and what's costing you traffic. \
No obligation, no pitch, just honest feedback.

Interested? Just reply "yes" and send me your website URL.

— Maya
WebByMaya.com
"""

ALREADY_HAS_SITE_HTML = """\
<!DOCTYPE html><html><body style="font-family:Arial,sans-serif;color:#333;
max-width:560px;margin:auto;padding:24px">
<p>Hi there,</p>
<p>Thanks for letting me know — good to hear you already have a site!</p>
<p>Quick question: <strong>is it mobile-friendly and loading fast?</strong>
Most sites built more than 3 years ago score poorly on Google's mobile test,
which directly hurts how often you show up in search results.</p>
<p>I offer a <strong>free site audit</strong> — I'll run your current site through
Google's tools and send you a short report on what's working and what's costing
you traffic. No obligation, no pitch, just honest feedback.</p>
<p style="background:#f5f5f5;padding:14px 18px;border-radius:6px;font-size:14px">
Interested? Just reply <strong>"yes"</strong> and send me your website URL.
</p>
<p style="color:#888;font-size:13px;margin-top:20px">
— Maya<br>
<a href="https://webbymaya.com" style="color:#C9A96E">WebByMaya.com</a>
</p>
</body></html>"""

NOT_NOW_SUBJECT = "Re: no problem at all"

NOT_NOW_PLAIN = """\
Hi there,

No problem at all — I completely understand. Timing is everything.

I'll check back in a few months. In the meantime, if anything changes \
or you just want to see what a site for your business would look like, \
my form is always open:

https://webbymaya.com/book

Wishing you a great rest of the season.

— Maya
WebByMaya.com
"""

NOT_NOW_HTML = """\
<!DOCTYPE html><html><body style="font-family:Arial,sans-serif;color:#555;
max-width:560px;margin:auto;padding:24px">
<p style="color:#333">Hi there,</p>
<p>No problem at all — I completely understand. Timing is everything.</p>
<p>I'll check back in a few months. In the meantime, if anything changes or
you just want to see what a site for your business could look like, my form
is always open:</p>
<p><a href="https://webbymaya.com/book"
  style="color:#C9A96E;font-weight:600;text-decoration:none">
  webbymaya.com/book &rarr;
</a></p>
<p style="color:#888;font-size:13px;margin-top:20px">
Wishing you a great rest of the season.<br><br>
— Maya<br>
<a href="https://webbymaya.com" style="color:#C9A96E">WebByMaya.com</a>
</p>
</body></html>"""

# ---------------------------------------------------------------------------
# Senders
# ---------------------------------------------------------------------------

def _send_email(to: str, subject: str, plain: str, html: str,
                dry_run: bool = False, attachment_path=None) -> bool:
    if dry_run:
        print(f"    [DRY RUN] Would email {to}: {subject}"
              + (f" + PDF {Path(attachment_path).name}" if attachment_path else ""))
        return True
    if not SENDGRID_KEY:
        return False
    import json as _json
    body = {
        "personalizations": [{"to": [{"email": to}]}],
        "from": {"email": FROM_EMAIL, "name": FROM_NAME},
        "subject": subject,
        "content": [{"type": "text/plain", "value": plain}, {"type": "text/html", "value": html}],
    }
    if attachment_path:
        try:
            pdf_b64 = base64.b64encode(Path(attachment_path).read_bytes()).decode("ascii")
            fname   = Path(attachment_path).name
            body["attachments"] = [{"content": pdf_b64, "type": "application/pdf",
                                    "filename": fname, "disposition": "attachment"}]
        except Exception as ae:
            print(f"    [attachment warn] {ae} — sending without PDF")
    payload = _json.dumps(body).encode()
    req = urllib.request.Request(
        "https://api.sendgrid.com/v3/mail/send", data=payload,
        headers={"Authorization": f"Bearer {SENDGRID_KEY}", "Content-Type": "application/json"},
        method="POST")
    try:
        urllib.request.urlopen(req, timeout=10)
        return True
    except Exception as e:
        print(f"    [email error] {e}")
        return False


def _send_sms(to: str, body: str, dry_run: bool = False) -> bool:
    if dry_run:
        print(f"    [DRY RUN] Would SMS {to}: {body[:60]}")
        return True
    if not (TWILIO_SID and TWILIO_TOKEN and TWILIO_PHONE):
        return False
    import urllib.parse
    data = urllib.parse.urlencode({"To": to, "From": TWILIO_PHONE, "Body": body}).encode()
    creds = base64.b64encode(f"{TWILIO_SID}:{TWILIO_TOKEN}".encode()).decode()
    req = urllib.request.Request(
        f"https://api.twilio.com/2010-04-01/Accounts/{TWILIO_SID}/Messages.json",
        data=data, method="POST",
        headers={"Authorization": f"Basic {creds}",
                 "Content-Type": "application/x-www-form-urlencoded"})
    try:
        urllib.request.urlopen(req, timeout=10)
        return True
    except Exception as e:
        print(f"    [SMS error] {e}")
        return False

# ---------------------------------------------------------------------------
# Gmail reply scanner
# ---------------------------------------------------------------------------

GMAIL_USER     = "mayas.worldwide.web@gmail.com"
GMAIL_APP_PASS = os.environ.get("GMAIL_APP_PASSWORD", "")


def _gmail_imap():
    """Return an authenticated imaplib.IMAP4_SSL or None."""
    import imaplib
    if not GMAIL_APP_PASS:
        return None
    try:
        m = imaplib.IMAP4_SSL("imap.gmail.com", 993)
        m.login(GMAIL_USER, GMAIL_APP_PASS)
        return m
    except Exception as e:
        print(f"  [auto_reply] Gmail IMAP error: {e}")
        return None


def _imap_body(msg) -> str:
    """Extract plain-text body from an email.message.Message object."""
    import email as _email
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                try:
                    return part.get_payload(decode=True).decode("utf-8", errors="replace")
                except Exception:
                    pass
    else:
        try:
            return msg.get_payload(decode=True).decode("utf-8", errors="replace")
        except Exception:
            pass
    return ""


def _load_contacted() -> dict:
    contacts = {}
    for p in sorted(SCRIPT_DIR.glob("send_log_*.csv")):
        with open(p, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if row.get("status") == "sent":
                    e = row.get("email_sent_to", "").strip().lower()
                    if e: contacts[e] = row.get("name", e)
    return contacts


def process_gmail_replies(dry_run: bool = False) -> int:
    import imaplib, email as _email

    imap = _gmail_imap()
    if not imap:
        print("  [auto_reply] Gmail not available — add GMAIL_APP_PASSWORD to ~/.zshrc")
        return 0

    contacts = _load_contacted()
    if not contacts:
        imap.logout()
        return 0

    replied   = _load_state()
    processed = 0

    imap.select("INBOX")
    # Search for any unseen messages from addresses we contacted
    contact_set = set(contacts.keys())

    # Fetch all UNSEEN messages (keep it fast)
    _, data = imap.search(None, "UNSEEN")
    msg_ids = data[0].split() if data[0] else []

    for num in msg_ids:
        _, msg_data = imap.fetch(num, "(RFC822)")
        raw = msg_data[0][1]
        msg = _email.message_from_bytes(raw)

        raw_from = msg.get("From", "")
        if "<" in raw_from:
            from_email = raw_from.split("<")[1].rstrip(">").strip().lower()
        else:
            from_email = raw_from.strip().lower()

        # Only process if it's from someone we emailed
        if from_email not in contact_set:
            # Mark as seen so we don't reprocess, but skip
            imap.store(num, "+FLAGS", "\\Seen")
            continue

        uid = f"imap:{num.decode()}"
        if uid in replied:
            continue

        body   = _imap_body(msg)
        intent = _classify(body)
        biz    = contacts.get(from_email, from_email)

        # Mark as seen in Gmail
        imap.store(num, "+FLAGS", "\\Seen")

        if intent == "optout":
            print(f"  [opt-out] {biz} <{from_email}>")
            add_suppression(email=from_email, reason="replied_unsubscribe")
            ok = _send_email(from_email, "Removed from list — WebByMaya",
                             OPTOUT_PLAIN, f"<p>{OPTOUT_PLAIN}</p>", dry_run)
            if ok: print(f"    → opt-out confirmed + suppressed")
            replied[uid] = {"intent": "optout", "email": from_email}
            processed += 1

        elif intent == "already_has_site":
            print(f"  [has site] {biz} <{from_email}>")
            ok = _send_email(from_email, ALREADY_HAS_SITE_SUBJECT,
                             ALREADY_HAS_SITE_PLAIN, ALREADY_HAS_SITE_HTML, dry_run)
            if ok: print(f"    → free audit offer sent")
            replied[uid] = {"intent": "already_has_site", "email": from_email}
            processed += 1

        elif intent == "not_now":
            print(f"  [not now] {biz} <{from_email}>")
            ok = _send_email(from_email, NOT_NOW_SUBJECT,
                             NOT_NOW_PLAIN, NOT_NOW_HTML, dry_run)
            if ok: print(f"    → acknowledged, soft hold")
            replied[uid] = {"intent": "not_now", "email": from_email}
            processed += 1

        elif intent == "interest":
            print(f"  [hot lead] {biz} <{from_email}>")
            proposal_path = None
            try:
                from generate_proposal import make_proposal
                proposal_path = make_proposal(biz)
                print(f"    Proposal: {proposal_path.name}")
            except Exception as pe:
                print(f"    [proposal warn] {pe} — sending without PDF")
            ok = _send_email(from_email, PRICING_SUBJECT, PRICING_PLAIN, PRICING_HTML,
                             dry_run, attachment_path=proposal_path)
            if ok:
                print(f"    → pricing email + proposal PDF sent")
            replied[uid] = {"intent": "interest", "email": from_email}
            processed += 1

        else:
            print(f"  [review] {biz} <{from_email}> — unclear intent, flagged")
            replied[uid] = {"intent": "other", "email": from_email, "preview": body[:120]}
            _log_for_review(from_email, biz, body)
            processed += 1

    _save_state(replied)
    imap.logout()
    return processed

# ---------------------------------------------------------------------------
# Twilio inbound SMS scanner
# ---------------------------------------------------------------------------

SMS_PRICING = (
    "Hi! Thanks for your interest in WebByMaya. "
    "Websites start at $499 (1-page) or $799 (5-page). Payment plans available — as low as $150 down. "
    "Fill out my quick intake form: "
    "https://webbymaya.com/book "
    "No calls needed!"
)

SMS_OPTOUT = "Got it — you've been removed. Sorry for the disruption! -Maya @ WebByMaya"


def _load_all_sent_sms() -> dict:
    """Returns {phone_e164: business_name} for all SMS we've sent."""
    contacts = {}
    for p in sorted(SCRIPT_DIR.glob("sms_log_*.csv")):
        with open(p, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if row.get("status") == "sent":
                    ph = row.get("phone", "").strip()
                    if ph: contacts[ph] = row.get("name", ph)
    return contacts


def process_twilio_sms(dry_run: bool = False) -> int:
    if not (TWILIO_SID and TWILIO_TOKEN):
        return 0

    sms_contacts = _load_all_sent_sms()
    if not sms_contacts:
        return 0

    replied  = _load_state()
    processed = 0

    creds = base64.b64encode(f"{TWILIO_SID}:{TWILIO_TOKEN}".encode()).decode()
    req   = urllib.request.Request(
        f"https://api.twilio.com/2010-04-01/Accounts/{TWILIO_SID}/Messages.json?Direction=inbound&To={TWILIO_PHONE}&PageSize=50",
        headers={"Authorization": f"Basic {creds}"})
    try:
        data = json.loads(urllib.request.urlopen(req, timeout=10).read())
    except Exception:
        return 0

    for msg in data.get("messages", []):
        sid  = msg.get("sid", "")
        key  = f"sms_{sid}"
        if key in replied:
            continue

        from_phone = msg.get("from", "")
        body       = msg.get("body", "")
        intent     = _classify(body)
        biz        = sms_contacts.get(from_phone, from_phone)

        if intent == "optout":
            print(f"  [SMS opt-out] {biz} {from_phone}")
            add_suppression(phone=from_phone, reason="sms_stop")
            _send_sms(from_phone, SMS_OPTOUT, dry_run)
            replied[key] = {"intent": "optout", "phone": from_phone}
            processed += 1

        elif intent == "interest":
            print(f"  [SMS hot lead] {biz} {from_phone}")
            _send_sms(from_phone, SMS_PRICING, dry_run)
            print(f"    → pricing SMS sent")
            replied[key] = {"intent": "interest", "phone": from_phone}
            processed += 1

    _save_state(replied)
    return processed

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

def _load_state() -> dict:
    return json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else {}

def _save_state(state: dict):
    STATE_FILE.write_text(json.dumps(state, indent=2))

REVIEW_LOG = SCRIPT_DIR / "replies_need_review.csv"

def _log_for_review(email: str, biz: str, body: str):
    """Write unclear replies to a CSV for Maya to review manually."""
    is_new = not REVIEW_LOG.exists()
    with open(REVIEW_LOG, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["timestamp", "email", "business", "preview"])
        if is_new:
            w.writeheader()
        w.writerow({
            "timestamp": datetime.date.today().isoformat(),
            "email":     email,
            "business":  biz,
            "preview":   body[:200].replace("\n", " "),
        })

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="WebByMaya — auto-reply to hot leads and opt-outs")
    parser.add_argument("--dry-run", action="store_true", help="Preview without sending")
    args = parser.parse_args()

    tag = "[DRY RUN] " if args.dry_run else ""
    print(f"\n{tag}WebByMaya Auto-Reply — {datetime.date.today()}")

    email_count = process_gmail_replies(args.dry_run)
    sms_count   = process_twilio_sms(args.dry_run)
    total       = email_count + sms_count

    if total == 0:
        print("  No new hot leads or opt-outs.")
    else:
        print(f"\n  Done — {email_count} email + {sms_count} SMS replies handled.")


if __name__ == "__main__":
    main()
