#!/usr/bin/env python3
"""GitHub Actions helper: save zone_state.json back to Supabase after a run."""
import json, os, sys, urllib.request, urllib.parse
from pathlib import Path

URL = os.environ.get("SUPABASE_URL","")
KEY = os.environ.get("SUPABASE_KEY","")
path = Path("zone_state.json")

if not path.exists():
    print("No zone_state.json to save"); sys.exit(0)

data = json.dumps([{"id": 1, "state_json": path.read_text()}]).encode()
req  = urllib.request.Request(
    URL + "/rest/v1/zone_state",
    data=data,
    headers={
        "apikey": KEY, "Authorization": f"Bearer {KEY}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates,return=minimal",
    }, method="POST")
try:
    urllib.request.urlopen(req, timeout=8)
    print("zone_state saved to Supabase")
except Exception as e:
    print(f"Warning: could not save zone_state: {e}")
