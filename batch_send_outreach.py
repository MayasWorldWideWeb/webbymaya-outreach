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
import re as _re
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
BREVO_API_KEY_2       = os.environ.get("BREVO_API_KEY_2", "")        # 2nd free Brevo account — +300/day
SENDPULSE_API_KEY     = os.environ.get("SENDPULSE_API_KEY", "")      # SendPulse — +500/day free forever
SENDPULSE_CLIENT_ID   = os.environ.get("SENDPULSE_CLIENT_ID", "")    # legacy OAuth fallback
SENDPULSE_CLIENT_SEC  = os.environ.get("SENDPULSE_CLIENT_SECRET", "")
MAILGUN_API_KEY       = os.environ.get("MAILGUN_API_KEY", "")         # Mailgun trial — +5,000 first 3 months
MAILGUN_DOMAIN        = os.environ.get("MAILGUN_DOMAIN", "webbymaya.com")
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

# Default maximum emails per run — SG 100 + Brevo 300 + Brevo2 300 + Mailgun 500 + Gmail 500
DEFAULT_LIMIT = 1700

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

def _kw_match(kw: str, text: str) -> bool:
    """Word-boundary aware keyword check — 'pho' won't match 'photography'."""
    return bool(_re.search(r'\b' + _re.escape(kw.strip()) + r'\b', text))

# Rules are checked IN ORDER — first match wins.
# CRITICAL: most-specific terms must come BEFORE broad ones.
# "barber" must beat "salon", "nail" must beat "spa", etc.
_NAME_CATEGORY_RULES = [
    # ── AUTOMOTIVE (check before "motor"/"garage" bleed into other cats) ──────
    (["auto repair", "auto service", "auto care", "auto fix", "auto tech",
      "car repair", "car care", "car service", "car tech",
      "mechanic", "automotive", "auto body", "body shop",
      "transmission", "brakes", "muffler", "exhaust", "engine repair",
      "oil change", "lube"],                                                   "auto repair"),
    (["auto tag", "auto tags", "vehicle tag", "notary auto",
      "tag and title", "tags & title"],                                        "auto tags"),  # skip these — not web clients
    (["tire", "tires", "wheel alignment", "rim ", "rims"],                    "tire shop"),
    (["car wash", "auto wash", "auto detail", "car detail", "detailing"],     "car wash"),
    (["towing", "tow truck", "roadside"],                                      "towing"),

    # ── BARBERSHOP (before hair salon / beauty salon) ─────────────────────────
    (["barber", "barbershop", "barber shop", "barbers", "barbering",
      "barber lounge", "barber studio", "barber co",
      "kutz", "cutz", "kuts", "cuts by", "fade lounge",
      "gentlemen's cut", "gentleman's grooming"],                              "barbershop"),

    # ── NAIL SALON (before spa / beauty salon) ───────────────────────────────
    (["nail", "nails", "manicure", "pedicure", "gel nails",
      "acrylic", "nail art", "nail bar", "nail lounge",
      "nail studio", "nail spa"],                                              "nail salon"),

    # ── HAIR SALON (after barber, after nail) ────────────────────────────────
    # "beauty salon" is here — safe because barber check runs first
    (["hair salon", "hair studio", "hair lounge", "hair bar", "hair co",
      "hair boutique", "hair design", "hair care", "hair gallery",
      "hair works", "coiffure", "coiffeur",
      "blowout", "blow dry", "blowdry",
      "hair color", "highlights", "balayage", "keratin",
      "beauty salon", "beauty studio", "beauty parlor"],                      "hair salon"),

    # ── LASH / BROW (before generic "spa") ───────────────────────────────────
    (["lash", "eyelash", "lashes", "brow bar", "brow studio",
      "eyebrow", "threading", "microblading", "brow lamination"],             "lash studio"),

    # ── MASSAGE (before generic "spa") ───────────────────────────────────────
    (["massage", "bodywork", "body work", "therapeutic massage",
      "deep tissue", "swedish massage", "hot stone", "reflexology"],          "massage"),

    # ── SPA (after nail/barber/lash/massage — spa is a catch-all) ────────────
    (["day spa", "medi spa", "med spa", "medspa", "medical spa",
      "wellness spa", "luxury spa", "full service spa"],                      "spa"),

    # ── FOOD & DRINK ─────────────────────────────────────────────────────────
    # Bakery FIRST — "Italian Bakery" should be bakery, not restaurant
    (["bakery", "bakehouse", "bake shop", "patisserie", "boulangerie",
      "croissant", "donut", "doughnut", "bagel", "cupcake"],                 "bakery"),
    (["pizza", "pizzeria", "pie shop", "pizza co", "pizza kitchen"],          "pizza"),
    (["bbq", "barbeque", "barbecue", "smokehouse", "smoke house",
      "pit master", "pitmaster", "soul food", "southern food",
      "wings", "wing spot", "wing house", "burger", "burgers",
      "hoagie", "cheesesteak", "cheesesteaks", "sub shop",
      "deli", "seafood", "fish fry", "fish & chips",
      "taco", "tacos", "burrito", "quesadilla"],                              "restaurant"),
    # Note: word-boundary matching handles "pho" vs "photography" etc.
    (["sushi", "ramen", "pho", "dim sum", "wok", "hibachi",
      "thai", "chinese", "japanese", "korean", "vietnamese",
      "indian", "mexican", "italian", "greek", "mediterranean",
      "caribbean", "ethiopian", "peruvian"],                                  "restaurant"),
    (["restaurant", "ristorante", "bistro", "brasserie",
      "grille", "steakhouse", "steak house", "chophouse",
      "chop house", "eatery", "cantina", "trattoria", "taverna",
      "public house", "gastropub"],                                            "restaurant"),
    (["grill", "grill & bar", "bar & grill", "bar and grill"],                "restaurant"),
    (["cafe", "café", "coffee", "espresso", "roaster", "roastery",
      "coffee house", "coffee shop", "coffeehouse",
      "tea house", "boba", "bubble tea", "matcha"],                           "cafe"),
    # Remaining bakery words (lower priority than "Italian Bakery" → already caught above)
    (["bread", "pastry", "cookie", "muffin"],                                 "bakery"),
    (["diner", "pancake", "waffle", "breakfast spot", "brunch"],              "diner"),
    (["juice", "smoothie", "acai", "cold press"],                             "juice bar"),
    (["ice cream", "gelato", "frozen yogurt", "fro-yo", "froyo", "creamery",
      "sorbet", "soft serve"],                                                 "ice cream"),
    (["food truck", "foodtruck"],                                              "food truck"),
    (["catering", "caterer"],                                                  "catering"),
    (["bar ", "bar&", "bar/", "sports bar", "dive bar",
      "brewery", "brewhouse", "brew pub", "taproom",
      "wine bar", "cocktail lounge", "nightclub"],                            "bar"),

    # ── WELLNESS / FITNESS ───────────────────────────────────────────────────
    # Use "ink" as a whole word (word-boundary matching prevents "pink" false match)
    (["tattoo", "tatto", "ink", "inkhouse", "tattooing",
      "body piercing", "piercing studio", "body art"],                        "tattoo parlor"),
    (["yoga", "pilates", "barre"],                                            "yoga studio"),
    (["crossfit", "muay thai", "jiu jitsu", "jiu-jitsu", "bjj",
      "boxing gym", "martial art", "karate", "kickboxing", "mma "],           "gym"),
    (["gym", "fitness center", "fitness club", "health club",
      "athletic club", "personal training", "personal trainer",
      "cycle studio", "spin studio", "boot camp"],                            "gym"),

    # ── HOME SERVICES ────────────────────────────────────────────────────────
    (["cleaning service", "cleaning co", "cleaning company",
      "cleaning solutions", "cleaning pros",
      "maid service", "house cleaning", "home cleaning",
      "janitorial", "housekeeping"],                                           "cleaning service"),
    (["landscaping", "lawn care", "lawn service", "grass cutting",
      "garden", "tree service", "tree care", "arborist", "irrigation"],      "landscaping"),
    (["plumber", "plumbing", "drain cleaning", "pipe repair", "sewer"],       "plumber"),
    (["electric", "electrician", "electrical contractor",
      "electrical service"],                                                   "electrician"),
    (["roofing", "roofer", "roof repair", "roof replacement"],                "roofing"),
    (["hvac", "heating", "cooling", "air conditioning", "air condition",
      "furnace", "heat pump"],                                                 "hvac"),
    (["painter", "painting", "paint co", "interior painting",
      "exterior painting"],                                                    "painter"),
    (["moving company", "movers", "moving service", "relocation",
      "moving & storage", "moving and storage"],                               "moving company"),
    (["handyman", "home repair", "home improvement", "remodeling",
      "renovation", "contracting"],                                            "handyman"),

    # ── PETS ─────────────────────────────────────────────────────────────────
    (["pet grooming", "dog grooming", "dog spa", "dog salon",
      "puppy grooming", "cat grooming", "grooming salon"],                    "pet grooming"),
    (["veterinar", "animal clinic", "animal hospital", "animal care",
      "vet clinic", "pet clinic"],                                             "vet"),
    (["dog walker", "dog walking", "pet sitter", "pet sitting",
      "pet care", "doggy day", "dog boarding"],                               "dog walker"),
    (["pet store", "pet shop", "pet supply", "pet supplies"],                 "pet store"),

    # ── RETAIL / PROFESSIONAL SERVICES ───────────────────────────────────────
    (["florist", "flower shop", "flowers", "floral design",
      "floral studio", "flower studio"],                                       "florist"),
    (["photographer", "photography", "photo studio",
      "portrait studio", "headshot"],                                          "photographer"),
    (["videograph", "video production", "film production"],                   "videographer"),
    (["jewel", "jewelry", "jewellery", "ring repair", "watch repair",
      "custom jewelry"],                                                       "jeweler"),
    (["dry clean", "dryclean", "dry cleaning"],                               "dry cleaner"),
    (["laundry", "laundromat", "wash & fold", "wash and fold"],               "laundromat"),
    (["alteration", "tailor", "tailoring", "seamstress"],                     "tailor"),
    (["childcare", "child care", "daycare", "day care", "preschool",
      "nursery school", "after school"],                                       "daycare"),
    (["print", "printing", "signs", "signage", "banner"],                    "print shop"),
    (["pharmacy", "drug store", "drugstore"],                                  "pharmacy"),
]

# Categories we should SKIP entirely — not good website prospects
_SKIP_CATEGORIES = {
    "auto tags", "towing", "bar", "nightclub", "pharmacy",
    "laundromat", "print shop",
}

# Canonical aliases — unify fragmented categories in old data
_CATEGORY_ALIASES = {
    "mechanic":          "auto repair",
    "barber shop":       "barbershop",
    "beauty salon":      None,   # None = re-run name normalization
    "fitness":           "gym",
    "personal trainer":  "gym",
    "dog walker":        "pet grooming",
    "lawn care":         "landscaping",
    "diner":             "restaurant",
    "juice bar":         "cafe",
}


def normalize_category(name: str, category: str) -> str:
    """
    Return the correct category using the business name as primary signal.
    Uses word-boundary matching so 'pho' never matches 'photography',
    'lash' never matches 'flash', 'ink' never matches 'pink', etc.
    """
    n = (name or "").lower().strip()
    for keywords, correct_cat in _NAME_CATEGORY_RULES:
        if any(_kw_match(kw, n) for kw in keywords):
            return correct_cat
    # No name signal — canonicalize Yelp's category
    cat = (category or "").lower().strip()
    if cat in _CATEGORY_ALIASES:
        alias = _CATEGORY_ALIASES[cat]
        return alias if alias else category
    return category


# 7 subject-line angles — one per day of week (Mon=0 … Sun=6)
# Each is a format string taking {name}
_SUBJECT_ANGLES = [
    "I built {name} a website — free preview inside",          # Mon
    "Your {name} customers can't find you — I made a site",    # Tue
    "{name} doesn't show up online — I fixed that for free",   # Wed
    "Free website preview for {name}",                         # Thu
    "I put together a site for {name} — take a look",          # Fri
    "{name} is missing from Google — I built something",       # Sat
    "Quick question about {name}'s online presence",           # Sun
]

# Category overrides that still rotate on the second token of each angle
_SUBJECT_CAT_OVERRIDE = {
    "nail salon":       ["I built {name} a nail salon website (free preview)",
                         "Your {name} clients can't find you online",
                         "{name} doesn't show up for nail salons near me",
                         "Free nail salon website preview — {name}",
                         "I made a nail salon site for {name} — see it",
                         "{name} is missing from Google Maps",
                         "Quick question for {name}"],
    "hair salon":       ["I built {name} a hair salon website (free preview)",
                         "Your {name} clients can't find you online",
                         "{name} doesn't show up for hair salons near me",
                         "Free hair salon website preview — {name}",
                         "I made a salon site for {name} — take a look",
                         "{name} isn't showing up on Google",
                         "Quick question for {name}"],
    "barbershop":       ["I built {name} a barbershop website (free preview)",
                         "Your {name} customers can't find you online",
                         "{name} doesn't show up for barbers near me",
                         "Free barber website preview — {name}",
                         "I made a barbershop site for {name} — see it",
                         "{name} is missing from Google",
                         "Quick question for {name}"],
    "restaurant":       ["I built {name} a restaurant website (free preview)",
                         "Your {name} customers can't find your menu online",
                         "{name} doesn't show up for restaurants near me",
                         "Free restaurant website preview — {name}",
                         "I made a restaurant site for {name} — take a look",
                         "{name} isn't showing up on Google",
                         "Quick question for {name}"],
    "auto repair":      ["{name} is missing from Google — I built a site",
                         "Your {name} customers can't find you online",
                         "{name} doesn't show up for auto repair near me",
                         "Free auto shop website preview — {name}",
                         "I made an auto repair site for {name}",
                         "{name} isn't showing up on Google Maps",
                         "Quick question for {name}"],
    "cleaning service": ["I built {name} a cleaning website (free preview)",
                         "Your {name} customers can't find you online",
                         "{name} doesn't show up for cleaning services near me",
                         "Free cleaning website preview — {name}",
                         "I made a cleaning service site for {name}",
                         "{name} isn't showing up on Google",
                         "Quick question for {name}"],
}

def get_subject(name: str, category: str) -> str:
    """Return a subject line rotated by day of week (7 angles, category-specific)."""
    import datetime
    cat  = normalize_category(name, category).strip().lower()
    dow  = datetime.date.today().weekday()   # 0=Mon … 6=Sun

    angles = _SUBJECT_CAT_OVERRIDE.get(cat)
    if not angles:
        # Try partial match against override keys
        for key, angle_list in _SUBJECT_CAT_OVERRIDE.items():
            if key in cat:
                angles = angle_list
                break
    if not angles:
        # Fall back to generic angles, injecting category hint where possible
        tpl = _SUBJECT_MAP.get(cat)
        if not tpl:
            for key, t in _SUBJECT_MAP.items():
                if key in cat:
                    tpl = t
                    break
        if tpl:
            # Build 7 variants around the category-specific wording
            base = tpl.replace("{name}", "{name}")
            angles = [
                base,
                "Your {name} customers can't find you — I made a site",
                "{name} doesn't show up online — I fixed that for free",
                "Free website preview for {name}",
                "I put together a site for {name} — take a look",
                "{name} is missing from Google — I built something",
                "Quick question about {name}'s online presence",
            ]
        else:
            angles = _SUBJECT_ANGLES

    return angles[dow % len(angles)].replace("{name}", name)

# HTML template path — sits next to this script's parent directory
_SCRIPT_DIR   = Path(__file__).parent
_TEMPLATE_PATH = _SCRIPT_DIR.parent / "webbymaaya-email-template.html"

# Plain-text fallback (shown by email clients that block HTML)
EMAIL_PLAIN_TEMPLATE = """\
{mockup_hero}{opener}

{review_hook}{pain_point}
I'm Maya, a web designer based in Philly. I built {business_name} a free preview — \
Starting at $499 — live in 7 days. No monthly fees, no tech work on your end.

Just reply YES to this email and I'll send everything over.

Maya Sierra
WebByMaya.com · maya@webbymaya.com

P.S. {ps_line}
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
        return upload_mockup(name, category, phone, city, address)
    except Exception:
        return ""


# Category-specific pain points — what each business type loses without a website
_CAT_PAIN = {
    "nail salon":       "Nail salon clients almost always search online before they walk in. Right now those searches are sending them to your competitors.",
    "hair salon":       "Most people won't call a salon they can't look up first — they want to see the work, read reviews, and book online. You're losing those clients daily.",
    "barbershop":       "When someone new to {neighborhood} searches 'barbershop near me,' {name} doesn't come up. First impressions happen online now.",
    "spa":              "Spa clients research before they commit. Without a website, you're invisible to exactly the people who are ready to pay for what you offer.",
    "massage":          "Massage clients want to see your services, pricing, and reviews before they call. A website is what turns a searcher into a booking.",
    "restaurant":       "People decide where to eat by searching online — if there's no website, no menu, no hours, they pick someone else. It's that fast.",
    "cafe":             "Coffee regulars are built online now. People search, read reviews, then walk in. You're missing every person who looked you up first.",
    "bakery":           "Catering orders, event cakes, custom orders — all of that business goes to bakeries with a website. You're leaving money on the table.",
    "auto repair":      "When someone's car breaks down in {neighborhood}, they pull out their phone. {name} doesn't come up — so they call whoever does.",
    "cleaning service": "Most cleaning clients search online before calling anyone. A professional website turns those Google searches into calls directly to you.",
    "barbershop":       "When someone moves to {neighborhood}, the first thing they do is search 'barber near me.' Right now {name} isn't showing up.",
    "tattoo parlor":    "Tattoo clients spend hours researching artists online. Without a portfolio site, you're invisible to the clients willing to pay for quality work.",
    "florist":          "Wedding and event clients shortlist florists from Google before ever making a call. Without a website you're not even in the running.",
    "gym":              "Most people join a gym after checking it out online. Photos, membership prices, class schedule — if it's not on a site, they go somewhere else.",
    "pet grooming":     "Pet owners are protective — they want to see your setup, read reviews, and know you're legit before they hand over their dog. A website builds that trust.",
    "photographer":     "Your portfolio is your pitch. Without a website, potential clients can't find your work, and you lose bookings to photographers who do have one.",
}

_CAT_PS = {
    "nail salon":       "I can have your new site ranking for '{neighborhood} nail salon' searches within 30 days of going live.",
    "hair salon":       "The site includes an online booking button — so clients can schedule directly without calling.",
    "barbershop":       "I include a booking button so new clients can book a cut without having to hunt down your number.",
    "restaurant":       "The site includes your menu, hours, and a Google Maps embed so customers can find and order from you in seconds.",
    "auto repair":      "I'll make sure your site shows up when people search 'auto repair near {neighborhood}' — that's the traffic that actually converts.",
    "cleaning service": "I write the copy for you — services, pricing, areas covered. You don't touch anything.",
    "spa":              "I can add an online booking link straight to your booking software — no extra monthly cost.",
    "massage":          "I include a services + pricing page so clients know exactly what they're getting before they book.",
    "tattoo parlor":    "I'll build out a portfolio page with your best work so clients can see your style before reaching out.",
    "photographer":     "Your gallery will be front and center — fast-loading, mobile-ready, built to book.",
}

_DEFAULT_PAIN = "When someone in {neighborhood} searches for a {type} right now, they find your competitors — not you. A website fixes that."
_DEFAULT_PS   = "The preview I built already has your phone number, address, and photos pulled in — it would take me 7 days to make it live."


def _neighborhood(city: str, address: str) -> str:
    """Extract the most specific location label for email copy."""
    if address:
        parts = [p.strip() for p in address.split(",")]
        # Address format: "123 Main St, Neighborhood, City, State ZIP"
        if len(parts) >= 3:
            candidate = parts[1]
            if candidate and not candidate[0].isdigit() and len(candidate) > 3:
                return candidate
    return city.split(",")[0].strip() if city else "your area"


# ---------------------------------------------------------------------------
# Shared email design helpers — used by this script and all follow-up scripts
# ---------------------------------------------------------------------------

_UNSUB_BASE = "https://ycsauzlqsjjbusugshpz.supabase.co/storage/v1/object/public/mockups/unsubscribe.html"

def html_card(body_html: str, email: str = "") -> str:
    """Wrap body_html in the standard WebByMaya branded email card."""
    import urllib.parse as _up
    unsub_url = _UNSUB_BASE + (f"?email={_up.quote(email)}" if email else "")
    return (
        '<!DOCTYPE html><html><head>'
        '<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        '</head><body style="margin:0;padding:0;background:#f0ede8;">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f0ede8;">'
        '<tr><td align="center" style="padding:28px 12px;">'
        '<table role="presentation" width="600" cellpadding="0" cellspacing="0"'
        ' style="max-width:600px;width:100%;background:#ffffff;border-radius:10px;'
        'overflow:hidden;border:1px solid #e4dfd8;">'
        '<tr><td style="background:#C9A96E;height:3px;font-size:0;line-height:3px;">&nbsp;</td></tr>'
        '<tr><td style="padding:20px 36px 0;">'
        '<p style="margin:0;font-size:10px;font-weight:700;letter-spacing:3px;text-transform:uppercase;'
        'color:#C9A96E;font-family:Arial,sans-serif;">WebByMaya</p>'
        '</td></tr>'
        '<tr><td style="padding:22px 36px 30px;">'
        + body_html
        + '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin-top:24px;">'
        '<tr><td style="border-top:1px solid #eeeeee;padding-top:16px;">'
        '<p style="margin:0 0 5px;font-size:12px;color:#bbbbbb;font-family:Arial,sans-serif;line-height:1.9;">'
        'Maya Sierra &nbsp;&middot;&nbsp; '
        '<a href="https://webbymaya.com" style="color:#C9A96E;text-decoration:none;font-weight:600;">'
        'WebByMaya.com</a> &nbsp;&middot;&nbsp; maya@webbymaya.com</p>'
        f'<p style="margin:0;font-size:11px;color:#cccccc;font-family:Arial,sans-serif;">'
        f'Philadelphia, PA &nbsp;&middot;&nbsp; '
        f'<a href="{unsub_url}" style="color:#cccccc;text-decoration:underline;">Unsubscribe</a></p>'
        '</td></tr></table>'
        '</td></tr>'
        '</table>'
        '</td></tr></table>'
        '</body></html>'
    )


def _ep(text: str, muted: bool = False, small: bool = False, italic: bool = False) -> str:
    """Standard email paragraph."""
    color  = "#999999" if muted else "#1c1c1c"
    size   = "13px" if small else "15px"
    style_ = f"font-style:italic;" if italic else ""
    return (
        f'<p style="margin:0 0 18px;font-size:{size};line-height:1.8;'
        f'color:{color};font-family:Arial,sans-serif;{style_}">{text}</p>'
    )


def _ecta(url: str, label: str, dark: bool = False) -> str:
    """Email CTA — gold button (default) or dark card with gold text."""
    if dark:
        return (
            '<table role="presentation" width="100%" cellpadding="0" cellspacing="0"'
            ' style="margin:4px 0 24px;">'
            '<tr><td style="background:#1a1a1a;border-radius:8px;padding:18px 24px;">'
            f'<p style="margin:0;font-size:16px;font-weight:700;color:#ffffff;'
            f'font-family:Arial,sans-serif;line-height:1.5;">{label}</p>'
            '</td></tr></table>'
        )
    return (
        '<table role="presentation" cellpadding="0" cellspacing="0" width="100%"'
        ' style="margin:20px 0 24px;">'
        '<tr><td align="center">'
        f'<a href="{url}" style="display:inline-block;background:#C9A96E;color:#0d0d0d;'
        f'padding:14px 36px;border-radius:6px;font-weight:800;font-size:15px;'
        f'font-family:Arial,sans-serif;text-decoration:none;">{label}</a>'
        '</td></tr></table>'
    )


def build_email_body(name: str, category: str, phone: str = "", city: str = "Philadelphia, PA",
                     mockup_url: str = "", rating: str = "", review_count: str = "",
                     address: str = "", to_email: str = "") -> tuple[str, str]:
    """Return (plain_text, html) tuple for the given business."""
    import datetime as _dt, urllib.parse as _up
    friendly      = _friendly_type(category)
    cat           = (category or "").strip().lower()
    neighborhood  = _neighborhood(city, address)
    city_display  = city.split(",")[0].strip() if city else "your area"

    try:
        r  = float(rating) if rating else 0.0
        rc = int(review_count) if review_count else 0
    except (ValueError, TypeError):
        r, rc = 0.0, 0

    # ── Opener — specific to their review situation ───────────────────────
    if rc >= 100:
        opener = f"I came across {name} on Yelp — {rc} reviews and a {r:g}-star rating. Impressive. But you don't have a website, which means all those happy customers can't send anyone new your way."
    elif rc >= 30:
        opener = f"I found {name} on Yelp — {rc} reviews, {r:g} stars. You've clearly built something real. The problem is, none of that shows up when someone searches for a {friendly} in {neighborhood}."
    elif rc >= 5 and r >= 4.0:
        opener = f"I noticed {name} on Yelp — {r:g} stars, {rc} reviews. You have happy customers, but no website means the next one can't find you."
    else:
        opener = f"I came across {name} while looking at {friendly} businesses in {neighborhood}. You don't have a website yet — and that's costing you customers every day."

    # ── Review hook (only if meaningful data) ────────────────────────────
    review_hook = ""
    if rc >= 50:
        review_hook = f"You have {rc} people who already trust {name}. A website turns those reviews into referrals — new customers who find you on Google because your happy customers sent them.\n\n"
    elif rc >= 10:
        review_hook = f"With {rc} Yelp reviews, you've already proven the business works. A website just makes sure new customers can actually find it.\n\n"

    # ── Category-specific pain point ──────────────────────────────────────
    pain_raw  = _CAT_PAIN.get(cat, _DEFAULT_PAIN)
    pain_point = pain_raw.replace("{neighborhood}", neighborhood).replace("{name}", name).replace("{type}", friendly)

    # ── P.S. line ────────────────────────────────────────────────────────
    ps_raw  = _CAT_PS.get(cat, _DEFAULT_PS)
    ps_line = ps_raw.replace("{neighborhood}", neighborhood).replace("{name}", name).replace("{type}", friendly)

    # ── Add UTM params to mockup URL for click attribution ────────────────
    utm_url = mockup_url
    if mockup_url and mockup_url.startswith("http"):
        utm_cat = _re.sub(r"[^a-z0-9]+", "-", cat) if cat else "general"
        utm_url = mockup_url + "?" + _up.urlencode({
            "utm_source":   "email",
            "utm_medium":   "outreach",
            "utm_campaign": utm_cat,
            "utm_content":  _dt.date.today().isoformat(),
        })

    # ── Mockup hero (table row — injected into card) ─────────────────────
    mockup_hero_plain = ""
    mockup_hero_tr    = ""
    if utm_url:
        mockup_hero_plain = f"Here's the preview I built for you:\n{utm_url}\n\n"

        mockup_hero_tr = (
            '<tr><td style="background:#111111;padding:28px 36px;text-align:center;">'
            f'<p style="margin:0 0 14px;font-size:10px;font-weight:700;letter-spacing:3px;'
            f'text-transform:uppercase;color:#C9A96E;font-family:Arial,sans-serif;">'
            f'I built this for {name}</p>'
            + f'<a href="{utm_url}" style="display:inline-block;background:#C9A96E;color:#0d0d0d;'
            f'padding:14px 36px;border-radius:6px;font-weight:800;font-size:15px;'
            f'font-family:Arial,sans-serif;text-decoration:none;letter-spacing:0.4px;">'
            '&#128064;&nbsp;&nbsp;See Your Website Preview &rarr;</a>'
            '<p style="margin:12px 0 0;font-size:11px;color:#555;font-family:Arial,sans-serif;">'
            'Takes 30 seconds &nbsp;&middot;&nbsp; No sign-up needed</p>'
            '</td></tr>'
        )

    # ── Social proof (inline pull-quote, plain text + HTML) ──────────────
    social_proof_plain = ""
    social_proof_html  = ""
    if rc >= 5 and r >= 4.0:
        stars = f"{r:g}★"
        rev   = f", {rc} Yelp reviews" if rc > 0 else ""
        social_proof_plain = f"{name} — {stars}{rev}. You've built something real. Let's make sure people can find it.\n\n"
        social_proof_html  = (
            '<table role="presentation" width="100%" cellpadding="0" cellspacing="0"'
            ' style="margin:0 0 20px;">'
            '<tr><td style="border-left:3px solid #C9A96E;padding:10px 16px;background:#faf9f7;'
            'border-radius:0 4px 4px 0;">'
            f'<p style="margin:0;font-size:13px;color:#666666;font-style:italic;'
            f'line-height:1.65;font-family:Arial,sans-serif;">'
            f'<strong style="color:#1a1a1a;">{name}</strong> &mdash; '
            f'<strong style="color:#1a1a1a;">{r:g}&#9733;</strong>'
            + (f'&nbsp;<strong style="color:#1a1a1a;">{rc} Yelp reviews</strong>' if rc > 0 else '')
            + ". You've built something real. Let's make sure people can find it.</p>"
            '</td></tr></table>'
        )

    plain = EMAIL_PLAIN_TEMPLATE.format(
        business_name=name,
        business_type=friendly,
        city=city_display,
        mockup_hero=mockup_hero_plain,
        opener=opener,
        review_hook=review_hook,
        pain_point=pain_point,
        ps_line=ps_line,
        social_proof=social_proof_plain,
    )

    review_hook_html = _ep(review_hook.strip()) if review_hook.strip() else ""

    body = (
        social_proof_html
        + _ep(opener)
        + review_hook_html
        + _ep(pain_point)
        + _ep(
            f"I'm Maya, a web designer based in Philly. I built {name} a free preview — "
            f"<strong>starting at $499</strong>, live in 7 days. No monthly fees, no tech work on your end."
        )
        + _ecta("", f'Just reply <span style="color:#C9A96E;">YES</span> to this email and I\'ll send everything over.', dark=True)
        + _ep(f"P.S. {ps_line}", muted=True, small=True, italic=True)
    )

    # Cold outreach email has an optional dark hero band — can't use plain html_card()
    html = (
        '<!DOCTYPE html><html><head>'
        '<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        '</head><body style="margin:0;padding:0;background:#f0ede8;">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f0ede8;">'
        '<tr><td align="center" style="padding:28px 12px;">'
        '<table role="presentation" width="600" cellpadding="0" cellspacing="0"'
        ' style="max-width:600px;width:100%;background:#ffffff;border-radius:10px;'
        'overflow:hidden;border:1px solid #e4dfd8;">'
        '<tr><td style="background:#C9A96E;height:3px;font-size:0;line-height:3px;">&nbsp;</td></tr>'
        '<tr><td style="padding:22px 36px 0;">'
        '<p style="margin:0;font-size:10px;font-weight:700;letter-spacing:3px;'
        'text-transform:uppercase;color:#C9A96E;font-family:Arial,sans-serif;">WebByMaya</p>'
        '</td></tr>'
        + mockup_hero_tr
        + '<tr><td style="padding:26px 36px 30px;">'
        + body
        + '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin-top:6px;">'
        '<tr><td style="border-top:1px solid #eeeeee;padding-top:16px;">'
        '<p style="margin:0 0 5px;font-size:12px;color:#bbbbbb;font-family:Arial,sans-serif;line-height:1.9;">'
        'Maya Sierra &nbsp;&middot;&nbsp; '
        '<a href="https://webbymaya.com" style="color:#C9A96E;text-decoration:none;font-weight:600;">'
        'WebByMaya.com</a> &nbsp;&middot;&nbsp; maya@webbymaya.com</p>'
        + f'<p style="margin:0;font-size:11px;color:#cccccc;font-family:Arial,sans-serif;">'
        f'Philadelphia, PA &nbsp;&middot;&nbsp; '
        f'<a href="{_UNSUB_BASE + ("?email=" + __import__("urllib.parse", fromlist=["quote"]).quote(to_email) if to_email else "")}" '
        f'style="color:#cccccc;text-decoration:underline;">Unsubscribe</a></p>'
        + '</td></tr></table>'
        '</td></tr></table></td></tr></table></body></html>'
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


def _send_via_brevo2(to: str, subject: str, plain: str, html: str) -> bool:
    """Second Brevo account — another free 300/day."""
    import urllib.request, urllib.error
    if not BREVO_API_KEY_2 or "brevo2" in _exhausted_providers:
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
        headers={"api-key": BREVO_API_KEY_2, "Content-Type": "application/json"},
        method="POST")
    try:
        urllib.request.urlopen(req, timeout=10)
        return True
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:300]
        if e.code in (400, 402, 429) or "limit" in body.lower() or "quota" in body.lower() or "credit" in body.lower() or "dailySendingLimit" in body:
            print("  [Brevo2] Daily limit reached — switching to Mailgun.")
            _exhausted_providers.add("brevo2")
            _mark_exhausted("brevo2")
        else:
            print(f"  [BREVO2 ERROR] {e.code}: {body}")
        return False
    except Exception as exc:
        print(f"  [BREVO2 ERROR] {exc}")
        return False


_sendpulse_token: dict = {}  # {"token": str, "expires": float}

def _sendpulse_access_token() -> str:
    """Return SendPulse bearer token — direct API key or OAuth2 client credentials."""
    import time as _time, urllib.request
    # Direct API key (sp_apikey_... format) — use as-is
    if SENDPULSE_API_KEY:
        return SENDPULSE_API_KEY
    # OAuth2 fallback (client_id + client_secret)
    now = _time.time()
    if _sendpulse_token.get("token") and _sendpulse_token.get("expires", 0) > now + 60:
        return _sendpulse_token["token"]
    if not SENDPULSE_CLIENT_ID or not SENDPULSE_CLIENT_SEC:
        return ""
    payload = json.dumps({
        "grant_type":    "client_credentials",
        "client_id":     SENDPULSE_CLIENT_ID,
        "client_secret": SENDPULSE_CLIENT_SEC,
    }).encode()
    req = urllib.request.Request(
        "https://api.sendpulse.com/oauth/access_token",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST")
    try:
        resp = json.loads(urllib.request.urlopen(req, timeout=10).read())
        _sendpulse_token["token"]   = resp["access_token"]
        _sendpulse_token["expires"] = now + resp.get("expires_in", 3600)
        return _sendpulse_token["token"]
    except Exception as exc:
        print(f"  [SendPulse] Token fetch failed: {exc}")
        return ""


def _send_via_sendpulse(to: str, subject: str, plain: str, html: str) -> bool:
    """SendPulse SMTP API — 15,000 emails/month free forever (~500/day)."""
    import urllib.request, urllib.error
    if not (SENDPULSE_API_KEY or SENDPULSE_CLIENT_ID) or "sendpulse" in _exhausted_providers:
        return False
    token = _sendpulse_access_token()
    if not token:
        return False
    payload = json.dumps({
        "email": {
            "html":    html,
            "text":    plain,
            "subject": subject,
            "from":    {"name": SENDER_NAME, "email": SENDER_EMAIL},
            "to":      [{"email": to}],
        }
    }).encode()
    req = urllib.request.Request(
        "https://api.sendpulse.com/smtp/emails",
        data=payload,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST")
    try:
        urllib.request.urlopen(req, timeout=10)
        return True
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:300]
        if e.code == 429 or "limit" in body.lower() or "quota" in body.lower():
            print("  [SendPulse] Daily limit reached — switching to Mailgun.")
            _exhausted_providers.add("sendpulse")
            _mark_exhausted("sendpulse")
        else:
            print(f"  [SENDPULSE ERROR] {e.code}: {body}")
        return False
    except Exception as exc:
        print(f"  [SENDPULSE ERROR] {exc}")
        return False


def _send_via_mailgun(to: str, subject: str, plain: str, html: str) -> bool:
    """Mailgun — free trial 5,000 emails/3 months, then ~$0.10/1k. Requires DNS setup on webbymaya.com."""
    import urllib.request, urllib.error, urllib.parse, base64 as _b64
    if not MAILGUN_API_KEY or "mailgun" in _exhausted_providers:
        return False
    data = urllib.parse.urlencode({
        "from":    f"{SENDER_NAME} <maya@{MAILGUN_DOMAIN}>",
        "to":      to,
        "subject": subject,
        "text":    plain,
        "html":    html,
    }).encode("utf-8")
    creds = _b64.b64encode(f"api:{MAILGUN_API_KEY}".encode()).decode()
    req = urllib.request.Request(
        f"https://api.mailgun.net/v3/{MAILGUN_DOMAIN}/messages",
        data=data,
        headers={"Authorization": f"Basic {creds}"},
        method="POST")
    try:
        urllib.request.urlopen(req, timeout=10)
        return True
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:300]
        if e.code in (402, 429) or "limit" in body.lower() or "quota" in body.lower():
            print("  [Mailgun] Daily limit reached — switching to Gmail.")
            _exhausted_providers.add("mailgun")
            _mark_exhausted("mailgun")
        else:
            print(f"  [MAILGUN ERROR] {e.code}: {body}")
        return False
    except Exception as exc:
        print(f"  [MAILGUN ERROR] {exc}")
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
      1. Brevo     (300/day free)
      2. Brevo2    (300/day free — 2nd account)
      3. SendGrid  (100/day free)
      4. SendPulse (500/day free forever — 15k/month)
      5. Mailgun   (5,000 free first 3 months, needs webbymaya.com DNS verified)
      6. Gmail     (500/day free)
    Total: up to 1,700/day when all providers are active.
    Returns (success, provider_used).
    """
    if "brevo" not in _exhausted_providers and BREVO_API_KEY:
        if _send_via_brevo(to, subject, plain, html):
            return True, "brevo"
    if "brevo2" not in _exhausted_providers and BREVO_API_KEY_2:
        if _send_via_brevo2(to, subject, plain, html):
            return True, "brevo2"
    if "sendgrid" not in _exhausted_providers and SENDGRID_API_KEY:
        if _send_via_sendgrid(to, subject, plain, html):
            return True, "sendgrid"
    if "sendpulse" not in _exhausted_providers and (SENDPULSE_API_KEY or SENDPULSE_CLIENT_ID):
        if _send_via_sendpulse(to, subject, plain, html):
            return True, "sendpulse"
    if "mailgun" not in _exhausted_providers and MAILGUN_API_KEY:
        if _send_via_mailgun(to, subject, plain, html):
            return True, "mailgun"
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
    "mockup_url",
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
        recipient_email = prospect.get("email", "").strip()
        plain, html   = build_email_body(name, category, phone, lead_city, mockup_url, rating, review_count, address=prospect.get("address", ""), to_email=recipient_email)

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
                    if all(p in _exhausted_providers for p in ("sendgrid", "brevo", "brevo2", "gmail")):
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
            "mockup_url":     mockup_url,
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
