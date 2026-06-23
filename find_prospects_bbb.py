#!/usr/bin/env python3
"""
find_prospects_bbb.py — WebByMaya BBB Directory Scraper
=======================================================
Scrapes bbb.org for local businesses. FREE, no API key needed.
Targets businesses with no website (best prospects for WebByMaya).

USAGE
  python3 find_prospects_bbb.py --zone philly-north
  python3 find_prospects_bbb.py --zone sj-camden --output out.csv
"""

import argparse, csv, datetime, json, re, sys, time, urllib.request, urllib.parse
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent

ZONE_LOCATIONS = {
    "philly-north":          "North Philadelphia, PA",
    "philly-northeast":      "Northeast Philadelphia, PA",
    "philly-near-ne":        "Frankford, Philadelphia, PA",
    "philly-west":           "West Philadelphia, PA",
    "philly-south":          "South Philadelphia, PA",
    "philly-northwest":      "Northwest Philadelphia, PA",
    "philly-center":         "Center City Philadelphia, PA",
    "sj-camden":             "Camden, NJ",
    "sj-cherry-hill":        "Cherry Hill, NJ",
    "sj-mount-laurel":       "Mount Laurel, NJ",
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
    "sj-gloucester":         "Glassboro, NJ",
    "sj-voorhees":           "Voorhees, NJ",
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

SEARCH_TERMS = [
    ("hair salon",       "hair salon"),
    ("nail salon",       "nail salon"),
    ("beauty salon",     "beauty salon"),
    ("spa",              "spa"),
    ("massage",          "massage"),
    ("restaurant",       "restaurant"),
    ("bakery",           "bakery"),
    ("auto repair",      "auto repair"),
    ("tattoo",           "tattoo parlor"),
    ("florist",          "florist"),
    ("cleaning service", "cleaning service"),
    ("gym",              "gym"),
    ("landscaping",      "landscaping"),
    ("barber",           "barbershop"),
    ("photographer",     "photographer"),
]

SOCIAL_DOMAINS = {"facebook.com","instagram.com","twitter.com","yelp.com",
                  "google.com","linktr.ee","tiktok.com","youtube.com"}

CSV_COLUMNS = ["name","address","phone","email","category","city",
               "place_id","maps_url","website","website_status",
               "has_website","rating","review_count","notes","sms_status","email_status"]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate",
    "Connection": "keep-alive",
}


def fetch_html(url: str) -> str:
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        resp = urllib.request.urlopen(req, timeout=15)
        raw = resp.read()
        # BBB sometimes sends gzip
        try:
            import gzip
            raw = gzip.decompress(raw)
        except Exception:
            pass
        return raw.decode("utf-8", errors="replace")
    except Exception as e:
        print(f"  [WARN] BBB fetch failed: {e}")
        return ""


def extract_next_data(html: str) -> dict:
    m = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    return {}


def search_bbb(query: str, city_state: str, page: int = 1) -> list[dict]:
    url = (
        "https://www.bbb.org/search?"
        + urllib.parse.urlencode({
            "find_text": query,
            "find_loc":  city_state,
            "sort":      "Distance",
            "page":      page,
        })
    )
    html = fetch_html(url)
    if not html:
        return []

    # BBB embeds results as JSON-LD SearchResultsPage → ItemList → itemListElement
    ld_blocks = re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.DOTALL)
    businesses = []
    for block in ld_blocks:
        try:
            obj = json.loads(block)
        except json.JSONDecodeError:
            continue

        # SearchResultsPage wrapping an ItemList
        if isinstance(obj, dict) and obj.get("@type") == "SearchResultsPage":
            main = obj.get("mainEntity", {})
            for entry in main.get("itemListElement", []):
                item = entry.get("item", entry) if isinstance(entry, dict) else entry
                if isinstance(item, dict):
                    businesses.append(item)
        elif isinstance(obj, dict) and obj.get("@type") == "ItemList":
            for entry in obj.get("itemListElement", []):
                item = entry.get("item", entry) if isinstance(entry, dict) else entry
                if isinstance(item, dict):
                    businesses.append(item)
        elif isinstance(obj, dict) and obj.get("@type") in ("LocalBusiness", "Organization"):
            businesses.append(obj)
        elif isinstance(obj, list):
            for item in obj:
                if isinstance(item, dict) and item.get("@type") in ("LocalBusiness", "Organization"):
                    businesses.append(item)

    return businesses


def parse_business(biz: dict, category: str, city: str):
    # Works for both BBB JSON and JSON-LD schema
    name = (
        biz.get("businessName")
        or biz.get("name")
        or biz.get("legalName")
        or ""
    ).strip()
    if not name:
        return None

    # Address
    addr_obj = biz.get("address") or biz.get("location") or {}
    if isinstance(addr_obj, dict):
        address = ", ".join(filter(None, [
            addr_obj.get("streetAddress", ""),
            addr_obj.get("addressLocality", "") or addr_obj.get("city", ""),
            addr_obj.get("addressRegion", "") or addr_obj.get("state", ""),
            addr_obj.get("postalCode", "") or addr_obj.get("zip", ""),
        ]))
    elif isinstance(addr_obj, str):
        address = addr_obj
    else:
        address = city

    phone = (
        biz.get("phone")
        or biz.get("phoneNumber")
        or biz.get("telephone")
        or ""
    ).strip()

    # BBB JSON-LD puts the BBB profile URL in 'url', NOT the business website
    # Business websites aren't in BBB structured data — all results are no-website prospects
    bbb_profile = (biz.get("url") or "").strip()
    website  = ""  # BBB doesn't expose business websites in LD+JSON
    has_web  = "No"
    ws       = "no_website"

    bbb_id  = biz.get("id") or biz.get("externalID") or biz.get("@id") or ""
    rating  = biz.get("overallRating") or biz.get("ratingValue") or biz.get("rating") or ""
    reviews = biz.get("reviewCount") or biz.get("totalReviews") or biz.get("ratingCount") or ""

    maps_url = bbb_profile or f"https://www.bbb.org/search?find_text={urllib.parse.quote_plus(name)}&find_loc={urllib.parse.quote_plus(city)}"

    return {
        "name":           name,
        "address":        address or city,
        "phone":          phone,
        "email":          "",
        "category":       category,
        "city":           city,
        "place_id":       f"bbb_{bbb_id}" if bbb_id else "",
        "maps_url":       maps_url,
        "website":        website,
        "website_status": ws,
        "has_website":    has_web,
        "rating":         str(rating),
        "review_count":   str(reviews),
        "notes":          "source:bbb",
        "sms_status":     "",
        "email_status":   "",
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--zone",   required=True)
    ap.add_argument("--output", default="")
    ap.add_argument("--delay",  type=float, default=0.6)
    args = ap.parse_args()

    city = ZONE_LOCATIONS.get(args.zone)
    if not city:
        print(f"[BBB] Unknown zone '{args.zone}' — skipping.")
        sys.exit(0)

    today  = datetime.date.today().strftime("%Y-%m-%d")
    output = args.output or str(SCRIPT_DIR / f"prospects_bbb_{today}_{args.zone}.csv")

    print(f"\n[BBB] Zone: {args.zone} → {city}")

    seen: dict[str, dict] = {}

    for query, category in SEARCH_TERMS:
        results = []
        for pg in (1, 2):
            page_results = search_bbb(query, city, page=pg)
            results.extend(page_results)
            if len(page_results) < 15:
                break  # fewer than full page means no page 2
            time.sleep(args.delay)
        added = 0
        for biz in results:
            row = parse_business(biz, category, city)
            if not row or not row["name"]:
                continue
            key = row["name"].lower().strip()
            if key not in seen:
                seen[key] = row
                added += 1
        print(f"  {query}: {len(results)} results → {added} new leads")
        time.sleep(args.delay)

    rows = list(seen.values())
    print(f"[BBB] Total unique no-website leads: {len(rows)}")

    if not rows:
        print("[BBB] No prospects found.")
        sys.exit(0)

    with open(output, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    print(f"[BBB] Saved → {output}")


if __name__ == "__main__":
    main()
