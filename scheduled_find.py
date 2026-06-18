#!/usr/bin/env python3
"""
scheduled_find.py — Auto-rotating lead finder for WebByMaya
Runs find_prospects.py on the next Philly zone, advances the rotation,
and notifies when all zones are exhausted.
"""
import csv
import json
import subprocess
import sys
import datetime
from pathlib import Path

try:
    from rapidfuzz import fuzz as _fuzz
    _RF_OK = True
except ImportError:
    _RF_OK = False

SCRIPT_DIR = Path(__file__).parent
STATE_FILE = SCRIPT_DIR / "zone_state.json"


def load_state():
    return json.loads(STATE_FILE.read_text())


def save_state(state):
    STATE_FILE.write_text(json.dumps(state, indent=2))


ZONES_PER_RUN = 4   # run this many zones per daily call to hit 600-900 emails/day


def run_zone(zone, today):
    """Run find + OSM/HERE for one zone. Returns list of prospect rows merged."""
    print(f"\n  → Searching zone: {zone}")
    cmd = [sys.executable, str(SCRIPT_DIR / "find_prospects_yelp.py"), "--zone", zone]
    result = subprocess.run(cmd)
    if result.returncode != 0:
        print(f"  [scheduled_find] Yelp failed for zone '{zone}' — continuing.")
    return result.returncode == 0


def main():
    state = load_state()
    zones = state["zones"]
    idx   = state["current_index"]

    if idx >= len(zones):
        print("=" * 60)
        print("  ALL ZONES EXHAUSTED — resetting rotation to start over.")
        print("=" * 60)
        state["current_index"] = 0
        save_state(state)
        idx = 0

    today = datetime.date.today().strftime("%Y-%m-%d")
    zones_to_run = min(ZONES_PER_RUN, len(zones) - idx)
    batch = zones[idx : idx + zones_to_run]

    print(f"\n{'='*60}")
    print(f"  WebByMaya Scheduled Find — {today}")
    print(f"  Running {len(batch)} zone(s) this pass: {', '.join(batch)}")
    print(f"  Zone progress: {idx+1}–{idx+len(batch)} of {len(zones)}")
    print(f"{'='*60}\n")

    # Run each zone; collect all output into today's CSV (zones append to same file)
    for zone in batch:
        run_zone(zone, today)
        state["current_index"] = idx + batch.index(zone) + 1
        state["completed"].append({"zone": zone, "date": today})

    state["last_find"] = today
    save_state(state)

    yelp_csv = SCRIPT_DIR / f"prospects_{today}.csv"
    yelp_rows = []
    if yelp_csv.exists():
        import os
        with open(yelp_csv, newline="", encoding="utf-8") as f:
            yelp_rows = list(csv.DictReader(f))

    phones_with_data = sum(1 for r in yelp_rows if r.get("phone","").strip())
    print(f"\n[scheduled_find] Combined: {len(yelp_rows)} prospects ({phones_with_data} with phones) from {len(batch)} zones.")

    import os

    # ── OSM supplement for each zone run ─────────────────────────────────────
    seen_phones = {r["phone"].strip() for r in yelp_rows if r.get("phone","").strip()}
    seen_names  = [r.get("name","").strip().lower() for r in yelp_rows if r.get("name","").strip()]
    merged = list(yelp_rows)

    def merge_source(label, source_csv):
        nonlocal merged
        if not source_csv.exists():
            return
        with open(source_csv, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        new = []
        for row in rows:
            phone = row.get("phone","").strip()
            name  = row.get("name","").strip().lower()
            key = phone if phone else name
            if key and key in seen_phones:
                continue
            if _RF_OK and name:
                if any(_fuzz.token_set_ratio(name, n) >= 90 for n in seen_names):
                    continue
            row.setdefault("sms_status","")
            row.setdefault("email_status","")
            new.append(row)
            if key:   seen_phones.add(key)
            if name:  seen_names.append(name)
        if new:
            print(f"[scheduled_find] {label} added {len(new)} new prospects.")
            merged.extend(new)
        source_csv.unlink(missing_ok=True)

    for zone in batch:
        osm_csv = SCRIPT_DIR / f"prospects_osm_{today}_{zone}.csv"
        osm_result = subprocess.run([
            sys.executable, str(SCRIPT_DIR / "find_prospects_osm.py"),
            "--zone", zone, "--output", str(osm_csv),
        ])
        if osm_result.returncode == 0:
            merge_source(f"OSM/{zone}", osm_csv)

    here_key = os.environ.get("HERE_API_KEY", "")
    if here_key:
        for zone in batch:
            here_csv = SCRIPT_DIR / f"prospects_here_{today}_{zone}.csv"
            here_result = subprocess.run([
                sys.executable, str(SCRIPT_DIR / "find_prospects_here.py"),
                "--zone", zone, "--output", str(here_csv),
            ])
            if here_result.returncode == 0:
                merge_source(f"HERE/{zone}", here_csv)

    if len(merged) > len(yelp_rows):
        all_columns = list(merged[0].keys()) if merged else []
        for row in merged[1:]:
            for col in row.keys():
                if col not in all_columns:
                    all_columns.append(col)
        yelp_csv = SCRIPT_DIR / f"prospects_{today}.csv"
        with open(yelp_csv, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=all_columns, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(merged)
        print(f"\n[scheduled_find] Final merged CSV: {len(merged)} prospects from {len(batch)} zones.")

    state["current_index"] = idx + 1
    state["completed"].append({"zone": zone, "date": today})
    state["last_find"] = today
    save_state(state)

    remaining = len(zones) - (idx + 1)
    if remaining == 0:
        print(f"\n*** Last Philly zone searched. Reply to Maya's next check-in to plan suburbs. ***")
    else:
        print(f"\nZone '{zone}' done. Next zone: {zones[idx+1]}  ({remaining} remaining)")


if __name__ == "__main__":
    main()
