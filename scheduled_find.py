#!/usr/bin/env python3
"""
scheduled_find.py — Auto-rotating lead finder for WebByMaya
Runs find_prospects.py on the next Philly zone, advances the rotation,
and notifies when all zones are exhausted.
"""
import json
import subprocess
import sys
import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
STATE_FILE = SCRIPT_DIR / "zone_state.json"


def load_state():
    return json.loads(STATE_FILE.read_text())


def save_state(state):
    STATE_FILE.write_text(json.dumps(state, indent=2))


def main():
    state = load_state()
    zones = state["zones"]
    idx   = state["current_index"]

    if idx >= len(zones):
        print("=" * 60)
        print("  ALL PHILLY ZONES EXHAUSTED")
        print("  Every zone has been searched at least once.")
        print("  Time to plan the next market (suburbs, South Jersey, etc).")
        print("=" * 60)
        sys.exit(0)

    zone = zones[idx]
    today = datetime.date.today().strftime("%Y-%m-%d")

    print(f"\n{'='*60}")
    print(f"  WebByMaya Scheduled Find")
    print(f"  Zone     : {zone}  ({idx+1} of {len(zones)})")
    print(f"  Date     : {today}")
    print(f"  Remaining: {len(zones) - idx - 1} zone(s) after this")
    print(f"{'='*60}\n")

    cmd = [
        sys.executable, str(SCRIPT_DIR / "find_prospects_yelp.py"),
        "--zone", zone,
    ]

    result = subprocess.run(cmd)

    if result.returncode != 0:
        print(f"\n[scheduled_find] find_prospects.py failed for zone '{zone}'.")
        sys.exit(1)

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
