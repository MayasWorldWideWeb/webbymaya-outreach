#!/usr/bin/env python3
"""
build_unsent_csv.py — Build today's prospects CSV from existing untexted leads.
Replaces scheduled_find.py when Google Places API billing isn't active.
Pulls from all existing prospect CSVs, skips anyone already texted.
"""
import csv, datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
TODAY      = datetime.date.today().strftime("%Y-%m-%d")
OUT_PATH   = SCRIPT_DIR / f"prospects_{TODAY}.csv"

# Collect already-texted phones
texted = set()
for p in sorted(SCRIPT_DIR.glob("sms_log_*.csv")):
    with open(p, newline="") as f:
        for r in csv.DictReader(f):
            if r.get("status") == "sent":
                texted.add(r.get("phone","").strip())

# Collect already-emailed emails
emailed = set()
for p in sorted(SCRIPT_DIR.glob("send_log_*.csv")):
    with open(p, newline="") as f:
        for r in csv.DictReader(f):
            if r.get("status") == "sent":
                emailed.add(r.get("email_sent_to","").lower().strip())

# Pull untexted prospects from existing CSVs (enriched preferred)
seen_phones = set()
prospects   = []

csvs = sorted(SCRIPT_DIR.glob("prospects_*_enriched.csv"), reverse=True)
if not csvs:
    csvs = sorted(SCRIPT_DIR.glob("prospects_*.csv"), reverse=True)
    csvs = [c for c in csvs if "_enriched" not in c.name]

for p in csvs:
    with open(p, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        continue
    fieldnames = rows[0].keys()
    for r in rows:
        phone = r.get("phone","").strip()
        if not phone or phone in texted or phone in seen_phones:
            continue
        seen_phones.add(phone)
        # Reset send statuses so they get picked up
        r["sms_status"]   = ""
        r["email_status"] = ""
        prospects.append(r)

if not prospects:
    print("No untexted prospects found. All leads have been contacted.")
    raise SystemExit(0)

# Write today's CSV
with open(OUT_PATH, "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=list(prospects[0].keys()))
    writer.writeheader()
    writer.writerows(prospects)

print(f"Built {OUT_PATH.name} with {len(prospects)} untexted prospects")
print(f"  (skipped {len(texted)} already-texted phones)")
