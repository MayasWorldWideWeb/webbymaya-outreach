#!/usr/bin/env python3
"""GitHub Actions helper: load zone_state.json from Supabase if not present locally."""
import json, os, sys, urllib.request
from pathlib import Path

URL = os.environ.get("SUPABASE_URL","")
KEY = os.environ.get("SUPABASE_KEY","")
path = Path("zone_state.json")

if path.exists():
    print("zone_state.json already present"); sys.exit(0)

if URL and KEY:
    req = urllib.request.Request(
        URL + "/rest/v1/zone_state?select=state_json&limit=1",
        headers={"apikey": KEY, "Authorization": f"Bearer {KEY}"})
    try:
        rows = json.loads(urllib.request.urlopen(req, timeout=8).read())
        if rows:
            path.write_text(rows[0]["state_json"])
            print("Loaded zone_state from Supabase"); sys.exit(0)
    except Exception as e:
        print(f"Could not load from Supabase: {e}")

default = {
    "zones": ["philly-north","philly-northeast","philly-near-ne",
              "philly-west","philly-south","philly-northwest","philly-center"],
    "current_index": 0, "completed": [], "last_find": None, "last_send": None
}
path.write_text(json.dumps(default, indent=2))
print("Created default zone_state.json")
