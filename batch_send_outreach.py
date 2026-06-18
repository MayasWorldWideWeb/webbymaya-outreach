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

SENDER_EMAIL = "maya@webbymaya.com"
SENDER_NAME  = "Maya Sierra"

SENDGRID_API_KEY = os.environ.get("SENDGRID_API_KEY", "")
BREVO_API_KEY    = os.environ.get("BREVO_API_KEY", "")
GMAIL_TOKEN_PATH = Path.home() / ".webbymaaya/gmail_token.json"

# Notion API base
NOTION_API_BASE = "https://api.notion.com/v1"
NOTION_VERSION  = "2022-06-28"

# Delay (seconds) between sends to stay well clear of spam filters
SEND_DELAY_SECONDS = 15

# Load suppressed (bounced/blocked) emails so we never retry them
def _load_suppressed() -> set:
    path = Path(__file__).parent / "bounce_log.csv"
    if not path.exists():
        return set()
    import csv as _csv
    with open(path, newline="") as f:
        return {row["email"].lower() for row in _csv.DictReader(f)}

SUPPRESSED_EMAILS = _load_suppressed()

def _load_all_sent() -> set:
    """Return every email already sent across ALL historical send logs — prevents cross-CSV duplicates."""
    sent = set()
    for p in sorted(Path(__file__).parent.glob("send_log_*.csv")):
        with open(p, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if row.get("status") == "sent":
                    e = row.get("email_sent_to", "").strip().lower()
                    if e:
                        sent.add(e)
    return sent

ALREADY_SENT_EMAILS = _load_all_sent()

_DISPOSABLE_DOMAINS = None  # type: Optional[set]

def _load_disposable_domains() -> set:
    """
    Download the disposable-email-domains blocklist (free, open-source).
    Falls back to an empty set if network fails.
    github.com/disposable-email-domains/disposable-email-domains
    """
    import urllib.request
    try:
        url = "https://raw.githubusercontent.com/disposable-email-domains/disposable-email-domains/master/disposable_email_blocklist.conf"
        data = urllib.request.urlopen(url, timeout=8).read().decode()
        return {line.strip().lower() for line in data.splitlines() if line.strip() and not line.startswith("#")}
    except Exception:
        return set()

def validate_email(email: str) -> tuple[bool, str]:
    """
    Free email validation. Three checks:
      1. Basic format
      2. DNS MX record — domain must have a mail server (stronger than A record)
      3. Disposable/throwaway domain blocklist
    Fails open on network errors so temporary DNS hiccups never block sends.
    """
    global _DISPOSABLE_DOMAINS
    import re as _re

    # 1. Format
    if not _re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        return False, "invalid format"

    domain = email.split("@")[-1].lower()

    # 2. MX record check — confirms domain actually accepts mail (not just exists)
    try:
        import dns.resolver
        dns.resolver.resolve(domain, "MX")
    except Exception as _dns_err:
        err_name = type(_dns_err).__name__
        if "NXDOMAIN" in err_name or "NoNameservers" in err_name:
            return False, "domain doesn't exist"
        if "NoAnswer" in err_name:
            return False, "domain has no mail server"
        # Network timeout / other transient error → fail-open

    # 3. Disposable domain check
    if _DISPOSABLE_DOMAINS is None:
        _DISPOSABLE_DOMAINS = _load_disposable_domains()
    if domain in _DISPOSABLE_DOMAINS:
        return False, "disposable/throwaway address"

    return True, ""

# Platform/SaaS domains that forward to the software company, not the business owner
SKIP_DOMAINS = {
    "fresha.com", "birdeye.com", "nailsalonbeauty.com", "thryv.com",
    "yext.com", "yelp.com", "google.com", "facebook.com", "instagram.com",
    "squareup.com", "toasttab.com", "grubhub.com", "doordash.com",
    "opentable.com", "mindbodyonline.com", "vagaro.com", "booker.com",
    "schedulicity.com", "appointy.com", "setmore.com", "acuityscheduling.com",
    "zendesk.com", "hubspot.com", "mailchimp.com", "constantcontact.com",
}

# Default maximum emails per run — uses all three free providers (SG 100 + Brevo 300 + Gmail 500)
DEFAULT_LIMIT = 900

# ---------------------------------------------------------------------------
# Email template
# ---------------------------------------------------------------------------

EMAIL_SUBJECT = "I built {business_name} a website"  # fallback only

# Category-specific subject lines
_SUBJECT_MAP = {
    "hair salon":       "I built {name} a website — want to see it?",
    "nail salon":       "I built {name} a nail salon website",
    "beauty salon":     "I built {name} a website — take a look",
    "spa":              "I built {name} a spa website — take a look",
    "lash":             "I built {name} a website — take a look",
    "lash studio":      "I built {name} a website — take a look",
    "barber":           "I built {name} a barber website — take a look",
    "barbershop":       "I built {name} a barbershop website",
    "massage":          "I built {name} a website — take a look",
    "wax":              "I built {name} a website — take a look",
    "threading":        "I built {name} a website — take a look",
    "esthetician":      "I built {name} a website — take a look",
    "skincare":         "I built {name} a skincare website — take a look",
    "restaurant":       "I built {name} a restaurant website",
    "cafe":             "I put together a website for {name}",
    "coffee":           "I put together a website for {name}",
    "bakery":           "I built {name} a bakery website",
    "pizza":            "I built {name} a website — take a look",
    "bar":              "I built {name} a website — check it out",
    "food truck":       "I built {name} a food truck website",
    "diner":            "I built {name} a diner website",
    "auto repair":      "{name} is missing from Google — I built a site",
    "mechanic":         "I built {name} a website — take a look",
    "auto shop":        "I built {name} a website — take a look",
    "plumber":          "I built {name} a plumbing website",
    "plumbing":         "I built {name} a plumbing website",
    "electrician":      "I built {name} a website — take a look",
    "landscaping":      "I built {name} a landscaping website",
    "lawn":             "I built {name} a lawn care website",
    "cleaning":         "I put together a website for {name}",
    "cleaning service": "I put together a website for {name}",
    "roofing":          "I built {name} a roofing website",
    "hvac":             "I built {name} a website — take a look",
    "gym":              "I built {name} a gym website",
    "fitness":          "I built {name} a fitness website",
    "yoga":             "I built {name} a yoga studio website",
    "personal trainer": "I built {name} a trainer website",
    "tattoo":           "I built {name} a tattoo shop website",
    "tattoo parlor":    "I built {name} a tattoo shop website",
    "florist":          "I built {name} a florist website",
    "photographer":     "I built {name} a photography website",
    "photography":      "I built {name} a photography website",
    "pet grooming":     "I built {name} a pet grooming website",
    "pet":              "I built {name} a website — take a look",
    "daycare":          "I built {name} a daycare website",
    "childcare":        "I built {name} a childcare website",
    "nail":             "I built {name} a nail salon website",
}


# ---------------------------------------------------------------------------
# Category normalization — correct mislabeled businesses using their name
# ---------------------------------------------------------------------------

_NAME_CATEGORY_RULES = [
    # Food & drink — check these first (very common mismatches)
    (["pizza", "pizzeria", "pie shop"],                                         "pizza"),
    (["diner", "pancake", "waffle", "breakfast", "brunch"],                     "diner"),
    (["bbq", "barbeque", "barbecue", "smokehouse", "smoke house"],              "restaurant"),
    (["sushi", "ramen", "pho", "dim sum", "wok", "hibachi", "thai", "chinese",
      "japanese", "korean", "vietnamese", "indian", "mexican", "italian",
      "greek", "mediterranean", "caribbean", "ethiopian", "peruvian"],          "restaurant"),
    (["restaurant", "ristorante", "bistro", "brasserie", "tavern", "grill",
      "grille", "steakhouse", "steak house", "chophouse", "chop house",
      "kitchen", "eatery", "house of", "public house"],                         "restaurant"),
    (["cafe", "café", "coffee", "espresso", "roaster", "roastery",
      "tea house", "boba", "bubble tea"],                                        "cafe"),
    (["bakery", "bakehouse", "bread", "pastry", "patisserie", "boulangerie",
      "cookie", "cupcake", "muffin", "bagel", "donut", "doughnut"],             "bakery"),
    (["bar ", "bar&", "bar/", "lounge", "pub ", "pub,", "pub.", "tavern",
      "brewery", "brewhouse", "brew pub", "wine bar", "cocktail"],              "bar"),
    (["juice", "smoothie", "acai"],                                             "juice bar"),
    (["ice cream", "gelato", "frozen yogurt", "fro-yo", "froyo", "creamery"],  "ice cream"),
    (["food truck", "foodtruck", "catering"],                                   "food truck"),
    # Beauty & wellness
    (["nail", "nails", "nail spa", "manicure", "pedicure"],                    "nail salon"),
    (["hair salon", "hair studio", "hair lounge", "hair bar",
      "salon & spa", "salon and spa", "beauty salon"],                          "hair salon"),
    (["barber", "barbershop", "barber shop", "cuts ", "fade", "kutz"],         "barbershop"),
    (["lash", "eyelash", "brow", "eyebrow", "threading"],                      "lash studio"),
    (["spa", "day spa", "medi spa", "medspa", "med spa"],                      "spa"),
    (["massage", "bodywork", "body work", "therapeutic"],                       "massage"),
    (["tattoo", "ink ", "inkhouse", "tattooing", "piercing", "body art"],      "tattoo parlor"),
    (["yoga", "pilates", "barre", "cycle", "cycling", "spin"],                 "yoga studio"),
    (["gym", "fitness", "crossfit", "crossfit", "muay thai", "jiu jitsu",
      "boxing", "martial art", "karate", "kickboxing"],                         "gym"),
    # Automotive
    (["auto repair", "auto service", "auto care", "car repair", "mechanic",
      "automotive", "motor", "garage", "transmission", "brakes",
      "muffler", "exhaust", "engine"],                                          "auto repair"),
    (["tire", "tires", "wheel", "wheels", "rim ", "rims"],                     "tire shop"),
    (["car wash", "auto wash", "detailing", "detail shop"],                    "car wash"),
    # Home services
    (["cleaning", "cleaners", "janitorial", "maid", "housekeeping"],           "cleaning service"),
    (["landscaping", "lawn", "grass", "garden", "tree service", "tree care",
      "arborist", "irrigation"],                                                 "landscaping"),
    (["plumber", "plumbing", "drain", "pipe", "sewer"],                        "plumber"),
    (["electric", "electrician"],                                               "electrician"),
    (["roofing", "roofer", "roof repair"],                                     "roofing"),
    (["hvac", "heating", "cooling", "air condition", "furnace"],               "hvac"),
    (["painter", "painting", "paint contractor"],                              "painter"),
    (["moving", "movers", "mover", "relocation", "storage"],                  "moving company"),
    # Pets
    (["pet grooming", "dog grooming", "grooming"],                             "pet grooming"),
    (["veterinar", "animal clinic", "animal hospital", "vet "],                "vet"),
    (["dog walker", "pet sitter", "pet care", "doggy day"],                   "dog walker"),
    # Retail / services
    (["florist", "flower", "flowers", "floral"],                               "florist"),
    (["photo", "photographer", "photography", "portrait", "headshot"],         "photographer"),
    (["jewel", "jewelry", "jewellery", "ring repair", "watch repair"],         "jeweler"),
    (["dry clean", "dryclean", "laundry", "alteration", "tailor"],             "dry cleaner"),
    (["childcare", "child care", "daycare", "day care", "preschool",
      "nursery", "after school"],                                               "daycare"),
]


def normalize_category(name: str, category: str) -> str:
    """
    Correct the category using the business name as ground truth.
    Yelp sometimes returns a business under the wrong search bucket —
    e.g., "Joe's Pizza" showing up in a nail salon search.
    """
    n = (name or "").lower()
    for keywords, correct_cat in _NAME_CATEGORY_RULES:
        if any(kw in n for kw in keywords):
            return correct_cat
    return category  # no match → keep original


def get_subject(name: str, category: str) -> str:
    """Return a category-specific email subject, or the generic fallback."""
    cat = normalize_category(name, category).strip().lower()
    template = _SUBJECT_MAP.get(cat)
    if not template:
        for key, tpl in _SUBJECT_MAP.items():
            if key in cat:
                template = tpl
                break
    if template:
        return template.replace("{name}", name)
    return f"I built {name} a website"

# HTML template path — sits next to this script's parent directory
_SCRIPT_DIR   = Path(__file__).parent
_TEMPLATE_PATH = _SCRIPT_DIR.parent / "webbymaaya-email-template.html"

# Plain-text fallback (shown by email clients that block HTML)
EMAIL_PLAIN_TEMPLATE = """\
{mockup_hero}I put together a website for {business_name} — you don't have one online yet, \
and anyone in {city} searching for a {business_type} right now can't find you.

{social_proof}I'm Maya, a web designer based in Philly. If you want it live, it's $799 flat \
and ready in 7 days. No monthly fees, no tech work on your end — I handle everything.

Reply here or fill out my 2-minute form to get started:
https://webbymaya.com/book

Maya Sierra
WebByMaya.com · maya@webbymaya.com
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


def _get_mockup_url(name: str, category: str, phone: str = "", city: str = "Philadelphia, PA", address: str = "") -> str:
    """Upload a personalized mockup to Supabase. Returns public URL or ''."""
    try:
        import sys as _sys
        _sys.path.insert(0, str(_SCRIPT_DIR))
        from mockup_uploader import upload_mockup
        return upload_mockup(name, category, phone, city)
    except Exception:
        return ""


def build_email_body(name: str, category: str, phone: str = "", city: str = "Philadelphia, PA",
                     mockup_url: str = "", rating: str = "", review_count: str = "") -> tuple[str, str]:
    """Return (plain_text, html) tuple for the given business."""
    friendly     = _friendly_type(category)
    city_display = city.split(",")[0].strip() if city else "your area"

    # ── Social proof line (rating + review count) ─────────────────────────
    social_proof_plain = ""
    social_proof_html  = ""
    try:
        r  = float(rating) if rating else 0.0
        rc = int(review_count) if review_count else 0
        if r >= 4.0:
            stars = f"{r:g}-star rating"
            reviews_txt = f" with {rc} reviews" if rc > 0 else ""
            social_proof_plain = (
                f"I noticed {name} has a {stars}{reviews_txt} — "
                f"you deserve a site that shows it off.\n\n"
            )
            social_proof_html = (
                f'<p style="margin:0 0 20px;font-size:15px;line-height:1.7;'
                f'color:#666666;font-style:italic;border-left:3px solid #C9A96E;'
                f'padding-left:14px;">'
                f'I noticed <strong>{name}</strong> has a <strong>{stars}</strong>'
                + (f' with <strong>{rc} reviews</strong>' if rc > 0 else '')
                + ' — you deserve a site that shows it off.</p>'
            )
    except (ValueError, TypeError):
        pass

    # ── Mockup hero block ─────────────────────────────────────────────────
    mockup_hero_plain = ""
    mockup_hero_html  = ""
    if mockup_url:
        mockup_hero_plain = f"I built a website preview for {name}:\n{mockup_url}\n\n"

        # Try to capture a Playwright screenshot to embed as inline image
        screenshot_img_tag = ""
        try:
            from capture_mockup_screenshot import screenshot_html_for_email
            b64 = screenshot_html_for_email(name, category)
            if b64:
                screenshot_img_tag = (
                    f'<a href="{mockup_url}" style="display:block;text-decoration:none;margin-bottom:10px;">'
                    f'<img src="data:image/png;base64,{b64}" alt="Website preview for {name}" '
                    f'width="540" style="width:100%;max-width:540px;border-radius:6px;display:block;'
                    f'border:1px solid #1e1e1e;" /></a>'
                )
        except Exception:
            pass

        mockup_hero_html = (
            '<table role="presentation" width="100%" cellpadding="0" cellspacing="0"'
            ' style="margin:0 0 28px;">'
            '<tr><td style="background:#0d0d0d;border-radius:8px;padding:20px 28px;text-align:center;">'
            f'<div style="font-family:Arial,sans-serif;font-size:11px;text-transform:uppercase;'
            f'letter-spacing:2px;color:#C9A96E;margin-bottom:12px;">I built this for {name}</div>'
            + screenshot_img_tag
            + f'<a href="{mockup_url}" style="display:inline-block;background:#C9A96E;color:#0d0d0d;'
            f'padding:14px 32px;border-radius:6px;font-weight:800;font-size:15px;'
            f'font-family:Arial,sans-serif;text-decoration:none;letter-spacing:0.3px;">'
            '&#128064;&nbsp; See Your Website Preview &rarr;'
            '</a>'
            '<div style="font-family:Arial,sans-serif;font-size:12px;color:#666;margin-top:10px;">'
            'Ready to launch — takes 2 minutes to look at</div>'
            '</td></tr></table>'
        )

    plain = EMAIL_PLAIN_TEMPLATE.format(
        business_name=name,
        business_type=friendly,
        city=city_display,
        mockup_hero=mockup_hero_plain,
        social_proof=social_proof_plain,
    )

    if _TEMPLATE_PATH.exists():
        raw_html = _TEMPLATE_PATH.read_text(encoding="utf-8")
        html = (raw_html
                .replace("{business_name}", name)
                .replace("{business_type}",  friendly)
                .replace("{city}",           city_display)
                .replace("{mockup_hero}",    mockup_hero_html)
                .replace("{social_proof}",   social_proof_html))
    else:
        html = (
            f'<html><body style="font-family:Arial,sans-serif;color:#333;max-width:600px;margin:auto">'
            + (f'<p style="background:#0d0d0d;padding:20px;border-radius:8px;text-align:center">'
               f'<a href="{mockup_url}" style="background:#C9A96E;color:#111;padding:12px 24px;'
               f'text-decoration:none;font-weight:bold;border-radius:3px;display:inline-block">'
               f'&#128064; See Your Website Preview &rarr;</a></p>' if mockup_url else '')
            + (f'<p><em>{social_proof_plain.strip()}</em></p>' if social_proof_plain else '')
            + f'<p>I put together a website for <strong>{name}</strong> — you don\'t have one online yet, '
            f'and anyone in {city_display} searching for a {friendly} right now can\'t find you.</p>'
            f'<p>I\'m Maya, a web designer based in Philly. If you want it live, it\'s <strong>$799 flat</strong> '
            f'and ready in 7 days. No monthly fees, no tech work on your end — I handle everything.</p>'
            f'<p><a href="https://webbymaya.com/book" style="background:#C9A96E;color:#111;'
            f'padding:12px 24px;text-decoration:none;font-weight:bold;border-radius:3px;'
            f'display:inline-block">Get started — 2 min form &rarr;</a></p>'
            f'<p style="color:#888;font-size:12px">Or just reply to this email.<br><br>'
            f'Maya Sierra &middot; <a href="https://webbymaya.com">WebByMaya.com</a></p>'
            f'</body></html>'
        )

    return plain, html


# ---------------------------------------------------------------------------
# SendGrid helper
# ---------------------------------------------------------------------------

def _gmail_access_token() -> str:
    """Return a fresh Gmail OAuth access token, auto-refreshing if expired."""
    import json as _json, datetime as _dt, urllib.request as _ur, urllib.parse as _up
    from datetime import timezone
    if not GMAIL_TOKEN_PATH.exists():
        return ""
    try:
        tok = _json.loads(GMAIL_TOKEN_PATH.read_text())
        access = tok.get("token", "")
        exp = _dt.datetime.fromisoformat(tok["expiry"].replace("Z", "+00:00"))
        if _dt.datetime.now(timezone.utc) >= exp - _dt.timedelta(seconds=60):
            data = _up.urlencode({
                "client_id":     tok["client_id"],
                "client_secret": tok["client_secret"],
                "refresh_token": tok["refresh_token"],
                "grant_type":    "refresh_token",
            }).encode()
            resp = _json.loads(_ur.urlopen(_ur.Request(
                "https://oauth2.googleapis.com/token", data=data), timeout=10).read())
            access = resp["access_token"]
            tok["token"] = access
            tok["expiry"] = (_dt.datetime.now(timezone.utc) +
                             _dt.timedelta(seconds=resp.get("expires_in", 3600))
                             ).strftime("%Y-%m-%dT%H:%M:%SZ")
            GMAIL_TOKEN_PATH.write_text(_json.dumps(tok))
        return access
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Provider daily-limit state — persists across runs (file-backed, resets at midnight)
# ---------------------------------------------------------------------------
_PROVIDER_LIMIT_FILE = Path.home() / ".webbymaaya/provider_limits.json"

def _load_exhausted() -> set:
    """Return providers that already hit their daily limit today."""
    try:
        data = json.loads(_PROVIDER_LIMIT_FILE.read_text())
        today = str(datetime.date.today())
        return {p for p, d in data.items() if d == today}
    except Exception:
        return set()

def _mark_exhausted(provider: str) -> None:
    """Persist a provider's daily exhaustion so future runs skip it."""
    try:
        data = json.loads(_PROVIDER_LIMIT_FILE.read_text()) if _PROVIDER_LIMIT_FILE.exists() else {}
    except Exception:
        data = {}
    data[provider] = str(datetime.date.today())
    _PROVIDER_LIMIT_FILE.parent.mkdir(parents=True, exist_ok=True)
    _PROVIDER_LIMIT_FILE.write_text(json.dumps(data))

_exhausted_providers: set = _load_exhausted()


def _send_via_sendgrid(to: str, subject: str, plain: str, html: str) -> bool:
    import urllib.request, urllib.error
    if not SENDGRID_API_KEY or "sendgrid" in _exhausted_providers:
        return False
    payload = json.dumps({
        "personalizations": [{"to": [{"email": to}]}],
        "from": {"email": SENDER_EMAIL, "name": SENDER_NAME},
        "subject": subject,
        "content": [{"type": "text/plain", "value": plain}, {"type": "text/html", "value": html}],
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://api.sendgrid.com/v3/mail/send", data=payload,
        headers={"Authorization": f"Bearer {SENDGRID_API_KEY}", "Content-Type": "application/json"},
        method="POST")
    try:
        urllib.request.urlopen(req)
        return True
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:300]
        if e.code in (401, 402, 429, 403) or "limit" in body.lower() or "quota" in body.lower() or "credits" in body.lower():
            print("  [SG] Daily limit reached — switching to Brevo.")
            _exhausted_providers.add("sendgrid")
            _mark_exhausted("sendgrid")
        else:
            print(f"  [SG ERROR] {e.code}: {body}")
        return False
    except Exception as exc:
        print(f"  [SG ERROR] {exc}")
        return False


def _send_via_brevo(to: str, subject: str, plain: str, html: str) -> bool:
    """Brevo REST API — 300 emails/day free."""
    import urllib.request, urllib.error
    if not BREVO_API_KEY or "brevo" in _exhausted_providers:
        return False
    payload = json.dumps({
        "sender":      {"email": SENDER_EMAIL, "name": SENDER_NAME},
        "to":          [{"email": to}],
        "subject":     subject,
        "textContent": plain,
        "htmlContent": html,
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://api.brevo.com/v3/smtp/email", data=payload,
        headers={"api-key": BREVO_API_KEY, "Content-Type": "application/json"},
        method="POST")
    try:
        urllib.request.urlopen(req, timeout=10)
        return True
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:300]
        if e.code in (400, 402, 429) or "limit" in body.lower() or "quota" in body.lower() or "credit" in body.lower() or "dailySendingLimit" in body:
            print("  [Brevo] Daily limit reached — switching to Gmail.")
            _exhausted_providers.add("brevo")
            _mark_exhausted("brevo")
        else:
            print(f"  [BREVO ERROR] {e.code}: {body}")
        return False
    except Exception as exc:
        print(f"  [BREVO ERROR] {exc}")
        return False


def _send_via_gmail(to: str, subject: str, plain: str, html: str) -> bool:
    import email.mime.multipart, email.mime.text, base64 as _b64
    import urllib.request, urllib.error
    if "gmail" in _exhausted_providers:
        return False
    access = _gmail_access_token()
    if not access:
        return False
    try:
        msg = email.mime.multipart.MIMEMultipart("alternative")
        msg["To"] = to
        msg["From"] = f"{SENDER_NAME} <{SENDER_EMAIL}>"
        msg["Subject"] = subject
        msg.attach(email.mime.text.MIMEText(plain, "plain"))
        msg.attach(email.mime.text.MIMEText(html,  "html"))
        raw = _b64.urlsafe_b64encode(msg.as_bytes()).decode()
        payload = json.dumps({"raw": raw}).encode()
        req = urllib.request.Request(
            "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
            data=payload,
            headers={"Authorization": f"Bearer {access}", "Content-Type": "application/json"},
            method="POST")
        urllib.request.urlopen(req, timeout=10)
        return True
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:300]
        if e.code == 429 or "limit" in body.lower() or "quota" in body.lower():
            print("  [Gmail] Daily limit reached.")
            _exhausted_providers.add("gmail")
        else:
            print(f"  [GMAIL ERROR] {e.code}: {body}")
        return False
    except Exception as exc:
        print(f"  [GMAIL ERROR] {exc}")
        return False


def send_email(to: str, subject: str, plain: str, html: str) -> tuple[bool, str]:
    """
    Smart tiered sending — auto-switches provider when daily limit hit:
      1. SendGrid  (100/day free)
      2. Brevo     (300/day free)
      3. Gmail     (500/day free)
    Returns (success, provider_used).
    """
    if "sendgrid" not in _exhausted_providers and SENDGRID_API_KEY:
        if _send_via_sendgrid(to, subject, plain, html):
            return True, "sendgrid"
    if "brevo" not in _exhausted_providers and BREVO_API_KEY:
        if _send_via_brevo(to, subject, plain, html):
            return True, "brevo"
    if "gmail" not in _exhausted_providers:
        if _send_via_gmail(to, subject, plain, html):
            return True, "gmail"
    return False, ""


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


def _load_csv_raw(path: str) -> tuple[list[dict], list[str]]:
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)
    return rows, fieldnames


def _save_csv(path: str, rows: list[dict], fieldnames: list[str]) -> None:
    if "email_status" not in fieldnames:
        fieldnames.append("email_status")
    for row in rows:
        row.setdefault("email_status", "")
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


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
    new   = not os.path.exists(path)
    with open(path, "a", newline="", encoding="utf-8") as f:  # append — never overwrite
        writer = csv.DictWriter(f, fieldnames=LOG_COLUMNS)
        if new:
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
        choices=["none", "bad", "all"],
        default="none",
        help="none = only no-website businesses (default), bad = dead/parked sites only, all = everyone",
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
        before = len(prospects)
        prospects = [p for p in prospects
                     if p.get("email_status", "").strip() not in ("sent", "bounced", "unsubscribed")
                     and p.get("email", "").strip() and "@" in p.get("email", "")]
        skipped_already = before - len(prospects)
        print(f"  Found {len(prospects)} prospect(s) with email addresses ({skipped_already} skipped).")

    if not prospects:
        print("No prospects to process. Exiting.")
        return

    # Apply --website-filter (default: "none" — only email businesses without a website)
    if args.website_filter == "none":
        prospects = [p for p in prospects if p.get("has_website", "").strip() == "No"]
        print(f"  After filter (no website): {len(prospects)} prospect(s).")
    elif args.website_filter == "bad":
        prospects = [p for p in prospects if p.get("has_website", "").strip().startswith("Yes -")]
        print(f"  After filter (bad/outdated site): {len(prospects)} prospect(s).")
    # "all" skips filtering

    if not prospects:
        print("No prospects match the filter. Exiting.")
        return

    # Apply --limit
    if args.limit < len(prospects):
        print(f"Limiting to {args.limit} email(s) this run (--limit {args.limit}).")
    prospects = prospects[: args.limit]

    # ---- Confirm at least one sending method is available ----------------
    if not args.dry_run and not SENDGRID_API_KEY and not BREVO_API_KEY and not GMAIL_TOKEN_PATH.exists():
        sys.exit("ERROR: No email provider configured. Need SENDGRID_API_KEY, BREVO_API_KEY, or Gmail token.")

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

        category      = normalize_category(name, category)
        subject       = get_subject(name, category)
        lead_city     = prospect.get("city", "Philadelphia, PA")
        rating        = prospect.get("rating", "")
        review_count  = prospect.get("review_count", "")
        mockup_url    = _get_mockup_url(name, category, phone, lead_city, prospect.get("address", ""))
        if mockup_url:
            print(f"  Mockup  : {mockup_url}")
        plain, html   = build_email_body(name, category, phone, lead_city, mockup_url, rating, review_count)

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
        elif recipient_email.split("@")[-1].lower() in SKIP_DOMAINS:
            status = "skipped"
            note   = f"Platform email — {recipient_email.split('@')[-1]}"
            print(f"  Skipped — platform/SaaS email: {recipient_email}")
        elif recipient_email.lower() in ALREADY_SENT_EMAILS:
            status = "skipped"
            note   = "Already emailed in a previous run"
            print(f"  Skipped — {recipient_email} was already contacted.")
        elif recipient_email.lower() in SUPPRESSED_EMAILS:
            status = "skipped"
            note   = "Suppressed — previously bounced or blocked"
            print(f"  Skipped — {recipient_email} is on bounce suppression list.")
        else:
            # Free email validation: format + DNS + disposable domain check
            valid, reason = validate_email(recipient_email)
            if not valid:
                status = "skipped"
                note   = f"Disify: {reason}"
                print(f"  Skipped — {reason}: {recipient_email}")
            else:
                success, provider = send_email(recipient_email, subject, plain, html)
                if success:
                    sent_count += 1
                    status = "sent"
                    note   = provider
                    ALREADY_SENT_EMAILS.add(recipient_email.lower())
                    print(f"  Sent via {provider} → {recipient_email}.")
                    if page_id:
                        mark_notion_contacted(page_id, today_str)
                        print(f"  Notion updated: Status → Contacted.")
                    if all(p in _exhausted_providers for p in ("sendgrid", "brevo", "gmail")):
                        print("\n  All email providers exhausted for today. Stopping.")
                        break
                else:
                    failed_count += 1
                    status = "failed"
                    note   = "Send failed — check console output"

        log_rows.append({
            "timestamp":      datetime.datetime.now().isoformat(timespec="seconds"),
            "name":           name,
            "category":       category,
            "email_sent_to":  recipient_email,
            "subject":        subject,
            "status":         status,
            "notes":          note,
        })

        # Throttle only between actual sends, not skips/failures
        if not args.dry_run and status == "sent" and i < len(prospects) - 1:
            print(f"  Waiting {SEND_DELAY_SECONDS}s before next send ...")
            time.sleep(SEND_DELAY_SECONDS)

    # ---- Write send log --------------------------------------------------
    log_path = write_log(log_rows, output_dir=str(_SCRIPT_DIR))
    if not args.dry_run:
        log_email(log_rows)

    # ---- Mark sent rows back in source CSV --------------------------------
    if not args.dry_run and args.input.lower() != "notion":
        sent_emails = {row["email_sent_to"].lower() for row in log_rows if row["status"] == "sent"}
        if sent_emails:
            all_rows, fieldnames = _load_csv_raw(args.input)
            for row in all_rows:
                if row.get("email", "").strip().lower() in sent_emails:
                    row["email_status"] = "sent"
            _save_csv(args.input, all_rows, fieldnames)
            print(f"Source CSV updated: {len(sent_emails)} row(s) marked sent.")

    # ---- Summary ---------------------------------------------------------
    print("\n" + "=" * 50)
    if args.dry_run:
        print(f"DRY RUN complete. {len(prospects)} email(s) previewed.")
    else:
        print(f"Done. Sent: {sent_count}  |  Failed: {failed_count}  |  Skipped (no email): {len(log_rows) - sent_count - failed_count}")
    print(f"Send log written to: {log_path}")


if __name__ == "__main__":
    main()
