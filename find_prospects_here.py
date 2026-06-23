#!/usr/bin/env python3
"""
find_prospects_here.py — WebByMaya HERE Places Prospect Finder
==============================================================
Free tier: 250,000 API calls/month — the most generous free Places API available.
Replaces Foursquare (which killed its free tier in 2024).

GET YOUR FREE KEY (2 min):
  1. Go to developer.here.com → Sign up free (no credit card)
  2. Create a project → copy the API Key
  3. Add to ~/.zshrc:  export HERE_API_KEY="your-key-here"
  4. Run: source ~/.zshrc

USAGE
  python3 find_prospects_here.py --zone philly-center
  python3 find_prospects_here.py --zone sj-camden --output custom_output.csv
"""

import argparse, csv, datetime, json, os, re, sys, time, urllib.parse, urllib.request
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
API_KEY    = os.environ.get("HERE_API_KEY", "")

HERE_DISCOVER = "https://discover.search.hereapi.com/v1/discover"

ZONE_COORDS = {
    "philly-center":    (39.9526, -75.1652),
    "philly-north":     (39.9984, -75.1502),
    "philly-northeast": (40.0634, -75.0380),
    "philly-near-ne":   (40.0150, -75.0700),
    "philly-west":      (39.9630, -75.2290),
    "philly-south":     (39.9100, -75.1700),
    "philly-northwest": (40.0350, -75.1990),
    "sj-camden":        (39.9259, -75.1196),
    "sj-cherry-hill":   (39.9348, -74.9913),
    "sj-mount-laurel":  (39.9512, -74.9091),
    "sj-gloucester":    (39.7026, -75.1121),
    "sj-voorhees":      (39.8562, -74.9574),
    "de-wilmington":    (39.7447, -75.5484),
    "de-newark":        (39.6837, -75.7497),
    "de-dover":         (39.1582, -75.5244),
    "pa-montco-south":  (40.1215, -75.3399),
    "pa-montco-east":   (40.1773, -75.1224),
    "pa-montco-north":  (40.2415, -75.2835),
    "pa-delco-inner":   (39.9526, -75.2688),
    "pa-delco-outer":   (39.9201, -75.4024),
    "pa-bucks-lower":   (40.1065, -74.8631),
    "pa-bucks-upper":   (40.3101, -75.1299),
    "pa-chester-west":  (39.9607, -75.6055),
    "pa-chester-east":  (40.0026, -75.8196),
}

SEARCH_QUERIES = [
    "hair salon", "nail salon", "beauty salon", "spa", "massage",
    "restaurant", "cafe", "bakery",
    "auto repair", "mechanic",
    "gym", "personal trainer",
    "landscaping", "lawn care",
    "cleaning service",
    "photographer",
    "tattoo",
    "florist",
    "pet grooming",
    "barber",
]

CSV_COLUMNS = [
    "name", "address", "phone", "email", "category", "city",
    "place_id", "maps_url", "website", "website_status",
    "has_website", "rating", "review_count", "notes",
    "sms_status", "email_status",
]


def _search(lat: float, lon: float, query: str, radius: int = 5000) -> list[dict]:
    if not API_KEY:
        return []
    params = urllib.parse.urlencode({
        "at":    f"{lat},{lon}",
        "q":     query,
        "limit": 100,
        "apiKey": API_KEY,
    })
    req = urllib.request.Request(
        f"{HERE_DISCOVER}?{params}",
        headers={"Accept": "application/json"})
    try:
        data = json.loads(urllib.request.urlopen(req, timeout=10).read())
        return data.get("items", [])
    except Exception as e:
        print(f"  [HERE] {query}: {e}")
        return []


def _has_working_website(contacts: list) -> bool:
    for c in contacts:
        for entry in c.get("www", []):
            url = entry.get("value", "").strip()
            if url and not _is_placeholder(url):
                return True
    return False


def _is_placeholder(url: str) -> bool:
    placeholder_domains = {
        "facebook.com", "instagram.com", "yelp.com", "google.com",
        "squareup.com", "toasttab.com", "grubhub.com", "doordash.com",
    }
    try:
        from urllib.parse import urlparse
        domain = urlparse(url).netloc.lower().lstrip("www.")
        return any(domain == d or domain.endswith("." + d) for d in placeholder_domains)
    except Exception:
        return False


def _extract_phone(contacts: list) -> str:
    for c in contacts:
        for ph in c.get("phone", []):
            v = ph.get("value", "").strip()
            if v: return v
    return ""


def _format_address(address: dict) -> str:
    parts = []
    if address.get("houseNumber"): parts.append(address["houseNumber"])
    if address.get("street"):      parts.append(address["street"])
    if address.get("city"):        parts.append(address["city"])
    if address.get("stateCode"):   parts.append(address["stateCode"])
    return ", ".join(parts)


def find_prospects(zone: str, output_path: Path) -> int:
    if not API_KEY:
        print("ERROR: HERE_API_KEY not set.")
        print("  1. Sign up free at developer.here.com")
        print("  2. Create a project → copy API Key")
        print('  3. Add to ~/.zshrc:  export HERE_API_KEY="your-key"')
        print("  4. Run: source ~/.zshrc")
        return 1

    if zone not in ZONE_COORDS:
        print(f"ERROR: Unknown zone '{zone}'. Available zones:")
        for z in sorted(ZONE_COORDS): print(f"  {z}")
        return 1

    lat, lon = ZONE_COORDS[zone]
    today    = datetime.date.today().strftime("%Y-%m-%d")

    print(f"\n{'='*58}")
    print(f"  HERE Places · Zone: {zone}")
    print(f"  Coords: {lat}, {lon}")
    print(f"  Searching {len(SEARCH_QUERIES)} categories …")
    print(f"{'='*58}\n")

    seen   : set[str]  = set()
    rows   : list[dict] = []

    for query in SEARCH_QUERIES:
        items = _search(lat, lon, query)
        time.sleep(0.3)

        no_site = 0
        for item in items:
            pid      = item.get("id", "")
            name     = item.get("title", "").strip()
            if not name or pid in seen:
                continue
            seen.add(pid)

            contacts = item.get("contacts", [])
            has_site = _has_working_website(contacts)
            if has_site:
                continue

            address_obj = item.get("address", {})
            address     = _format_address(address_obj)
            city        = address_obj.get("city", "")
            phone       = _extract_phone(contacts)
            pos         = item.get("position", {})
            maps_url    = f"https://maps.google.com/?q={pos.get('lat',0)},{pos.get('lng',0)}"
            rating      = item.get("rating", {}).get("value", "")
            reviews     = item.get("rating", {}).get("count", "")
            category_   = query

            rows.append({
                "name":         name,
                "address":      address,
                "phone":        phone,
                "email":        "",
                "category":     category_,
                "city":         city or zone,
                "place_id":     pid,
                "maps_url":     maps_url,
                "website":      "",
                "website_status": "none",
                "has_website":  "No",
                "rating":       rating,
                "review_count": reviews,
                "notes":        f"HERE:{today}",
                "sms_status":   "",
                "email_status": "",
            })
            no_site += 1

        if no_site:
            print(f"  {query:25s} → {no_site} without a website")

    if not rows:
        print("\nNo prospects found without websites in this zone.")
        return 0

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    print(f"\nFound {len(rows)} prospects without websites.")
    print(f"Saved to: {output_path}")
    return 0


def main():
    parser = argparse.ArgumentParser(description="WebByMaya — HERE Places prospect finder")
    parser.add_argument("--zone",   required=True, metavar="ZONE")
    parser.add_argument("--output", default="", metavar="CSV")
    args = parser.parse_args()

    today = datetime.date.today().strftime("%Y-%m-%d")
    out   = Path(args.output) if args.output else SCRIPT_DIR / f"prospects_here_{today}.csv"
    sys.exit(find_prospects(args.zone, out))


if __name__ == "__main__":
    main()
