#!/usr/bin/env python3
"""
find_prospects_manta.py — WebByMaya Manta.com Directory Scraper
===============================================================
Scrapes manta.com for local businesses without websites.
FREE — no API key needed. Different dataset from Yelp/BBB.

USAGE
  python3 find_prospects_manta.py --zone philly-north
  python3 find_prospects_manta.py --zone sj-camden --output out.csv
"""

import argparse, csv, datetime, json, re, sys, time, urllib.request, urllib.parse
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent

ZONE_LOCATIONS = {
    "philly-north":          ("Philadelphia", "PA"),
    "philly-northeast":      ("Philadelphia", "PA"),
    "philly-near-ne":        ("Philadelphia", "PA"),
    "philly-west":           ("Philadelphia", "PA"),
    "philly-south":          ("Philadelphia", "PA"),
    "philly-northwest":      ("Philadelphia", "PA"),
    "philly-center":         ("Philadelphia", "PA"),
    "sj-camden":             ("Camden", "NJ"),
    "sj-cherry-hill":        ("Cherry Hill", "NJ"),
    "sj-mount-laurel":       ("Mount Laurel", "NJ"),
    "de-wilmington":         ("Wilmington", "DE"),
    "de-newark":             ("Newark", "DE"),
    "de-dover":              ("Dover", "DE"),
    "pa-montco-south":       ("Norristown", "PA"),
    "pa-montco-east":        ("Horsham", "PA"),
    "pa-montco-north":       ("Lansdale", "PA"),
    "pa-delco-inner":        ("Upper Darby", "PA"),
    "pa-delco-outer":        ("Media", "PA"),
    "pa-bucks-lower":        ("Bristol", "PA"),
    "pa-bucks-upper":        ("Doylestown", "PA"),
    "pa-chester-west":       ("West Chester", "PA"),
    "pa-chester-east":       ("Coatesville", "PA"),
    "sj-gloucester":         ("Glassboro", "NJ"),
    "sj-voorhees":           ("Voorhees", "NJ"),
    "pa-lancaster-city":     ("Lancaster", "PA"),
    "pa-lancaster-north":    ("Lititz", "PA"),
    "pa-lancaster-east":     ("Ephrata", "PA"),
    "pa-berks-reading":      ("Reading", "PA"),
    "pa-berks-north":        ("Kutztown", "PA"),
    "pa-lehigh-allentown":   ("Allentown", "PA"),
    "pa-lehigh-bethlehem":   ("Bethlehem", "PA"),
    "pa-northampton-easton": ("Easton", "PA"),
    "pa-york-city":          ("York", "PA"),
    "pa-york-east":          ("Red Lion", "PA"),
    "pa-harrisburg":         ("Harrisburg", "PA"),
    "pa-dauphin-east":       ("Hershey", "PA"),
    "pa-lebanon":            ("Lebanon", "PA"),
    "pa-schuylkill":         ("Pottsville", "PA"),
    "md-baltimore-inner":    ("Baltimore", "MD"),
    "md-baltimore-north":    ("Towson", "MD"),
    "md-baltimore-east":     ("Essex", "MD"),
    "md-baltimore-west":     ("Catonsville", "MD"),
    "md-baltimore-south":    ("Dundalk", "MD"),
    "md-annapolis":          ("Annapolis", "MD"),
    "md-columbia":           ("Columbia", "MD"),
    "md-ellicott-city":      ("Ellicott City", "MD"),
    "md-bel-air":            ("Bel Air", "MD"),
    "md-dundalk":            ("Dundalk", "MD"),
    "md-rockville":          ("Rockville", "MD"),
    "md-silver-spring":      ("Silver Spring", "MD"),
    "sj-atlantic-city":      ("Atlantic City", "NJ"),
    "sj-vineland":           ("Vineland", "NJ"),
    "sj-millville":          ("Millville", "NJ"),
    "sj-bridgeton":          ("Bridgeton", "NJ"),
    "sj-pleasantville":      ("Pleasantville", "NJ"),
    "sj-somers-point":       ("Somers Point", "NJ"),
    "sj-hammonton":          ("Hammonton", "NJ"),
    "sj-medford":            ("Medford", "NJ"),
    "sj-marlton":            ("Marlton", "NJ"),
    "sj-turnersville":       ("Turnersville", "NJ"),
    "sj-washington-twp":     ("Washington Township", "NJ"),
    "nj-trenton":            ("Trenton", "NJ"),
    "nj-hamilton":           ("Hamilton", "NJ"),
    "nj-princeton":          ("Princeton", "NJ"),
    "nj-new-brunswick":      ("New Brunswick", "NJ"),
    "nj-edison":             ("Edison", "NJ"),
    "de-middletown":         ("Middletown", "DE"),
    "de-milford":            ("Milford", "DE"),
    "de-seaford":            ("Seaford", "DE"),
    "de-rehoboth":           ("Rehoboth Beach", "DE"),
    "pa-stroudsburg":        ("Stroudsburg", "PA"),
    "pa-wilkes-barre":       ("Wilkes-Barre", "PA"),
    "pa-scranton":           ("Scranton", "PA"),
}

SEARCH_TERMS = [
    ("hair+salon",       "hair salon"),
    ("nail+salon",       "nail salon"),
    ("beauty+salon",     "beauty salon"),
    ("spa",              "spa"),
    ("massage",          "massage"),
    ("restaurant",       "restaurant"),
    ("bakery",           "bakery"),
    ("auto+repair",      "auto repair"),
    ("tattoo",           "tattoo parlor"),
    ("florist",          "florist"),
    ("cleaning",         "cleaning service"),
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
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def fetch_html(url: str) -> str:
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        resp = urllib.request.urlopen(req, timeout=15)
        raw = resp.read()
        try:
            import gzip
            raw = gzip.decompress(raw)
        except Exception:
            pass
        return raw.decode("utf-8", errors="replace")
    except Exception as e:
        print(f"  [WARN] Manta fetch failed: {e}")
        return ""


def parse_manta_html(html: str, category: str, city_label: str) -> list[dict]:
    rows = []

    # Try JSON-LD blocks first
    ld_blocks = re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.DOTALL)
    for block in ld_blocks:
        try:
            obj = json.loads(block)
            items = []
            if isinstance(obj, list):
                items = obj
            elif isinstance(obj, dict):
                if obj.get("@type") == "ItemList":
                    items = [e.get("item", e) for e in obj.get("itemListElement", [])]
                elif obj.get("@type") in ("LocalBusiness", "Organization"):
                    items = [obj]
            for item in items:
                if not isinstance(item, dict):
                    continue
                name = (item.get("name") or "").strip()
                if not name:
                    continue
                website = (item.get("url") or item.get("sameAs") or "").strip()
                if website and not any(s in website.lower() for s in SOCIAL_DOMAINS):
                    continue  # has real website

                addr = item.get("address") or {}
                if isinstance(addr, dict):
                    address = ", ".join(filter(None, [
                        addr.get("streetAddress", ""),
                        addr.get("addressLocality", ""),
                        addr.get("addressRegion", ""),
                        addr.get("postalCode", ""),
                    ]))
                else:
                    address = str(addr) if addr else city_label

                phone = (item.get("telephone") or "").strip()
                has_web = "No"
                ws      = "no_website"
                if website:
                    has_web = "Yes - social"
                    ws      = "social"

                rows.append({
                    "name":           name,
                    "address":        address or city_label,
                    "phone":          phone,
                    "email":          "",
                    "category":       category,
                    "city":           city_label,
                    "place_id":       "",
                    "maps_url":       "",
                    "website":        website,
                    "website_status": ws,
                    "has_website":    has_web,
                    "rating":         "",
                    "review_count":   "",
                    "notes":          "source:manta",
                    "sms_status":     "",
                    "email_status":   "",
                })
        except (json.JSONDecodeError, TypeError):
            continue

    if rows:
        return rows

    # Fallback: parse HTML cards
    # Manta listing cards typically: <div class="... company-name ..."><a>NAME</a>
    card_blocks = re.findall(
        r'<(?:div|article)[^>]+class="[^"]*(?:result|listing|company)[^"]*"[^>]*>(.*?)</(?:div|article)>',
        html, re.DOTALL | re.IGNORECASE
    )
    for card in card_blocks:
        name_m = re.search(r'<(?:h2|h3|a)[^>]*class="[^"]*(?:name|title|company)[^"]*"[^>]*>(.*?)</(?:h2|h3|a)>', card, re.DOTALL | re.IGNORECASE)
        if not name_m:
            continue
        name = re.sub(r'<[^>]+>', '', name_m.group(1)).strip()
        if not name:
            continue

        phone_m = re.search(r'(\(?\d{3}\)?[\s.\-]\d{3}[\s.\-]\d{4})', card)
        phone   = phone_m.group(1) if phone_m else ""

        website_m = re.search(r'href="(https?://[^"]+)"[^>]*>.*?(?:website|visit|www)', card, re.IGNORECASE)
        website   = website_m.group(1) if website_m else ""
        if website and not any(s in website.lower() for s in SOCIAL_DOMAINS):
            continue  # has real website

        has_web = "No"
        ws      = "no_website"
        if website:
            has_web = "Yes - social"
            ws      = "social"

        rows.append({
            "name":           name,
            "address":        city_label,
            "phone":          phone,
            "email":          "",
            "category":       category,
            "city":           city_label,
            "place_id":       "",
            "maps_url":       "",
            "website":        website,
            "website_status": ws,
            "has_website":    has_web,
            "rating":         "",
            "review_count":   "",
            "notes":          "source:manta",
            "sms_status":     "",
            "email_status":   "",
        })

    return rows


def search_manta(query: str, city: str, state: str, category: str) -> list[dict]:
    city_label = f"{city}, {state}"
    # Manta URL: /search?search_source=nav&term=hair+salon&location=Philadelphia%2C+PA
    params = urllib.parse.urlencode({
        "search_source": "nav",
        "term": query.replace("+", " "),
        "location": city_label,
    })
    url = f"https://www.manta.com/search?{params}"
    html = fetch_html(url)
    if not html:
        return []
    return parse_manta_html(html, category, city_label)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--zone",   required=True)
    ap.add_argument("--output", default="")
    ap.add_argument("--delay",  type=float, default=1.5)
    args = ap.parse_args()

    loc = ZONE_LOCATIONS.get(args.zone)
    if not loc:
        print(f"[Manta] Unknown zone '{args.zone}' — skipping.")
        sys.exit(0)

    city, state = loc
    city_label  = f"{city}, {state}"
    today  = datetime.date.today().strftime("%Y-%m-%d")
    output = args.output or str(SCRIPT_DIR / f"prospects_manta_{today}_{args.zone}.csv")

    print(f"\n[Manta] Zone: {args.zone} → {city_label}")

    seen: dict[str, dict] = {}

    for query, category in SEARCH_TERMS:
        results = search_manta(query, city, state, category)
        added = 0
        for row in results:
            key = row["name"].lower().strip()
            if key not in seen:
                seen[key] = row
                added += 1
        print(f"  {query.replace('+', ' ')}: {len(results)} results → {added} new leads")
        time.sleep(args.delay)

    rows = list(seen.values())
    print(f"[Manta] Total unique no-website leads: {len(rows)}")

    if not rows:
        print("[Manta] No prospects found.")
        sys.exit(0)

    with open(output, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    print(f"[Manta] Saved → {output}")


if __name__ == "__main__":
    main()
