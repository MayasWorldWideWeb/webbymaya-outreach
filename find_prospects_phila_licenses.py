#!/usr/bin/env python3
"""
find_prospects_phila_licenses.py — WebByMaya Philly Business-License Finder
===========================================================================
FREE — no API key, no rate limits. Queries OpenDataPhilly's L&I business
license dataset (phl.carto.com). A freshly issued license = a brand-new
business that almost certainly has no website yet — the best possible lead.

Only pulls storefront license types that fit WebByMaya's niches (food,
auto, towing, etc.). Rental / residential licenses are ignored.

State: phl_licenses_state.json remembers the newest license already seen,
so each daily run only returns genuinely new businesses.

USAGE
  python3 find_prospects_phila_licenses.py                     # since last run (first run: 90 days)
  python3 find_prospects_phila_licenses.py --days-back 30      # override window
  python3 find_prospects_phila_licenses.py --output out.csv
  python3 find_prospects_phila_licenses.py --dry-run           # print, don't write/advance state
"""
import argparse
import csv
import datetime
import importlib.util
import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
STATE_FILE = SCRIPT_DIR / "phl_licenses_state.json"
CARTO_URL  = "https://phl.carto.com/api/v2/sql"

# License type → WebByMaya category (normalize_category refines from the name)
LICENSE_CATEGORIES = {
    "Food Preparing and Serving":                        "restaurant",
    "Food Preparing and Serving (30+ SEATS)":            "restaurant",
    "Food Establishment, Retail Permanent Location":     "restaurant",
    "Food Establishment, Retail Perm Location (Large)":  "restaurant",
    "Sidewalk Cafe":                                     "cafe",
    "Food Caterer":                                      "caterer",
    "Motor Vehicle Repair / Retail Mobile Dispensing":   "auto repair",
    "Tire Dealer":                                       "tire shop",
    "Tow Truck":                                         "towing",
    "Tow Company":                                       "towing",
    "Child Care Facility":                               "child care",
}

CSV_COLUMNS = ["name","address","phone","email","category","city",
               "place_id","maps_url","website","website_status",
               "has_website","rating","review_count","notes","sms_status","email_status"]


def _get_normalizer():
    spec = importlib.util.spec_from_file_location(
        "bso", SCRIPT_DIR / "batch_send_outreach.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.normalize_category

try:
    normalize_category = _get_normalizer()
except Exception:
    normalize_category = lambda name, cat: cat


BIG_CHAINS = {
    "ihop","mcdonald's","mcdonalds","dunkin","dunkin donuts","subway","wendy's",
    "popeyes","kfc","domino's","dominos","taco bell","chipotle","starbucks",
    "7-eleven","wawa","burger king","chick-fil-a","pizza hut","little caesars",
    "checkers","rally's","auntie anne's","dairy queen","five guys","jersey mike's",
}


def clean_name(raw: str) -> str:
    """Strip corporate suffixes so outreach copy reads naturally.
    'H Coco Grille Llc (Coco Grille)' → 'Coco Grille' (trade name wins)."""
    n = re.sub(r"\s+", " ", (raw or "")).strip()
    m = re.search(r"\(([^)]{3,})\)", n)
    if m:  # parenthetical trade name — use it
        n = m.group(1).strip()
    n = re.sub(r"[,]?\s*(LLC|L\.L\.C\.|Inc\.?|Incorporated|Corp\.?|Corporation|Co\.?|Ltd\.?)\s*$",
               "", n, flags=re.I).strip().rstrip(",")
    return n


def looks_like_person(name: str) -> bool:
    """Skip licenses issued to an individual with no trade name."""
    words = name.split()
    return len(words) in (2, 3) and all(w.isalpha() and w[0].isupper() and w[1:].islower() for w in words)


def fetch_licenses(since: str, limit: int) -> list[dict]:
    types = ", ".join("'" + t.replace("'", "''") + "'" for t in LICENSE_CATEGORIES)
    sql = (
        "SELECT business_name, legalname, initialissuedate, licensetype, "
        "address, zip, licensenum "
        "FROM business_licenses "
        f"WHERE licensestatus = 'Active' AND licensetype IN ({types}) "
        f"AND initialissuedate > '{since}' "
        f"ORDER BY initialissuedate ASC LIMIT {int(limit)}"
    )
    url = CARTO_URL + "?q=" + urllib.parse.quote(sql)
    req = urllib.request.Request(url, headers={"User-Agent": "WebByMaya-prospect-finder/1.0"})
    return json.loads(urllib.request.urlopen(req, timeout=60).read()).get("rows", [])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days-back", type=int, default=90,
                    help="First-run lookback window in days (default 90)")
    ap.add_argument("--limit", type=int, default=400)
    ap.add_argument("--output", default="")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    today = datetime.date.today().isoformat()

    # Resume from newest license already seen; else use the lookback window
    since = (datetime.date.today() - datetime.timedelta(days=args.days_back)).isoformat()
    if STATE_FILE.exists():
        try:
            since = json.loads(STATE_FILE.read_text()).get("last_issue_date", since)
        except Exception:
            pass

    print(f"\n{'='*60}")
    print("  WebByMaya Philly Business-License Finder (OpenDataPhilly)")
    print(f"  Date  : {today}")
    print(f"  Since : {since}")
    print(f"{'='*60}\n")

    try:
        rows = fetch_licenses(since, args.limit)
    except Exception as e:
        print(f"[ERROR] Carto fetch failed: {e}")
        sys.exit(1)
    print(f"  Raw licenses: {len(rows)}")

    leads, seen, last_issue = [], set(), since
    for r in rows:
        issued = (r.get("initialissuedate") or "")[:10]
        if issued > last_issue:
            last_issue = issued
        name = clean_name(r.get("business_name") or "")
        if not name and r.get("legalname"):
            # Legal-name fallback is where person names show up ("John Smith")
            name = clean_name(r["legalname"])
            if looks_like_person(name):
                continue
        if not name:
            continue
        if name.lower() in BIG_CHAINS or any(c in name.lower() for c in BIG_CHAINS if len(c) > 6):
            continue  # franchise of a national chain — corporate handles their web
        if name.isupper():
            name = name.title()
        addr = (r.get("address") or "").strip().title()
        key = (name.lower(), addr.lower())
        if key in seen:
            continue
        seen.add(key)
        category = normalize_category(name, LICENSE_CATEGORIES.get(r.get("licensetype", ""), ""))
        zipc = (r.get("zip") or "")[:5]
        leads.append({
            "name":           name,
            "address":        f"{addr}, Philadelphia, PA {zipc}".strip().rstrip(","),
            "phone":          "",
            "email":          "",
            "category":       category,
            "city":           f"Philadelphia, PA ({zipc})" if zipc else "Philadelphia, PA",
            "place_id":       f"phl_lic_{r.get('licensenum','')}",
            "maps_url":       "https://www.google.com/maps/search/" + urllib.parse.quote(f"{name} {addr} Philadelphia PA"),
            "website":        "",
            "website_status": "none",
            "has_website":    "No",
            "rating":         "",
            "review_count":   "",
            "notes":          f"source:phl-licenses licensed:{issued} type:{r.get('licensetype','')}",
            "sms_status":     "",
            "email_status":   "",
        })

    print(f"  New business leads: {len(leads)}")
    if args.dry_run:
        for l in leads[:15]:
            print(f"    {l['name']:40} {l['category']:12} {l['notes'].split('licensed:')[1][:10]}")
        if len(leads) > 15:
            print(f"    … and {len(leads)-15} more")
        return

    if not leads:
        print("No new prospects from Philly licenses.")
        sys.exit(1)

    out = Path(args.output) if args.output else SCRIPT_DIR / f"prospects_phl_licenses_{today}.csv"
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        w.writeheader()
        w.writerows(leads)
    print(f"  Wrote {out}")

    STATE_FILE.write_text(json.dumps({"last_issue_date": last_issue, "last_run": today}, indent=2))


if __name__ == "__main__":
    main()
