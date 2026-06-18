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
# Daily API budget (stay under 300 to stay free forever)
DAILY_CALL_BUDGET  = 280   # 20 buffer below the 300 limit
SEARCH_CALLS_MAX   = 20    # 20 search calls × 50 results = 1,000 businesses scanned
DETAIL_CALLS_MAX   = 260   # 260 detail calls to check websites

CATEGORIES = [
    # Beauty & wellness
    ("hair",              "hair salon"),
    ("nailedsalons",      "nail salon"),
    ("massage",           "massage"),
    ("beautysvc",         "beauty salon"),
    ("skincare",          "skincare"),
    ("eyelashservice",    "lash studio"),
    ("browservices",      "brow studio"),
    ("barbers",           "barbershop"),
    ("spas",              "spa"),
    ("tanning",           "tanning salon"),
    ("waxing",            "waxing"),
    ("makeupartists",     "makeup artist"),
    # Food & drink
    ("restaurants",       "restaurant"),
    ("cafes",             "cafe"),
    ("bakeries",          "bakery"),
    ("pizza",             "pizza"),
    ("sandwiches",        "deli"),
    ("chicken_wings",     "wings"),
    ("icecream",          "ice cream"),
    ("foodtrucks",        "food truck"),
    ("catering",          "catering"),
    ("desserts",          "dessert"),
    ("juicebars",         "juice bar"),
    # Automotive
    ("auto",              "auto repair"),
    ("autorepair",        "auto repair"),
    ("tires",             "tire shop"),
    ("oilchange",         "oil change"),
    ("carwash",           "car wash"),
    ("autoglass",         "auto glass"),
    # Home services
    ("landscaping",       "landscaping"),
    ("homecleaning",      "cleaning service"),
    ("plumbing",          "plumber"),
    ("electricians",      "electrician"),
    ("painters",          "painter"),
    ("handyman",          "handyman"),
    ("movers",            "moving company"),
    ("interiordesign",    "interior design"),
    # Health & fitness
    ("gyms",              "gym"),
    ("trainers",          "personal trainer"),
    ("yoga",              "yoga studio"),
    ("pilates",           "pilates"),
    ("martialarts",       "martial arts"),
    ("cycling",           "cycling studio"),
    ("nutritionists",     "nutritionist"),
    # Pets
    ("petservices",       "pet store"),
    ("grooming",          "pet grooming"),
    ("dogwalkers",        "dog walker"),
    ("veterinarians",     "vet"),
    # Retail & services
    ("florists",          "florist"),
    ("photographers",     "photographer"),
    ("tattoo",            "tattoo parlor"),
    ("jewelryrepair",     "jeweler"),
    ("drycleaninglaundry","dry cleaner"),
    ("alterations",       "tailor"),
    ("videographers",     "videographer"),
    ("eventplanning",     "event planner"),
    ("childcare",         "daycare"),
    ("tutoring",          "tutor"),
    ("realestateagents",  "real estate"),
    ("insurance",         "insurance"),
    ("accountants",       "accountant"),
    ("lawyers",           "law office"),
    ("dentists",          "dentist"),
    ("chiropractors",     "chiropractor"),
    ("acupuncture",       "acupuncture"),
]

ZONE_LOCATIONS = {
    # Philadelphia
    "philly-center":         "Center City, Philadelphia, PA",
    "philly-north":          "North Philadelphia, PA",
    "philly-northeast":      "Northeast Philadelphia, PA",
    "philly-near-ne":        "Frankford, Philadelphia, PA",
    "philly-west":           "West Philadelphia, PA",
    "philly-south":          "South Philadelphia, PA",
    "philly-northwest":      "Northwest Philadelphia, PA",
    # South Jersey
    "sj-camden":             "Camden, NJ",
    "sj-cherry-hill":        "Cherry Hill, NJ",
    "sj-mount-laurel":       "Mount Laurel, NJ",
    "sj-gloucester":         "Glassboro, NJ",
    "sj-voorhees":           "Voorhees, NJ",
    # Delaware
    "de-wilmington":         "Wilmington, DE",
    "de-newark":             "Newark, DE",
    "de-dover":              "Dover, DE",
    # Montgomery County, PA
    "pa-montco-south":       "Norristown, PA",
    "pa-montco-east":        "Horsham, PA",
    "pa-montco-north":       "Lansdale, PA",
    # Delaware County, PA
    "pa-delco-inner":        "Upper Darby, PA",
    "pa-delco-outer":        "Media, PA",
    # Bucks County, PA
    "pa-bucks-lower":        "Bristol, PA",
    "pa-bucks-upper":        "Doylestown, PA",
    # Chester County, PA
    "pa-chester-west":       "West Chester, PA",
    "pa-chester-east":       "Coatesville, PA",
    # Lancaster County, PA
    "pa-lancaster-city":     "Lancaster, PA",
    "pa-lancaster-north":    "Lititz, PA",
    "pa-lancaster-east":     "Ephrata, PA",
    # Berks County, PA
    "pa-berks-reading":      "Reading, PA",
    "pa-berks-north":        "Kutztown, PA",
    # Lehigh Valley
    "pa-lehigh-allentown":   "Allentown, PA",
    "pa-lehigh-bethlehem":   "Bethlehem, PA",
    "pa-northampton-easton": "Easton, PA",
    # York County, PA
    "pa-york-city":          "York, PA",
    "pa-york-east":          "Red Lion, PA",
    # Dauphin / Harrisburg
    "pa-harrisburg":         "Harrisburg, PA",
    "pa-dauphin-east":       "Hershey, PA",
    # Lebanon County, PA
    "pa-lebanon":            "Lebanon, PA",
    # Schuylkill County, PA
    "pa-schuylkill":         "Pottsville, PA",
    # Maryland — Baltimore metro
    "md-baltimore-inner":    "Baltimore, MD",
    "md-baltimore-north":    "Towson, MD",
    "md-baltimore-east":     "Essex, MD",
    "md-baltimore-west":     "Catonsville, MD",
    "md-baltimore-south":    "Glen Burnie, MD",
    "md-annapolis":          "Annapolis, MD",
    "md-columbia":           "Columbia, MD",
    "md-ellicott-city":      "Ellicott City, MD",
    "md-bel-air":            "Bel Air, MD",
    "md-dundalk":            "Dundalk, MD",
    "md-rockville":          "Rockville, MD",
    "md-silver-spring":      "Silver Spring, MD",
    # South Jersey — expanded
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
    # Central & North Jersey
    "nj-trenton":            "Trenton, NJ",
    "nj-hamilton":           "Hamilton, NJ",
    "nj-princeton":          "Princeton, NJ",
    "nj-new-brunswick":      "New Brunswick, NJ",
    "nj-edison":             "Edison, NJ",
    # Delaware — expanded
    "de-middletown":         "Middletown, DE",
    "de-milford":            "Milford, DE",
    "de-seaford":            "Seaford, DE",
    "de-rehoboth":           "Rehoboth Beach, DE",
    # More PA
    "pa-stroudsburg":        "Stroudsburg, PA",
    "pa-wilkes-barre":       "Wilkes-Barre, PA",
    "pa-scranton":           "Scranton, PA",
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


_detail_calls_used = 0

def search_category(location, yelp_cat, friendly_cat, seen_ids, limit=50):
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

            # Get actual website (costs 1 API call) — stop if budget hit
            global _detail_calls_used
            if _detail_calls_used >= DETAIL_CALLS_MAX:
                print(f"  [budget] Detail call limit ({DETAIL_CALLS_MAX}) reached for today.")
                return prospects
            _, website = get_business_website(biz_id)
            _detail_calls_used += 1
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
        if _detail_calls_used >= DETAIL_CALLS_MAX:
            print(f"\n[budget] Daily detail limit reached — stopping search.")
            break
        print(f"\n[{friendly_cat}] searching...")
        found = search_category(location, yelp_cat, friendly_cat, seen_ids)
        print(f"  → {len(found)} new prospects without websites")
        all_prospects.extend(found)
    print(f"\nAPI calls used today: ~{20 + _detail_calls_used} of 300")

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
