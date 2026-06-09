#!/usr/bin/env python3
"""
find_prospects_yelp.py — WebByMaya Prospect Finder (Yelp Edition)
FREE replacement for find_prospects.py — no Google billing ever needed.

GET YOUR FREE API KEY (no card required):
  1. Go to https://www.yelp.com/developers/v3/manage_app
  2. Create an app (takes 2 min)
  3. Copy the API Key
  4. Add to ~/.zshrc:  export YELP_API_KEY="your_key_here"

Free tier: 500 API calls/day — enough to find 200-400 new prospects daily.

USAGE:
  python3 find_prospects_yelp.py --city "Philadelphia, PA"
  python3 find_prospects_yelp.py --city "Camden, NJ"
  python3 find_prospects_yelp.py --zone sj-cherry-hill
"""
import argparse, csv, datetime, json, os, sys, time, urllib.request, urllib.parse
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
API_KEY    = os.environ.get("YELP_API_KEY","")

# Yelp category aliases → friendly names
CATEGORIES = [
    ("hair",              "hair salon"),
    ("nailedsalons",      "nail salon"),
    ("massage",           "massage"),
    ("beautysvc",         "beauty salon"),
    ("restaurants",       "restaurant"),
    ("cafes",             "cafe"),
    ("bakeries",          "bakery"),
    ("auto",              "auto repair"),
    ("autorepair",        "auto repair"),
    ("petservices",       "pet store"),
    ("florists",          "florist"),
    ("landscaping",       "landscaping"),
    ("homecleaning",      "cleaning service"),
    ("photographers",     "photographer"),
    ("tattoo",            "tattoo parlor"),
    ("gyms",              "gym"),
    ("trainers",          "personal trainer"),
]

ZONE_LOCATIONS = {
    "philly-center":    "Center City, Philadelphia, PA",
    "philly-north":     "North Philadelphia, PA",
    "philly-northeast": "Northeast Philadelphia, PA",
    "philly-near-ne":   "Frankford, Philadelphia, PA",
    "philly-west":      "West Philadelphia, PA",
    "philly-south":     "South Philadelphia, PA",
    "philly-northwest":  "Northwest Philadelphia, PA",
    "sj-camden":        "Camden, NJ",
    "sj-cherry-hill":   "Cherry Hill, NJ",
    "sj-mount-laurel":  "Mount Laurel, NJ",
    "de-wilmington":    "Wilmington, DE",
    "de-newark":        "Newark, DE",
    "de-dover":         "Dover, DE",
}

SOCIAL_DOMAINS = {"facebook.com","instagram.com","twitter.com","yelp.com",
                  "google.com","linktr.ee","tiktok.com","youtube.com"}

CSV_COLUMNS = ["name","address","phone","email","category","city",
               "place_id","maps_url","website","website_status",
               "has_website","rating","review_count","notes","sms_status"]


def yelp_get(path, params=None):
    if not API_KEY:
        sys.exit("ERROR: YELP_API_KEY not set.\nGet a free key at https://www.yelp.com/developers/v3/manage_app\nThen: export YELP_API_KEY='your_key'")
    url = f"https://api.yelp.com/v3{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {API_KEY}"})
    try:
        resp = urllib.request.urlopen(req, timeout=10)
        return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        if e.code == 429:
            print("  [rate limit] sleeping 60s...")
            time.sleep(60)
            return yelp_get(path, params)
        err = json.loads(e.read().decode())
        print(f"  [yelp error] {err.get('error',{}).get('description','unknown')}")
        return {}
    except Exception as e:
        print(f"  [error] {e}")
        return {}


def get_business_website(biz_id):
    """Call business details to get actual website URL."""
    time.sleep(0.25)  # be polite
    data = yelp_get(f"/businesses/{biz_id}")
    return data.get("url",""), data.get("website","") or ""


def classify_website(url):
    if not url:
        return "No", "no_website"
    domain = url.lower().split("/")[2] if "//" in url else url.lower()
    domain = domain.replace("www.","").split("/")[0]
    for social in SOCIAL_DOMAINS:
        if social in domain:
            return "Yes - social only", "social_only"
    return "Yes", "has_website"


def load_seen_place_ids():
    seen = set()
    for p in SCRIPT_DIR.glob("prospects_*.csv"):
        try:
            with open(p, newline="") as f:
                for row in csv.DictReader(f):
                    pid = row.get("place_id","").strip()
                    if pid:
                        seen.add(pid)
        except: pass
    return seen


def search_category(location, yelp_cat, friendly_cat, seen_ids, limit=200):
    """Search Yelp for one category in one location. Returns prospect list."""
    prospects = []
    offset = 0
    batch  = 50

    while offset < limit:
        data = yelp_get("/businesses/search", {
            "categories": yelp_cat,
            "location":   location,
            "limit":      min(batch, limit - offset),
            "offset":     offset,
        })
        businesses = data.get("businesses", [])
        if not businesses:
            break

        for biz in businesses:
            biz_id = biz.get("id","")
            if biz_id in seen_ids:
                continue

            name    = biz.get("name","").strip()
            phone   = biz.get("phone","").strip()
            addr    = biz.get("location",{})
            address = ", ".join(filter(None, [
                addr.get("address1",""),
                addr.get("city",""),
                addr.get("state",""),
                addr.get("zip_code",""),
            ]))
            city_str    = f"{addr.get('city','')}, {addr.get('state','')}"
            rating      = biz.get("rating","")
            review_cnt  = biz.get("review_count","")
            yelp_url    = biz.get("url","")
            maps_url    = f"https://www.yelp.com/biz/{biz_id}"

            # Get actual website (costs 1 API call)
            _, website = get_business_website(biz_id)
            has_web, web_status = classify_website(website)

            # Only add if no real website
            if has_web == "Yes":
                seen_ids.add(biz_id)
                continue

            prospects.append({
                "name":          name,
                "address":       address,
                "phone":         phone,
                "email":         "",
                "category":      friendly_cat,
                "city":          city_str,
                "place_id":      biz_id,
                "maps_url":      maps_url,
                "website":       website,
                "website_status":web_status,
                "has_website":   has_web,
                "rating":        rating,
                "review_count":  review_cnt,
                "notes":         "",
                "sms_status":    "",
            })
            seen_ids.add(biz_id)
            print(f"  ✓ {name} ({friendly_cat}) — no website")

        offset += len(businesses)
        if len(businesses) < batch:
            break
        time.sleep(0.5)

    return prospects


def main():
    parser = argparse.ArgumentParser(description="WebByMaya Yelp Prospect Finder")
    parser.add_argument("--city", help='City to search, e.g. "Philadelphia, PA"')
    parser.add_argument("--zone", help="Named zone from zone_state.json")
    parser.add_argument("--limit", type=int, default=200, help="Max businesses to check per category")
    args = parser.parse_args()

    # Resolve location
    if args.zone:
        location = ZONE_LOCATIONS.get(args.zone.lower())
        if not location:
            sys.exit(f"Unknown zone '{args.zone}'. Options: {', '.join(ZONE_LOCATIONS)}")
    elif args.city:
        location = args.city
    else:
        parser.print_help(); sys.exit(1)

    today     = datetime.date.today().strftime("%Y-%m-%d")
    out_path  = SCRIPT_DIR / f"prospects_{today}.csv"
    seen_ids  = load_seen_place_ids()

    print(f"\n{'='*55}")
    print(f"  WebByMaya Yelp Prospect Finder")
    print(f"  Location : {location}")
    print(f"  Date     : {today}")
    print(f"  Output   : {out_path.name}")
    print(f"{'='*55}\n")

    all_prospects = []
    for yelp_cat, friendly_cat in CATEGORIES:
        print(f"\n[{friendly_cat}] searching...")
        found = search_category(location, yelp_cat, friendly_cat, seen_ids, args.limit)
        print(f"  → {len(found)} new prospects without websites")
        all_prospects.extend(found)

    if not all_prospects:
        print("\nNo new prospects found. Try a different location.")
        return

    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(all_prospects)

    print(f"\n{'='*55}")
    print(f"  Done. {len(all_prospects)} prospects → {out_path.name}")
    print(f"  Run: python3 enrich_emails.py --input {out_path.name}")
    print(f"{'='*55}\n")


if __name__ == "__main__":
    main()
