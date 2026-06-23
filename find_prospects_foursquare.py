#!/usr/bin/env python3
"""
find_prospects_foursquare.py — WebByMaya Foursquare Prospect Finder
===================================================================
Free tier: 1,000 API calls/day — no credit card required.

GET YOUR FREE KEY (2 min):
  1. Go to developer.foursquare.com → Create account → Create App
  2. Copy the API Key from your app dashboard
  3. Add to ~/.zshrc:  export FSQ_API_KEY="fsq3..."
  4. Run: source ~/.zshrc

USAGE
  python3 find_prospects_foursquare.py --zone philly-north
  python3 find_prospects_foursquare.py --zone sj-camden --output my_output.csv
"""

import argparse, csv, datetime, json, os, re, sys, time, urllib.request, urllib.parse
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
API_KEY    = os.environ.get("FSQ_API_KEY", "")

FSQ_BASE = "https://api.foursquare.com/v3/places/search"  # deprecated 2025 — exits cleanly on 410

ZONE_LOCATIONS = {
    "philly-center":         "Center City, Philadelphia, PA",
    "philly-north":          "North Philadelphia, PA",
    "philly-northeast":      "Northeast Philadelphia, PA",
    "philly-near-ne":        "Frankford, Philadelphia, PA",
    "philly-west":           "West Philadelphia, PA",
    "philly-south":          "South Philadelphia, PA",
    "philly-northwest":      "Northwest Philadelphia, PA",
    "sj-camden":             "Camden, NJ",
    "sj-cherry-hill":        "Cherry Hill, NJ",
    "sj-mount-laurel":       "Mount Laurel, NJ",
    "sj-gloucester":         "Glassboro, NJ",
    "sj-voorhees":           "Voorhees, NJ",
    "de-wilmington":         "Wilmington, DE",
    "de-newark":             "Newark, DE",
    "de-dover":              "Dover, DE",
    "pa-montco-south":       "Norristown, PA",
    "pa-montco-east":        "Horsham, PA",
    "pa-montco-north":       "Lansdale, PA",
    "pa-delco-inner":        "Upper Darby, PA",
    "pa-delco-outer":        "Media, PA",
    "pa-bucks-lower":        "Bristol, PA",
    "pa-bucks-upper":        "Doylestown, PA",
    "pa-chester-west":       "West Chester, PA",
    "pa-chester-east":       "Coatesville, PA",
    "pa-lancaster-city":     "Lancaster, PA",
    "pa-lancaster-north":    "Lititz, PA",
    "pa-lancaster-east":     "Ephrata, PA",
    "pa-berks-reading":      "Reading, PA",
    "pa-berks-north":        "Kutztown, PA",
    "pa-lehigh-allentown":   "Allentown, PA",
    "pa-lehigh-bethlehem":   "Bethlehem, PA",
    "pa-northampton-easton": "Easton, PA",
    "pa-york-city":          "York, PA",
    "pa-york-east":          "Red Lion, PA",
    "pa-harrisburg":         "Harrisburg, PA",
    "pa-dauphin-east":       "Hershey, PA",
    "pa-lebanon":            "Lebanon, PA",
    "pa-schuylkill":         "Pottsville, PA",
    "md-baltimore-inner":    "Baltimore, MD",
    "md-baltimore-north":    "Towson, MD",
    "md-baltimore-east":     "Essex, MD",
    "md-baltimore-west":     "Catonsville, MD",
    "md-baltimore-south":    "Dundalk, MD",
    "md-annapolis":          "Annapolis, MD",
    "md-columbia":           "Columbia, MD",
    "md-ellicott-city":      "Ellicott City, MD",
    "md-bel-air":            "Bel Air, MD",
    "md-dundalk":            "Dundalk, MD",
    "md-rockville":          "Rockville, MD",
    "md-silver-spring":      "Silver Spring, MD",
    "sj-atlantic-city":      "Atlantic City, NJ",
    "sj-vineland":           "Vineland, NJ",
    "sj-millville":          "Millville, NJ",
    "sj-bridgeton":          "Bridgeton, NJ",
    "sj-pleasantville":      "Pleasantville, NJ",
    "sj-somers-point":       "Somers Point, NJ",
    "sj-hammonton":          "Hammonton, NJ",
    "sj-medford":            "Medford, NJ",
    "sj-marlton":            "Marlton, NJ",
    "sj-turnersville":       "Turnersville, NJ",
    "sj-washington-twp":     "Washington Township, NJ",
    "nj-trenton":            "Trenton, NJ",
    "nj-hamilton":           "Hamilton, NJ",
    "nj-princeton":          "Princeton, NJ",
    "nj-new-brunswick":      "New Brunswick, NJ",
    "nj-edison":             "Edison, NJ",
    "de-middletown":         "Middletown, DE",
    "de-milford":            "Milford, DE",
    "de-seaford":            "Seaford, DE",
    "de-rehoboth":           "Rehoboth Beach, DE",
    "pa-stroudsburg":        "Stroudsburg, PA",
    "pa-wilkes-barre":       "Wilkes-Barre, PA",
    "pa-scranton":           "Scranton, PA",
}

# (search query, friendly category name)
SEARCH_CATEGORIES = [
    ("hair salon",        "hair salon"),
    ("nail salon",        "nail salon"),
    ("beauty salon",      "beauty salon"),
    ("spa",               "spa"),
    ("massage",           "massage"),
    ("restaurant",        "restaurant"),
    ("cafe",              "cafe"),
    ("bakery",            "bakery"),
    ("auto repair",       "auto repair"),
    ("tattoo",            "tattoo parlor"),
    ("florist",           "florist"),
    ("pet grooming",      "pet store"),
    ("cleaning service",  "cleaning service"),
    ("gym",               "gym"),
    ("photographer",      "photographer"),
    ("landscaping",       "landscaping"),
]

SOCIAL_DOMAINS = {"facebook.com","instagram.com","twitter.com","yelp.com",
                  "google.com","linktr.ee","tiktok.com","youtube.com"}

CSV_COLUMNS = ["name","address","phone","email","category","city",
               "place_id","maps_url","website","website_status",
               "has_website","rating","review_count","notes","sms_status","email_status"]


def fsq_search(query: str, near: str, limit: int = 50) -> list[dict]:
    if not API_KEY:
        sys.exit("ERROR: FSQ_API_KEY not set.\nGet a free key at developer.foursquare.com\nThen: export FSQ_API_KEY='fsq3...' in ~/.zshrc")
    params = urllib.parse.urlencode({
        "query": query,
        "near":  near,
        "limit": limit,
        "fields": "fsq_id,name,location,tel,website,rating,stats,categories",
    })
    req = urllib.request.Request(
        f"{FSQ_BASE}?{params}",
        headers={"Authorization": API_KEY, "Accept": "application/json"},
    )
    try:
        resp = json.loads(urllib.request.urlopen(req, timeout=15).read())
        return resp.get("results", [])
    except urllib.error.HTTPError as e:
        if e.code == 410:
            print("  [FSQ] API deprecated — Foursquare retired the free Places API in 2025. Skipping.")
            sys.exit(0)
        if e.code == 401:
            sys.exit("ERROR: FSQ_API_KEY invalid. Check developer.foursquare.com")
        print(f"  [WARN] Foursquare {e.code} for '{query}' in '{near}'")
        return []
    except Exception as ex:
        print(f"  [WARN] Foursquare error: {ex}")
        return []


def website_status(url: str) -> tuple[str, str]:
    """Returns (has_website label, website_status)."""
    if not url:
        return "No", "no_website"
    domain = re.sub(r"https?://(www\.)?", "", url).split("/")[0].lower()
    if any(s in domain for s in SOCIAL_DOMAINS):
        return "Yes - social", "social"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}, method="HEAD")
        r = urllib.request.urlopen(req, timeout=8)
        if r.status < 400:
            return "Yes", ""
        return "Yes - dead", "dead"
    except Exception:
        return "Yes - dead", "dead"


def place_to_row(place: dict, category: str, city: str) -> dict:
    loc      = place.get("location", {})
    address  = ", ".join(filter(None, [
        loc.get("address", ""),
        loc.get("locality", ""),
        loc.get("region", ""),
        loc.get("postcode", ""),
    ]))
    phone   = place.get("tel", "").strip()
    website = place.get("website", "").strip()
    fsq_id  = place.get("fsq_id", "")
    maps_url = f"https://foursquare.com/v/{fsq_id}" if fsq_id else ""
    rating  = place.get("rating", "")
    stats   = place.get("stats", {})
    reviews = stats.get("total_ratings", "")

    has_web, ws = website_status(website)

    return {
        "name":           place.get("name", "").strip(),
        "address":        address or city,
        "phone":          phone,
        "email":          "",
        "category":       category,
        "city":           city,
        "place_id":       f"fsq_{fsq_id}",
        "maps_url":       maps_url,
        "website":        website,
        "website_status": ws,
        "has_website":    has_web,
        "rating":         str(rating),
        "review_count":   str(reviews),
        "notes":          "source:foursquare",
        "sms_status":     "",
        "email_status":   "",
    }


def main():
    ap = argparse.ArgumentParser(description="WebByMaya — Foursquare prospect finder (free, 1k/day)")
    ap.add_argument("--zone",    required=True, help="Zone key (e.g. philly-north)")
    ap.add_argument("--output",  default="", help="Output CSV path")
    ap.add_argument("--delay",   type=float, default=0.25, help="Seconds between API calls (default 0.25)")
    args = ap.parse_args()

    city = ZONE_LOCATIONS.get(args.zone)
    if not city:
        print(f"[FSQ] Unknown zone '{args.zone}' — skipping.")
        sys.exit(0)

    today  = datetime.date.today().strftime("%Y-%m-%d")
    output = args.output or str(SCRIPT_DIR / f"prospects_fsq_{today}.csv")

    print(f"\n{'='*60}")
    print(f"  WebByMaya Foursquare Prospect Finder")
    print(f"  Zone : {args.zone}  →  {city}")
    print(f"  Date : {today}")
    print(f"{'='*60}\n")

    all_rows: dict[str, dict] = {}  # keyed by name.lower() to dedup

    for query, cat in SEARCH_CATEGORIES:
        print(f"  Searching '{query}' in {city}...")
        results = fsq_search(query, city)
        added = 0
        for place in results:
            row = place_to_row(place, cat, city)
            if not row["name"]:
                continue
            if row["has_website"] == "Yes":
                continue  # skip businesses with working websites
            key = row["name"].lower()
            if key not in all_rows:
                all_rows[key] = row
                added += 1
        print(f"    → {len(results)} results, {added} new leads")
        time.sleep(args.delay)

    rows = list(all_rows.values())
    print(f"\nTotal unique leads: {len(rows)}")

    if not rows:
        print("No new prospects found from Foursquare.")
        return

    with open(output, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)

    print(f"Saved → {output}")


if __name__ == "__main__":
    main()
