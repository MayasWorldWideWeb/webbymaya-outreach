#!/usr/bin/env python3
"""
scheduled_find.py — Auto-rotating lead finder for WebByMaya
Runs Yelp + OSM + HERE + BBB + TomTom + Bing on zones in parallel.
"""
import csv
import json
import os
import subprocess
import sys
import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

try:
    from rapidfuzz import fuzz as _fuzz
    _RF_OK = True
except ImportError:
    _RF_OK = False

SCRIPT_DIR = Path(__file__).parent
STATE_FILE = SCRIPT_DIR / "zone_state.json"

ZONES_PER_RUN  = 4    # zones per scheduled daily call (overridden to 999 by run_until_stop)
ZONE_TIMEOUT   = 240  # seconds per Yelp zone before giving up
PARALLEL_ZONES = 4    # how many zones to scrape simultaneously


def load_state():
    return json.loads(STATE_FILE.read_text())


def save_state(state):
    STATE_FILE.write_text(json.dumps(state, indent=2))


def _run_subprocess(cmd, timeout=None):
    try:
        r = subprocess.run(cmd, timeout=timeout)
        return r.returncode == 0
    except subprocess.TimeoutExpired:
        return False
    except Exception:
        return False


def run_yelp_zone(zone: str, today: str) -> tuple[str, Path, bool]:
    """Run Yelp for one zone into a per-zone temp file. Returns (zone, csv_path, ok)."""
    out = SCRIPT_DIR / f"prospects_yelp_{today}_{zone}.csv"
    print(f"  [Yelp] → {zone}")
    ok = _run_subprocess(
        [sys.executable, str(SCRIPT_DIR / "find_prospects_yelp.py"),
         "--zone", zone, "--output", str(out)],
        timeout=ZONE_TIMEOUT,
    )
    if not ok:
        print(f"  [Yelp] {zone} timed out or failed — skipping.")
    return zone, out, ok


def run_source_zone(script: str, zone: str, out: Path, timeout: int = 180) -> tuple[str, Path, bool]:
    ok = _run_subprocess(
        [sys.executable, str(SCRIPT_DIR / script), "--zone", zone, "--output", str(out)],
        timeout=timeout,
    )
    return zone, out, ok


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
    print(f"  {len(batch)} zone(s) this pass ({PARALLEL_ZONES} parallel): {', '.join(batch)}")
    print(f"  Zone progress: {idx+1}–{idx+len(batch)} of {len(zones)}")
    print(f"{'='*60}\n")

    # ── 1. Yelp: run all zones in parallel chunks ─────────────────────────────
    yelp_rows: list[dict] = []
    seen_phones: set[str] = set()
    seen_names:  list[str] = []

    # Load emails already sent so we don't re-enrich contacted businesses
    already_sent_emails: set[str] = set()
    for _sl in sorted(SCRIPT_DIR.glob("send_log_*.csv")):
        with open(_sl, newline="", encoding="utf-8") as _f:
            for _r in csv.DictReader(_f):
                if _r.get("status") == "sent":
                    _e = _r.get("email_sent_to", "").lower().strip()
                    if _e:
                        already_sent_emails.add(_e)

    # Load any rows already in today's CSV from a previous pass
    main_csv = SCRIPT_DIR / f"prospects_{today}.csv"
    if main_csv.exists():
        with open(main_csv, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                email = row.get("email", "").lower().strip()
                if email and email in already_sent_emails:
                    continue  # drop already-contacted businesses from prior fallback
                yelp_rows.append(row)
                ph = row.get("phone","").strip()
                nm = row.get("name","").strip().lower()
                if ph: seen_phones.add(ph)
                if nm: seen_names.append(nm)

    for chunk_start in range(0, len(batch), PARALLEL_ZONES):
        chunk = batch[chunk_start : chunk_start + PARALLEL_ZONES]
        with ThreadPoolExecutor(max_workers=len(chunk)) as ex:
            futures = {ex.submit(run_yelp_zone, z, today): z for z in chunk}
            for fut in as_completed(futures):
                zone, csv_path, ok = fut.result()
                if ok and csv_path.exists():
                    with open(csv_path, newline="", encoding="utf-8") as f:
                        for row in csv.DictReader(f):
                            ph = row.get("phone","").strip()
                            nm = row.get("name","").strip().lower()
                            key = ph if ph else nm
                            if key and key in seen_phones:
                                continue
                            if _RF_OK and nm and any(_fuzz.token_set_ratio(nm, n) >= 90 for n in seen_names):
                                continue
                            yelp_rows.append(row)
                            if ph: seen_phones.add(ph)
                            if nm: seen_names.append(nm)
                    csv_path.unlink(missing_ok=True)

    # Update state after Yelp pass
    for zone in batch:
        state["completed"].append({"zone": zone, "date": today})
    state["current_index"] = idx + len(batch)
    state["last_find"] = today
    save_state(state)

    phones_with_data = sum(1 for r in yelp_rows if r.get("phone","").strip())
    print(f"\n[scheduled_find] Yelp total: {len(yelp_rows)} prospects ({phones_with_data} with phones)")

    merged = list(yelp_rows)

    # ── 2. Merge helper ───────────────────────────────────────────────────────
    def merge_source(label: str, source_csv: Path):
        if not source_csv.exists():
            return
        with open(source_csv, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        new = []
        for row in rows:
            ph   = row.get("phone","").strip()
            nm   = row.get("name","").strip().lower()
            key  = ph if ph else nm
            if key and key in seen_phones:
                continue
            if _RF_OK and nm and any(_fuzz.token_set_ratio(nm, n) >= 90 for n in seen_names):
                continue
            row.setdefault("sms_status","")
            row.setdefault("email_status","")
            new.append(row)
            if key: seen_phones.add(key)
            if nm:  seen_names.append(nm)
        if new:
            print(f"[scheduled_find] {label} +{len(new)} new prospects")
            merged.extend(new)
        source_csv.unlink(missing_ok=True)

    # ── 3. Supplemental sources: run all zones in parallel ────────────────────
    def parallel_source(script, label_prefix, timeout=180):
        tasks = []
        for zone in batch:
            slug = script.replace("find_prospects_","").replace(".py","")
            out  = SCRIPT_DIR / f"prospects_{slug}_{today}_{zone}.csv"
            tasks.append((zone, out))
        with ThreadPoolExecutor(max_workers=min(PARALLEL_ZONES, len(batch))) as ex:
            futures = {ex.submit(run_source_zone, script, z, o, timeout): (z, o) for z, o in tasks}
            for fut in as_completed(futures):
                zone, out, ok = fut.result()
                if ok:
                    merge_source(f"{label_prefix}/{zone}", out)

    parallel_source("find_prospects_osm.py", "OSM", timeout=120)

    here_key = os.environ.get("HERE_API_KEY", "")
    if here_key:
        parallel_source("find_prospects_here.py", "HERE", timeout=120)

    tt_key = os.environ.get("TOMTOM_API_KEY", "")
    if tt_key:
        parallel_source("find_prospects_tomtom.py", "TomTom", timeout=180)

    bing_key = os.environ.get("BING_MAPS_KEY", "")
    if bing_key:
        parallel_source("find_prospects_bing.py", "Bing", timeout=180)

    parallel_source("find_prospects_bbb.py", "BBB", timeout=240)

    # Manta blocks bots (403) — skipping
    # FSQ free API deprecated 2025 — skipping

    # ── 4. Write merged CSV ───────────────────────────────────────────────────
    if merged:
        all_columns = list(merged[0].keys())
        for row in merged[1:]:
            for col in row.keys():
                if col not in all_columns:
                    all_columns.append(col)
        with open(main_csv, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=all_columns, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(merged)
        print(f"\n[scheduled_find] Final merged CSV: {len(merged)} prospects from {len(batch)} zones.")

    remaining = len(zones) - (idx + len(batch))
    if remaining <= 0:
        print(f"\n*** All zones done — next pass will reset. ***")
    else:
        print(f"\nNext zone: {zones[idx + len(batch)]}  ({remaining} remaining)")


if __name__ == "__main__":
    main()
