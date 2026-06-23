#!/usr/bin/env python3
"""
find_prospects_bing.py — WebByMaya Bing Maps Local Business Finder
==================================================================
Free tier: 125,000 transactions/month — just a Microsoft account needed.

GET YOUR FREE KEY (5 min):
  1. Go to bingmapsportal.com
  2. Sign in with any Microsoft / Outlook / Hotmail account (free)
  3. Click "My Keys" → "Create a new key"
  4. Application name: WebByMaya  |  Key type: Basic  |  Application type: Dev/Test
  5. Copy the key
  6. Add to ~/.zshrc:  export BING_MAPS_KEY="your_key_here"
  7. Then: source ~/.zshrc

USAGE
  python3 find_prospects_bing.py --zone philly-north
  python3 find_prospects_bing.py --zone sj-camden --output out.csv
"""

import argparse, csv, datetime, json, os, re, sys, time, urllib.request, urllib.parse
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
API_KEY    = os.environ.get("BING_MAPS_KEY", "")

SEARCH_BASE = "https://dev.virtualearth.net/REST/v1/LocalSearch/"

# Zone → "lat,lon" string for Bing userLocation
ZONE_COORDS = {
    "philly-center":         "39.9526,-75.1652",
    "philly-north":          "39.9918,-75.1577",
    "philly-northeast":      "40.0612,-75.0500",
    "philly-near-ne":        "40.0097,-75.0730",
    "philly-west":           "39.9601,-75.2301",
    "philly-south":          "39.9101,-75.1577",
    "philly-northwest":      "40.0293,-75.1924",
    "sj-camden":             "39.9259,-75.1196",
    "sj-cherry-hill":        "39.9346,-75.0246",
    "sj-mount-laurel":       "39.9515,-74.9093",
    "sj-gloucester":         "39.7023,-75.1115",
    "sj-voorhees":           "39.8617,-74.9532",
    "de-wilmington":         "39.7447,-75.5484",
    "de-newark":             "39.6837,-75.7497",
    "de-dover":              "39.1582,-75.5244",
    "pa-montco-south":       "40.1215,-75.3399",
    "pa-montco-east":        "40.1968,-75.1218",
    "pa-montco-north":       "40.2415,-75.2835",
    "pa-delco-inner":        "39.9612,-75.2657",
    "pa-delco-outer":        "39.9185,-75.4018",
    "pa-bucks-lower":        "40.1045,-74.8527",
    "pa-bucks-upper":        "40.3101,-75.1299",
    "pa-chester-west":       "39.9595,-75.6055",
    "pa-chester-east":       "39.9818,-75.8230",
    "pa-lancaster-city":     "40.0379,-76.3055",
    "pa-lancaster-north":    "40.1576,-76.3016",
    "pa-lancaster-east":     "40.1798,-76.1766",
    "pa-berks-reading":      "40.3357,-75.9268",
    "pa-berks-north":        "40.5157,-75.7807",
    "pa-lehigh-allentown":   "40.6023,-75.4714",
    "pa-lehigh-bethlehem":   "40.6259,-75.3705",
    "pa-northampton-easton": "40.6884,-75.2207",
    "pa-york-city":          "39.9626,-76.7277",
    "pa-york-east":          "39.9015,-76.5996",
    "pa-harrisburg":         "40.2732,-76.8867",
    "pa-dauphin-east":       "40.2857,-76.6496",
    "pa-lebanon":            "40.3418,-76.4113",
    "pa-schuylkill":         "40.6851,-76.1955",
    "md-baltimore-inner":    "39.2904,-76.6122",
    "md-baltimore-north":    "39.4015,-76.6021",
    "md-baltimore-east":     "39.3085,-76.4780",
    "md-baltimore-west":     "39.2796,-76.7319",
    "md-baltimore-south":    "39.2451,-76.5122",
    "md-annapolis":          "38.9784,-76.4922",
    "md-columbia":           "39.2037,-76.8610",
    "md-ellicott-city":      "39.2673,-76.7983",
    "md-bel-air":            "39.5354,-76.3485",
    "md-dundalk":            "39.2715,-76.5024",
    "md-rockville":          "39.0840,-77.1528",
    "md-silver-spring":      "38.9907,-77.0261",
    "sj-atlantic-city":      "39.3643,-74.4229",
    "sj-vineland":           "39.4860,-74.9218",
    "sj-millville":          "39.4032,-75.0371",
    "sj-bridgeton":          "39.4265,-75.2349",
    "sj-pleasantville":      "39.3890,-74.5218",
    "sj-somers-point":       "39.3179,-74.5996",
    "sj-hammonton":          "39.6401,-74.7999",
    "sj-medford":            "39.8701,-74.8249",
    "sj-marlton":            "39.8951,-74.9218",
    "sj-turnersville":       "39.7751,-75.0546",
    "sj-washington-twp":     "39.7901,-75.0849",
    "nj-trenton":            "40.2171,-74.7429",
    "nj-hamilton":           "40.2240,-74.6960",
    "nj-princeton":          "40.3573,-74.6672",
    "nj-new-brunswick":      "40.4874,-74.4454",
    "nj-edison":             "40.5187,-74.4121",
    "de-middletown":         "39.4490,-75.7163",
    "de-milford":            "38.9126,-75.4288",
    "de-seaford":            "38.6415,-75.6107",
    "de-rehoboth":           "38.7151,-75.0746",
    "pa-stroudsburg":        "40.9870,-75.1977",
    "pa-wilkes-barre":       "41.2459,-75.8813",
    "pa-scranton":           "41.4090,-75.6624",
}

SEARCH_QUERIES = [
    ("nail salon",       "nail salon"),
    ("hair salon",       "hair salon"),
    ("beauty salon",     "beauty salon"),
    ("barber shop",      "barbershop"),
    ("day spa",          "spa"),
    ("massage therapy",  "massage"),
    ("restaurant",       "restaurant"),
    ("bakery",           "bakery"),
    ("auto repair shop", "auto repair"),
    ("tattoo shop",      "tattoo parlor"),
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


def bing_search(query: str, user_location: str, max_results: int = 25) -> list[dict]:
    if not API_KEY:
        sys.exit("ERROR: BING_MAPS_KEY not set.\nGet free key at bingmapsportal.com\nThen: export BING_MAPS_KEY='your_key' in ~/.zshrc")
    params = urllib.parse.urlencode({
        "query":          query,
        "userLocation":   user_location,
        "maxResults":     max_results,
        "key":            API_KEY,
    })
    try:
        req = urllib.request.Request(
            f"{SEARCH_BASE}?{params}",
            headers={"User-Agent": "WebByMaya-Outreach/1.0"},
        )
        resp = json.loads(urllib.request.urlopen(req, timeout=15).read())
        resources = (
            resp.get("resourceSets", [{}])[0]
                .get("resources", [])
        )
        return resources
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            sys.exit("ERROR: BING_MAPS_KEY invalid. Check bingmapsportal.com")
        if e.code == 429:
            print("  [Bing] Rate limit — sleeping 5s")
            time.sleep(5)
            return []
        print(f"  [WARN] Bing {e.code} for '{query}'")
        return []
    except Exception as ex:
        print(f"  [WARN] Bing error: {ex}")
        return []


def resource_to_row(res: dict, category: str):
    name = res.get("name", "").strip()
    if not name:
        return None

    addr_obj = res.get("Address", {})
    address  = addr_obj.get("formattedAddress", "").strip()
    city_name = addr_obj.get("locality", "") or addr_obj.get("adminDistrict", "")

    phones = res.get("PhoneNumber", "") or ""
    phone  = phones.strip() if isinstance(phones, str) else ""

    website = (res.get("Website") or "").strip()
    has_web = "No"
    ws      = "no_website"
    if website:
        domain = re.sub(r"https?://(www\.)?", "", website).split("/")[0].lower()
        if any(s in domain for s in SOCIAL_DOMAINS):
            has_web = "Yes - social"
            ws      = "social"
        else:
            return None  # has real website — not a prospect

    point = res.get("point", {}).get("coordinates", [])
    lat   = point[0] if len(point) > 0 else ""
    lon   = point[1] if len(point) > 1 else ""
    maps_url = f"https://www.bing.com/maps?q={urllib.parse.quote(name + ' ' + address)}"

    return {
        "name":           name,
        "address":        address,
        "phone":          phone,
        "email":          "",
        "category":       category,
        "city":           city_name,
        "place_id":       f"bing_{res.get('id', '')}",
        "maps_url":       maps_url,
        "website":        website,
        "website_status": ws,
        "has_website":    has_web,
        "rating":         "",
        "review_count":   "",
        "notes":          "source:bing",
        "sms_status":     "",
        "email_status":   "",
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--zone",   required=True)
    ap.add_argument("--output", default="")
    ap.add_argument("--delay",  type=float, default=0.5)
    args = ap.parse_args()

    location = ZONE_COORDS.get(args.zone)
    if not location:
        print(f"[Bing] Unknown zone '{args.zone}' — skipping.")
        sys.exit(0)

    today  = datetime.date.today().strftime("%Y-%m-%d")
    output = args.output or str(SCRIPT_DIR / f"prospects_bing_{today}_{args.zone}.csv")

    print(f"\n[Bing] Zone: {args.zone}  ({location})")

    seen: dict[str, dict] = {}

    for query, category in SEARCH_QUERIES:
        results = bing_search(query, location)
        added = 0
        for res in results:
            row = resource_to_row(res, category)
            if not row:
                continue
            key = row["name"].lower().strip()
            if key not in seen:
                seen[key] = row
                added += 1
        print(f"  {query}: {len(results)} results → {added} new leads")
        time.sleep(args.delay)

    rows = list(seen.values())
    print(f"[Bing] Total unique no-website leads: {len(rows)}")

    if not rows:
        print("[Bing] No prospects found.")
        sys.exit(0)

    with open(output, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    print(f"[Bing] Saved → {output}")


if __name__ == "__main__":
    main()
