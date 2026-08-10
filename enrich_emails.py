"""
enrich_emails.py — WebByMaya Email Enrichment
===============================================
Takes the prospects CSV from find_prospects.py and automatically searches
the web for a contact email address for each business. Checks Yelp, Facebook,
local directories, and search results. Runs in parallel for speed.

SETUP
-----
    pip3 install duckduckgo-search requests beautifulsoup4

USAGE
-----
    python3 enrich_emails.py --input prospects_2026-05-28.csv

    # Preview only — don't overwrite the original
    python3 enrich_emails.py --input prospects_2026-05-28.csv --dry-run

    # Fewer parallel workers if you get blocked
    python3 enrich_emails.py --input prospects_2026-05-28.csv --workers 4

OUTPUT
------
    Same filename with _enriched suffix:  prospects_2026-05-28_enriched.csv
    Businesses where no email was found get an empty email column.

HOW IT WORKS
------------
For each business it:
  1. Searches DuckDuckGo for "[name] [city] contact email"
  2. Fetches the top 3 result pages (Yelp, Facebook, local directories, etc.)
  3. Extracts any email addresses found using regex
  4. Picks the most likely business email (filters out social media noise)
  5. Falls back to a direct Yelp search if nothing is found
"""

import argparse
import csv
import os
import re
import sys
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urlparse

# ---------------------------------------------------------------------------
# Check dependencies
# ---------------------------------------------------------------------------

def _require(pkg, install):
    import importlib
    try:
        return importlib.import_module(pkg)
    except ImportError:
        sys.exit(f"ERROR: '{pkg}' not found.\nInstall with:  pip3 install {install}")

requests  = _require("requests",  "requests")
bs4       = _require("bs4",       "beautifulsoup4")
BeautifulSoup = bs4.BeautifulSoup

try:
    from ddgs import DDGS
except ImportError:
    sys.exit("ERROR: 'ddgs' not found.\nInstall with:  pip3 install ddgs")

try:
    from playwright.sync_api import sync_playwright as _pw
    _PLAYWRIGHT_OK = True
except ImportError:
    _PLAYWRIGHT_OK = False

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

MAX_PAGES       = 3
REQUEST_TIMEOUT = 8
FETCH_DELAY     = 0.3

_SCRIPT_DIR = Path(__file__).parent

# ---------------------------------------------------------------------------
# Cost controls (added 2026-08-09)
# ---------------------------------------------------------------------------
# The pipeline targets businesses with NO website — and you cannot scrape an
# email off a site that doesn't exist. A typical run is ~537 prospects of which
# ~518 are has_website="No", so 96% of the fetch/render work was structurally
# guaranteed to return nothing. Three guards fix that:
#   1. WEBSITE GATE   — skip has_website="No" rows entirely (--all to override)
#   2. NEGATIVE CACHE — never re-look-up a business that already came up empty
#   3. NO BROWSER     — Playwright is opt-in via --render, not the default
# Together these cut a daily run from ~500 page fetches + browser launches to
# roughly 20 plain HTTP GETs.

NEGATIVE_CACHE_PATH = _SCRIPT_DIR / ".enrich_negative_cache.json"
NEGATIVE_CACHE_DAYS = 60          # re-try a dead business only after this long

# One pooled session for every worker — reuses TCP/TLS connections instead of
# renegotiating per request.
_SESSION = requests.Session()
_SESSION.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
})


def _has_own_website(row: dict) -> bool:
    """True if this business has something we could actually scrape.

    find_prospects.py writes has_website as "No" / "Yes - dead" / "Yes - social"
    / "Yes". Only "No" with no URL is hopeless; a dead or social site still
    often carries a contact address, so those stay in."""
    site = (row.get("website") or "").strip()
    if site.startswith("http"):
        return True
    return not (row.get("has_website") or "").strip().lower().startswith("no")


def _load_negative_cache() -> dict:
    """{normalized business name: iso date last searched with no result}"""
    try:
        import json
        return json.loads(NEGATIVE_CACHE_PATH.read_text())
    except Exception:
        return {}


def _save_negative_cache(cache: dict) -> None:
    try:
        import json
        NEGATIVE_CACHE_PATH.write_text(json.dumps(cache, indent=0, sort_keys=True))
    except Exception:
        pass


def _negative_cache_is_fresh(stamp: str) -> bool:
    from datetime import datetime, timedelta
    try:
        return datetime.fromisoformat(stamp) > datetime.now() - timedelta(days=NEGATIVE_CACHE_DAYS)
    except Exception:
        return False


def _norm_business_name(name: str) -> str:
    """Normalize a business name for cross-run dedup: strip HTML, drop
    'Your '/'Free ' subject prefixes, lowercase, collapse to alnum words."""
    n = re.sub(r"<[^>]+>", "", name or "")
    n = re.sub(r"^(your|free)\s+", "", n.strip(), flags=re.I)
    n = re.sub(r"[^a-z0-9]+", " ", n.lower()).strip()
    return n


# Providers whose "sent" rows never actually delivered (see batch_send_outreach).
# "brevo" = Brevo #1, unvalidated sender, 0 delivered — those businesses must be
# re-contactable, so we do NOT treat them as already-contacted.
_FAILED_SEND_PROVIDERS = {"brevo"}


def _load_contacted_names() -> set:
    """Every business TRULY emailed (status=sent via a working provider) across
    ALL send logs, keyed by normalized name. Skips enrichment on already-contacted
    businesses — but NOT ones whose only send went through a failed provider."""
    names: set = set()
    for p in sorted(_SCRIPT_DIR.glob("send_log_*.csv")):
        try:
            with open(p, newline="", encoding="utf-8", errors="replace") as f:
                for row in csv.DictReader(f):
                    if row.get("status") == "sent" and \
                       (row.get("notes") or "").strip().lower() not in _FAILED_SEND_PROVIDERS:
                        nm = _norm_business_name(row.get("name", ""))
                        if nm:
                            names.add(nm)
        except Exception:
            continue
    return names

SKIP_DOMAINS = {
    "google.com", "google.co", "goo.gl",
    "facebook.com", "instagram.com", "twitter.com", "tiktok.com",
    "youtube.com", "linkedin.com",
    "apple.com", "amazon.com", "wikipedia.org",
    "bbb.org",
}

REJECT_EMAIL_PATTERNS = [
    r"\.png$", r"\.jpg$", r"\.gif$", r"\.svg$", r"\.webp$",
    r"^noreply@", r"^no-reply@", r"^donotreply@",
    r"@sentry\.", r"@example\.", r"@test\.",
    r"wix\.com$", r"squarespace\.com$", r"godaddy\.com$",
    # Generic catch-all domains that almost always bounce
    r"@info\.com$", r"@email\.com$", r"@mail\.com$", r"@webmail\.",
    r"@server\.", r"@domain\.", r"@website\.",
    # Large corporate / national brands — never a local small biz
    r"@wawa\.com$", r"@alexanderwang\.com$", r"@github\.com$",
    r"@gannett\.com$", r"@spoton\.com$", r"@vwstores\.com$",
    r"@mountlaurel\.com$", r"@rittenhousehotel\.com$", r"@sila\.org$",
    r"@jae\.com$", r"@harvestseasonal\.com$", r"@dolcegabbana\.com$",
    r"@smalls\.com$", r"@forsythiaphilly\.com$",
]

# Personal email providers — always valid for a small biz owner
_PERSONAL_DOMAINS = {
    "gmail.com", "yahoo.com", "outlook.com", "hotmail.com",
    "icloud.com", "me.com", "mac.com", "aol.com", "comcast.net",
    "verizon.net", "att.net", "msn.com", "live.com", "ymail.com",
}


# Generic industry words + common first names. These are NOT distinctive enough
# to prove an email belongs to a business — "beauty" matching "mybeautyexchange"
# or "richard" matching "richardbolesfuneralservice" are false positives that let
# a scraped, unrelated address (e.g. a funeral home's email on a salon) slip in.
_GENERIC_NAME_WORDS = {
    # industry / descriptors
    "salon", "salons", "nails", "spa", "hair", "barber", "barbers", "beauty",
    "studio", "studios", "shop", "store", "boutique", "cafe", "coffee",
    "restaurant", "grill", "kitchen", "pizza", "pizzeria", "bakery", "diner",
    "auto", "automotive", "repair", "service", "services", "fitness", "gym",
    "cleaning", "cleaners", "landscaping", "photography", "dental", "dentist",
    "medical", "clinic", "center", "centre", "group", "company", "family",
    "home", "homes", "house", "total", "image", "quality", "professional",
    "best", "premier", "elite", "prime", "first", "local", "philly",
    "philadelphia", "jersey", "incorporated",
    # common first names
    "richard", "robert", "michael", "william", "david", "james", "john",
    "joseph", "thomas", "charles", "steven", "kevin", "brian", "george",
    "edward", "ronald", "anthony", "jason", "jeffrey", "nicholas", "frank",
    "mary", "patricia", "jennifer", "linda", "elizabeth", "susan", "jessica",
    "sarah", "karen", "nancy", "maria", "angela", "donna", "michelle",
}


def _email_belongs_to_biz(email: str, name: str) -> bool:
    """Return True if the email is plausibly from this business."""
    domain = email.split("@")[-1].lower().rstrip(".")
    # Personal emails are always acceptable
    if domain in _PERSONAL_DOMAINS:
        return True
    # Strip TLD(s) to get the brand part of the domain
    domain_brand = re.sub(r"\.[a-z]{2,6}(\.[a-z]{2})?$", "", domain).lower()
    # Tokenise business name — words of 5+ chars, minus generic/common words, so
    # only a DISTINCTIVE brand token can vouch for the domain.
    name_words = [w.lower() for w in re.split(r"\W+", name)
                  if len(w) >= 5 and w.lower() not in _GENERIC_NAME_WORDS]
    # Accept if any distinctive name word appears in the domain brand (or vice-versa)
    for word in name_words:
        if word in domain_brand or domain_brand in word:
            return True
    return False

# Local parts (before @) that are too generic or clearly garbage
REJECT_LOCAL_PARTS = re.compile(
    r"^[a-z0-9]$"                          # single character: o@gmail.com
    r"|^[a-z]{1,2}[0-9]{0,2}$"            # 1-2 letters + optional digits: ab@...
    r"|^(test|user|admin|postmaster|webmaster|hostmaster|abuse|spam|bounce)$",
    re.IGNORECASE,
)

PREFER_PATTERNS = [
    r"@gmail\.com$", r"@yahoo\.com$", r"@outlook\.com$", r"@hotmail\.com$",
    r"@icloud\.com$", r"@me\.com$", r"@mac\.com$",
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

# ---------------------------------------------------------------------------
# Email extraction helpers
# ---------------------------------------------------------------------------

EMAIL_RE = re.compile(
    r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}",
    re.IGNORECASE,
)


def extract_emails_from_text(text: str) -> list[str]:
    found = EMAIL_RE.findall(text)
    results = []
    for email in found:
        email = email.strip(".,;:\"'()")
        if any(re.search(p, email, re.IGNORECASE) for p in REJECT_EMAIL_PATTERNS):
            continue
        local = email.split("@")[0]
        if REJECT_LOCAL_PARTS.match(local):
            continue
        results.append(email.lower())
    return list(dict.fromkeys(results))


def score_email(email: str, name: str = "") -> int:
    score = 0
    for pattern in PREFER_PATTERNS:
        if re.search(pattern, email, re.IGNORECASE):
            score += 10
            break
    local = email.split("@")[0]
    if len(local) > 30:
        score -= 5
    if re.match(r"^(info|contact|hello|hi|booking|reservations|owner|manager)", local, re.IGNORECASE):
        score += 5
    # Strongly prefer the business's OWN custom domain over a generic free inbox —
    # an email on their own domain is the most reliable, deliverable address.
    domain = email.split("@")[-1].lower()
    if name and domain not in _PERSONAL_DOMAINS:
        brand = re.sub(r"\.[a-z]{2,6}(\.[a-z]{2})?$", "", domain)
        toks = [w.lower() for w in re.split(r"\W+", name)
                if len(w) >= 5 and w.lower() not in _GENERIC_NAME_WORDS]
        if any(t in brand for t in toks):
            score += 20
    return score


def best_email(candidates: list[str], name: str = "") -> str:
    if not candidates:
        return ""
    return max(candidates, key=lambda e: score_email(e, name))

# ---------------------------------------------------------------------------
# Fetching helpers
# ---------------------------------------------------------------------------

def safe_fetch(url: str) -> str:
    """Plain HTTP GET on the shared pooled session.

    Streams and caps the body at 512 KB — some 'contact' pages are multi-MB of
    inlined base64 images, and parsing those was a large part of the old CPU
    cost for zero extra emails."""
    try:
        resp = _SESSION.get(url, timeout=REQUEST_TIMEOUT, allow_redirects=True, stream=True)
        if not resp.ok or "text" not in resp.headers.get("content-type", ""):
            resp.close()
            return ""
        body = resp.raw.read(512_000, decode_content=True) or b""
        resp.close()
        return body.decode(resp.encoding or "utf-8", errors="replace")
    except Exception:
        pass
    return ""


def _emails_from_html(html: str, name: str) -> list[str]:
    """Pull business-matching emails out of a page.

    Uses a regex pass first and only falls back to BeautifulSoup when the raw
    scan finds nothing — building a full DOM for every page was pure overhead
    on the ~90% of pages that have the address sitting in a mailto: link."""
    if not html:
        return []
    hits = [e for e in extract_emails_from_text(html) if _email_belongs_to_biz(e, name)]
    if hits:
        return hits
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    return [e for e in extract_emails_from_text(soup.get_text(separator=" "))
            if _email_belongs_to_biz(e, name)]


def should_skip_url(url: str) -> bool:
    try:
        domain = urlparse(url).netloc.lower().lstrip("www.")
        return any(domain == d or domain.endswith("." + d) for d in SKIP_DOMAINS)
    except Exception:
        return True

# ---------------------------------------------------------------------------
# Core enrichment logic for one business
# ---------------------------------------------------------------------------

# A single browser is shared by every worker that needs one, instead of the old
# behaviour of launching (and tearing down) a full Chromium per URL. Only built
# if --render is passed; most runs never touch it.
_BROWSER_LOCK = threading.Lock()
_BROWSER = None
_BROWSER_PW = None
RENDER_ENABLED = False


def _shared_browser():
    global _BROWSER, _BROWSER_PW
    if _BROWSER is None:
        _BROWSER_PW = _pw().start()
        _BROWSER = _BROWSER_PW.chromium.launch(headless=True)
    return _BROWSER


def close_browser() -> None:
    global _BROWSER, _BROWSER_PW
    try:
        if _BROWSER is not None:
            _BROWSER.close()
        if _BROWSER_PW is not None:
            _BROWSER_PW.stop()
    except Exception:
        pass
    _BROWSER, _BROWSER_PW = None, None


def _playwright_fetch(url: str) -> str:
    """Render a JS-heavy page and return its text. Opt-in only (--render)."""
    if not (RENDER_ENABLED and _PLAYWRIGHT_OK):
        return ""
    try:
        with _BROWSER_LOCK:
            page = _shared_browser().new_page()
            try:
                page.goto(url, timeout=15000, wait_until="domcontentloaded")
                page.wait_for_timeout(1500)
                return page.inner_text("body")
            finally:
                page.close()
    except Exception:
        return ""


def find_email_for_business(name: str, city: str, website: str = "",
                            use_search: bool = False) -> str:
    """Find a contact email. Cheapest source first, and stop at the first hit.

    The business's own site is both the most reliable source and the cheapest,
    so it runs first and short-circuits. Search-engine and Yelp fallbacks are
    off by default — both are actively blocked from this machine, so they only
    ever contributed timeouts."""
    # ── 0. The business's own website — most reliable, and usually the only hit
    if website and website.startswith("http"):
        base = website.rstrip("/")
        for path in ["", "/contact", "/contact-us", "/about"]:
            candidates = _emails_from_html(safe_fetch(base + path), name)
            if candidates:
                return best_email(candidates, name)

    if not use_search:
        return ""

    # ── 1. Search-engine fallback (opt-in via --search) ───────────────────────
    query = f'"{name}" {city} contact email'
    urls = []
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=6))
        urls = [r["href"] for r in results if r.get("href") and not should_skip_url(r["href"])]
    except Exception:
        pass

    all_emails: list[str] = []

    for url in urls[:MAX_PAGES]:
        time.sleep(FETCH_DELAY)
        all_emails.extend(_emails_from_html(safe_fetch(url), name))
        if all_emails:
            break

    # ── 2. Rendered fallback (opt-in via --render) ────────────────────────────
    if not all_emails and RENDER_ENABLED and _PLAYWRIGHT_OK and urls:
        for url in urls[:2]:
            time.sleep(FETCH_DELAY)
            text = _playwright_fetch(url)
            if text:
                all_emails.extend(
                    e for e in extract_emails_from_text(text)
                    if _email_belongs_to_biz(e, name)
                )
                if all_emails:
                    break

    # ── 3. Yelp direct URL fallback ───────────────────────────────────────────
    if not all_emails:
        yelp_query = name.lower().replace(" ", "-") + "-" + city.lower().split(",")[0].replace(" ", "-")
        time.sleep(FETCH_DELAY)
        all_emails.extend(
            _emails_from_html(safe_fetch(f"https://www.yelp.com/biz/{yelp_query}"), name)
        )

    return best_email(all_emails, name)

# ---------------------------------------------------------------------------
# Progress tracker
# ---------------------------------------------------------------------------

class Progress:
    def __init__(self, total: int):
        self.total = total
        self.done = 0
        self.found = 0
        self._lock = threading.Lock()

    def tick(self, found_email: bool):
        with self._lock:
            self.done += 1
            if found_email:
                self.found += 1
            pct = int(self.done / self.total * 100)
            print(
                f"  [{self.done}/{self.total}] {pct}% done  |  "
                f"{self.found} emails found so far",
                flush=True,
            )

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def parse_args():
    parser = argparse.ArgumentParser(
        description="WebByMaya — auto-enrich prospects CSV with contact emails",
    )
    parser.add_argument(
        "--input", required=True, metavar="CSV",
        help="Path to the prospects CSV from find_prospects.py",
    )
    parser.add_argument(
        "--workers", type=int, default=6, metavar="N",
        help="Parallel workers (default: 6 — lower if you get blocked)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print found emails without writing output file",
    )
    parser.add_argument(
        "--all", action="store_true",
        help="Also look up businesses with no website (default: skip them — "
             "there is nothing to scrape, and they are ~96%% of every run)",
    )
    parser.add_argument(
        "--search", action="store_true",
        help="Enable the DuckDuckGo + Yelp fallbacks (default: off — both are "
             "blocked from this machine and only cost timeouts)",
    )
    parser.add_argument(
        "--render", action="store_true",
        help="Enable the headless-browser fallback (default: off — expensive)",
    )
    parser.add_argument(
        "--no-cache", action="store_true",
        help="Ignore the negative cache and re-look-up known-empty businesses",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    if not os.path.exists(args.input):
        sys.exit(f"ERROR: File not found: {args.input}")

    with open(args.input, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames or []
        prospects = list(reader)

    if not prospects:
        sys.exit("No rows found in CSV.")

    if "email" not in fieldnames:
        fieldnames = list(fieldnames) + ["email"]
        for row in prospects:
            row.setdefault("email", "")

    global RENDER_ENABLED
    RENDER_ENABLED = args.render

    contacted_names = _load_contacted_names()
    neg_cache = {} if args.no_cache else _load_negative_cache()

    to_enrich = []
    skipped_contacted = skipped_no_site = skipped_cached = 0
    for i, row in enumerate(prospects):
        if row.get("email", "").strip():
            continue                       # already has an email — nothing to enrich
        norm = _norm_business_name(row.get("name", ""))
        if norm in contacted_names:
            if "email_status" in fieldnames:
                row["email_status"] = row.get("email_status", "") or "already_contacted"
            skipped_contacted += 1
            continue                       # already emailed in a prior run — don't waste a lookup
        if not args.all and not _has_own_website(row):
            if "email_status" in fieldnames:
                row["email_status"] = row.get("email_status", "") or "no_website"
            skipped_no_site += 1
            continue                       # nothing to scrape — reach these by phone
        if _negative_cache_is_fresh(neg_cache.get(norm, "")):
            if "email_status" in fieldnames:
                row["email_status"] = row.get("email_status", "") or "no_email_cached"
            skipped_cached += 1
            continue                       # came up empty recently — don't re-fetch
        to_enrich.append(i)
    already_done = (len(prospects) - len(to_enrich)
                    - skipped_contacted - skipped_no_site - skipped_cached)

    print(f"\nLoaded {len(prospects)} prospects.")
    if already_done:
        print(f"  {already_done} already have emails — skipping.")
    if skipped_contacted:
        print(f"  {skipped_contacted} already contacted in a prior run — skipping enrichment (dedup).")
    if skipped_no_site:
        print(f"  {skipped_no_site} have no website to scrape — skipping (use --all to override).")
        print(f"     ^ these are your best leads. Reach them by phone: python3 call_list.py")
    if skipped_cached:
        print(f"  {skipped_cached} came up empty within the last {NEGATIVE_CACHE_DAYS} days — skipping (negative cache).")
    print(f"  Searching for emails for {len(to_enrich)} businesses "
          f"using {args.workers} parallel workers ...\n")

    if not to_enrich:
        print("Nothing to enrich. All rows already have emails.")
        return

    progress = Progress(len(to_enrich))

    def enrich_one(idx: int):
        row = prospects[idx]
        name    = row.get("name", "").strip()
        city    = row.get("city", row.get("address", "")).strip()
        website = row.get("website", "").strip()
        if not name:
            progress.tick(False)
            return idx, ""
        email = find_email_for_business(name, city, website=website,
                                        use_search=args.search)
        progress.tick(bool(email))
        if args.dry_run and email:
            print(f"    ✓ {name} → {email}")
        return idx, email

    try:
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = {pool.submit(enrich_one, i): i for i in to_enrich}
            for future in as_completed(futures):
                idx, email = future.result()
                prospects[idx]["email"] = email
    finally:
        close_browser()

    # Remember the misses so tomorrow's run doesn't repeat them.
    if not args.no_cache:
        from datetime import datetime
        today = datetime.now().isoformat(timespec="seconds")
        for idx in to_enrich:
            if not prospects[idx].get("email", "").strip():
                nm = _norm_business_name(prospects[idx].get("name", ""))
                if nm:
                    neg_cache[nm] = today
        _save_negative_cache(neg_cache)

    found = sum(1 for row in prospects if row.get("email", "").strip())
    print(f"\n✓ Enrichment complete: {found}/{len(prospects)} businesses have emails.")

    if args.dry_run:
        print("Dry run — no file written.")
        return

    p = Path(args.input)
    output_path = str(p.parent / (p.stem + "_enriched" + p.suffix))
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(prospects)

    print(f"Written to: {output_path}")
    print(f"\nNext step:")
    print(f"  python3 batch_send_outreach.py --input {output_path} --dry-run")


if __name__ == "__main__":
    main()
