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


def _email_belongs_to_biz(email: str, name: str) -> bool:
    """Return True if the email is plausibly from this business."""
    domain = email.split("@")[-1].lower().rstrip(".")
    # Personal emails are always acceptable
    if domain in _PERSONAL_DOMAINS:
        return True
    # Strip TLD(s) to get the brand part of the domain
    domain_brand = re.sub(r"\.[a-z]{2,6}(\.[a-z]{2})?$", "", domain).lower()
    # Tokenise business name — words of 5+ chars to avoid short coincidental matches
    name_words = [w.lower() for w in re.split(r"\W+", name) if len(w) >= 5]
    # Accept if any name word appears in the domain brand (or vice-versa)
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


def score_email(email: str) -> int:
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
    return score


def best_email(candidates: list[str]) -> str:
    if not candidates:
        return ""
    return max(candidates, key=score_email)

# ---------------------------------------------------------------------------
# Fetching helpers
# ---------------------------------------------------------------------------

def safe_fetch(url: str) -> str:
    try:
        resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT, allow_redirects=True)
        if resp.ok and "text" in resp.headers.get("content-type", ""):
            return resp.text
    except Exception:
        pass
    return ""


def should_skip_url(url: str) -> bool:
    try:
        domain = urlparse(url).netloc.lower().lstrip("www.")
        return any(domain == d or domain.endswith("." + d) for d in SKIP_DOMAINS)
    except Exception:
        return True

# ---------------------------------------------------------------------------
# Core enrichment logic for one business
# ---------------------------------------------------------------------------

def _playwright_fetch(url: str) -> str:
    """Render a JS-heavy page with Playwright and return its text content."""
    if not _PLAYWRIGHT_OK:
        return ""
    try:
        with _pw() as pw:
            browser = pw.chromium.launch(headless=True)
            page    = browser.new_page()
            page.goto(url, timeout=15000, wait_until="domcontentloaded")
            page.wait_for_timeout(2000)
            text = page.inner_text("body")
            browser.close()
            return text
    except Exception:
        return ""


def find_email_for_business(name: str, city: str, website: str = "") -> str:
    # ── 0. Try the business's own website first (most reliable) ──────────────
    if website and website.startswith("http"):
        for path in ["", "/contact", "/contact-us", "/about"]:
            html = safe_fetch(website.rstrip("/") + path)
            if html:
                soup = BeautifulSoup(html, "html.parser")
                for tag in soup(["script", "style"]):
                    tag.decompose()
                candidates = [
                    e for e in extract_emails_from_text(soup.get_text(separator=" "))
                    if _email_belongs_to_biz(e, name)
                ]
                if candidates:
                    return best_email(candidates)

    # ── 1. DuckDuckGo search ──────────────────────────────────────────────────
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
        html = safe_fetch(url)
        if not html:
            continue
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style"]):
            tag.decompose()
        emails = [
            e for e in extract_emails_from_text(soup.get_text(separator=" "))
            if _email_belongs_to_biz(e, name)
        ]
        all_emails.extend(emails)
        if all_emails:
            break

    # ── 2. Playwright fallback ────────────────────────────────────────────────
    if not all_emails and _PLAYWRIGHT_OK and urls:
        for url in urls[:2]:
            time.sleep(FETCH_DELAY)
            text = _playwright_fetch(url)
            if text:
                emails = [
                    e for e in extract_emails_from_text(text)
                    if _email_belongs_to_biz(e, name)
                ]
                all_emails.extend(emails)
                if all_emails:
                    break

    # ── 3. Yelp direct URL fallback ───────────────────────────────────────────
    if not all_emails:
        yelp_query = name.lower().replace(" ", "-") + "-" + city.lower().split(",")[0].replace(" ", "-")
        yelp_url = f"https://www.yelp.com/biz/{yelp_query}"
        time.sleep(FETCH_DELAY)
        html = safe_fetch(yelp_url)
        if html:
            soup = BeautifulSoup(html, "html.parser")
            for tag in soup(["script", "style"]):
                tag.decompose()
            emails = [
                e for e in extract_emails_from_text(soup.get_text(separator=" "))
                if _email_belongs_to_biz(e, name)
            ]
            all_emails.extend(emails)

    return best_email(all_emails)

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

    to_enrich = [i for i, row in enumerate(prospects) if not row.get("email", "").strip()]
    already_done = len(prospects) - len(to_enrich)

    print(f"\nLoaded {len(prospects)} prospects.")
    if already_done:
        print(f"  {already_done} already have emails — skipping.")
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
        email = find_email_for_business(name, city, website=website)
        progress.tick(bool(email))
        if args.dry_run and email:
            print(f"    ✓ {name} → {email}")
        return idx, email

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(enrich_one, i): i for i in to_enrich}
        for future in as_completed(futures):
            idx, email = future.result()
            prospects[idx]["email"] = email

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
