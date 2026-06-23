#!/usr/bin/env python3
"""
find_prospects_tomtom.py — WebByMaya TomTom Places Prospect Finder
==================================================================
Free tier: 2,500 API calls/day — no credit card required.

GET YOUR FREE KEY (5 min):
  1. Go to developer.tomtom.com → Create account (free)
  2. Click "My Apps" → "Create New App"
  3. Enable "Places API" and "Search API"
  4. Copy the API Key
  5. Add to ~/.zshrc:  export TOMTOM_API_KEY="your_key_here"
  6. Then: source ~/.zshrc

USAGE
  python3 find_prospects_tomtom.py --zone philly-north
  python3 find_prospects_tomtom.py --zone sj-camden --output out.csv
"""

import argparse, csv, datetime, json, os, re, sys, time, urllib.request, urllib.parse
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
API_KEY    = os.environ.get("TOMTOM_API_KEY", "")

SEARCH_BASE = "https://api.tomtom.com/search/2/poiSearch/{query}.json"

# Zone → (lat, lon, radius_meters)
ZONE_COORDS = {
    "philly-center":         (39.9526, -75.1652, 4000),
    "philly-north":          (39.9918, -75.1577, 5000),
    "philly-northeast":      (40.0612, -75.0500, 6000),
    "philly-near-ne":        (40.0097, -75.0730, 4000),
    "philly-west":           (39.9601, -75.2301, 5000),
    "philly-south":          (39.9101, -75.1577, 5000),
    "philly-northwest":      (40.0293, -75.1924, 5000),
    "sj-camden":             (39.9259, -75.1196, 5000),
    "sj-cherry-hill":        (39.9346, -75.0246, 6000),
    "sj-mount-laurel":       (39.9515, -74.9093, 6000),
    "sj-gloucester":         (39.7023, -75.1115, 5000),
    "sj-voorhees":           (39.8617, -74.9532, 5000),
    "de-wilmington":         (39.7447, -75.5484, 5000),
    "de-newark":             (39.6837, -75.7497, 5000),
    "de-dover":              (39.1582, -75.5244, 5000),
    "pa-montco-south":       (40.1215, -75.3399, 5000),
    "pa-montco-east":        (40.1968, -75.1218, 5000),
    "pa-montco-north":       (40.2415, -75.2835, 5000),
    "pa-delco-inner":        (39.9612, -75.2657, 5000),
    "pa-delco-outer":        (39.9185, -75.4018, 5000),
    "pa-bucks-lower":        (40.1045, -74.8527, 5000),
    "pa-bucks-upper":        (40.3101, -75.1299, 5000),
    "pa-chester-west":       (39.9595, -75.6055, 5000),
    "pa-chester-east":       (39.9818, -75.8230, 5000),
    "pa-lancaster-city":     (40.0379, -76.3055, 5000),
    "pa-lancaster-north":    (40.1576, -76.3016, 5000),
    "pa-lancaster-east":     (40.1798, -76.1766, 5000),
    "pa-berks-reading":      (40.3357, -75.9268, 5000),
    "pa-berks-north":        (40.5157, -75.7807, 5000),
    "pa-lehigh-allentown":   (40.6023, -75.4714, 6000),
    "pa-lehigh-bethlehem":   (40.6259, -75.3705, 5000),
    "pa-northampton-easton": (40.6884, -75.2207, 5000),
    "pa-york-city":          (39.9626, -76.7277, 5000),
    "pa-york-east":          (39.9015, -76.5996, 5000),
    "pa-harrisburg":         (40.2732, -76.8867, 5000),
    "pa-dauphin-east":       (40.2857, -76.6496, 5000),
    "pa-lebanon":            (40.3418, -76.4113, 5000),
    "pa-schuylkill":         (40.6851, -76.1955, 5000),
    "md-baltimore-inner":    (39.2904, -76.6122, 5000),
    "md-baltimore-north":    (39.4015, -76.6021, 5000),
    "md-baltimore-east":     (39.3085, -76.4780, 5000),
    "md-baltimore-west":     (39.2796, -76.7319, 5000),
    "md-baltimore-south":    (39.2451, -76.5122, 5000),
    "md-annapolis":          (38.9784, -76.4922, 5000),
    "md-columbia":           (39.2037, -76.8610, 5000),
    "md-ellicott-city":      (39.2673, -76.7983, 5000),
    "md-bel-air":            (39.5354, -76.3485, 5000),
    "md-dundalk":            (39.2715, -76.5024, 5000),
    "md-rockville":          (39.0840, -77.1528, 5000),
    "md-silver-spring":      (38.9907, -77.0261, 5000),
    "sj-atlantic-city":      (39.3643, -74.4229, 5000),
    "sj-vineland":           (39.4860, -74.9218, 6000),
    "sj-millville":          (39.4032, -75.0371, 5000),
    "sj-bridgeton":          (39.4265, -75.2349, 5000),
    "sj-pleasantville":      (39.3890, -74.5218, 4000),
    "sj-somers-point":       (39.3179, -74.5996, 4000),
    "sj-hammonton":          (39.6401, -74.7999, 4000),
    "sj-medford":            (39.8701, -74.8249, 4000),
    "sj-marlton":            (39.8951, -74.9218, 4000),
    "sj-turnersville":       (39.7751, -75.0546, 4000),
    "sj-washington-twp":     (39.7901, -75.0849, 4000),
    "nj-trenton":            (40.2171, -74.7429, 5000),
    "nj-hamilton":           (40.2240, -74.6960, 5000),
    "nj-princeton":          (40.3573, -74.6672, 5000),
    "nj-new-brunswick":      (40.4874, -74.4454, 5000),
    "nj-edison":             (40.5187, -74.4121, 5000),
    "de-middletown":         (39.4490, -75.7163, 4000),
    "de-milford":            (38.9126, -75.4288, 4000),
    "de-seaford":            (38.6415, -75.6107, 4000),
    "de-rehoboth":           (38.7151, -75.0746, 4000),
    "pa-stroudsburg":        (40.9870, -75.1977, 5000),
    "pa-wilkes-barre":       (41.2459, -75.8813, 5000),
    "pa-scranton":           (41.4090, -75.6624, 5000),
}

SEARCH_QUERIES = [
    ("nail salon",       "nail salon"),
    ("hair salon",       "hair salon"),
    ("beauty salon",     "beauty salon"),
    ("barber shop",      "barbershop"),
    ("spa",              "spa"),
    ("massage",          "massage"),
    ("restaurant",       "restaurant"),
    ("cafe",             "cafe"),
    ("bakery",           "bakery"),
    ("auto repair",      "auto repair"),
    ("tattoo",           "tattoo parlor"),
    ("florist",          "florist"),
    ("gym fitness",      "gym"),
    ("cleaning service", "cleaning service"),
    ("landscaping",      "landscaping"),
    ("photographer",     "photographer"),
]

SOCIAL_DOMAINS = {"facebook.com","instagram.com","twitter.com","yelp.com",
                  "google.com","linktr.ee","tiktok.com","youtube.com"}

CSV_COLUMNS = ["name","address","phone","email","category","city",
               "place_id","maps_url","website","website_status",
               "has_website","rating","review_count","notes","sms_status","email_status"]


def tomtom_search(query: str, lat: float, lon: float, radius: int, limit: int = 100) -> list[dict]:
    if not API_KEY:
        sys.exit("ERROR: TOMTOM_API_KEY not set.\nGet free key at developer.tomtom.com\nThen: export TOMTOM_API_KEY='your_key' in ~/.zshrc")
    url = SEARCH_BASE.format(query=urllib.parse.quote(query))
    params = urllib.parse.urlencode({
        "key":        API_KEY,
        "lat":        lat,
        "lon":        lon,
        "radius":     radius,
        "limit":      limit,
        "countrySet": "US",
        "language":   "en-US",
    })
    try:
        req = urllib.request.Request(
            f"{url}?{params}",
            headers={"User-Agent": "WebByMaya-Outreach/1.0"},
        )
        resp = json.loads(urllib.request.urlopen(req, timeout=15).read())
        return resp.get("results", [])
    except urllib.error.HTTPError as e:
        if e.code == 401:
            sys.exit("ERROR: TOMTOM_API_KEY invalid. Check developer.tomtom.com")
        if e.code == 429:
            print("  [TomTom] Rate limit hit — sleeping 10s")
            time.sleep(10)
            return []
        print(f"  [WARN] TomTom {e.code} for '{query}'")
        return []
    except Exception as ex:
        print(f"  [WARN] TomTom error: {ex}")
        return []


def place_to_row(place: dict, category: str, zone: str):
    poi  = place.get("poi", {})
    addr = place.get("address", {})
    pos  = place.get("position", {})

    name = poi.get("name", "").strip()
    if not name:
        return None

    phone = ""
    phones = poi.get("phone", "") or poi.get("phones", "")
    if isinstance(phones, str):
        phone = phones.strip()
    elif isinstance(phones, list) and phones:
        phone = phones[0].strip()

    website = (poi.get("url") or "").strip()
    has_web = "No"
    ws      = "no_website"
    if website:
        domain = re.sub(r"https?://(www\.)?", "", website).split("/")[0].lower()
        if any(s in domain for s in SOCIAL_DOMAINS):
            has_web = "Yes - social"
            ws      = "social"
        else:
            return None  # has real website — not a prospect

    address = ", ".join(filter(None, [
        addr.get("streetNumber", "") + " " + addr.get("streetName", ""),
        addr.get("municipality", ""),
        addr.get("countrySubdivision", ""),
        addr.get("postalCode", ""),
    ])).strip().strip(",")

    city_name = addr.get("municipality", "") or zone
    place_id  = place.get("id", "")
    lat2, lon2 = pos.get("lat", ""), pos.get("lon", "")
    maps_url  = f"https://maps.tomtom.com/search/{urllib.parse.quote(name)}"

    return {
        "name":           name,
        "address":        address or city_name,
        "phone":          phone,
        "email":          "",
        "category":       category,
        "city":           city_name,
        "place_id":       f"tt_{place_id}",
        "maps_url":       maps_url,
        "website":        website,
        "website_status": ws,
        "has_website":    has_web,
        "rating":         "",
        "review_count":   "",
        "notes":          "source:tomtom",
        "sms_status":     "",
        "email_status":   "",
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--zone",   required=True)
    ap.add_argument("--output", default="")
    ap.add_argument("--delay",  type=float, default=0.3)
    args = ap.parse_args()

    coords = ZONE_COORDS.get(args.zone)
    if not coords:
        print(f"[TomTom] Unknown zone '{args.zone}' — skipping.")
        sys.exit(0)

    lat, lon, radius = coords
    today  = datetime.date.today().strftime("%Y-%m-%d")
    output = args.output or str(SCRIPT_DIR / f"prospects_tt_{today}_{args.zone}.csv")

    print(f"\n[TomTom] Zone: {args.zone}  ({lat},{lon} r={radius}m)")

    seen: dict[str, dict] = {}

    for query, category in SEARCH_QUERIES:
        results = tomtom_search(query, lat, lon, radius)
        added = 0
        for place in results:
            row = place_to_row(place, category, args.zone)
            if not row:
                continue
            key = row["name"].lower().strip()
            if key not in seen:
                seen[key] = row
                added += 1
        print(f"  {query}: {len(results)} results → {added} new leads")
        time.sleep(args.delay)

    rows = list(seen.values())
    print(f"[TomTom] Total unique no-website leads: {len(rows)}")

    if not rows:
        print("[TomTom] No prospects found.")
        sys.exit(0)

    with open(output, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    print(f"[TomTom] Saved → {output}")


if __name__ == "__main__":
    main()
