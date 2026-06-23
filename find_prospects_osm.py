#!/usr/bin/env python3
"""
find_prospects_osm.py — WebByMaya OpenStreetMap Prospect Finder
===============================================================
FREE — no API key, no rate limits, no billing ever.
Supplements Yelp with businesses from OpenStreetMap that Yelp doesn't list.

HOW IT WORKS
  1. Nominatim (free) geocodes the city → bounding box
  2. Overpass API queries all OSM businesses in that box
  3. Businesses with no OSM website tag → leads (likely no web presence)
  4. Businesses WITH a website tag → website health-checked like find_prospects.py

USAGE
  python3 find_prospects_osm.py --zone philly-north
  python3 find_prospects_osm.py --zone sj-camden --output my_output.csv
"""

import argparse, csv, datetime, json, re, sys, time, urllib.request, urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
OVERPASS_URL  = "https://overpass-api.de/api/interpreter"
HEADERS       = {"User-Agent": "WebByMaya-Outreach/1.0 (mayas.worldwide.web@gmail.com)"}

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
}

# OSM tag → friendly category name
TAG_MAP = {
    ("amenity", "restaurant"):      "restaurant",
    ("amenity", "cafe"):            "cafe",
    ("amenity", "fast_food"):       "restaurant",
    ("amenity", "bar"):             "restaurant",
    ("amenity", "beauty_salon"):    "beauty salon",
    ("amenity", "hairdresser"):     "hair salon",
    ("amenity", "nail_salon"):      "nail salon",
    ("amenity", "massage"):         "massage",
    ("amenity", "spa"):             "spa",
    ("amenity", "car_repair"):      "auto repair",
    ("amenity", "gym"):             "gym",
    ("amenity", "tattoo_parlour"):  "tattoo parlor",
    ("amenity", "photography_studio"): "photographer",
    ("shop",    "beauty"):          "beauty salon",
    ("shop",    "hairdresser"):     "hair salon",
    ("shop",    "nail_salon"):      "nail salon",
    ("shop",    "bakery"):          "bakery",
    ("shop",    "florist"):         "florist",
    ("shop",    "tattoo"):          "tattoo parlor",
    ("shop",    "massage"):         "massage",
    ("shop",    "car_repair"):      "auto repair",
    ("shop",    "pet"):             "pet store",
    ("shop",    "garden_centre"):   "landscaping",
    ("shop",    "cleaning"):        "cleaning service",
    ("leisure", "fitness_centre"):  "gym",
}

SOCIAL_DOMAINS = {"facebook.com","instagram.com","twitter.com","yelp.com",
                  "google.com","linktr.ee","tiktok.com","youtube.com"}

CSV_COLUMNS = ["name","address","phone","email","category","city",
               "place_id","maps_url","website","website_status",
               "has_website","rating","review_count","notes","sms_status","email_status"]


def nominatim_bbox(city: str) -> tuple[float, float, float, float]:
    """Return (south, west, north, east) bounding box for city."""
    params = urllib.parse.urlencode({"q": city, "format": "json", "limit": "1"})
    req = urllib.request.Request(f"{NOMINATIM_URL}?{params}", headers=HEADERS)
    try:
        data = json.loads(urllib.request.urlopen(req, timeout=10).read())
        if not data:
            raise ValueError(f"Nominatim found nothing for '{city}'")
        bb = data[0]["boundingbox"]
        return float(bb[0]), float(bb[2]), float(bb[1]), float(bb[3])
    except Exception as e:
        sys.exit(f"ERROR: Nominatim geocode failed for '{city}': {e}")


def overpass_query(s: float, w: float, n: float, e: float) -> list[dict]:
    """Run Overpass query and return list of OSM node elements."""
    amenities = "restaurant|cafe|fast_food|bar|beauty_salon|hairdresser|nail_salon|massage|spa|car_repair|gym|tattoo_parlour|photography_studio"
    shops     = "beauty|hairdresser|nail_salon|bakery|florist|tattoo|massage|car_repair|pet|garden_centre|cleaning"
    bbox = f"{s},{w},{n},{e}"
    ql = f"""
[out:json][timeout:90];
(
  node["amenity"~"{amenities}"]({bbox});
  node["shop"~"{shops}"]({bbox});
  node["leisure"="fitness_centre"]({bbox});
  way["amenity"~"{amenities}"]({bbox});
  way["shop"~"{shops}"]({bbox});
);
out center body;
"""
    req = urllib.request.Request(
        OVERPASS_URL,
        data=urllib.parse.urlencode({"data": ql}).encode(),
        headers=HEADERS,
    )
    try:
        resp = json.loads(urllib.request.urlopen(req, timeout=120).read())
        return resp.get("elements", [])
    except Exception as e:
        print(f"  [WARN] Overpass query failed: {e}")
        return []


def get_category(tags: dict) -> str:
    for (key, val), cat in TAG_MAP.items():
        if tags.get(key, "").lower() == val:
            return cat
    return ""


def check_website(url: str) -> str:
    """Returns 'alive', 'dead', 'social', or 'parked'."""
    if not url:
        return ""
    domain = re.sub(r"https?://(www\.)?", "", url).split("/")[0].lower()
    if any(s in domain for s in SOCIAL_DOMAINS):
        return "social"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}, method="HEAD")
        r = urllib.request.urlopen(req, timeout=8)
        return "alive" if r.status < 400 else "dead"
    except Exception:
        return "dead"


def to_row(el: dict, city: str):
    tags = el.get("tags", {})
    name = tags.get("name", "").strip()
    if not name:
        return None

    cat = get_category(tags)
    if not cat:
        return None

    phone = tags.get("phone", tags.get("contact:phone", "")).strip()
    website = tags.get("website", tags.get("contact:website", "")).strip()
    lat = el.get("lat") or el.get("center", {}).get("lat")
    lon = el.get("lon") or el.get("center", {}).get("lon")

    osm_id = f"osm_{el.get('type','n')[0]}{el.get('id','')}"
    maps_url = f"https://www.openstreetmap.org/node/{el.get('id','')}" if lat else ""

    # Determine website status
    if website:
        ws = check_website(website)
        if ws == "alive":
            has_website = "Yes"
            ws_status   = ""
        elif ws == "social":
            has_website = "Yes - social"
            ws_status   = "social"
        else:
            has_website = "Yes - dead"
            ws_status   = "dead"
    else:
        has_website = "No"
        ws_status   = "no_website"

    addr_parts = [tags.get(k, "") for k in ("addr:housenumber","addr:street","addr:city","addr:state","addr:postcode")]
    address = " ".join(p for p in addr_parts if p).strip() or tags.get("addr:full", "")

    return {
        "name":         name,
        "address":      address or city,
        "phone":        phone,
        "email":        "",
        "category":     cat,
        "city":         city,
        "place_id":     osm_id,
        "maps_url":     maps_url,
        "website":      website,
        "website_status": ws_status,
        "has_website":  has_website,
        "rating":       "",
        "review_count": "",
        "notes":        "source:osm",
        "sms_status":   "",
        "email_status": "",
    }


def main():
    ap = argparse.ArgumentParser(description="WebByMaya — OSM prospect finder (free)")
    ap.add_argument("--zone",   required=True, help="Zone key (e.g. philly-north)")
    ap.add_argument("--output", default="", help="Output CSV path (default: prospects_YYYY-MM-DD.csv)")
    ap.add_argument("--workers", type=int, default=20, help="Parallel website check threads")
    args = ap.parse_args()

    city = ZONE_LOCATIONS.get(args.zone)
    if not city:
        sys.exit(f"ERROR: Unknown zone '{args.zone}'.\nAvailable: {', '.join(ZONE_LOCATIONS)}")

    today  = datetime.date.today().strftime("%Y-%m-%d")
    output = args.output or str(SCRIPT_DIR / f"prospects_osm_{today}.csv")

    print(f"\n{'='*60}")
    print(f"  WebByMaya OSM Prospect Finder")
    print(f"  Zone : {args.zone}  →  {city}")
    print(f"  Date : {today}")
    print(f"{'='*60}\n")

    print("Geocoding city via Nominatim...")
    time.sleep(1)  # Nominatim rate limit: 1 req/sec
    s, w, n, e = nominatim_bbox(city)
    print(f"  Bounding box: {s:.4f},{w:.4f} → {n:.4f},{e:.4f}")

    print("Querying Overpass API...")
    elements = overpass_query(s, w, n, e)
    print(f"  Raw OSM elements: {len(elements)}")

    # Parse elements (skip alive websites — only want no-web or dead-web businesses)
    leads = []
    skip_alive = 0
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(to_row, el, city): el for el in elements}
        for fut in as_completed(futures):
            row = fut.result()
            if row is None:
                continue
            if row["has_website"] == "Yes":
                skip_alive += 1
                continue
            leads.append(row)

    # Dedup by name+phone
    seen = set()
    unique = []
    for r in leads:
        key = (r["name"].lower(), r["phone"])
        if key not in seen:
            seen.add(key)
            unique.append(r)

    print(f"  Leads (no/bad website): {len(unique)}  |  Skipped (has live site): {skip_alive}")

    if not unique:
        print("No new prospects found from OSM.")
        return

    with open(output, "w", newline="", encoding="utf-8") as f:
        w_csv = csv.DictWriter(f, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        w_csv.writeheader()
        w_csv.writerows(unique)

    print(f"  Saved → {output}")


if __name__ == "__main__":
    main()
