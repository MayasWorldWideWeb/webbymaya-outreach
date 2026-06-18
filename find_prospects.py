"""
find_prospects.py — WebByMaya Google Places Prospect Finder
============================================================
Finds local businesses that either have NO website or have a bad/outdated one
(dead link, parked domain, social-media-only, or "coming soon" page).
Also attempts to find a contact email for every prospect.
Runs all searches in parallel for speed.

SETUP
-----
1. Install dependencies:
       pip3 install googlemaps requests

2. Set your API key:
       export GOOGLE_PLACES_API_KEY="your_key_here"

3. Run:
       python3 find_prospects.py --city "Cedar City, UT"
       python3 find_prospects.py --city "Page, AZ" --radius 5000
       python3 find_prospects.py  # defaults to St. George area

FLAGS
-----
   --city CITY       City to search (repeatable). Omit for St. George area default.
   --radius METERS   Search radius in metres (default: 8000 ≈ 5 miles)
   --workers N       Parallel threads (default: 20)
   --categories LIST Comma-separated business types (default: all built-in)

OUTPUT
------
   prospects_YYYY-MM-DD.csv
   Columns: name, address, phone, contact_email, category, city,
            place_id, maps_url, website, website_status, has_website,
            rating, review_count, notes
   website_status values: dead | parked | soon | social | (blank = no website)
"""

import argparse
import csv
import datetime
import json
import os
import re
import sys
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urlparse, urljoin
from sb import log_prospects

try:
    import googlemaps
except ImportError:
    sys.exit("ERROR: googlemaps not found.\nInstall: pip3 install googlemaps")

try:
    import requests
    requests.packages.urllib3.disable_warnings()
except ImportError:
    sys.exit("ERROR: requests not found.\nInstall: pip3 install requests")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEFAULT_WORKERS        = 80   # parallel search jobs
DEFAULT_DETAIL_WORKERS = 20   # parallel Place Detail API calls per search
DEFAULT_WEB_WORKERS    = 50   # parallel website health checks per search

DEFAULT_LOCATIONS = [
    ("St. George",  (37.0965, -113.5684), 8000),
    ("Hurricane",   (37.1753, -113.2899), 5000),
    ("Washington",  (37.1305, -113.5082), 5000),
    ("Ivins",       (37.1686, -113.6791), 4000),
]

DEFAULT_CATEGORIES = [
    "restaurant", "cafe", "bakery",
    "hair salon", "nail salon", "beauty salon",
    "spa", "massage",
    "photographer", "videographer",
    "auto repair", "mechanic",
    "landscaping", "lawn care", "cleaning service",
    "personal trainer", "gym", "fitness",
    "tattoo parlor", "pet grooming", "pet store", "florist",
]

CHAIN_KEYWORDS = {
    "mcdonald", "burger king", "wendy", "subway", "taco bell", "kfc",
    "pizza hut", "domino", "papa john", "little caesar",
    "starbucks", "dunkin", "panda express", "chipotle", "chick-fil-a",
    "olive garden", "applebee", "chili's", "chilis", "ihop", "denny",
    "walmart", "target", "costco", "home depot", "lowe's", "lowes",
    "walgreen", "cvs", "rite aid",
    "great clips", "supercuts", "sport clips",
    "planet fitness", "la fitness", "anytime fitness", "24 hour fitness",
    "jiffy lube", "valvoline", "midas", "pep boys", "o'reilly", "autozone",
    "holiday inn", "marriott", "hilton", "hampton inn", "best western",
    "jack in the box", "carl's jr", "sonic drive",
    "jersey mike", "jimmy john", "firehouse subs", "fantastic sam",
}

MIN_REVIEWS = 3

# ---------------------------------------------------------------------------
# Named city zones (zip-code groups) for large cities
# Usage: --zone philly-center  or  --zips "19102,19103,19106"
# ---------------------------------------------------------------------------

CITY_ZONES = {
    # Philadelphia zones
    "philly-center":    ["19102", "19103", "19106", "19107", "19146", "19147"],
    "philly-north":     ["19120", "19121", "19122", "19123", "19133", "19134", "19140", "19141"],
    "philly-northeast": ["19111", "19114", "19115", "19116", "19135", "19136", "19149", "19152", "19154"],
    "philly-near-ne":   ["19124", "19125", "19134"],
    "philly-west":      ["19104", "19131", "19139", "19143", "19151"],
    "philly-south":     ["19112", "19145", "19148"],
    "philly-northwest":  ["19117", "19118", "19119", "19126", "19128", "19129", "19138", "19150"],

    # South Jersey zones
    "sj-camden":        ["08101", "08102", "08103", "08104", "08105", "08030", "08110"],
    "sj-cherry-hill":   ["08002", "08003", "08034", "08033", "08043", "08108"],
    "sj-mount-laurel":  ["08054", "08057", "08053", "08021"],
    "sj-gloucester":    ["08028", "08096", "08080", "08094", "08012", "08093"],
    "sj-voorhees":      ["08043", "08033", "08108", "08107", "08078", "08077"],

    # Delaware zones
    "de-wilmington":    ["19801", "19802", "19803", "19805", "19806", "19809"],
    "de-newark":        ["19711", "19713", "19702", "19707", "19709"],
    "de-dover":         ["19901", "19904"],

    # Montgomery County PA
    "pa-montco-south":  ["19401", "19403", "19405", "19406", "19428", "19002", "19422"],
    "pa-montco-east":   ["19046", "19001", "19044", "19090", "19038", "19072", "19096"],
    "pa-montco-north":  ["19446", "19454", "19440", "19047", "18974", "18976", "19462"],

    # Delaware County PA
    "pa-delco-inner":   ["19082", "19026", "19003", "19041", "19050", "19081", "19023"],
    "pa-delco-outer":   ["19063", "19013", "19014", "19079", "19032", "19061", "19064"],

    # Bucks County PA
    "pa-bucks-lower":   ["19054", "19055", "19056", "19057", "19007", "19067", "19047"],
    "pa-bucks-upper":   ["18901", "18902", "18974", "18976", "18914", "18944", "18940"],

    # Chester County PA
    "pa-chester":       ["19380", "19382", "19320", "19460", "19341", "19335", "19425"],
}

ZONE_DEFAULT_CITY = {
    "philly-center":    "Philadelphia, PA",
    "philly-north":     "Philadelphia, PA",
    "philly-northeast": "Philadelphia, PA",
    "philly-near-ne":   "Philadelphia, PA",
    "philly-west":      "Philadelphia, PA",
    "philly-south":     "Philadelphia, PA",
    "philly-northwest":  "Philadelphia, PA",
    "sj-camden":        "Camden, NJ",
    "sj-cherry-hill":   "Cherry Hill, NJ",
    "sj-mount-laurel":  "Mount Laurel, NJ",
    "sj-gloucester":    "Gloucester County, NJ",
    "sj-voorhees":      "Voorhees, NJ",
    "de-wilmington":    "Wilmington, DE",
    "de-newark":        "Newark, DE",
    "de-dover":         "Dover, DE",
    "pa-montco-south":  "Norristown, PA",
    "pa-montco-east":   "Abington, PA",
    "pa-montco-north":  "Lansdale, PA",
    "pa-delco-inner":   "Upper Darby, PA",
    "pa-delco-outer":   "Media, PA",
    "pa-bucks-lower":   "Levittown, PA",
    "pa-bucks-upper":   "Doylestown, PA",
    "pa-chester":       "West Chester, PA",
}

SOCIAL_DOMAINS = {
    "facebook.com", "fb.com", "instagram.com",
    "twitter.com", "x.com", "tiktok.com",
    "yelp.com", "linkedin.com", "youtube.com", "linktr.ee",
}

PARKED_KEYWORDS = [
    "domain for sale", "buy this domain", "this domain is for sale",
    "godaddy", "namecheap", "sedo.com", "afternic", "dan.com",
    "domain parking", "parked domain",
]

SOON_KEYWORDS = [
    "coming soon", "under construction", "launching soon",
    "website coming soon", "we're coming soon", "stay tuned",
    "site is under construction",
]

# Regex for email addresses
EMAIL_RE = re.compile(
    r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}',
    re.IGNORECASE,
)

# Email domains to discard — these are never real contact emails
EMAIL_EXCLUDE_DOMAINS = {
    "example.com", "sentry.io", "wix.com", "squarespace.com",
    "wordpress.com", "shopify.com", "godaddy.com", "cloudflare.com",
    "google.com", "facebook.com", "instagram.com", "twitter.com",
    "amazonaws.com", "w3.org", "schema.org", "openid.net",
    "jquery.com", "bootstrapcdn.com", "fontawesome.com",
}

# Contact pages to try when the homepage has no email
CONTACT_PATHS = ["/contact", "/contact-us", "/about", "/about-us", "/reach-us"]

# Prefixes that are almost always contact emails (ranked by preference)
CONTACT_PREFIXES = ["info", "contact", "hello", "hi", "support", "admin", "booking", "reservations", "office"]

CSV_COLUMNS = [
    "name", "address", "phone", "email",
    "category", "city", "place_id", "maps_url",
    "website", "website_status", "has_website",
    "rating", "review_count", "notes",
]

HTTP_HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}


# ---------------------------------------------------------------------------
# Thread-safe progress counter
# ---------------------------------------------------------------------------

PROGRESS_FILE = Path(__file__).parent / "search_progress.json"


class Progress:
    def __init__(self, total, label=""):
        self.total = total
        self.done = 0
        self.found = 0
        self.label = label
        self._lock = threading.Lock()
        self._started = time.time()
        self._write()

    def tick(self, new_found=0):
        with self._lock:
            self.done += 1
            self.found += new_found
            print(f"  [{self.done}/{self.total}] done  |  {self.found} prospects so far", flush=True)
            self._write()

    def _write(self):
        try:
            import json
            data = {
                "label":      self.label,
                "total":      self.total,
                "done":       self.done,
                "found":      self.found,
                "started_at": self._started,
                "updated_at": time.time(),
            }
            PROGRESS_FILE.write_text(json.dumps(data))
        except Exception:
            pass

    def finish(self):
        self._write()
        try:
            import json
            data = json.loads(PROGRESS_FILE.read_text())
            data["finished"] = True
            PROGRESS_FILE.write_text(json.dumps(data))
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------

def is_chain(name):
    lower = name.lower()
    return any(kw in lower for kw in CHAIN_KEYWORDS)


# ---------------------------------------------------------------------------
# Email extraction helpers
# ---------------------------------------------------------------------------

def extract_emails(html, site_domain=""):
    """
    Pull email addresses from HTML. Returns a ranked list — contact/info
    prefixes first, then emails matching the site's own domain, then others.
    Filters out known system/CDN email domains.
    """
    raw = EMAIL_RE.findall(html)
    candidates = []
    for email in raw:
        email = email.lower().strip(".")
        domain = email.split("@")[1]
        if domain in EMAIL_EXCLUDE_DOMAINS:
            continue
        # Skip image/asset false-positives
        if re.search(r'\.(png|jpg|gif|svg|js|css|woff)$', domain):
            continue
        candidates.append(email)

    if not candidates:
        return []

    def rank(email):
        prefix = email.split("@")[0]
        domain = email.split("@")[1]
        score = 0
        if prefix in CONTACT_PREFIXES:
            score += 10
        if site_domain and domain == site_domain:
            score += 5
        return score

    return sorted(set(candidates), key=rank, reverse=True)


def fetch_html(url, timeout=5):
    """Fetch a URL and return (final_url, text). Returns ("", "") on failure."""
    try:
        resp = requests.get(url, timeout=timeout, allow_redirects=True,
                            headers=HTTP_HEADERS, verify=False)
        if resp.status_code >= 400:
            return ("", "")
        return (resp.url, resp.text)
    except Exception:
        return ("", "")


def find_contact_email(url, existing_html=""):
    """
    Try to find a contact email for the given URL.
    1. Checks existing_html if provided (avoids re-fetching the homepage).
    2. Fetches the homepage if no email found yet.
    3. Tries CONTACT_PATHS (/contact, /about, etc.) as a fallback.
    Returns the best email found, or "".
    """
    if not url:
        return ""

    try:
        site_domain = urlparse(url).netloc.lstrip("www.").lower()
    except Exception:
        site_domain = ""

    # 1. Check already-fetched HTML
    if existing_html:
        emails = extract_emails(existing_html, site_domain)
        if emails:
            return emails[0]

    # 2. Fetch homepage
    _, html = fetch_html(url)
    if html:
        emails = extract_emails(html, site_domain)
        if emails:
            return emails[0]

    # 3. Try contact / about sub-pages
    base = url.rstrip("/")
    for path in CONTACT_PATHS:
        _, html = fetch_html(base + path)
        if html:
            emails = extract_emails(html, site_domain)
            if emails:
                return emails[0]

    return ""


# ---------------------------------------------------------------------------
# Website health check + email scrape (combined to avoid double-fetching)
# ---------------------------------------------------------------------------

def check_and_scrape(url):
    """
    Returns (status, email) for a URL that a business has listed.
    status: "social" | "dead" | "parked" | "soon" | "ok"
    email:  best contact email found, or ""
    """
    if not url:
        return ("", "")

    try:
        host = urlparse(url).netloc.lower().lstrip("www.")
    except Exception:
        host = url.lower()

    # Social media profile — try to scrape email from it
    if any(sd in host for sd in SOCIAL_DOMAINS):
        email = find_contact_email(url)
        return ("social", email)

    # Fetch the page once and reuse for both health check and email extraction
    final_url, html = fetch_html(url)

    if not html:
        return ("dead", "")

    body = html.lower()[:10000]

    if any(kw in body for kw in PARKED_KEYWORDS):
        return ("parked", "")

    if any(kw in body for kw in SOON_KEYWORDS):
        # Still try to find an email even on coming-soon pages
        email = find_contact_email(url, existing_html=html)
        return ("soon", email)

    # Looks like a real (possibly outdated) site — extract email
    email = find_contact_email(url, existing_html=html)
    return ("ok", email)


# ---------------------------------------------------------------------------
# Geocoding
# ---------------------------------------------------------------------------

def geocode_city(client, city):
    print(f"  Geocoding '{city}' ...")
    results = client.geocode(city)
    if not results:
        sys.exit(f"ERROR: Could not geocode '{city}'. Check spelling and that Geocoding API is enabled.")
    loc = results[0]["geometry"]["location"]
    lat, lng = loc["lat"], loc["lng"]
    print(f"    → ({lat:.4f}, {lng:.4f})")
    return (lat, lng)


# ---------------------------------------------------------------------------
# Places API helpers
# ---------------------------------------------------------------------------

def build_maps_url(place_id):
    return f"https://www.google.com/maps/place/?q=place_id:{place_id}"


def fetch_place_detail(client, place_id):
    try:
        resp = client.place(
            place_id,
            fields=[
                "name", "formatted_address", "formatted_phone_number",
                "website", "place_id", "business_status",
                "rating", "user_ratings_total",
            ],
        )
        return resp.get("result", {})
    except Exception as exc:
        print(f"    [WARN] detail fetch failed for {place_id}: {exc}")
        return None


# ---------------------------------------------------------------------------
# Core search worker
# ---------------------------------------------------------------------------

def search_one(client, city, location, radius, category, seen_ids, seen_lock, progress, no_web_check=False):
    """
    Search one (city, category) pair. Returns a list of prospect dicts.
    Includes businesses with no website AND businesses with a bad/outdated website.
    """
    query = f"{category} in {city}"
    new_place_ids = []

    try:
        response = client.places(query=query, location=location, radius=radius)
    except Exception as exc:
        print(f"    [ERROR] search failed for '{query}': {exc}")
        progress.tick()
        return []

    while True:
        for place in response.get("results", []):
            pid = place.get("place_id", "")
            if not pid:
                continue
            with seen_lock:
                if pid in seen_ids:
                    continue
                seen_ids.add(pid)
            new_place_ids.append(pid)

        next_token = response.get("next_page_token")
        if not next_token:
            break
        time.sleep(2)
        try:
            response = client.places(
                query=query, location=location, radius=radius,
                page_token=next_token,
            )
        except Exception:
            break

    no_website_prospects = []
    needs_web_check = {}   # url -> prospect dict

    if new_place_ids:
        with ThreadPoolExecutor(max_workers=min(DEFAULT_DETAIL_WORKERS, len(new_place_ids))) as detail_pool:
            detail_futures = {
                detail_pool.submit(fetch_place_detail, client, pid): pid
                for pid in new_place_ids
            }
            for future in as_completed(detail_futures):
                pid = detail_futures[future]
                detail = future.result()
                if not detail:
                    continue
                if detail.get("business_status") == "PERMANENTLY_CLOSED":
                    continue

                name = detail.get("name", "")
                if is_chain(name):
                    continue

                review_count = detail.get("user_ratings_total") or 0
                if review_count < MIN_REVIEWS:
                    continue

                website = detail.get("website", "")
                prospect = {
                    "name":           name,
                    "address":        detail.get("formatted_address", ""),
                    "phone":          detail.get("formatted_phone_number", ""),
                    "email":          "",
                    "category":       category,
                    "city":           city,
                    "place_id":       detail.get("place_id", pid),
                    "maps_url":       build_maps_url(pid),
                    "website":        website,
                    "website_status": "",
                    "has_website":    "No" if not website else "Yes",
                    "rating":         detail.get("rating", ""),
                    "review_count":   review_count,
                    "notes":          "",
                }

                if not website:
                    no_website_prospects.append(prospect)
                else:
                    needs_web_check[website] = prospect

    # Check websites + scrape emails in parallel (skipped with --no-web-check)
    bad_website_prospects = []
    if needs_web_check and not no_web_check:
        with ThreadPoolExecutor(max_workers=min(DEFAULT_WEB_WORKERS, len(needs_web_check))) as web_pool:
            web_futures = {
                web_pool.submit(check_and_scrape, url): url
                for url in needs_web_check
            }
            for wf in as_completed(web_futures):
                url = web_futures[wf]
                status, email = wf.result()
                prospect = needs_web_check[url]
                prospect["email"] = email
                if status in ("dead", "parked", "soon", "social"):
                    prospect["website_status"] = status
                    prospect["has_website"] = f"Yes - {status}"
                    bad_website_prospects.append(prospect)

    all_found = no_website_prospects + bad_website_prospects
    progress.tick(len(all_found))
    return all_found


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def parse_args():
    zone_list = ", ".join(CITY_ZONES.keys())
    parser = argparse.ArgumentParser(
        description="WebByMaya — find businesses with no website or a bad/outdated one",
    )
    parser.add_argument("--city", action="append", metavar="CITY",
                        help='City to search, e.g. "Cedar City, UT". Repeatable.')
    parser.add_argument("--radius", type=int, default=8000, metavar="METERS",
                        help="Search radius in metres (default: 8000 ≈ 5 miles)")
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS, metavar="N",
                        help=f"Parallel search threads (default: {DEFAULT_WORKERS})")
    parser.add_argument("--categories", metavar="LIST",
                        help="Comma-separated business types (default: all built-in)")
    parser.add_argument("--no-web-check", action="store_true",
                        help="Skip website health checks — only finds no-website businesses, much faster")
    # Zip code / zone flags for large cities
    parser.add_argument("--zips", metavar="ZIPS",
                        help='Comma-separated zip codes to search individually, e.g. "19102,19103,19106"')
    parser.add_argument("--zone", metavar="ZONE",
                        help=f"Named zip-code zone preset. Options: {zone_list}")
    parser.add_argument("--zip-city", metavar="CITY", default=None,
                        help='City label for zip searches (default auto-detected from zone, or "Philadelphia, PA")')
    parser.add_argument("--zip-radius", type=int, default=2000, metavar="METERS",
                        help="Search radius per zip code in metres (default: 2000 ≈ 1.25 miles)")
    parser.add_argument("--output", metavar="PATH",
                        help="Output CSV path (default: SCRIPT_DIR/prospects_YYYY-MM-DD.csv)")
    return parser.parse_args()


def run():
    args = parse_args()

    api_key = os.environ.get("GOOGLE_PLACES_API_KEY", "")
    if not api_key:
        sys.exit("ERROR: GOOGLE_PLACES_API_KEY not set.\nRun: export GOOGLE_PLACES_API_KEY='...'")

    client = googlemaps.Client(key=api_key)

    if args.zone or args.zips:
        # Zip code / zone mode — geocode each zip individually with a small radius
        if args.zone:
            zone_name = args.zone.lower()
            if zone_name not in CITY_ZONES:
                sys.exit(f"ERROR: Unknown zone '{zone_name}'.\nOptions: {', '.join(CITY_ZONES.keys())}")
            zip_list = CITY_ZONES[zone_name]
            default_city = ZONE_DEFAULT_CITY.get(zone_name, "Philadelphia, PA")
            print(f"\nZone '{zone_name}': {len(zip_list)} zip codes")
        else:
            zip_list = [z.strip() for z in args.zips.split(",") if z.strip()]
            default_city = "Philadelphia, PA"
            print(f"\nCustom zips: {len(zip_list)} zip codes")

        zip_city  = args.zip_city or default_city
        zip_radius = args.zip_radius

        print(f"Geocoding {len(zip_list)} zip code(s) ...")
        locations = []
        for z in zip_list:
            query = f"{z} {zip_city}"
            loc = geocode_city(client, query)
            locations.append((f"{zip_city} ({z})", loc, zip_radius))

    elif args.city:
        print(f"\nGeocoding {len(args.city)} city/cities ...")
        locations = [(c, geocode_city(client, c), args.radius) for c in args.city]
    else:
        print("\nNo --city specified — using default St. George area locations.")
        locations = DEFAULT_LOCATIONS

    categories = (
        [c.strip() for c in args.categories.split(",") if c.strip()]
        if args.categories else DEFAULT_CATEGORIES
    )

    jobs = [
        (city, loc, radius, cat)
        for (city, loc, radius) in locations
        for cat in categories
    ]
    total = len(jobs)
    workers = min(args.workers, total)

    print(f"\nRunning {total} searches across {len(locations)} location(s) "
          f"with {workers} parallel workers ...\n")

    seen_ids = set()
    seen_lock = threading.Lock()
    if args.zone:
        label = f"zone: {args.zone}"
    elif args.zips:
        label = f"zips: {args.zips}"
    elif args.city:
        label = ", ".join(args.city)
    else:
        label = "St. George area"
    progress = Progress(total, label=label)
    all_prospects = []

    no_web_check = getattr(args, "no_web_check", False)
    if no_web_check:
        print("  [fast mode] Website checks disabled — finding no-website businesses only.\n")

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [
            pool.submit(search_one, client, city, loc, radius, cat, seen_ids, seen_lock, progress, no_web_check)
            for (city, loc, radius, cat) in jobs
        ]
        for f in as_completed(futures):
            try:
                all_prospects.extend(f.result())
            except Exception as exc:
                print(f"  [ERROR] job failed: {exc}")

    today = datetime.date.today().strftime("%Y-%m-%d")
    output_path = args.output if args.output else str(Path(__file__).parent / f"prospects_{today}.csv")
    with open(output_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(all_prospects)
    log_prospects(all_prospects)

    no_web      = sum(1 for p in all_prospects if p["has_website"] == "No")
    bad_web     = len(all_prospects) - no_web
    with_email  = sum(1 for p in all_prospects if p["email"])

    progress.finish()

    print(f"\n✓ Done. {len(all_prospects)} total prospects → {output_path}")
    print(f"   {no_web} no website  |  {bad_web} bad/outdated website (dead/parked/soon/social)")
    print(f"   {with_email} contact emails found")


if __name__ == "__main__":
    run()
