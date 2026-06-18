#!/usr/bin/env python3
"""
score_leads.py — Score prospects by conversion likelihood before sending outreach.

Adds/updates 'score' and 'tier' columns in-place and sorts highest first so
the send pipeline naturally works HOT → WARM → COLD.

Scoring (max 10):
  Rating:         5.0 → +3   4.5+ → +2   4.0+ → +1
  Review count:   50+ → +2   20+  → +1
  Category tier:  salon/spa/lash/beauty/brow → +2
                  restaurant/cafe/bakery/bar  → +1
                  auto/mechanic/cleaning/massage/gym/tattoo → +1
  Has phone:      +1
  Has email:      +1
  Not a chain:    +1  (name doesn't match known franchise keywords)

HOT  = 7–10   priority sends + clicker follow-up target
WARM = 4–6    standard cadence
COLD = 1–3    last-batch / deprioritize

USAGE
    python3 score_leads.py                       # scores most recent prospects CSV
    python3 score_leads.py prospects_2026-06-17.csv
    python3 score_leads.py --preview             # print scores without writing
"""

import argparse
import csv
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent

HOT_CATEGORIES = {
    "hair salon", "nail salon", "beauty salon", "spa", "lash", "barber",
    "wax", "brow", "estheti", "skin", "eyelash", "threading", "massage",
}
WARM_CATEGORIES = {
    "restaurant", "cafe", "bakery", "food", "coffee", "pizza", "bar", "grill",
    "diner", "bistro", "eatery",
}
SOLID_CATEGORIES = {
    "auto repair", "mechanic", "landscaping", "lawn", "cleaning",
    "yoga", "fitness", "gym", "tattoo", "florist", "photographer",
    "plumber", "electrician", "hvac", "roofing", "painting",
}

CHAIN_KEYWORDS = {
    "mcdonald", "subway", "domino", "starbucks", "dunkin", "chick-fil",
    "taco bell", "burger king", "jersey mike", "chipotle", "wawa", "panera",
    "olive garden", "applebee", "7-eleven", "great clips", "sport clips",
    "supercuts", "regis", "fantastic sam", "denny", "ihop", "sonic drive",
}


def score_lead(row: dict) -> int:
    s = 0

    # Rating
    try:
        r = float(row.get("rating") or 0)
        if r >= 5.0:
            s += 3
        elif r >= 4.5:
            s += 2
        elif r >= 4.0:
            s += 1
    except (ValueError, TypeError):
        pass

    # Review count
    try:
        rc = int(row.get("review_count") or 0)
        if rc >= 50:
            s += 2
        elif rc >= 20:
            s += 1
    except (ValueError, TypeError):
        pass

    # Category
    cat = (row.get("category") or "").lower()
    if any(k in cat for k in HOT_CATEGORIES):
        s += 2
    elif any(k in cat for k in WARM_CATEGORIES):
        s += 1
    elif any(k in cat for k in SOLID_CATEGORIES):
        s += 1

    # Contact info
    if (row.get("phone") or "").strip():
        s += 1
    if (row.get("email") or "").strip():
        s += 1

    # Not a known chain
    name_lower = (row.get("name") or "").lower()
    if not any(k in name_lower for k in CHAIN_KEYWORDS):
        s += 1

    return min(s, 10)


def tier(score: int) -> str:
    if score >= 7:
        return "HOT"
    if score >= 4:
        return "WARM"
    return "COLD"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("input", nargs="?", help="CSV file to score (default: most recent prospects_*.csv)")
    p.add_argument("--preview", action="store_true", help="Print scores without writing")
    args = p.parse_args()

    if args.input:
        csv_path = Path(args.input)
    else:
        candidates = sorted(SCRIPT_DIR.glob("prospects_*.csv"), reverse=True)
        if not candidates:
            print("No prospects CSV found.")
            return
        csv_path = candidates[0]

    if not csv_path.exists():
        print(f"File not found: {csv_path}")
        return

    with open(csv_path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
        fieldnames_orig = rows[0].keys() if rows else []

    if not rows:
        print("Empty CSV — nothing to score.")
        return

    for row in rows:
        row["score"] = score_lead(row)
        row["tier"]  = tier(row["score"])

    rows.sort(key=lambda r: -int(r["score"]))

    if args.preview:
        print(f"\n{'Scr':>4}  {'Tier':>5}  {'Rating':>7}  {'Reviews':>8}  Name")
        print("-" * 65)
        for r in rows:
            print(
                f"  {r['score']:>2}  {r['tier']:>5}  "
                f"{r.get('rating',''):>7}  {r.get('review_count',''):>8}  "
                f"{r.get('name','')}"
            )
        counts = {t: sum(1 for r in rows if r["tier"] == t) for t in ("HOT", "WARM", "COLD")}
        print(f"\nTotal: {len(rows)}  HOT {counts['HOT']}  WARM {counts['WARM']}  COLD {counts['COLD']}")
        return

    # Build fieldnames preserving original order, then appending new cols
    fieldnames = list(fieldnames_orig)
    for col in ("score", "tier"):
        if col not in fieldnames:
            fieldnames.append(col)

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)

    hot  = sum(1 for r in rows if r["tier"] == "HOT")
    warm = sum(1 for r in rows if r["tier"] == "WARM")
    cold = sum(1 for r in rows if r["tier"] == "COLD")
    print(f"Scored {len(rows)} leads in {csv_path.name}")
    print(f"  HOT  {hot:>4} — send first, priority follow-up")
    print(f"  WARM {warm:>4} — standard cadence")
    print(f"  COLD {cold:>4} — last batch")
    print(f"  File sorted highest score first.")


if __name__ == "__main__":
    main()
